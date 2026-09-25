from __future__ import annotations

import html
import json
import re
from datetime import date
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field


FEDERAL_REGISTER_API = "https://www.federalregister.gov/api/v1/documents/{document_number}.json"
DEFAULT_USER_AGENT = "PolicyTrace/0.1 (+https://github.com/steveonw/microsoft-letastlator-thing)"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NormalizedChunk(StrictModel):
    id: str
    sequence: int = Field(ge=1)
    heading: str | None = None
    text: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)


class NormalizedPolicyDocument(StrictModel):
    document_number: str
    title: str
    document_type: str | None = None
    action: str | None = None
    agency_names: list[str] = Field(default_factory=list)
    publication_date: date | None = None
    comments_close_on: date | None = None
    docket_ids: list[str] = Field(default_factory=list)
    regulation_id_numbers: list[str] = Field(default_factory=list)
    citation: str | None = None
    cfr_references: list[dict[str, Any]] = Field(default_factory=list)
    html_url: str | None = None
    pdf_url: str | None = None
    regulations_dot_gov_url: str | None = None
    regulations_dot_gov_docket_id: str | None = None
    raw_text_url: str | None = None
    raw_text: str
    chunks: list[NormalizedChunk] = Field(default_factory=list)


class OfflineFederalRegisterFixture(StrictModel):
    metadata: dict[str, Any]
    raw_text: str


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return "".join(self.parts)


def _get_json(url: str, *, timeout: int = 30) -> dict[str, Any]:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _get_text(url: str, *, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": DEFAULT_USER_AGENT})
    with urlopen(request, timeout=timeout) as response:
        body = response.read()
        charset = response.headers.get_content_charset() or "utf-8"
        return body.decode(charset, errors="replace")


def _plain_text(payload: str) -> str:
    lower = payload[:500].lower()
    if "<html" in lower or "<body" in lower or "<pre" in lower:
        parser = _TextExtractor()
        parser.feed(payload)
        payload = parser.text()

    payload = html.unescape(payload)
    payload = payload.replace("\r\n", "\n").replace("\r", "\n")
    payload = payload.replace("\u00a0", " ")
    # Federal Register plain text encodes superscripts as "10[supcaret]26".
    # A model reading that writes "10^26", so the marker has to become a caret
    # here or every citation to a computational-threshold definition -- the
    # most citation-worthy facts in an AI rule -- fails to match.
    payload = payload.replace("[supcaret]", "^")
    payload = re.sub(r"[ \t]+\n", "\n", payload)
    payload = re.sub(r"\n{3,}", "\n\n", payload)
    return payload.strip()


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _agency_names(metadata: dict[str, Any]) -> list[str]:
    names = metadata.get("agency_names")
    if isinstance(names, list):
        return [str(name) for name in names if name]

    agencies = metadata.get("agencies") or []
    result: list[str] = []
    for agency in agencies:
        if isinstance(agency, dict) and agency.get("name"):
            result.append(str(agency["name"]))
    return result


def _list_of_strings(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)]


def _regulations_dot_gov_docket_id(metadata: dict[str, Any]) -> str | None:
    info = metadata.get("regulations_dot_gov_info")
    if not isinstance(info, dict):
        return None
    value = info.get("docket_id")
    return str(value).strip() if value else None


def _infer_regulations_dot_gov_url(text: str) -> str | None:
    patterns = [
        r"regulations\.gov ID for this proposed rule is:\s*([A-Z]+[-–]\d{4}[-–]\d+)",
        r"regulations\.gov.*?([A-Z]+[-–]\d{4}[-–]\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            docket_id = match.group(1).replace("–", "-")
            return f"https://www.regulations.gov/docket/{docket_id}"
    return None


def _looks_like_heading(line: str) -> bool:
    candidate = line.strip()
    if len(candidate) < 2 or len(candidate) > 180:
        return False

    normalized = candidate.rstrip(":").strip().lower()
    if normalized in {
        "summary",
        "dates",
        "addresses",
        "for further information contact",
        "supplementary information",
        "background",
        "discussion of the proposed rule",
        "request for comments",
        "rulemaking requirements",
        "list of subjects in 15 cfr part 702",
    }:
        return True

    if candidate.startswith("§ "):
        return True

    if re.match(r"^(?:Sec\.\s+\d+|§\s*\d+|[IVXLC]+\.|[A-Z]\.|\d+\.)\s+", candidate):
        return True

    letters = [char for char in candidate if char.isalpha()]
    if (
        len(candidate) <= 120
        and len(letters) >= 4
        and all(char.isupper() for char in letters)
    ):
        return True

    return False


def _heading_candidates(text: str) -> list[tuple[int, str]]:
    candidates: list[tuple[int, str]] = []
    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.strip()
        if line and _looks_like_heading(line):
            candidates.append((offset, line))
        offset += len(raw_line)
    return candidates


def _heading_for_offset(
    candidates: list[tuple[int, str]],
    start_offset: int,
    chunk_text_value: str,
) -> str:
    nearest: str | None = None
    for offset, heading in candidates:
        if offset > start_offset:
            break
        nearest = heading

    if nearest:
        return nearest

    for line in chunk_text_value.splitlines()[:10]:
        if _looks_like_heading(line):
            return line.strip()

    return "Federal Register document body"


def chunk_text(
    document_number: str,
    text: str,
    *,
    max_chars: int = 4500,
    min_break_fraction: float = 0.6,
) -> list[NormalizedChunk]:
    if max_chars < 500:
        raise ValueError("max_chars must be at least 500")
    if not 0.3 <= min_break_fraction <= 0.95:
        raise ValueError("min_break_fraction must be between 0.3 and 0.95")

    chunks: list[NormalizedChunk] = []
    start = 0
    sequence = 1
    text_length = len(text)
    headings = _heading_candidates(text)

    while start < text_length:
        while start < text_length and text[start].isspace():
            start += 1
        if start >= text_length:
            break

        target = min(start + max_chars, text_length)
        end = target

        if target < text_length:
            lower_bound = start + int(max_chars * min_break_fraction)
            search_window = text[lower_bound:target]

            candidates = [
                search_window.rfind("\n\n"),
                search_window.rfind("\n"),
                search_window.rfind(". "),
            ]
            best = max(candidates)
            if best >= 0:
                delimiter_width = (
                    2
                    if search_window[best:best + 2] in {"\n\n", ". "}
                    else 1
                )
                end = lower_bound + best + delimiter_width

        while end > start and text[end - 1].isspace():
            end -= 1

        if end <= start:
            end = min(start + max_chars, text_length)

        chunk_value = text[start:end]
        chunks.append(
            NormalizedChunk(
                id=f"{document_number}-chunk-{sequence:03d}",
                sequence=sequence,
                heading=_heading_for_offset(headings, start, chunk_value),
                text=chunk_value,
                start_offset=start,
                end_offset=end,
            )
        )
        sequence += 1
        start = end

    return chunks


def normalize_document(
    metadata: dict[str, Any],
    raw_text: str,
    *,
    max_chunk_chars: int = 4500,
) -> NormalizedPolicyDocument:
    document_number = str(metadata["document_number"])
    text = _plain_text(raw_text)

    return NormalizedPolicyDocument(
        document_number=document_number,
        title=str(metadata["title"]),
        document_type=metadata.get("type"),
        action=metadata.get("action"),
        agency_names=_agency_names(metadata),
        publication_date=_parse_date(metadata.get("publication_date")),
        comments_close_on=_parse_date(metadata.get("comments_close_on")),
        docket_ids=_list_of_strings(
            metadata.get("docket_ids") or metadata.get("docket_id")
        ),
        regulation_id_numbers=_list_of_strings(
            metadata.get("regulation_id_numbers")
        ),
        citation=metadata.get("citation"),
        cfr_references=metadata.get("cfr_references") or [],
        html_url=metadata.get("html_url"),
        pdf_url=metadata.get("pdf_url"),
        regulations_dot_gov_url=(
            metadata.get("regulations_dot_gov_url")
            or _infer_regulations_dot_gov_url(text)
        ),
        regulations_dot_gov_docket_id=_regulations_dot_gov_docket_id(metadata),
        raw_text_url=metadata.get("raw_text_url"),
        raw_text=text,
        chunks=chunk_text(
            document_number,
            text,
            max_chars=max_chunk_chars,
        ),
    )


def load_fixture_and_normalize(
    fixture_path: str | Path,
    *,
    max_chunk_chars: int = 4500,
) -> NormalizedPolicyDocument:
    path = Path(fixture_path)
    fixture = OfflineFederalRegisterFixture.model_validate_json(
        path.read_text(encoding="utf-8")
    )
    return normalize_document(
        fixture.metadata,
        fixture.raw_text,
        max_chunk_chars=max_chunk_chars,
    )


def fetch_and_normalize(
    document_number: str,
    *,
    max_chunk_chars: int = 4500,
    timeout: int = 30,
) -> NormalizedPolicyDocument:
    metadata_url = FEDERAL_REGISTER_API.format(document_number=document_number)
    metadata = _get_json(metadata_url, timeout=timeout)

    raw_text_url = metadata.get("raw_text_url")
    if not raw_text_url:
        raise ValueError(
            f"Federal Register document {document_number} does not expose raw_text_url"
        )

    raw_text = _get_text(str(raw_text_url), timeout=timeout)
    return normalize_document(
        metadata,
        raw_text,
        max_chunk_chars=max_chunk_chars,
    )


# Phase 9: Federal Register search and conservative docket detection.

FEDERAL_REGISTER_SEARCH_API = "https://www.federalregister.gov/api/v1/documents.json"
SEARCHABLE_DOCUMENT_TYPES = ("RULE", "PRORULE", "NOTICE", "PRESDOCU")
DEFAULT_SEARCH_TYPES = ("RULE", "PRORULE")
MAX_SEARCH_RESULTS = 20
SEARCH_FIELDS = (
    "document_number",
    "title",
    "type",
    "action",
    "abstract",
    "agencies",
    "publication_date",
    "comments_close_on",
    "docket_ids",
    "regulation_id_numbers",
    "regulations_dot_gov_info",
    "html_url",
)

_DOCUMENT_NUMBER_RE = re.compile(
    r"^(?:\\d{4}|\\d{2}|[A-Z]\\d{1,2})-\\d{3,6}$",
    re.IGNORECASE,
)
_REGULATIONS_DOCKET_RE = re.compile(
    r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)*-\\d{4}-(?:[A-Z]-)?\\d{4,}$"
)
_CATCH_ALL_DOCKET_RE = re.compile(r"_FRDOC_", re.IGNORECASE)
_DOCKET_PREFIX_RE = re.compile(
    r"^\\s*(?:docket\\s*(?:no\\.?|number|id)?\\s*[:#]?\\s*)",
    re.IGNORECASE,
)


class DocketCandidate(StrictModel):
    docket_id: str
    source: str
    kind: str


class DocketDetection(StrictModel):
    status: str
    docket_id: str | None = None
    candidates: list[DocketCandidate] = Field(default_factory=list)
    excluded: list[DocketCandidate] = Field(default_factory=list)
    note: str


class SearchCandidate(StrictModel):
    document_number: str
    title: str
    document_type: str | None = None
    action: str | None = None
    abstract: str | None = None
    agency_names: list[str] = Field(default_factory=list)
    publication_date: date | None = None
    comments_close_on: date | None = None
    regulation_id_numbers: list[str] = Field(default_factory=list)
    html_url: str | None = None
    comments_count: int | None = None
    docket: DocketDetection


class DocumentSearchResult(StrictModel):
    query: str
    document_types: list[str]
    total_count: int
    candidates: list[SearchCandidate]
    search_url: str
    source: str = "Federal Register API"


def looks_like_document_number(text: str) -> bool:
    return bool(_DOCUMENT_NUMBER_RE.match(text.strip()))


def _clean_docket_id(value: Any) -> str:
    text = str(value or "").replace("\\u2013", "-").replace("\\u2014", "-")
    text = _DOCKET_PREFIX_RE.sub("", text)
    return text.strip().strip(".;,").upper()


def classify_docket_id(docket_id: str) -> str:
    if _CATCH_ALL_DOCKET_RE.search(docket_id):
        return "catch_all"
    if _REGULATIONS_DOCKET_RE.match(docket_id):
        return "regulations_gov"
    return "agency_reference"


def _docket_from_url(value: Any) -> str | None:
    if not value:
        return None
    try:
        parsed = urlparse(str(value))
    except ValueError:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2 and parts[-2].casefold() == "docket":
        return _clean_docket_id(parts[-1])
    return None


def detect_docket(metadata: dict[str, Any]) -> DocketDetection:
    """Conservatively identify a docket that is safe to pre-fill.

    Only an explicit Regulations.gov pointer is treated as verified enough to
    auto-fill. Federal Register docket_ids are disclosed but are not auto-
    fetched because some agency-internal IDs look exactly like Regulations.gov
    docket IDs.
    """
    verified_raw: list[tuple[str, str]] = []
    info = metadata.get("regulations_dot_gov_info")
    if isinstance(info, dict) and info.get("docket_id"):
        verified_raw.append(
            (str(info["docket_id"]), "regulations_dot_gov_info")
        )

    from_url = _docket_from_url(metadata.get("regulations_dot_gov_url"))
    if from_url:
        verified_raw.append((from_url, "regulations_dot_gov_url"))

    seen: set[str] = set()
    usable: list[DocketCandidate] = []
    excluded: list[DocketCandidate] = []

    for value, source in verified_raw:
        docket_id = _clean_docket_id(value)
        if not docket_id or docket_id in seen:
            continue
        seen.add(docket_id)
        kind = classify_docket_id(docket_id)
        candidate = DocketCandidate(
            docket_id=docket_id,
            source=source,
            kind=kind,
        )
        if kind == "regulations_gov":
            usable.append(candidate)
        else:
            excluded.append(candidate)

    for value in _list_of_strings(
        metadata.get("docket_ids") or metadata.get("docket_id")
    ):
        docket_id = _clean_docket_id(value)
        if not docket_id or docket_id in seen:
            continue
        seen.add(docket_id)
        kind = classify_docket_id(docket_id)
        excluded.append(
            DocketCandidate(
                docket_id=docket_id,
                source="federal_register_docket_ids",
                kind=(
                    "catch_all"
                    if kind == "catch_all"
                    else "unverified_reference"
                ),
            )
        )

    if len(usable) == 1:
        return DocketDetection(
            status="single",
            docket_id=usable[0].docket_id,
            candidates=usable,
            excluded=excluded,
            note=(
                f"Detected Regulations.gov docket {usable[0].docket_id} from "
                "an explicit official Regulations.gov pointer. Confirm before "
                "loading comments."
            ),
        )
    if len(usable) > 1:
        return DocketDetection(
            status="multiple",
            candidates=usable,
            excluded=excluded,
            note=(
                "Several explicit Regulations.gov dockets are listed. Choose "
                "one before loading comments."
            ),
        )

    if any(item.kind == "catch_all" for item in excluded):
        note = (
            "Only an agency catch-all docket is listed. PolicyTrace will not "
            "auto-load comments from it."
        )
    elif excluded:
        refs = ", ".join(item.docket_id for item in excluded[:3])
        note = (
            "Federal Register metadata lists docket reference"
            f"{'s' if len(excluded) != 1 else ''} {refs}, but no explicit "
            "Regulations.gov comment-docket pointer was provided. PolicyTrace "
            "will not auto-load comments; enter a verified docket manually if needed."
        )
    else:
        note = (
            "No Regulations.gov comment docket was detected. Enter one manually "
            "if you know it."
        )
    return DocketDetection(
        status="none",
        excluded=excluded,
        note=note,
    )


def detect_document_docket(
    document: NormalizedPolicyDocument,
) -> DocketDetection:
    info = (
        {"docket_id": document.regulations_dot_gov_docket_id}
        if document.regulations_dot_gov_docket_id
        else None
    )
    return detect_docket(
        {
            "regulations_dot_gov_info": info,
            "regulations_dot_gov_url": document.regulations_dot_gov_url,
            "docket_ids": document.docket_ids,
        }
    )


def build_search_url(
    term: str,
    document_types: list[str],
    limit: int,
) -> str:
    params: list[tuple[str, str]] = [
        ("conditions[term]", term),
        ("per_page", str(limit)),
        ("order", "relevance"),
    ]
    params += [
        ("conditions[type][]", document_type)
        for document_type in document_types
    ]
    params += [("fields[]", field) for field in SEARCH_FIELDS]
    return f"{FEDERAL_REGISTER_SEARCH_API}?{urlencode(params)}"


def _search_candidate(item: dict[str, Any]) -> SearchCandidate:
    info = item.get("regulations_dot_gov_info")
    comments_count = (
        info.get("comments_count")
        if isinstance(info, dict)
        else None
    )
    return SearchCandidate(
        document_number=str(item["document_number"]),
        title=str(item.get("title") or item["document_number"]),
        document_type=item.get("type"),
        action=item.get("action"),
        abstract=item.get("abstract"),
        agency_names=_agency_names(item),
        publication_date=_parse_date(item.get("publication_date")),
        comments_close_on=_parse_date(item.get("comments_close_on")),
        regulation_id_numbers=_list_of_strings(
            item.get("regulation_id_numbers")
        ),
        html_url=item.get("html_url"),
        comments_count=(
            comments_count
            if isinstance(comments_count, int)
            else None
        ),
        docket=detect_docket(item),
    )


def search_documents(
    term: str,
    *,
    document_types: list[str] | tuple[str, ...] | None = None,
    limit: int = 8,
    timeout: int = 30,
    get_json: Callable[..., dict[str, Any]] | None = None,
) -> DocumentSearchResult:
    term = " ".join(str(term or "").split())
    if not term:
        raise ValueError("Enter a document number or search words.")
    if not 1 <= limit <= MAX_SEARCH_RESULTS:
        raise ValueError(
            f"limit must be between 1 and {MAX_SEARCH_RESULTS}"
        )

    types = [
        value.strip().upper()
        for value in (document_types or DEFAULT_SEARCH_TYPES)
        if value.strip()
    ]
    unknown = sorted(set(types) - set(SEARCHABLE_DOCUMENT_TYPES))
    if unknown:
        raise ValueError(
            f"Unsupported document type(s): {', '.join(unknown)}"
        )
    types = list(dict.fromkeys(types)) or list(DEFAULT_SEARCH_TYPES)

    url = build_search_url(term, types, limit)
    payload = (get_json or _get_json)(url, timeout=timeout)
    items = payload.get("results") or []

    return DocumentSearchResult(
        query=term,
        document_types=types,
        total_count=int(payload.get("count") or 0),
        candidates=[
            _search_candidate(item)
            for item in items[:limit]
            if isinstance(item, dict)
            and item.get("document_number")
        ],
        search_url=url,
    )

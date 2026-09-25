from __future__ import annotations

import hashlib
import html
import json
import os
import random
import re
import unicodedata
import warnings
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from xml.etree import ElementTree
from zipfile import ZipFile

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from models import InformationType, PiiRedactionStatus, Source


REGULATIONS_GOV_BASE_URL = "https://api.regulations.gov/v4"
DEFAULT_USER_AGENT = "PolicyTrace/0.1 (+https://github.com/steveonw/microsoft-letastlator-thing)"
ATTACHMENT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0 Safari/537.36"
)
MAX_ATTACHMENT_BYTES = 15_000_000
MAX_ATTACHMENT_CHARS = 50_000
COMMENT_FETCH_WORKERS = 4
COMMENT_PAGE_SIZE = 250
MAX_COMMENT_PAGES = 20
MAX_RANDOM_COMMENTS_PER_OBJECT = COMMENT_PAGE_SIZE * MAX_COMMENT_PAGES
_ATTACHMENT_PLACEHOLDER_RE = re.compile(
    r"^\s*see\s+attached\s+file\(s\)[.]?\s*$",
    re.IGNORECASE,
)
_ATTACHMENT_FORMAT_PRIORITY = {
    "txt": 0,
    "text": 0,
    "html": 1,
    "htm": 1,
    "pdf": 2,
    "docx": 3,
}

# The local part may not start or end on a separator, and the domain must end
# on a letter. A trailing "." is sentence punctuation, not part of the address,
# so the lookahead must not reject it -- "email me at a@b.com." is the common
# case and an earlier (?![\w.-]) let it through unredacted.
_EMAIL_RE = re.compile(
    r"(?<![\w.+-])[\w+-]+(?:[.][\w+-]+)*@[\w-]+(?:[.][\w-]+)*\.[A-Za-z]{2,}(?![\w@])"
)
_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?1[ .-]?)?(?:\(?\d{3}\)?[ .-]?)\d{3}[ .-]?\d{4}(?!\d)"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResponseRecord(StrictModel):
    id: str
    title: str
    text: str = Field(min_length=1)
    information_type: InformationType
    url: HttpUrl | None = None
    posted_at: datetime | None = None
    organization: str | None = None


class ResponseFixture(StrictModel):
    fixture_kind: str
    records: list[ResponseRecord]


class CommentFetchFailure(StrictModel):
    comment_id: str
    error_type: str


class CommentFetchReport(StrictModel):
    docket_id: str
    requested_count: int
    source_document_count: int = 0
    observed_candidate_count: int = 0
    attempted_count: int = 0
    retrieved_count: int = 0
    unusable_count: int = 0
    failures: list[CommentFetchFailure] = Field(default_factory=list)
    sampling_method: Literal["earliest", "random"] = "earliest"
    sampling_seed: int | None = None
    population_count: int | None = None
    population_object_ids: list[str] = Field(default_factory=list)
    selected_positions: list[int] = Field(default_factory=list)
    replacement_positions: list[int] = Field(default_factory=list)
    selected_comment_ids: list[str] = Field(default_factory=list)
    page_requests: list[str] = Field(default_factory=list)


class CommentFetchResult(StrictModel):
    records: list[ResponseRecord] = Field(default_factory=list)
    report: CommentFetchReport


class CommentFetchError(RuntimeError):
    def __init__(self, message: str, report: CommentFetchReport):
        super().__init__(message)
        self.report = report


def sanitize_public_text(text: str) -> tuple[str, PiiRedactionStatus]:
    redacted = _EMAIL_RE.sub("[REDACTED EMAIL]", text)
    redacted = _PHONE_RE.sub("[REDACTED PHONE]", redacted)

    if redacted != text:
        return redacted, PiiRedactionStatus.REDACTED
    return redacted, PiiRedactionStatus.NOT_DETECTED


def is_attachment_placeholder(text: str | None) -> bool:
    if not text:
        return False
    return bool(_ATTACHMENT_PLACEHOLDER_RE.fullmatch(text.strip()))


def duplicate_cluster_id(text: str) -> str:
    normalized = re.sub(r"\s+", " ", text).strip().casefold()
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]
    return f"exact-text-{digest}"


def source_from_response_record(record: ResponseRecord) -> Source:
    sanitized, pii_status = sanitize_public_text(record.text)
    return Source(
        id=f"response-{record.id}",
        title=record.title,
        information_type=record.information_type,
        url=record.url,
        submitted_at=record.posted_at,
        raw_text=sanitized,
        pii_redaction_status=pii_status,
        duplicate_cluster_id=(
            None
            if is_attachment_placeholder(sanitized)
            else duplicate_cluster_id(sanitized)
        ),
    )


def load_response_fixture(path: str | Path) -> list[ResponseRecord]:
    payload = ResponseFixture.model_validate_json(
        Path(path).read_text(encoding="utf-8")
    )
    return payload.records


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value)
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _get_json(
    path: str,
    *,
    api_key: str,
    params: dict[str, Any] | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    query = urlencode(params or {}, doseq=True)
    url = f"{REGULATIONS_GOV_BASE_URL}{path}"
    if query:
        url += f"?{query}"

    request = Request(
        url,
        headers={
            "X-Api-Key": api_key,
            "Accept": "application/vnd.api+json",
            "User-Agent": DEFAULT_USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


class _AttachmentHtmlTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        del attrs
        if tag in {"br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def text(self) -> str:
        return re.sub(r"\n{3,}", "\n\n", "".join(self.parts)).strip()


def _attachment_format(item: dict[str, Any]) -> str:
    value = str(item.get("format") or "").strip().lower()
    if "/" in value:
        value = value.rsplit("/", 1)[-1]
    value = value.lstrip(".")
    if value:
        return value

    file_url = str(item.get("fileUrl") or "")
    suffix = Path(urlparse(file_url).path).suffix.lower().lstrip(".")
    return suffix


def _attachment_candidates(
    detail: dict[str, Any],
) -> list[tuple[str, list[dict[str, Any]]]]:
    included = detail.get("included")
    if not isinstance(included, list):
        return []

    result: list[tuple[str, list[dict[str, Any]]]] = []
    for index, item in enumerate(included, start=1):
        if not isinstance(item, dict) or item.get("type") != "attachments":
            continue
        attributes = item.get("attributes")
        if not isinstance(attributes, dict):
            continue

        title = str(attributes.get("title") or f"Attachment {index}").strip()
        formats = attributes.get("fileFormats")
        if not isinstance(formats, list):
            continue

        supported = [
            candidate
            for candidate in formats
            if isinstance(candidate, dict)
            and candidate.get("fileUrl")
            and _attachment_format(candidate) in _ATTACHMENT_FORMAT_PRIORITY
        ]
        supported.sort(
            key=lambda candidate: _ATTACHMENT_FORMAT_PRIORITY[
                _attachment_format(candidate)
            ]
        )
        if supported:
            result.append((title, supported))

    return result


def _validate_attachment_url(file_url: str) -> None:
    parsed = urlparse(file_url)
    if parsed.scheme != "https" or parsed.hostname != "downloads.regulations.gov":
        raise ValueError(
            "attachment URL is not an approved Regulations.gov download host"
        )


def _download_attachment_bytes(
    file_url: str,
    *,
    timeout: int = 30,
    max_bytes: int = MAX_ATTACHMENT_BYTES,
) -> bytes:
    _validate_attachment_url(file_url)
    request = Request(
        file_url,
        headers={
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": "https://www.regulations.gov/",
            "User-Agent": ATTACHMENT_USER_AGENT,
        },
    )
    with urlopen(request, timeout=timeout) as response:
        payload = response.read(max_bytes + 1)
    if len(payload) > max_bytes:
        raise ValueError(
            f"attachment exceeds the {max_bytes}-byte PolicyTrace safety limit"
        )
    return payload


def _extract_docx_text(payload: bytes) -> str:
    with ZipFile(BytesIO(payload)) as archive:
        document_xml = archive.read("word/document.xml")
    root = ElementTree.fromstring(document_xml)

    parts: list[str] = []
    for element in root.iter():
        if element.tag.endswith("}t") and element.text:
            parts.append(element.text)
        elif element.tag.endswith("}p"):
            parts.append("\n")
    return re.sub(r"\n{3,}", "\n\n", "".join(parts)).strip()


DEGRADED_ATTACHMENT_MARKER = (
    "[PolicyTrace: this attachment extracted without word spacing."
)

MIN_SPACE_RATIO = 0.08
"""
Minimum spaces-per-character for extracted text to be usable.

Ordinary English prose runs about 0.16. Some PDFs extract with word spacing
dropped entirely -- "byemailingai_reporting@bis.doc.govonaquarterlybasis" --
which silently defeats both PII redaction and quote matching, because neither
a regex nor a model's quote can find word boundaries that are not there.
Nothing downstream can repair that, so it has to be visible.
"""


def extraction_is_degraded(text: str) -> bool:
    """True when extracted text lost its word spacing and cannot be trusted."""
    stripped = text.strip()
    if len(stripped) < 200:
        return False
    return (stripped.count(" ") / len(stripped)) < MIN_SPACE_RATIO


def _extract_attachment_payload(payload: bytes, format_name: str) -> str:
    fmt = format_name.lower()
    if fmt in {"txt", "text"}:
        text = payload.decode("utf-8", errors="replace")
    elif fmt in {"html", "htm"}:
        parser = _AttachmentHtmlTextParser()
        parser.feed(payload.decode("utf-8", errors="replace"))
        text = parser.text()
    elif fmt == "pdf":
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(payload))
        text = "\n\n".join(
            page.extract_text() or ""
            for page in reader.pages
        )
    elif fmt == "docx":
        text = _extract_docx_text(payload)
    else:
        raise ValueError(f"unsupported attachment format {format_name!r}")

    text = html.unescape(text)
    text = text.replace("\x00", "")
    # PDF extraction emits typographic ligatures: "deﬁned" is one character,
    # not "fi". NFKC decomposes them so the stored text matches what a model
    # writes when it quotes the passage. Done here, before offsets exist, so
    # stored offsets stay correct.
    text = unicodedata.normalize("NFKC", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if len(text) > MAX_ATTACHMENT_CHARS:
        text = (
            text[:MAX_ATTACHMENT_CHARS].rstrip()
            + "\n\n[Attachment text truncated by PolicyTrace.]"
        )
    return text


def _extract_attachment_texts(
    detail: dict[str, Any],
    *,
    timeout: int = 30,
) -> list[tuple[str, str]]:
    extracted: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    for title, formats in _attachment_candidates(detail):
        for candidate in formats:
            file_url = str(candidate["fileUrl"])
            if file_url in seen_urls:
                continue
            seen_urls.add(file_url)

            try:
                payload = _download_attachment_bytes(
                    file_url,
                    timeout=timeout,
                )
                text = _extract_attachment_payload(
                    payload,
                    _attachment_format(candidate),
                )
            except Exception as exc:
                warnings.warn(
                    f"Skipping Regulations.gov attachment {file_url}: {exc}",
                    RuntimeWarning,
                    stacklevel=2,
                )
                continue

            if text:
                extracted.append((title, text))
                break

    return extracted


def _combine_comment_and_attachments(
    comment: str,
    attachment_texts: list[tuple[str, str]],
) -> str:
    parts: list[str] = []
    clean_comment = comment.strip()
    if clean_comment and not is_attachment_placeholder(clean_comment):
        parts.append(clean_comment)

    for title, text in attachment_texts:
        if not text.strip():
            continue
        body = text.strip()
        if extraction_is_degraded(body):
            # Keep the text -- a human can still read it -- but say plainly
            # that automated redaction and citation cannot be relied on here.
            warnings.warn(
                f"attachment {title!r} extracted without word spacing; "
                "PII redaction and quote matching are unreliable for it",
                RuntimeWarning,
                stacklevel=2,
            )
            body = (
                DEGRADED_ATTACHMENT_MARKER
                + " Automated redaction and citation matching are unreliable for "
                "it and it needs human review.]\n"
                + body
            )
        parts.append(f"Attachment: {title}\n{body}")

    if parts:
        return "\n\n".join(parts)
    return clean_comment


def _comment_record_from_detail(
    comment_id: str,
    detail: dict[str, Any],
    *,
    attachment_texts: list[tuple[str, str]] | None = None,
) -> ResponseRecord | None:
    data = detail.get("data")
    if not isinstance(data, dict):
        return None

    attributes = data.get("attributes")
    if not isinstance(attributes, dict):
        return None

    raw_comment = attributes.get("comment")
    comment = raw_comment if isinstance(raw_comment, str) else ""
    text = _combine_comment_and_attachments(
        comment,
        attachment_texts or [],
    )
    if not text.strip():
        return None

    title = attributes.get("title")
    if not isinstance(title, str) or not title.strip():
        title = f"Regulations.gov comment {comment_id}"

    organization = attributes.get("organization")
    if organization is not None:
        organization = str(organization).strip() or None

    return ResponseRecord(
        id=comment_id,
        title=title,
        text=text,
        information_type=InformationType.PUBLIC_OPINION,
        url=f"https://www.regulations.gov/comment/{comment_id}",
        posted_at=_parse_datetime(attributes.get("postedDate")),
        organization=organization,
    )


def _fetch_comment_record(
    comment_id: str,
    *,
    api_key: str,
    timeout: int,
) -> ResponseRecord | None:
    detail = _get_json(
        f"/comments/{comment_id}",
        api_key=api_key,
        params={"include": "attachments"},
        timeout=timeout,
    )
    attachment_texts = _extract_attachment_texts(
        detail,
        timeout=timeout,
    )
    return _comment_record_from_detail(
        comment_id,
        detail,
        attachment_texts=attachment_texts,
    )


def _fetch_candidate_batch(
    candidate_ids: list[str],
    *,
    records: list[ResponseRecord],
    report: CommentFetchReport,
    attempted_comment_ids: set[str],
    api_key: str,
    timeout: int,
    max_comments: int,
) -> None:
    if not candidate_ids:
        return

    workers = min(COMMENT_FETCH_WORKERS, len(candidate_ids))
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [
            executor.submit(
                _fetch_comment_record,
                comment_id,
                api_key=api_key,
                timeout=timeout,
            )
            for comment_id in candidate_ids
        ]

        # Futures are consumed in submission order, so successful records
        # remain deterministic even when requests finish in a different order.
        for comment_id, future in zip(candidate_ids, futures):
            attempted_comment_ids.add(comment_id)
            report.attempted_count += 1
            try:
                record = future.result()
            except Exception as exc:
                report.failures.append(
                    CommentFetchFailure(
                        comment_id=comment_id,
                        error_type=type(exc).__name__,
                    )
                )
                continue

            if record is None:
                report.unusable_count += 1
                continue

            records.append(record)
            if len(records) >= max_comments:
                break


def _meta_total_elements(payload: dict[str, Any]) -> int:
    meta = payload.get("meta")
    if not isinstance(meta, dict) or "totalElements" not in meta:
        raise ValueError(
            "Regulations.gov comment search did not provide meta.totalElements"
        )
    try:
        total = int(meta["totalElements"])
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "Regulations.gov comment search returned an invalid totalElements"
        ) from exc
    if total < 0:
        raise ValueError("Regulations.gov totalElements must not be negative")
    return total


def _draw_unique_position(
    rng: random.Random,
    *,
    population_count: int,
    used_positions: set[int],
) -> int | None:
    if len(used_positions) >= population_count:
        return None

    while True:
        position = rng.randrange(1, population_count + 1)
        if position not in used_positions:
            used_positions.add(position)
            return position


def _position_target(
    position: int,
    populations: list[tuple[str, int]],
) -> tuple[str, int]:
    remaining = position
    for object_id, count in populations:
        if remaining <= count:
            return object_id, remaining
        remaining -= count
    raise ValueError(f"sample position {position} is outside the comment population")


def _comment_id_for_random_position(
    position: int,
    *,
    populations: list[tuple[str, int]],
    page_cache: dict[tuple[str, int], list[dict[str, Any]]],
    report: CommentFetchReport,
    api_key: str,
    timeout: int,
) -> str | None:
    object_id, local_position = _position_target(position, populations)
    page_number = ((local_position - 1) // COMMENT_PAGE_SIZE) + 1
    row_index = (local_position - 1) % COMMENT_PAGE_SIZE
    if page_number > MAX_COMMENT_PAGES:
        raise ValueError(
            "Random comment sampling cannot address a Regulations.gov page "
            f"beyond {MAX_COMMENT_PAGES}. Use earliest sampling for this docket."
        )

    cache_key = (object_id, page_number)
    rows = page_cache.get(cache_key)
    if rows is None:
        payload = _get_json(
            "/comments",
            api_key=api_key,
            params={
                "filter[commentOnId]": object_id,
                "page[size]": COMMENT_PAGE_SIZE,
                "page[number]": page_number,
                "sort": "postedDate,documentId",
            },
            timeout=timeout,
        )
        raw_rows = payload.get("data")
        rows = (
            [row for row in raw_rows if isinstance(row, dict)]
            if isinstance(raw_rows, list)
            else []
        )
        page_cache[cache_key] = rows
        report.page_requests.append(f"{object_id}:page {page_number}")

    if row_index >= len(rows):
        return None
    comment_id = rows[row_index].get("id")
    return str(comment_id) if comment_id else None


def fetch_comments_for_docket_with_report(
    docket_id: str,
    *,
    api_key: str | None = None,
    max_comments: int = 12,
    timeout: int = 30,
    sampling_method: Literal["earliest", "random"] = "earliest",
    sampling_seed: int | None = None,
) -> CommentFetchResult:
    if max_comments < 1 or max_comments > 100:
        raise ValueError("max_comments must be between 1 and 100")
    if sampling_method not in {"earliest", "random"}:
        raise ValueError("sampling_method must be 'earliest' or 'random'")
    if sampling_seed is not None and sampling_seed < 0:
        raise ValueError("sampling_seed must not be negative")

    key = api_key or os.environ.get("REGULATIONS_GOV_API_KEY")
    if not key:
        raise ValueError(
            "REGULATIONS_GOV_API_KEY is required for live Regulations.gov ingestion"
        )

    report = CommentFetchReport(
        docket_id=docket_id,
        requested_count=max_comments,
        sampling_method=sampling_method,
        sampling_seed=sampling_seed,
    )

    documents = _get_json(
        "/documents",
        api_key=key,
        params={
            "filter[docketId]": docket_id,
            "page[size]": 100,
        },
        timeout=timeout,
    )

    document_rows = documents.get("data")
    if not isinstance(document_rows, list):
        raise ValueError("Regulations.gov document search returned no data list")

    object_ids: list[str] = []
    seen_object_ids: set[str] = set()
    for row in document_rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("attributes")
        if not isinstance(attrs, dict):
            continue
        object_id = attrs.get("objectId")
        if not object_id:
            continue
        normalized = str(object_id)
        if normalized in seen_object_ids:
            continue
        seen_object_ids.add(normalized)
        object_ids.append(normalized)

    report.source_document_count = len(object_ids)

    if not object_ids:
        raise ValueError(
            f"no Regulations.gov document object IDs found for docket {docket_id}"
        )

    records: list[ResponseRecord] = []
    attempted_comment_ids: set[str] = set()
    observed_candidate_ids: set[str] = set()

    if sampling_method == "random":
        populations: list[tuple[str, int]] = []
        for object_id in sorted(object_ids):
            count_payload = _get_json(
                "/comments",
                api_key=key,
                params={
                    "filter[commentOnId]": object_id,
                    "page[size]": 1,
                    "page[number]": 1,
                    "sort": "postedDate,documentId",
                },
                timeout=timeout,
            )
            count = _meta_total_elements(count_payload)
            if count > MAX_RANDOM_COMMENTS_PER_OBJECT:
                raise ValueError(
                    "Random comment sampling currently supports up to "
                    f"{MAX_RANDOM_COMMENTS_PER_OBJECT} comments per "
                    "Regulations.gov source document because the API limits "
                    f"direct paging to {MAX_COMMENT_PAGES} pages. "
                    "Use earliest sampling for this docket."
                )
            if count:
                populations.append((object_id, count))

        population_count = sum(count for _, count in populations)
        report.population_count = population_count
        report.population_object_ids = [object_id for object_id, _ in populations]

        if population_count:
            seed = (
                sampling_seed
                if sampling_seed is not None
                else random.SystemRandom().randrange(0, 2**63)
            )
            report.sampling_seed = seed
            rng = random.Random(seed)
            used_positions: set[int] = set()
            page_cache: dict[tuple[str, int], list[dict[str, Any]]] = {}
            initial_round = True

            while (
                len(records) < max_comments
                and len(used_positions) < population_count
            ):
                remaining = max_comments - len(records)
                positions: list[int] = []
                for _ in range(remaining):
                    position = _draw_unique_position(
                        rng,
                        population_count=population_count,
                        used_positions=used_positions,
                    )
                    if position is None:
                        break
                    positions.append(position)

                if not positions:
                    break

                if initial_round:
                    report.selected_positions.extend(positions)
                    initial_round = False
                else:
                    report.replacement_positions.extend(positions)

                candidate_ids: list[str] = []
                batch_seen: set[str] = set()
                for position in positions:
                    comment_id = _comment_id_for_random_position(
                        position,
                        populations=populations,
                        page_cache=page_cache,
                        report=report,
                        api_key=key,
                        timeout=timeout,
                    )
                    if not comment_id:
                        report.unusable_count += 1
                        continue
                    if (
                        comment_id in attempted_comment_ids
                        or comment_id in batch_seen
                    ):
                        report.unusable_count += 1
                        continue
                    candidate_ids.append(comment_id)
                    batch_seen.add(comment_id)
                    observed_candidate_ids.add(comment_id)

                _fetch_candidate_batch(
                    candidate_ids,
                    records=records,
                    report=report,
                    attempted_comment_ids=attempted_comment_ids,
                    api_key=key,
                    timeout=timeout,
                    max_comments=max_comments,
                )
    else:
        for object_id in object_ids:
            if len(records) >= max_comments:
                break

            comments = _get_json(
                "/comments",
                api_key=key,
                params={
                    "filter[commentOnId]": object_id,
                    # Fetch extra IDs so a failed/unusable detail request can be
                    # replaced without reducing the requested usable corpus.
                    "page[size]": COMMENT_PAGE_SIZE,
                    "sort": "postedDate,documentId",
                },
                timeout=timeout,
            )

            rows = comments.get("data")
            if not isinstance(rows, list):
                continue

            candidate_ids: list[str] = []
            batch_seen: set[str] = set()
            for row in rows:
                if not isinstance(row, dict):
                    continue

                comment_id = row.get("id")
                if not comment_id:
                    continue

                normalized = str(comment_id)
                if normalized in attempted_comment_ids or normalized in batch_seen:
                    continue

                candidate_ids.append(normalized)
                batch_seen.add(normalized)
                observed_candidate_ids.add(normalized)

            cursor = 0
            while cursor < len(candidate_ids) and len(records) < max_comments:
                remaining = max_comments - len(records)
                batch = candidate_ids[cursor : cursor + remaining]
                cursor += len(batch)
                if not batch:
                    break
                _fetch_candidate_batch(
                    batch,
                    records=records,
                    report=report,
                    attempted_comment_ids=attempted_comment_ids,
                    api_key=key,
                    timeout=timeout,
                    max_comments=max_comments,
                )

    report.observed_candidate_count = len(observed_candidate_ids)
    report.retrieved_count = len(records)
    report.selected_comment_ids = [record.id for record in records]

    if not records and report.attempted_count:
        raise CommentFetchError(
            "No usable Regulations.gov comments could be retrieved; "
            f"attempted {report.attempted_count}, "
            f"failed {len(report.failures)}, "
            f"unusable {report.unusable_count}.",
            report,
        )

    return CommentFetchResult(records=records, report=report)

def fetch_comments_for_docket(
    docket_id: str,
    *,
    api_key: str | None = None,
    max_comments: int = 12,
    timeout: int = 30,
    sampling_method: Literal["earliest", "random"] = "earliest",
    sampling_seed: int | None = None,
) -> list[ResponseRecord]:
    return fetch_comments_for_docket_with_report(
        docket_id,
        api_key=api_key,
        max_comments=max_comments,
        timeout=timeout,
        sampling_method=sampling_method,
        sampling_seed=sampling_seed,
    ).records


from __future__ import annotations

import html
import json
import re
from datetime import date
from html.parser import HTMLParser
from typing import Any
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
    raw_text_url: str | None = None
    raw_text: str
    chunks: list[NormalizedChunk] = Field(default_factory=list)


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


def _guess_heading(chunk_text: str) -> str | None:
    lines = [line.strip() for line in chunk_text.splitlines() if line.strip()]
    for line in lines[:8]:
        if len(line) > 140:
            continue
        if line.startswith("§ "):
            return line
        if re.match(r"^(?:[IVXLC]+\.|[A-Z]\.|\d+\.)\s+", line):
            return line
        if line.lower() in {
            "background",
            "discussion of the proposed rule",
            "request for comments",
            "rulemaking requirements",
            "list of subjects in 15 cfr part 702",
        }:
            return line
        letters = [char for char in line if char.isalpha()]
        if letters and len(line) >= 4 and all(char.isupper() for char in letters):
            return line
    return None


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
                delimiter_width = 2 if search_window[best:best + 2] in {"\n\n", ". "} else 1
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
                heading=_guess_heading(chunk_value),
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
        docket_ids=_list_of_strings(metadata.get("docket_ids") or metadata.get("docket_id")),
        regulation_id_numbers=_list_of_strings(metadata.get("regulation_id_numbers")),
        citation=metadata.get("citation"),
        cfr_references=metadata.get("cfr_references") or [],
        html_url=metadata.get("html_url"),
        pdf_url=metadata.get("pdf_url"),
        regulations_dot_gov_url=metadata.get("regulations_dot_gov_url"),
        raw_text_url=metadata.get("raw_text_url"),
        raw_text=text,
        chunks=chunk_text(document_number, text, max_chars=max_chunk_chars),
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

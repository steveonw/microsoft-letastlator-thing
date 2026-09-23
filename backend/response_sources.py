from __future__ import annotations

import hashlib
import html
import json
import os
import re
import warnings
from datetime import datetime
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path
from typing import Any
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

_EMAIL_RE = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}(?![\w.-])")
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


def sanitize_public_text(text: str) -> tuple[str, PiiRedactionStatus]:
    redacted = _EMAIL_RE.sub("[REDACTED EMAIL]", text)
    redacted = _PHONE_RE.sub("[REDACTED PHONE]", redacted)

    if redacted != text:
        return redacted, PiiRedactionStatus.REDACTED
    return redacted, PiiRedactionStatus.NOT_DETECTED


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
        duplicate_cluster_id=duplicate_cluster_id(sanitized),
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
    if clean_comment and not _ATTACHMENT_PLACEHOLDER_RE.fullmatch(clean_comment):
        parts.append(clean_comment)

    for title, text in attachment_texts:
        if text.strip():
            parts.append(f"Attachment: {title}\n{text.strip()}")

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


def fetch_comments_for_docket(
    docket_id: str,
    *,
    api_key: str | None = None,
    max_comments: int = 12,
    timeout: int = 30,
) -> list[ResponseRecord]:
    if max_comments < 1 or max_comments > 100:
        raise ValueError("max_comments must be between 1 and 100")

    key = api_key or os.environ.get("REGULATIONS_GOV_API_KEY")
    if not key:
        raise ValueError(
            "REGULATIONS_GOV_API_KEY is required for live Regulations.gov ingestion"
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
    for row in document_rows:
        if not isinstance(row, dict):
            continue
        attrs = row.get("attributes")
        if not isinstance(attrs, dict):
            continue
        object_id = attrs.get("objectId")
        if object_id:
            object_ids.append(str(object_id))

    if not object_ids:
        raise ValueError(
            f"no Regulations.gov document object IDs found for docket {docket_id}"
        )

    records: list[ResponseRecord] = []
    seen_comment_ids: set[str] = set()

    for object_id in object_ids:
        remaining = max_comments - len(records)
        if remaining <= 0:
            break

        comments = _get_json(
            "/comments",
            api_key=key,
            params={
                "filter[commentOnId]": object_id,
                "page[size]": min(250, remaining),
                "sort": "postedDate,documentId",
            },
            timeout=timeout,
        )

        rows = comments.get("data")
        if not isinstance(rows, list):
            continue

        for row in rows:
            if len(records) >= max_comments:
                break
            if not isinstance(row, dict):
                continue

            comment_id = row.get("id")
            if not comment_id:
                continue

            comment_id = str(comment_id)
            if comment_id in seen_comment_ids:
                continue

            detail = _get_json(
                f"/comments/{comment_id}",
                api_key=key,
                params={"include": "attachments"},
                timeout=timeout,
            )
            attachment_texts = _extract_attachment_texts(
                detail,
                timeout=timeout,
            )
            record = _comment_record_from_detail(
                comment_id,
                detail,
                attachment_texts=attachment_texts,
            )
            if record is None:
                continue

            records.append(record)
            seen_comment_ids.add(comment_id)

    return records

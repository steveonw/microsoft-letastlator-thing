from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from models import InformationType, PiiRedactionStatus, Source


REGULATIONS_GOV_BASE_URL = "https://api.regulations.gov/v4"
DEFAULT_USER_AGENT = "PolicyTrace/0.1 (+https://github.com/steveonw/microsoft-letastlator-thing)"

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


def _comment_record_from_detail(
    comment_id: str,
    detail: dict[str, Any],
) -> ResponseRecord | None:
    data = detail.get("data")
    if not isinstance(data, dict):
        return None

    attributes = data.get("attributes")
    if not isinstance(attributes, dict):
        return None

    comment = attributes.get("comment")
    if not isinstance(comment, str) or not comment.strip():
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
        text=comment.strip(),
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
                timeout=timeout,
            )
            record = _comment_record_from_detail(comment_id, detail)
            if record is None:
                continue

            records.append(record)
            seen_comment_ids.add(comment_id)

    return records

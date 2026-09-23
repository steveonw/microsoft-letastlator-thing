"""Load user policy input as normalized documents for the analysis pipelines."""

from __future__ import annotations

import json
import re
from urllib.parse import urlsplit
from uuid import uuid4

from federal_register import NormalizedPolicyDocument, normalize_document
from models import InformationType
from source_ingest import MAX_SOURCE_CHARS, SourceInputError, extract_source_text


_DOCUMENT_NUMBER = re.compile(r"(?<!\d)(\d{4}-\d+)(?!\d)")


def federal_register_document_number(value: str) -> str:
    value = value.strip()
    if _DOCUMENT_NUMBER.fullmatch(value):
        return value

    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise SourceInputError("Enter a Federal Register document number or URL.") from exc
    host = (parsed.hostname or "").lower()
    if host not in {"federalregister.gov", "www.federalregister.gov"}:
        raise SourceInputError("Enter a Federal Register URL or document number.")
    match = _DOCUMENT_NUMBER.search(parsed.path)
    if not match:
        raise SourceInputError("The Federal Register URL does not contain a document number.")
    return match.group(1)


def _user_document(title: str, text: str) -> NormalizedPolicyDocument:
    clean_title = title.strip() or "User supplied policy"
    clean_text = text.strip()
    if not clean_text:
        raise SourceInputError("The policy text is empty.")
    if len(clean_text) > MAX_SOURCE_CHARS:
        raise SourceInputError("Policy text exceeds the 200,000 character demo limit.")
    return normalize_document(
        {
            "document_number": f"user-{uuid4().hex[:12]}",
            "title": clean_title,
            "type": "User-supplied policy text",
            "agency_names": [],
        },
        clean_text,
    )


def document_from_json(payload: object) -> tuple[NormalizedPolicyDocument, InformationType]:
    if not isinstance(payload, dict):
        raise SourceInputError("Policy JSON must be an object.")

    try:
        document = NormalizedPolicyDocument.model_validate(payload)
    except Exception:
        document = None
    if document is not None:
        # A user-provided JSON URL is metadata, not proof the body came from
        # the Federal Register. Only API-fetched or checked-in sources are official.
        return document, InformationType.UNVERIFIED

    metadata = payload.get("metadata")
    raw_text = payload.get("raw_text") or payload.get("text")
    if isinstance(metadata, dict) and isinstance(raw_text, str):
        if metadata.get("document_number") and metadata.get("title"):
            try:
                document = normalize_document(metadata, raw_text)
            except Exception as exc:
                raise SourceInputError("The policy JSON metadata is invalid.") from exc
            return document, InformationType.UNVERIFIED

    if isinstance(raw_text, str):
        title = payload.get("title")
        if not isinstance(title, str):
            title = "User supplied policy"
        return _user_document(title, raw_text), InformationType.UNVERIFIED

    raise SourceInputError(
        "Policy JSON must contain a normalized document, metadata with raw_text, or title and text."
    )


def document_from_file(
    filename: str,
    body: bytes,
    content_type: str | None,
    *,
    title: str | None = None,
) -> tuple[NormalizedPolicyDocument, InformationType]:
    if filename.lower().endswith(".json"):
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise SourceInputError("The policy JSON file is not valid UTF-8 JSON.") from exc
        return document_from_json(payload)

    extracted, extracted_title = extract_source_text(
        body,
        filename=filename,
        content_type=content_type or "",
    )
    return _user_document(title or extracted_title or filename, extracted), InformationType.UNVERIFIED


def document_from_pasted_text(
    text: str,
    *,
    title: str | None = None,
) -> tuple[NormalizedPolicyDocument, InformationType]:
    return _user_document(title or "Pasted policy text", text), InformationType.UNVERIFIED

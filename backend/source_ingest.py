"""Turn a submitted text, HTML, or PDF source into a traceable review draft."""

from __future__ import annotations

import ipaddress
import re
import socket
import ssl
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import PurePosixPath
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import uuid4

import certifi

from guided_review import begin_guided_review
from models import (
    AnalysisMode,
    AnalysisRun,
    AnalysisStep,
    Claim,
    Evidence,
    HumanReviewStatus,
    InformationType,
    PiiRedactionStatus,
    Policy,
    Source,
    StepKind,
    VerificationStatus,
)


MAX_SOURCE_BYTES = 5_000_000
MAX_SOURCE_CHARS = 200_000
USER_AGENT = "PolicyTrace demo/0.1"


class SourceInputError(ValueError):
    """A submitted source cannot be safely read as supported document text."""


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.title_parts: list[str] = []
        self.hidden = 0
        self.in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden += 1
        elif tag == "title":
            self.in_title = True
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript"}:
            self.hidden = max(0, self.hidden - 1)
        elif tag == "title":
            self.in_title = False
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "tr"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.hidden:
            return
        if self.in_title:
            self.title_parts.append(data)
        else:
            self.parts.append(data)


def _clean_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def extract_source_text(data: bytes, *, filename: str, content_type: str = "") -> tuple[str, str | None]:
    """Return extracted text and any HTML title from a bounded source body."""
    if not data:
        raise SourceInputError("The source is empty.")
    if len(data) > MAX_SOURCE_BYTES:
        raise SourceInputError("The source exceeds the 5 MB demo limit.")

    suffix = PurePosixPath(filename).suffix.lower()
    media_type = content_type.split(";", 1)[0].strip().lower()
    if suffix == ".pdf" or media_type == "application/pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(BytesIO(data))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise SourceInputError("The PDF could not be read as text.") from exc
        title = None
    elif suffix in {".html", ".htm"} or media_type in {"text/html", "application/xhtml+xml"}:
        parser = _HtmlText()
        parser.feed(data.decode("utf-8", errors="replace"))
        text = "".join(parser.parts)
        title = _clean_text(" ".join(parser.title_parts)) or None
    elif suffix in {".txt", ".md"} or media_type.startswith("text/plain"):
        text = data.decode("utf-8", errors="replace")
        title = None
    else:
        raise SourceInputError("Use a PDF, HTML, Markdown, or plain text source.")

    text = _clean_text(text)
    if not text:
        raise SourceInputError("No readable text was found in the source.")
    if len(text) > MAX_SOURCE_CHARS:
        raise SourceInputError("Extracted text exceeds the 200,000 character demo limit.")
    return text, title


def _validate_public_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except ValueError as exc:
        raise SourceInputError("Enter a valid public URL.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise SourceInputError("Enter a public HTTP or HTTPS URL.")
    if port not in {None, 80, 443}:
        raise SourceInputError("URLs must use the standard HTTP or HTTPS port.")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port or 443)
    except OSError as exc:
        raise SourceInputError("The URL host could not be resolved.") from exc
    if not addresses or any(
        not ipaddress.ip_address(address[4][0]).is_global for address in addresses
    ):
        raise SourceInputError("Local or private network URLs are not supported.")


class _PublicRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        _validate_public_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_source_url(url: str) -> tuple[str, str, str]:
    """Fetch a public URL with a size limit and return title, text, final URL."""
    _validate_public_url(url)
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        tls_context = ssl.create_default_context(cafile=certifi.where())
        opener = build_opener(_PublicRedirects(), HTTPSHandler(context=tls_context))
        with opener.open(request, timeout=12) as response:
            final_url = response.geturl()
            media_type = response.headers.get_content_type()
            data = response.read(MAX_SOURCE_BYTES + 1)
    except SourceInputError:
        raise
    except Exception as exc:
        raise SourceInputError("The URL could not be fetched.") from exc

    path_name = PurePosixPath(urlsplit(final_url).path).name or "webpage.html"
    text, html_title = extract_source_text(data, filename=path_name, content_type=media_type)
    return html_title or path_name or final_url, text, final_url


def build_source_review(
    title: str,
    text: str,
    *,
    url: str | None = None,
    source_information_type: InformationType = InformationType.UNVERIFIED,
) -> AnalysisRun:
    """Create one honest, source-backed step ready for human review."""
    run_id = uuid4().hex[:12]
    source_id = f"source-{run_id}"
    excerpt_end = min(len(text), 600)
    source = Source(
        id=source_id,
        title=title,
        information_type=source_information_type,
        url=url,
        raw_text=text,
        pii_redaction_status=PiiRedactionStatus.NOT_CHECKED,
    )
    evidence = Evidence(
        id=f"evidence-{run_id}",
        source_id=source_id,
        snippet=text[:excerpt_end],
        locator=f"chars 0-{excerpt_end}",
        start_offset=0,
        end_offset=excerpt_end,
        retrieved_at=datetime.now(timezone.utc),
    )
    claim = Claim(
        id=f"claim-{run_id}",
        text="The submitted source contains the excerpt shown in the evidence panel.",
        information_type=source_information_type,
        evidence_ids=[evidence.id],
        verification_status=VerificationStatus.NEEDS_HUMAN_REVIEW,
        verification_note="Source text was imported; policy meaning has not been analyzed.",
        confidence="low",
    )
    analysis = AnalysisRun(
        id=f"run-{run_id}",
        mode=AnalysisMode.GUIDED,
        policy=Policy(
            id=f"policy-{run_id}",
            title=title,
            jurisdiction="Not specified",
            source_ids=[source_id],
        ),
        sources=[source],
        evidence=[evidence],
        steps=[
            AnalysisStep(
                id=f"step-source-{run_id}",
                kind=StepKind.POLICY_UNDERSTANDING,
                title="Review submitted source",
                claims=[claim],
                ai_output=(
                    "The source was imported. Review its excerpt and record any "
                    "clarifications or edits. Policy interpretation has not been generated."
                ),
            )
        ],
        final_review_status=HumanReviewStatus.NOT_REVIEWED,
    )
    return begin_guided_review(analysis)

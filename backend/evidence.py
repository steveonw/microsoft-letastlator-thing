"""Turn normalized Federal Register documents into traceable demo analyses.

This module maps a document's metadata and raw text into the shared ``Source``
model, then locates literal query matches in that text. Evidence excerpts are
expanded to nearby word boundaries and retain source offsets plus a locator
built from the document citation, section heading, and chunk ID. Finally, the
demo builder links that evidence to a narrowly scoped claim and packages the
claim, evidence, source, policy, and review state into an ``AnalysisRun``.
"""

from __future__ import annotations

from datetime import datetime, timezone
import re

from federal_register import NormalizedChunk, NormalizedPolicyDocument
from models import (
    AnalysisMode,
    AnalysisRun,
    AnalysisStep,
    Claim,
    Evidence,
    HumanReview,
    HumanReviewStatus,
    InformationType,
    PiiRedactionStatus,
    Policy,
    Source,
    StepKind,
    StepStatus,
    VerificationStatus,
)


def source_from_federal_register(document: NormalizedPolicyDocument) -> Source:
    """Convert a normalized Federal Register document into the shared Source shape."""
    return Source(
        id=f"fr-{document.document_number}",
        title=document.title,
        information_type=InformationType.OFFICIAL_POLICY,
        url=document.html_url,
        agency=", ".join(document.agency_names) or None,
        published_at=document.publication_date,
        version=document.document_number,
        raw_text=document.raw_text,
        pii_redaction_status=PiiRedactionStatus.NOT_APPLICABLE,
    )


# Characters that mean the same thing but are written differently in the
# source and in model output. Federal Register plain text uses TeX-style
# ``quotes'' and PDF extraction yields curly quotes and en/em dashes, while a
# model quoting that text writes plain ASCII. Treating each group as
# interchangeable keeps matching exact on wording while ignoring typography.
_QUOTE_VARIANTS = "\"\u201c\u201d\u201e\u201f\u00ab\u00bb"
_APOSTROPHE_VARIANTS = "'\u2018\u2019\u201a\u201b\u00b4`"
_DASH_VARIANTS = "-\u2010\u2011\u2012\u2013\u2014\u2015\u2212"

_CHAR_CLASSES: dict[str, str] = {}
for _group in (_QUOTE_VARIANTS, _APOSTROPHE_VARIANTS, _DASH_VARIANTS):
    _class = f"[{re.escape(_group)}]"
    for _char in _group:
        _CHAR_CLASSES[_char] = _class

# Federal Register plain text writes double quotes as the TeX pairs ``like
# this'', which are two characters, so a single character class cannot cover
# them. Any double-quote variant in the query matches either form.
_DOUBLE_QUOTE_PATTERN = f"(?:[{re.escape(_QUOTE_VARIANTS)}]|``|'')"
for _char in _QUOTE_VARIANTS:
    _CHAR_CLASSES[_char] = _DOUBLE_QUOTE_PATTERN


def _token_pattern(token: str) -> str:
    """
    Match one query token while tolerating Federal Register hard wraps.

    Federal Register plain text can insert a newline after punctuation inside a
    token, for example "floating-\npoint" or "OP/\ns". Allow whitespace only
    after hyphens and slashes; all characters and punctuation remain otherwise
    exact, except that quotes, apostrophes and dashes match any variant of
    themselves.
    """
    parts: list[str] = []
    for char in token:
        parts.append(_CHAR_CLASSES.get(char, re.escape(char)))
        if char in _DASH_VARIANTS or char == "/":
            parts.append(r"\s*")
    return "".join(parts)


def find_quote_span(text: str, query: str) -> tuple[int, int]:
    """
    Locate a quoted passage while tolerating narrow source-formatting changes.

    Models often flatten hard line wraps into spaces. Matching token-by-token
    allows normal whitespace differences and Federal Register hard wraps after
    hyphens/slashes, while keeping wording and punctuation exact. Returned
    offsets always point into the original source text.
    """
    tokens = query.split()
    if not tokens:
        raise ValueError("query must not be empty")

    pattern = re.compile(
        r"\s+".join(_token_pattern(token) for token in tokens),
        flags=re.IGNORECASE,
    )
    match = pattern.search(text)
    if match is None:
        raise ValueError(f"query not found in source text: {query!r}")

    return match.start(), match.end()


def _find_match_in_source(
    document: NormalizedPolicyDocument,
    query: str,
) -> tuple[NormalizedChunk, int, int]:
    match_start, match_end = find_quote_span(document.raw_text, query)

    for chunk in document.chunks:
        if chunk.start_offset <= match_start < chunk.end_offset:
            return chunk, match_start, match_end

    # A match can begin in whitespace between chunks. Use the nearest following
    # chunk, or the final chunk as a stable locator fallback.
    for chunk in document.chunks:
        if chunk.start_offset > match_start:
            return chunk, match_start, match_end

    if document.chunks:
        return document.chunks[-1], match_start, match_end

    raise ValueError("normalized document has no chunks")


def _expand_window_to_word_boundaries(
    text: str,
    start: int,
    end: int,
) -> tuple[int, int]:
    """Expand a context window without ever trimming away the matched query."""
    if start > 0 and not text[start - 1].isspace() and not text[start].isspace():
        previous_space = text.rfind(" ", 0, start)
        previous_newline = text.rfind("\n", 0, start)
        boundary = max(previous_space, previous_newline)
        start = boundary + 1 if boundary >= 0 else 0

    if (
        end < len(text)
        and end > 0
        and not text[end - 1].isspace()
        and not text[end].isspace()
    ):
        next_space = text.find(" ", end)
        next_newline = text.find("\n", end)
        candidates = [value for value in (next_space, next_newline) if value >= 0]
        end = min(candidates) if candidates else len(text)

    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1

    return start, end


def locator_for(
    document: NormalizedPolicyDocument,
    chunk: NormalizedChunk,
    start_offset: int,
    end_offset: int,
) -> str:
    parts: list[str] = []
    if document.citation:
        parts.append(document.citation)
    if chunk.heading:
        parts.append(chunk.heading)
    parts.append(chunk.id)
    parts.append(f"chars {start_offset}-{end_offset}")
    return " | ".join(parts)


def evidence_for_query(
    document: NormalizedPolicyDocument,
    query: str,
    *,
    context_chars: int = 180,
    retrieved_at: datetime | None = None,
) -> Evidence:
    """
    Create exact, inspectable evidence around a source-grounded query.

    Matching tolerates narrow formatting changes from hard line wraps, but stored
    evidence is always sliced verbatim from the original source using exact offsets.
    """
    if context_chars < 0:
        raise ValueError("context_chars must be non-negative")

    chunk, global_match_start, global_match_end = _find_match_in_source(
        document,
        query,
    )

    global_start = max(0, global_match_start - context_chars)
    global_end = min(len(document.raw_text), global_match_end + context_chars)
    global_start, global_end = _expand_window_to_word_boundaries(
        document.raw_text,
        global_start,
        global_end,
    )
    snippet = document.raw_text[global_start:global_end]

    try:
        find_quote_span(snippet, query)
    except ValueError as exc:
        raise ValueError("evidence window lost the requested query") from exc
    if not snippet:
        raise ValueError("evidence snippet must not be empty")

    timestamp = retrieved_at or datetime.now(timezone.utc)

    return Evidence(
        id=(
            f"evidence-fr-{document.document_number}-"
            f"{global_start}-{global_end}"
        ),
        source_id=f"fr-{document.document_number}",
        snippet=snippet,
        locator=locator_for(
            document,
            chunk,
            global_start,
            global_end,
        ),
        start_offset=global_start,
        end_offset=global_end,
        retrieved_at=timestamp,
    )


def build_chunk3_demo_analysis(
    document: NormalizedPolicyDocument,
    *,
    query: str = "artificial intelligence",
    retrieved_at: datetime | None = None,
) -> AnalysisRun:
    """
    Build the smallest real-source AnalysisRun proving claim -> evidence -> source.

    The demo claim is intentionally narrow: it only says that the selected source
    contains discussion of the requested term. Core policy interpretation begins
    in Chunk 4.
    """
    source = source_from_federal_register(document)
    evidence = evidence_for_query(
        document,
        query,
        retrieved_at=retrieved_at,
    )

    claim = Claim(
        id="claim-real-source-evidence-001",
        text=(
            "The selected Federal Register source contains text discussing "
            f"{query}."
        ),
        information_type=InformationType.UNVERIFIED,
        evidence_ids=[evidence.id],
        verification_status=VerificationStatus.NEEDS_HUMAN_REVIEW,
        verification_note=(
            "Citation integrity checked. Semantic support still needs verification."
        ),
        confidence="high",
    )

    step = AnalysisStep(
        id="step-real-source-evidence",
        kind=StepKind.POLICY_UNDERSTANDING,
        title="Inspect real-source evidence",
        status=StepStatus.DRAFT,
        depends_on=[],
        claims=[claim],
        ai_output=(
            "Chunk 3 plumbing demo: the claim points to an exact passage in "
            "the normalized Federal Register source."
        ),
        human_review=HumanReview(
            status=HumanReviewStatus.NOT_REVIEWED,
        ),
        version=1,
    )

    return AnalysisRun(
        id=f"run-chunk3-{document.document_number}",
        mode=AnalysisMode.GUIDED,
        policy=Policy(
            id=f"policy-fr-{document.document_number}",
            title=document.title,
            jurisdiction="United States / federal",
            version=document.document_number,
            source_ids=[source.id],
        ),
        sources=[source],
        evidence=[evidence],
        steps=[step],
        current_step_id=step.id,
        final_review_status=HumanReviewStatus.NOT_REVIEWED,
    )

from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
from collections import defaultdict
from time import perf_counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from federal_register import NormalizedPolicyDocument
from models import AnalysisRun


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RevisionDocumentRef(StrictModel):
    document_number: str
    title: str
    document_type: str | None = None
    publication_date: date | None = None
    citation: str | None = None
    url: str | None = None


class RevisionChange(StrictModel):
    id: str
    kind: Literal["added", "removed", "changed"]
    tags: list[str] = Field(default_factory=list)
    before_text: str | None = None
    after_text: str | None = None
    before_start_offset: int | None = Field(default=None, ge=0)
    before_end_offset: int | None = Field(default=None, ge=0)
    after_start_offset: int | None = Field(default=None, ge=0)
    after_end_offset: int | None = Field(default=None, ge=0)
    before_locator: str | None = None
    after_locator: str | None = None
    before_url: str | None = None
    after_url: str | None = None
    potentially_affected_claim_ids: list[str] = Field(default_factory=list)


class RevisionComparison(StrictModel):
    from_document: RevisionDocumentRef
    to_document: RevisionDocumentRef
    shared_rins: list[str] = Field(default_factory=list)
    changes: list[RevisionChange] = Field(default_factory=list)
    added_count: int = Field(ge=0)
    removed_count: int = Field(ge=0)
    changed_count: int = Field(ge=0)
    tag_counts: dict[str, int] = Field(default_factory=dict)
    potentially_affected_claim_ids: list[str] = Field(default_factory=list)
    comparison_seconds: float = Field(ge=0)
    from_unit_count: int = Field(ge=0)
    to_unit_count: int = Field(ge=0)
    warning: str = (
        "This is a deterministic text comparison. It identifies changed source "
        "language but does not by itself establish the legal or policy effect of a change."
    )


class _Unit(StrictModel):
    text: str
    normalized: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(ge=0)


_MONTHS = (
    "January|February|March|April|May|June|July|August|September|October|"
    "November|December"
)
_DATE_RE = re.compile(
    rf"\b(?:{_MONTHS})\s+\d{{1,2}}(?:,\s*\d{{4}})?\b"
    r"|\b\d{1,2}/\d{1,2}/\d{2,4}\b"
    r"|\b\d{4}-\d{2}-\d{2}\b"
    r"|\bQ[1-4]\b"
    r"|\b\d+\s+(?:calendar\s+)?(?:day|days|week|weeks|month|months|quarter|quarters|year|years)\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"\b10\^\d+\b"
    r"|\b\d+(?:,\d{3})*(?:\.\d+)?\s*(?:%|percent|Gbit/s|Gbit|Mbit/s|"
    r"operations?|OP/s|hours?|days?|weeks?|months?|quarters?|years?)\b",
    re.IGNORECASE,
)
_WORD_RE = re.compile(r"[a-z0-9]+(?:\^[a-z0-9]+)?", re.IGNORECASE)
MAX_FUZZY_CANDIDATES = 5
MAX_TOKEN_POSTINGS = 48
MIN_CHEAP_CANDIDATE_SCORE = 0.12
MIN_SEQUENCE_MATCH_RATIO = 0.48
CRIB_WIDTH = 4
MAX_CRIB_POSTINGS = 2
SEQUENCE_CORRIDOR_RADIUS = 3
FUZZY_HEAD_CHARS = 600
FUZZY_TAIL_CHARS = 300

_STAKEHOLDER_TERMS = (
    "covered u.s. person",
    "covered person",
    "company",
    "companies",
    "individual",
    "individuals",
    "organization",
    "organizations",
    "entity",
    "entities",
    "developer",
    "developers",
    "provider",
    "providers",
    "small entity",
    "small entities",
    "business",
    "businesses",
    "agency",
    "agencies",
)


def _document_ref(document: NormalizedPolicyDocument) -> RevisionDocumentRef:
    return RevisionDocumentRef(
        document_number=document.document_number,
        title=document.title,
        document_type=document.document_type,
        publication_date=document.publication_date,
        citation=document.citation,
        url=document.html_url,
    )


def _normalize_for_diff(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().casefold()


def _split_span(
    text: str,
    start: int,
    end: int,
    *,
    max_chars: int = 1800,
) -> list[_Unit]:
    units: list[_Unit] = []
    cursor = start

    while cursor < end:
        while cursor < end and text[cursor].isspace():
            cursor += 1
        if cursor >= end:
            break

        target = min(cursor + max_chars, end)
        split_at = target
        if target < end:
            lower = min(cursor + 700, target)
            window = text[lower:target]
            candidates = [
                window.rfind("\n"),
                window.rfind(". "),
                window.rfind("; "),
            ]
            best = max(candidates)
            if best >= 0:
                width = 2 if window[best:best + 2] in {". ", "; "} else 1
                split_at = lower + best + width

        while split_at > cursor and text[split_at - 1].isspace():
            split_at -= 1
        if split_at <= cursor:
            split_at = target

        value = text[cursor:split_at]
        normalized = _normalize_for_diff(value)
        if normalized:
            units.append(
                _Unit(
                    text=value,
                    normalized=normalized,
                    start_offset=cursor,
                    end_offset=split_at,
                )
            )
        cursor = split_at

    return units


def _text_units(text: str) -> list[_Unit]:
    spans = list(re.finditer(r"\S(?:.*?\S)?(?=\n\s*\n|\Z)", text, re.DOTALL))
    if not spans:
        return _split_span(text, 0, len(text))

    units: list[_Unit] = []
    for match in spans:
        units.extend(_split_span(text, match.start(), match.end()))
    return units


def _containing_heading(
    document: NormalizedPolicyDocument,
    offset: int | None,
) -> str:
    if offset is None:
        return "Federal Register document body"
    for chunk in document.chunks:
        if chunk.start_offset <= offset < chunk.end_offset:
            return chunk.heading or "Federal Register document body"
    return "Federal Register document body"


def _locator(
    document: NormalizedPolicyDocument,
    start: int | None,
    end: int | None,
) -> str | None:
    if start is None or end is None:
        return None
    parts = [
        document.citation or document.document_number,
        _containing_heading(document, start),
        f"chars {start}-{end}",
    ]
    return " | ".join(parts)


def _term_set(pattern: re.Pattern[str], text: str | None) -> set[str]:
    if not text:
        return set()
    return {
        re.sub(r"\s+", " ", match.group(0)).strip().casefold()
        for match in pattern.finditer(text)
    }


def _stakeholder_terms(text: str | None) -> set[str]:
    value = (text or "").casefold()
    return {term for term in _STAKEHOLDER_TERMS if term in value}


def _change_tags(before: str | None, after: str | None) -> list[str]:
    tags: list[str] = []

    if _term_set(_DATE_RE, before) != _term_set(_DATE_RE, after):
        if _term_set(_DATE_RE, before) or _term_set(_DATE_RE, after):
            tags.append("deadline/date")

    if _term_set(_NUMBER_RE, before) != _term_set(_NUMBER_RE, after):
        if _term_set(_NUMBER_RE, before) or _term_set(_NUMBER_RE, after):
            tags.append("threshold/number")

    if _stakeholder_terms(before) != _stakeholder_terms(after):
        if _stakeholder_terms(before) or _stakeholder_terms(after):
            tags.append("stakeholder-scope language")

    if not tags:
        tags.append("text")
    return tags


def _make_change(
    *,
    sequence: int,
    kind: Literal["added", "removed", "changed"],
    before: _Unit | None,
    after: _Unit | None,
    before_document: NormalizedPolicyDocument,
    after_document: NormalizedPolicyDocument,
) -> RevisionChange:
    return RevisionChange(
        id=f"revision-change-{sequence:03d}",
        kind=kind,
        tags=_change_tags(
            None if before is None else before.text,
            None if after is None else after.text,
        ),
        before_text=None if before is None else before.text,
        after_text=None if after is None else after.text,
        before_start_offset=None if before is None else before.start_offset,
        before_end_offset=None if before is None else before.end_offset,
        after_start_offset=None if after is None else after.start_offset,
        after_end_offset=None if after is None else after.end_offset,
        before_locator=(
            None
            if before is None
            else _locator(
                before_document,
                before.start_offset,
                before.end_offset,
            )
        ),
        after_locator=(
            None
            if after is None
            else _locator(
                after_document,
                after.start_offset,
                after.end_offset,
            )
        ),
        before_url=before_document.html_url if before is not None else None,
        after_url=after_document.html_url if after is not None else None,
    )


def _word_tokens(text: str) -> set[str]:
    return {
        match.group(0).casefold()
        for match in _WORD_RE.finditer(text)
        if len(match.group(0)) >= 2
    }


def _word_similarity(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    shared = len(left & right)
    return (2.0 * shared) / (len(left) + len(right))


def _phrase_cribs(text: str, *, width: int = CRIB_WIDTH) -> set[tuple[str, ...]]:
    tokens = [match.group(0).casefold() for match in _WORD_RE.finditer(text)]
    if len(tokens) < width:
        return set()
    return {
        tuple(tokens[index:index + width])
        for index in range(len(tokens) - width + 1)
        if not all(token.isdigit() for token in tokens[index:index + width])
    }


def _rare_crib_candidates(
    before_units: list[_Unit],
    after_units: list[_Unit],
) -> tuple[dict[int, dict[int, int]], list[tuple[int, int]]]:
    before_cribs = [_phrase_cribs(unit.normalized) for unit in before_units]
    after_cribs = [_phrase_cribs(unit.normalized) for unit in after_units]

    before_postings: dict[tuple[str, ...], list[int]] = defaultdict(list)
    after_postings: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for index, cribs in enumerate(before_cribs):
        for crib in cribs:
            before_postings[crib].append(index)
    for index, cribs in enumerate(after_cribs):
        for crib in cribs:
            after_postings[crib].append(index)

    votes: dict[int, dict[int, int]] = defaultdict(lambda: defaultdict(int))
    for crib, before_indices in before_postings.items():
        after_indices = after_postings.get(crib, [])
        if not after_indices:
            continue
        if (
            len(before_indices) > MAX_CRIB_POSTINGS
            or len(after_indices) > MAX_CRIB_POSTINGS
        ):
            continue
        for before_index in before_indices:
            for after_index in after_indices:
                votes[before_index][after_index] += 1

    raw_anchors: list[tuple[int, int, int]] = []
    for before_index, matches in votes.items():
        if not matches:
            continue
        after_index, count = max(
            matches.items(),
            key=lambda item: (item[1], -item[0]),
        )
        if count >= 2:
            raw_anchors.append((before_index, after_index, count))

    # Patience-diff style monotonic anchors: distinctive shared phrases act as
    # "cribs" and establish a sequence corridor without forcing moved text to
    # stay local. The global token index below can still recover true moves.
    anchors: list[tuple[int, int]] = []
    last_after = -1
    used_after: set[int] = set()
    for before_index, after_index, _ in sorted(
        raw_anchors,
        key=lambda item: (item[0], -item[2], item[1]),
    ):
        if after_index <= last_after or after_index in used_after:
            continue
        anchors.append((before_index, after_index))
        used_after.add(after_index)
        last_after = after_index

    return {
        before_index: dict(matches)
        for before_index, matches in votes.items()
    }, anchors


def _sequence_expected_index(
    before_index: int,
    *,
    before_count: int,
    after_count: int,
    anchors: list[tuple[int, int]],
) -> int:
    if after_count <= 1:
        return 0
    if before_count <= 1:
        return 0

    left: tuple[int, int] | None = None
    right: tuple[int, int] | None = None
    for anchor_before, anchor_after in anchors:
        if anchor_before <= before_index:
            left = (anchor_before, anchor_after)
        if anchor_before >= before_index:
            right = (anchor_before, anchor_after)
            break

    if left and right and left[0] != right[0]:
        span = right[0] - left[0]
        fraction = (before_index - left[0]) / span
        expected = round(left[1] + fraction * (right[1] - left[1]))
    elif left:
        expected = left[1] + (before_index - left[0])
    elif right:
        expected = right[1] - (right[0] - before_index)
    else:
        expected = round(
            (before_index / (before_count - 1))
            * (after_count - 1)
        )
    return max(0, min(after_count - 1, expected))


def _bounded_fuzzy_text(text: str) -> str:
    if len(text) <= FUZZY_HEAD_CHARS + FUZZY_TAIL_CHARS:
        return text
    return (
        text[:FUZZY_HEAD_CHARS]
        + " ... "
        + text[-FUZZY_TAIL_CHARS:]
    )


def _relative_position_score(
    before_index: int,
    before_count: int,
    after_index: int,
    after_count: int,
) -> float:
    if before_count <= 1 or after_count <= 1:
        return 1.0
    before_pos = before_index / (before_count - 1)
    after_pos = after_index / (after_count - 1)
    return max(0.0, 1.0 - abs(before_pos - after_pos))


def _exact_pairs(
    before_units: list[_Unit],
    after_units: list[_Unit],
) -> tuple[
    list[tuple[_Unit, _Unit]],
    set[int],
    set[int],
]:
    after_by_text: dict[str, list[int]] = defaultdict(list)
    for index, unit in enumerate(after_units):
        after_by_text[unit.normalized].append(index)

    pairs: list[tuple[_Unit, _Unit]] = []
    used_before: set[int] = set()
    used_after: set[int] = set()

    for before_index, before in enumerate(before_units):
        choices = [
            index
            for index in after_by_text.get(before.normalized, [])
            if index not in used_after
        ]
        if not choices:
            continue
        after_index = min(
            choices,
            key=lambda index: (
                -_relative_position_score(
                    before_index,
                    len(before_units),
                    index,
                    len(after_units),
                ),
                index,
            ),
        )
        used_before.add(before_index)
        used_after.add(after_index)
        pairs.append((before, after_units[after_index]))

    return pairs, used_before, used_after


def _candidate_after_indices(
    *,
    before_index: int,
    before_tokens: set[str],
    token_index: dict[str, list[int]],
    after_token_sets: list[set[str]],
    before_count: int,
    after_count: int,
    excluded_after: set[int],
    crib_votes: dict[int, int],
    anchors: list[tuple[int, int]],
) -> list[tuple[int, int]]:
    candidate_indices: set[int] = set()

    # Like Read-Aloud's edited-sentence resolver: use cheap word overlap to
    # shortlist plausible places, then reserve SequenceMatcher for only the
    # strongest candidates. Very common tokens are deliberately ignored.
    for token in before_tokens:
        postings = token_index.get(token, [])
        if len(postings) <= MAX_TOKEN_POSTINGS:
            candidate_indices.update(postings)

    candidate_indices.update(crib_votes)
    candidate_indices.difference_update(excluded_after)

    # Anchor-guided sequence corridor: analogous to aligning nearby video
    # frames after a few known synchronization points. This adds only a small
    # local band; the token/crib index can still nominate far-away moved text.
    if after_count:
        center = _sequence_expected_index(
            before_index,
            before_count=before_count,
            after_count=after_count,
            anchors=anchors,
        )
        for offset in range(
            -SEQUENCE_CORRIDOR_RADIUS,
            SEQUENCE_CORRIDOR_RADIUS + 1,
        ):
            index = center + offset
            if 0 <= index < after_count and index not in excluded_after:
                candidate_indices.add(index)

    scored: list[tuple[float, int, int]] = []
    for after_index in candidate_indices:
        overlap = _word_similarity(
            before_tokens,
            after_token_sets[after_index],
        )
        position = _relative_position_score(
            before_index,
            before_count,
            after_index,
            after_count,
        )
        crib_count = crib_votes.get(after_index, 0)
        score = overlap + 0.08 * position + min(crib_count, 3) * 0.10
        if score >= MIN_CHEAP_CANDIDATE_SCORE:
            scored.append((score, crib_count, after_index))

    scored.sort(key=lambda item: (-item[0], -item[1], item[2]))
    return [
        (after_index, crib_count)
        for _, crib_count, after_index
        in scored[:MAX_FUZZY_CANDIDATES]
    ]


def _pair_replacements(
    before_units: list[_Unit],
    after_units: list[_Unit],
) -> tuple[list[tuple[_Unit, _Unit]], list[_Unit], list[_Unit]]:
    pairs, used_before, used_after = _exact_pairs(
        before_units,
        after_units,
    )

    crib_candidates, anchors = _rare_crib_candidates(
        before_units,
        after_units,
    )
    after_token_sets = [
        _word_tokens(unit.normalized)
        for unit in after_units
    ]
    token_index: dict[str, list[int]] = defaultdict(list)
    for after_index, tokens in enumerate(after_token_sets):
        for token in tokens:
            token_index[token].append(after_index)

    candidates: list[tuple[float, float, int, int]] = []
    for before_index, before in enumerate(before_units):
        if before_index in used_before:
            continue
        before_tokens = _word_tokens(before.normalized)
        shortlist = _candidate_after_indices(
            before_index=before_index,
            before_tokens=before_tokens,
            token_index=token_index,
            after_token_sets=after_token_sets,
            before_count=len(before_units),
            after_count=len(after_units),
            excluded_after=used_after,
            crib_votes=crib_candidates.get(before_index, {}),
            anchors=anchors,
        )

        for after_index, crib_count in shortlist:
            after = after_units[after_index]
            ratio = SequenceMatcher(
                None,
                _bounded_fuzzy_text(before.normalized),
                _bounded_fuzzy_text(after.normalized),
                autojunk=False,
            ).ratio()
            cheap_score = _word_similarity(
                before_tokens,
                after_token_sets[after_index],
            )

            # Conservative promotion into "changed": a fuzzy score alone is
            # not enough. Prefer shared distinctive phrase cribs; otherwise
            # require substantially stronger lexical overlap.
            confident = (
                ratio >= MIN_SEQUENCE_MATCH_RATIO
                and (
                    crib_count >= 1
                    or (ratio >= 0.62 and cheap_score >= 0.40)
                )
            )
            if not confident:
                continue
            candidates.append(
                (ratio, cheap_score, before_index, after_index)
            )

    for ratio, cheap_score, before_index, after_index in sorted(
        candidates,
        key=lambda item: (-item[0], -item[1], item[2], item[3]),
    ):
        del ratio, cheap_score
        if before_index in used_before or after_index in used_after:
            continue
        used_before.add(before_index)
        used_after.add(after_index)
        pairs.append((before_units[before_index], after_units[after_index]))

    pairs.sort(key=lambda pair: pair[0].start_offset)
    removed = [
        unit for index, unit in enumerate(before_units) if index not in used_before
    ]
    added = [
        unit for index, unit in enumerate(after_units) if index not in used_after
    ]
    return pairs, removed, added


def compare_documents(
    first: NormalizedPolicyDocument,
    second: NormalizedPolicyDocument,
) -> RevisionComparison:
    if first.document_number == second.document_number:
        raise ValueError("revision comparison requires two different documents")

    before_document = first
    after_document = second
    if (
        first.publication_date is not None
        and second.publication_date is not None
        and second.publication_date < first.publication_date
    ):
        before_document, after_document = second, first

    comparison_started = perf_counter()
    before_units = _text_units(before_document.raw_text)
    after_units = _text_units(after_document.raw_text)
    before_keys = [unit.normalized for unit in before_units]
    after_keys = [unit.normalized for unit in after_units]

    matcher = SequenceMatcher(None, before_keys, after_keys, autojunk=False)
    changes: list[RevisionChange] = []
    pending_removed: list[_Unit] = []
    pending_added: list[_Unit] = []
    sequence = 1

    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == "equal":
            continue

        if opcode == "delete":
            pending_removed.extend(before_units[i1:i2])
            continue

        if opcode == "insert":
            pending_added.extend(after_units[j1:j2])
            continue

        pairs, removed, added = _pair_replacements(
            before_units[i1:i2],
            after_units[j1:j2],
        )
        for before, after in pairs:
            changes.append(
                _make_change(
                    sequence=sequence,
                    kind="changed",
                    before=before,
                    after=after,
                    before_document=before_document,
                    after_document=after_document,
                )
            )
            sequence += 1
        pending_removed.extend(removed)
        pending_added.extend(added)

    # SequenceMatcher can represent moved text as a delete in one opcode and
    # an insert somewhere else. Give the same conservative crib/token matcher
    # one document-wide chance to recover those moved/edited provisions.
    moved_pairs, pending_removed, pending_added = _pair_replacements(
        pending_removed,
        pending_added,
    )
    for before, after in moved_pairs:
        changes.append(
            _make_change(
                sequence=sequence,
                kind="changed",
                before=before,
                after=after,
                before_document=before_document,
                after_document=after_document,
            )
        )
        sequence += 1

    for unit in pending_removed:
        changes.append(
            _make_change(
                sequence=sequence,
                kind="removed",
                before=unit,
                after=None,
                before_document=before_document,
                after_document=after_document,
            )
        )
        sequence += 1
    for unit in pending_added:
        changes.append(
            _make_change(
                sequence=sequence,
                kind="added",
                before=None,
                after=unit,
                before_document=before_document,
                after_document=after_document,
            )
        )
        sequence += 1

    changes.sort(
        key=lambda change: (
            change.before_start_offset
            if change.before_start_offset is not None
            else 10**12 + (change.after_start_offset or 0)
        )
    )
    for index, change in enumerate(changes, start=1):
        change.id = f"revision-change-{index:03d}"

    tag_counts: dict[str, int] = {}
    for change in changes:
        for tag in change.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1

    return RevisionComparison(
        from_document=_document_ref(before_document),
        to_document=_document_ref(after_document),
        shared_rins=sorted(
            set(before_document.regulation_id_numbers)
            & set(after_document.regulation_id_numbers)
        ),
        changes=changes,
        added_count=sum(change.kind == "added" for change in changes),
        removed_count=sum(change.kind == "removed" for change in changes),
        changed_count=sum(change.kind == "changed" for change in changes),
        tag_counts=tag_counts,
        comparison_seconds=round(perf_counter() - comparison_started, 3),
        from_unit_count=len(before_units),
        to_unit_count=len(after_units),
    )


def link_existing_claims(
    comparison: RevisionComparison,
    analysis: AnalysisRun,
    *,
    analyzed_document_number: str,
) -> RevisionComparison:
    updated = comparison.model_copy(deep=True)
    policy_source_ids = set(analysis.policy.source_ids)
    evidence_map = {
        evidence.id: evidence
        for evidence in analysis.evidence
        if evidence.source_id in policy_source_ids
    }

    claims_by_evidence: dict[str, set[str]] = {}
    for step in analysis.steps:
        for claim in step.claims:
            for evidence_id in claim.evidence_ids:
                if evidence_id in evidence_map:
                    claims_by_evidence.setdefault(evidence_id, set()).add(claim.id)

    analyzed_is_before = (
        analyzed_document_number == updated.from_document.document_number
    )
    analyzed_is_after = (
        analyzed_document_number == updated.to_document.document_number
    )
    if not analyzed_is_before and not analyzed_is_after:
        return updated

    all_claim_ids: set[str] = set()
    for change in updated.changes:
        if analyzed_is_before:
            start = change.before_start_offset
            end = change.before_end_offset
        else:
            start = change.after_start_offset
            end = change.after_end_offset

        if start is None or end is None:
            continue

        affected: set[str] = set()
        for evidence_id, evidence in evidence_map.items():
            if evidence.start_offset is None or evidence.end_offset is None:
                continue
            if evidence.start_offset < end and start < evidence.end_offset:
                affected.update(claims_by_evidence.get(evidence_id, set()))

        change.potentially_affected_claim_ids = sorted(affected)
        all_claim_ids.update(affected)

    updated.potentially_affected_claim_ids = sorted(all_claim_ids)
    return updated


def leadership_revision_summary(comparison: RevisionComparison) -> str:
    tags = ", ".join(
        f"{key}={value}"
        for key, value in sorted(comparison.tag_counts.items())
    ) or "none"
    affected = ", ".join(comparison.potentially_affected_claim_ids) or "none"
    return "\n".join(
        [
            "## Revision comparison",
            (
                f"- Compared: {comparison.from_document.document_number} "
                f"({comparison.from_document.publication_date or 'date unknown'}) -> "
                f"{comparison.to_document.document_number} "
                f"({comparison.to_document.publication_date or 'date unknown'})"
            ),
            (
                f"- Text changes: {comparison.changed_count} changed, "
                f"{comparison.added_count} added, {comparison.removed_count} removed"
            ),
            f"- Change flags: {tags}",
            f"- Existing claim IDs that may need refresh: {affected}",
            f"- Limitation: {comparison.warning}",
        ]
    )


def revision_audit_text(comparison: RevisionComparison) -> str:
    lines = [
        "## Revision comparison audit",
        (
            f"Compared {comparison.from_document.document_number} -> "
            f"{comparison.to_document.document_number}"
        ),
        f"Limitation: {comparison.warning}",
    ]

    for change in comparison.changes:
        lines.extend(
            [
                "",
                f"### {change.id}",
                f"- Kind: {change.kind}",
                f"- Tags: {', '.join(change.tags)}",
                (
                    "- Existing claims that may need refresh: "
                    + (
                        ", ".join(change.potentially_affected_claim_ids)
                        if change.potentially_affected_claim_ids
                        else "none"
                    )
                ),
            ]
        )
        if change.before_text is not None:
            lines.append(f"- Before locator: {change.before_locator}")
            if change.before_url:
                lines.append(f"- Before source: {change.before_url}")
            lines.extend(["- Before text:", change.before_text])
        if change.after_text is not None:
            lines.append(f"- After locator: {change.after_locator}")
            if change.after_url:
                lines.append(f"- After source: {change.after_url}")
            lines.extend(["- After text:", change.after_text])

    return "\n".join(lines)

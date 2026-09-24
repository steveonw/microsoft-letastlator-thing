from __future__ import annotations

import re
from datetime import date
from difflib import SequenceMatcher
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


def _pair_replacements(
    before_units: list[_Unit],
    after_units: list[_Unit],
) -> tuple[list[tuple[_Unit, _Unit]], list[_Unit], list[_Unit]]:
    candidates: list[tuple[float, int, int]] = []
    for before_index, before in enumerate(before_units):
        for after_index, after in enumerate(after_units):
            ratio = SequenceMatcher(
                None,
                before.normalized,
                after.normalized,
                autojunk=False,
            ).ratio()
            if ratio >= 0.38:
                candidates.append((ratio, before_index, after_index))

    pairs: list[tuple[_Unit, _Unit]] = []
    used_before: set[int] = set()
    used_after: set[int] = set()

    for ratio, before_index, after_index in sorted(
        candidates,
        key=lambda item: (-item[0], item[1], item[2]),
    ):
        del ratio
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

    before_units = _text_units(before_document.raw_text)
    after_units = _text_units(after_document.raw_text)
    before_keys = [unit.normalized for unit in before_units]
    after_keys = [unit.normalized for unit in after_units]

    matcher = SequenceMatcher(None, before_keys, after_keys, autojunk=False)
    changes: list[RevisionChange] = []
    sequence = 1

    for opcode, i1, i2, j1, j2 in matcher.get_opcodes():
        if opcode == "equal":
            continue

        if opcode == "delete":
            for unit in before_units[i1:i2]:
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
            continue

        if opcode == "insert":
            for unit in after_units[j1:j2]:
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
        for unit in removed:
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
        for unit in added:
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

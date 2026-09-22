# PolicyTrace shared contract

For the hackathon MVP, **JSON is the canonical contract** between the frontend, backend, and later AI/retrieval components.

The goal is to keep the contract small enough that every teammate can understand it quickly while making broken evidence references difficult to hide.

## Core relationship

```text
AnalysisRun
 ├── Policy
 ├── Sources[]
 ├── Evidence[]
 └── AnalysisSteps[]
       └── Claims[]
             └── evidence_ids[]
```

A claim points to one or more `Evidence` records by ID. Each evidence record points back to its original `Source`.

## Contract version

Current MVP contract: **0.2.0**

## Files

- `policytrace.schema.json` — canonical JSON shape for the MVP.
- `sample-analysis.json` — fictional end-to-end sample used for development.
- `../backend/models.py` — matching Pydantic models and cross-reference validation.
- `../frontend/types/policytrace.ts` — matching TypeScript types.
- `../backend/test_contract.py` — contract integrity tests.

## Rules enforced by the backend

1. Source, evidence, step, and claim IDs must be unique.
2. Policy source IDs must point to real sources.
3. Evidence must point to a real source.
4. When source text is available, evidence snippets must actually occur in that source.
5. If offsets are stored, they must reproduce the exact evidence snippet.
6. Claims cannot cite missing evidence.
7. Supported or partially supported claims must cite evidence.
8. Non-supported verification states require a verifier explanation.
9. Step dependencies must exist and cannot form cycles.
10. Human-review flags/edits must point to claims inside that step.
11. The current step must exist.
12. Rush and Guided modes use the same shared objects.

## Evidence offsets

Evidence can store `start_offset` and `end_offset` into the source's `raw_text`.

That enables deterministic checks before an LLM verifier is used:

```text
source.raw_text[start_offset:end_offset] == evidence.snippet
```

This catches fabricated or mislocated quote text cheaply.

## Human edits and verification notes

A claim can keep:

- `original_text` — the prior AI wording before a human or verifier narrows it
- `text` — the current accepted wording
- `verification_note` — why a claim is partially supported, unsupported, unclear, or needs review

This preserves the audit trail instead of silently overwriting the original AI wording.

## Public-feedback metadata

Sources now include optional metadata needed later for citizen/public-feedback workflows:

- `submitted_at`
- `pii_redaction_status`
- `duplicate_cluster_id`

The actual PII detector and duplicate clustering are later chunks; Chunk 1 only makes room for their results without changing the contract later.

## Status meanings

### Claim verification

- `supported`
- `partially_supported`
- `needs_clarification`
- `unsupported`
- `needs_human_review`

### Analysis step

- `draft`
- `verified`
- `needs_refresh`

Human approval is stored in `human_review.status`, so there is one clear place for human-review state.

### Human review

- `not_reviewed`
- `in_review`
- `reviewed`
- `approved`

## Sample behavior

The fictional sample intentionally contains:

- supported claims
- a claim that needs clarification
- an unsupported claim
- linked exact-source evidence
- an example original-vs-revised claim

This makes the sample useful for exercising green, yellow, and red verification states in later UI work.

The sample data is intentionally fictional so nobody mistakes it for a real policy finding.

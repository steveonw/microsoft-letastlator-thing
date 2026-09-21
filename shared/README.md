# PolicyTrace shared contract

For the hackathon MVP, **JSON is the canonical contract** between the frontend, backend, and later AI/retrieval components.

The goal is to keep the contract small enough that every teammate can understand it quickly.

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

A claim does not copy its citation text. It points to one or more `Evidence` records by ID. Each evidence record points back to its original `Source`.

## Files

- `policytrace.schema.json` — canonical JSON Schema for the MVP contract.
- `sample-analysis.json` — fictional end-to-end sample used for development.
- `../backend/models.py` — matching Pydantic models.
- `../frontend/types/policytrace.ts` — matching TypeScript types.

## MVP rules

1. Keep IDs stable once created.
2. Important AI-generated claims should reference evidence.
3. Evidence keeps the exact supporting snippet and a locator when available.
4. AI interpretation, human interpretation, public opinion, reporting, and official policy remain visibly distinct.
5. Rush and Guided modes use the same `AnalysisRun` / `AnalysisStep` structures.
6. Human review state is stored separately from AI verification state.
7. Later changes should extend the contract rather than silently changing the meaning of existing fields.

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
- `human_edited`
- `approved`
- `needs_refresh`

### Human review

- `not_reviewed`
- `in_review`
- `reviewed`
- `approved`

The sample data is intentionally fictional so nobody mistakes it for a real policy finding.

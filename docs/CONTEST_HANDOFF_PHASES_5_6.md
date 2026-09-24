# PolicyTrace Contest Handoff — Phases 5–6

Date: 2026-09-24
Working branch: `fix/contest-phase1-comment-resilience`
Base branch: `playground/main-two`
Checkpoint commit before this handoff: `785dec933605c3a72fa37a3d8a08cd48f1e18944`
CI: PolicyTrace CI #340 — SUCCESS

## Purpose

This handoff records contest-readiness work completed in Phases 5 and 6.

Core rule remains:

> No important AI claim without evidence, no evidence without a support check, and no final report without human review.

## Phase 5 — Verification and report-promotion hardening

Completed.

### Atomic findings

The Policy Interpreter and Response & Viewpoint Analyst prompts now explicitly ask for atomic findings.

Goal:
- one main factual proposition per finding;
- split independent requirements, deadlines, actors, thresholds, exceptions, reasons, concerns, questions, or viewpoints instead of bundling them together.

This is intended to reduce misleading `partially_supported` outcomes caused by compound claims.

### Partial-support explanations

The claim verifier now supports structured partial-support details:
- `supported_part`;
- `not_established_part`;
- optional narrower wording.

User-facing verification notes can therefore explain:
- what the evidence establishes;
- what the evidence does not establish or overstates;
- what narrower wording would be better supported.

### Deterministic report-promotion gate

A reviewed finding is eligible for normal report promotion only when:
- it has cited evidence;
- its semantic-verification status is `supported` or `partially_supported`;
- it has no unresolved reviewer flag.

A finding is withheld from normal report promotion when:
- it has no evidence;
- verification is unresolved, unsupported, unclear, or needs human review;
- a reviewer flag remains unresolved.

Withheld findings remain preserved for the Evidence Audit Log.

Human review does not magically convert an unevidenced AI finding into an evidence-backed finding.

### Degraded extraction accounting

Attachment extraction now uses an explicit deterministic marker when word-spacing loss makes automated redaction/citation matching unreliable.

Corpus status distinguishes:
- degraded source records;
- degraded attachments.

This fixes the manual-test case where three degraded attachments were combined into two source records.

## Phase 6 — Leadership Report + Evidence Audit Log

Completed.

UI build: `build 13`.

### Product architecture

Final outputs are now explicitly split into two views.

#### Leadership Report

Purpose:
- concise;
- leadership-facing;
- readable;
- contains only reviewed findings that pass the report-promotion gate.

Behavior:
- findings are grouped by reviewed analysis section;
- stable claim IDs are shown in brackets;
- no evidence dump is embedded in the leadership layer;
- withheld-finding count is disclosed under Review limitations;
- current-status / freshness context is appended;
- corpus / representativeness context is appended when comments were analyzed.

The Leadership Report does not generate new semantic synthesis. It reorganizes reviewed structured findings deterministically.

### Evidence Audit Log

Purpose:
- receipt / proof layer;
- answer the question: "How do I know the AI did not make this up?"

The audit log preserves every reviewed structured finding, including findings withheld from the Leadership Report.

For each claim it records:
- stable Claim ID;
- AI-generated vs human-edited origin;
- claim text;
- semantic-verification status;
- verification note;
- report-promotion state;
- block reason when withheld;
- model confidence when available;
- original AI wording for human edits;
- reviewer flags and reasons;
- evidence IDs;
- source ID;
- source title;
- source information type;
- source URL when available;
- locator;
- exact stored evidence passage.

Per-step audit metadata includes:
- Step ID;
- step version;
- step status;
- human-review status;
- human-review notes.

Run-level audit metadata includes:
- policy title;
- analysis run ID;
- final human-review status.

Current-status/freshness and corpus-limit context are also appended to the audit log in the live app.

### Stable linkage

Leadership Report claim IDs link conceptually to the matching Evidence Audit Log entries.

Desired contest-demo moment:

> You do not have to trust the AI. Here is the evidence trail.

Example flow:
1. Judge sees a concise claim in the Leadership Report.
2. Claim includes stable ID, e.g. `[claim-major-003]`.
3. Switch to Evidence Audit Log.
4. Search the same Claim ID.
5. Show exact source passage, source URL, verifier result, and reviewer history.

### Approval behavior

The existing final-review lifecycle remains attached to the Leadership Report.

- human approval is still required;
- unresolved reviewer flags still block normal approval unless explicitly acknowledged;
- the Evidence Audit Log is not a second competing approval lifecycle;
- after approval, the audit log remains available as the receipt layer.

### UI

The final-output screen now has two tabs:
- `Leadership Report`;
- `Evidence Audit Log`.

Copy behavior is view-aware:
- Copy report;
- Copy audit log.

The final approval button is shown for the Leadership Report view, not the Audit Log view.

## Regression tests

Phase 5–6 coverage includes:
- atomic policy findings prompt;
- atomic public-response findings prompt;
- structured partial-support explanation;
- zero-evidence claim withheld from report;
- unresolved semantic verification withheld from report;
- unresolved reviewer flag withheld from report;
- blocked findings retained in audit;
- degraded source vs attachment counts;
- leadership report contains stable claim IDs;
- leadership report does not contain evidence receipts;
- audit log contains exact evidence passages;
- audit log contains evidence/source metadata;
- reviewer flags survive into the audit log;
- final-output UI exposes separate report/audit views;
- build marker is `build 13`.

At this checkpoint:
- PolicyTrace CI #340 passed;
- full backend suite passed;
- provider tests passed;
- offline ingestion passed;
- Policy Interpreter passed;
- Response & Viewpoint Analyst passed;
- Claim Verifier passed;
- Guided Mode passed;
- Rush Mode passed;
- evidence offset/locator validation passed.

## Files changed in Phases 5–6

Primary files:
- `backend/policy_interpreter.py`
- `backend/response_viewpoint_analyst.py`
- `backend/claim_verifier.py`
- `backend/response_sources.py`
- `backend/selective_reanalysis.py`
- `backend/run_full_stack_guide.py`
- `backend/test_claim_verifier.py`
- `backend/test_selective_reanalysis.py`
- `backend/test_app_ui_contract.py`
- `backend/test_not_the_froutend.py`
- `frontend/app/index.html`
- `frontend/app/app.js`
- `frontend/app/styles.css`

Collaborator-owned legacy demo files were not intentionally modified.

## Known remaining work

1. Policy revision comparison is not implemented.
2. Factual/news-source integration is not implemented.
3. Full Microsoft Foundry contest-path validation remains required.
4. Recent Errors still mixes previous-session history with current-session errors.
5. PII detection remains intentionally narrow.
6. Exact-text duplicate clustering is not semantic/form-letter clustering.
7. A manual Phase 5–6 acceptance test should confirm the live report/audit split with real Federal Register + Regulations.gov material.
8. Leadership Report presentation can be polished further after functional acceptance, but should not introduce unsupported AI synthesis.
9. Audit Log could later add a direct clickable in-app Claim-ID jump/search, but stable IDs are already present.

## Recommended next work

### Phase 7
Policy revision comparison.

Minimum contest-ready version:
- load two authoritative policy versions;
- show added/removed/changed language;
- identify changed thresholds/deadlines/stakeholder implications;
- link each diff to source text;
- mark existing findings that may need refresh.

### Phase 8
Add one factual-reporting/news source type.

Suggested source:
- GDELT;
- official agency press releases;
- another clearly labeled factual reporting source.

Maintain visible separation between:
- official policy;
- factual reporting;
- public opinion / stakeholder claims;
- AI interpretation.

After Phases 7–8, create the next handoff sheet.

## Branch / merge rules

At this checkpoint:
- work remains on `fix/contest-phase1-comment-resilience`;
- `main` was not touched;
- issue #9 remains open;
- nothing should be merged without explicit user approval;
- do not close issue #9 without explicit user approval.

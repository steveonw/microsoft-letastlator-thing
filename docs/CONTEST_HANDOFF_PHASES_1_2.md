# PolicyTrace Contest Handoff — Phases 1–2

Date: 2026-09-23
Working branch: `fix/contest-phase1-comment-resilience`
Base branch: `playground/main-two`
Current checkpoint commit before this handoff: `5ed1913d300bf0202477868e6fc7743618c28760`
CI: PolicyTrace CI #295 — SUCCESS

## Purpose

This handoff records the contest-readiness work completed in Phases 1 and 2 so the project can be resumed later without reconstructing decisions from chat history.

The core product rule remains:

> No important AI claim without evidence, no evidence without a support check, and no final report without human review.

## Phase 1 — Comment-fetch resilience and retrieval-gap tracking

Completed.

### What changed

Regulations.gov live comment ingestion now has a structured retrieval report.

The fetcher tracks:
- requested comment count;
- source document count;
- candidate comment IDs observed;
- detail fetches attempted;
- successful records retrieved;
- unusable records;
- failed comment IDs;
- failure type.

### Failure behavior

The live comment fetch no longer needs to fail the whole docket when one detail request fails.

Current behavior:
- preserve successful records;
- continue trying later available candidate IDs;
- attempt to fill the requested usable-comment count when possible;
- keep successful record order deterministic;
- disclose individual fetch failures;
- if every attempted comment fails, raise an explicit `CommentFetchError` instead of silently producing an empty corpus.

The existing `fetch_comments_for_docket(...)` compatibility wrapper remains available for callers that only need records.

### App state

`GuideState.last_comment_fetch_report` retains the latest live retrieval report in process memory.

The backend exposes:

`GET /api/source/comments/status`

This endpoint intentionally contains corpus/retrieval metadata, not credentials or raw request bodies.

## Phase 2 — Visible corpus and representativeness limits

Completed.

### Product UI

Build marker is now:

`build 8`

A visible **Corpus & limitations** panel is shown in the review workspace when live public-response material is available.

It shows:
- comments requested;
- comments retrieved;
- source records analyzed;
- exact-text cluster count;
- retrieval failures;
- unusable retrieved records;
- PII-pattern redaction count;
- degraded-extraction count;
- source-type breakdown;
- docket ID;
- explicit representativeness warning.

The UI distinguishes:
- `retrieval complete`; from
- `corpus has disclosed gaps`.

### Representativeness wording

The product explicitly states:

> These materials are not a representative sample of the general public and must not be generalized to population-wide opinion.

This is intentionally a corpus limitation, not an AI-generated political conclusion.

### Duplicate wording

The old wording implied semantic/form-letter deduplication and distinct voices.

It now says that PolicyTrace performs **exact-text duplicate clustering**.

Important invariant:

- an exact-text cluster is not a verified unique person or "voice";
- similar-but-not-identical form letters may remain separate;
- do not describe the cluster count as the number of distinct people.

### PII wording

The UI no longer implies comprehensive personal-information detection.

It now states that supported email and phone patterns are redacted before analysis.

Do not broaden this claim until detection coverage actually expands.

### Final brief

When comment corpus data exists, the generated final brief now includes a deterministic:

`## Corpus limits`

section.

It includes the same core retrieval and representativeness metrics shown in the workspace so the report does not hide known evidence gaps.

The values come from backend state rather than being independently recomputed by browser code.

## Tests added / updated

Regression coverage now includes:
- bounded parallel comment fetching;
- deterministic record order;
- failed detail request with successful replacement;
- partial retrieval when no replacement is available;
- explicit failure when every detail request fails;
- live app retention of retrieval metadata;
- visible corpus panel contract;
- exact-text wording contract;
- representativeness warning;
- corpus-limit inclusion in the final brief;
- existing Guided/Rush live-source mode-choice behavior.

At this checkpoint:
- full backend suite passes;
- offline ingestion/interpreter/response/verifier checks pass;
- Guided and Rush checks pass;
- PolicyTrace CI #295 completed successfully.

## Important product decision — Report vs Audit Log

Do **not** turn the leadership report into the audit log.

The intended product should have two separate outputs.

### 1. Leadership / Analyst Report

Purpose: something an analyst can actually hand to leadership.

It should prioritize:
- what the policy does;
- current status and freshness;
- who is affected;
- key requirements;
- reasons for support in analyzed material;
- concerns and disagreements;
- issues to watch;
- corpus limitations;
- human-review status.

It should remain concise and readable.

### 2. Evidence Audit Log

Purpose: the proof layer when someone asks, "How do I know the AI did not make this up?"

The audit log should retain:
- stable claim ID;
- exact source evidence;
- source URL;
- source information type;
- citation-integrity state;
- semantic-verification state;
- AI-generated vs human-edited origin;
- original AI wording when edited;
- reviewer flags and reasons;
- re-analysis / refresh history;
- approval state;
- relevant version/timestamps.

The contest demo should be able to move from a claim in the leadership report directly to the matching audit entry by stable claim ID.

Desired demo moment:

> You do not have to trust the AI. Here is the evidence trail.

The current detailed final-brief output is closer to this future audit-log format than to the desired leadership report.

## Files changed in Phases 1–2

Primary files:
- `backend/response_sources.py`
- `backend/run_full_stack_guide.py`
- `backend/test_response_analysis.py`
- `backend/test_full_stack_guide.py`
- `backend/test_app_ui_contract.py`
- `frontend/app/index.html`
- `frontend/app/app.js`
- `frontend/app/styles.css`

No collaborator-owned legacy frontend/demo files were intentionally modified.

## Known limitations at this checkpoint

1. Comment listing still relies on the existing Regulations.gov list-request behavior; this work improves detail-fetch recovery but is not a full arbitrary-depth pagination redesign.
2. Exact-text clustering is not fuzzy or semantic form-letter clustering.
3. PII detection is still limited mainly to supported email and phone patterns.
4. Current regulatory status / freshness checking is not implemented yet.
5. User-facing legacy "Chunk 6" wording still needs cleanup.
6. Guided mode may still show the redundant final `Accept section and continue` action beside `Build final brief`.
7. The polished leadership report and dedicated audit-log interface are not implemented yet.
8. Policy revision comparison is not implemented yet.
9. Factual/news-source integration is not implemented yet.
10. Full Microsoft Foundry contest smoke testing still needs to be completed.

## Recommended next work

### Phase 3
Current-status / freshness checking.

Goal:
- distinguish the historical analyzed document from the current regulatory state;
- display source date, document type, current status, and last status check;
- flag withdrawn, superseded, amended, or finalized material without rewriting the historical source.

### Phase 4
User-facing trust / UX cleanup.

Suggested scope:
- replace visible `Chunk 6` terminology;
- hide redundant Guided-mode final Accept action;
- tighten "minority viewpoint" wording where prevalence was not measured;
- preserve the citation-integrity vs semantic-verification distinction.

After Phases 3–4, create the next handoff sheet.

## Branch / merge rules

At this checkpoint:
- work is on `fix/contest-phase1-comment-resilience`;
- `main` was not touched;
- issue #9 remains open;
- nothing should be merged without explicit user approval;
- do not close issue #9 without explicit user approval.

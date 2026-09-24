# PolicyTrace Contest Handoff — Phases 3–4

Date: 2026-09-24
Working branch: `fix/contest-phase1-comment-resilience`
Base branch: `playground/main-two`
Checkpoint commit before this handoff: `97bdb362179791c484cc2b0a9b8d08bb3672f5a7`
CI: PolicyTrace CI #317 — SUCCESS

## Purpose

This handoff records the contest-readiness work completed in Phases 3 and 4.

Core rule remains:

> No important AI claim without evidence, no evidence without a support check, and no final report without human review.

## Phase 3 — Current-status / freshness checking

Completed and manually tested.

### Why this exists

A historical Federal Register document can be interpreted accurately while no longer representing the current regulatory state.

PolicyTrace now keeps those two ideas separate:
- what the analyzed source document said;
- what later official rulemaking activity indicates about current status.

### Federal Register source check

PolicyTrace pulls Federal Register documents by Regulation Identifier Number (RIN).

It records:
- all Federal Register matches for the RIN;
- any Federal Register documents published after the analyzed source;
- document number, type, action, publication date, title, and source URL.

This is a corroborating source check.

Important limitation:
- the absence of a later Federal Register document does **not** prove there was no later rulemaking action.

### Unified Agenda / Reginfo check

PolicyTrace also checks Reginfo.gov / the Unified Agenda because some rulemaking actions are recorded there without a new Federal Register publication.

The Reginfo retrieval was hardened after a manual test exposed a failed lookup:
- browser-like request headers;
- RIN result-link parsing independent of query-parameter order;
- fallback discovery path;
- fail-open behavior retained.

### Current-status UI

The workspace now has a visible **Current status / freshness** panel.

It shows:
- source document number;
- source document type;
- source publication date;
- RIN;
- current status;
- agenda stage;
- RIN status;
- Federal Register matches for the RIN;
- later Federal Register document count;
- freshness-check time;
- link to the official status source.

UI build after Phase 3 fix: `build 10`.

### Known test case

Federal Register document:
`2024-20529`

RIN:
`0694-AJ55`

Manual acceptance test result:
- source document: 2024-20529;
- document type: Proposed Rule;
- source publication date: 2024-09-11;
- later material action found;
- status: Withdrawn — 2025-12-16;
- agenda stage: Completed Actions;
- Federal Register matches for RIN: 1;
- later Federal Register documents: 0.

This demonstrates why both source systems are needed:
- Federal Register confirms the published 2024 proposal;
- the Unified Agenda records the later withdrawal.

### Failure behavior

If current-status retrieval fails:
- policy analysis is not blocked;
- PolicyTrace displays `Status check unavailable`;
- it does not guess current status;
- the reviewer is told to check current status manually.

This is intentional fail-open behavior.

### Final brief

The final brief includes a deterministic:

`## Current status / freshness`

section containing source metadata, status result, Federal Register corroboration counts, check time, freshness warning, and official source URL when available.

## Phase 4 — Trust and UX cleanup

Completed.

UI build: `build 11`.

### Removed developer jargon

User-facing verification notes no longer say:
- `semantic verification is deferred to Chunk 6`;
- `verified until Chunk 6`.

Preferred wording is now:

> Citation integrity checked. Semantic support still needs verification.

This preserves the technical distinction without exposing internal project-phase terminology.

### Citation-integrity invariant preserved

Do not collapse these concepts:
- deterministic citation-integrity checking;
- semantic verification.

A failed citation-integrity check still means:
- the cited passage could not be deterministically located;
- semantic support was not assessed;
- human review is required.

It does **not** automatically mean the claim is false.

### Viewpoint prevalence wording tightened

The Response & Viewpoint Analyst still preserves disagreement and distinct viewpoints, but user-facing wording no longer calls a viewpoint a `minority` merely because it differs from another view.

Prompt guidance now says not to label a viewpoint as a minority unless the supplied material actually establishes prevalence.

User-facing section wording uses:

> Distinct / conflicting viewpoints

instead of:

> Minority / conflicting viewpoints

Internal `minority_conflicting` schema compatibility is retained for now to avoid unnecessary data-format breakage.

### Guided-mode final action cleanup

In Guided mode:
- while work remains, `Accept section and continue` remains available;
- once the selected section is already reviewed and all content sections are reviewed, the redundant Accept button is hidden;
- `Build final brief` becomes the clear next action.

This fixes the previously documented end-of-flow UI confusion.

## Regression tests

Phase 4 contract checks now verify:
- old Chunk 6 wording is absent;
- preferred citation/semantic wording is present;
- user-facing minority-prevalence wording is absent;
- distinct/conflicting wording is present;
- the Guided final-state suppression logic exists;
- `Build final brief` remains available;
- visible build marker is `build 11`.

At this checkpoint:
- PolicyTrace CI #317 passed;
- full backend suite passed;
- provider tests passed;
- offline ingestion passed;
- Policy Interpreter checks passed;
- Response & Viewpoint Analyst checks passed;
- Claim Verifier checks passed;
- Guided and Rush checks passed;
- evidence-offset validation passed.

## Important product decision retained — Report vs Audit Log

Do not merge the leadership report and audit log into one artifact.

### Leadership / Analyst Report

Goal:
- concise;
- readable;
- current-status aware;
- useful for leadership.

### Evidence Audit Log

Goal:
- prove where every important claim came from;
- preserve exact evidence;
- preserve verification history;
- preserve human edits, flags, overrides, and refresh history.

Stable claim IDs should connect the leadership report to the audit entry.

Desired demo moment:

> You do not have to trust the AI. Here is the evidence trail.

## Known issues / next priorities

The manual Phase 1–3 tests exposed several items that remain important:

1. Degraded attachment counting currently does not perfectly match attachment-level extraction warnings.
2. AI-generated findings with no evidence can still appear in the current detailed final brief after section review; the future leadership-report / audit-log split should enforce stricter promotion rules.
3. Current error history mixes old testing-session errors with the current session.
4. The dedicated Leadership Report is not implemented yet.
5. The dedicated Evidence Audit Log interface is not implemented yet.
6. Policy revision comparison is not implemented yet.
7. Factual/news-source integration is not implemented yet.
8. Full Microsoft Foundry contest-path validation remains required.

## Recommended next work

### Phase 5

Verification and report-promotion hardening.

Suggested goals:
- split compound AI findings into smaller atomic claims where practical;
- improve explanation of `partially_supported`;
- block zero-evidence AI claims from normal leadership-report promotion;
- preserve blocked/unresolved claims in the audit log;
- correct degraded attachment/source counting.

### Phase 6

Leadership Report + Evidence Audit Log separation.

Suggested goals:
- build a clean leadership-facing report;
- preserve the existing detailed trace output as the basis of the audit log;
- connect report claims to audit entries with stable claim IDs;
- include freshness/current-status and corpus limitations in the leadership layer;
- retain all reviewer flags, edits, and verification metadata in the audit layer.

After Phases 5–6, create the next handoff sheet.

## Branch / merge rules

At this checkpoint:
- work remains on `fix/contest-phase1-comment-resilience`;
- `main` was not touched;
- issue #9 remains open;
- nothing should be merged without explicit user approval;
- do not close issue #9 without explicit user approval.

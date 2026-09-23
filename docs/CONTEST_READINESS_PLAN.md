# PolicyTrace Contest Readiness Plan

Last updated: 2026-09-23
Target branch: `playground/main-two`

## Purpose

This document is the shared contest-readiness checklist for PolicyTrace. It is meant to be revisited during development and demo preparation.

Core rule:

> No important AI claim without evidence, no evidence without a support check, and no final report without human review.

## Priority order

### 1. Comment-fetch resilience and retrieval-gap tracking

Improve the Regulations.gov ingestion path so one failed comment does not kill the whole run.

Target behavior:
- keep successful comments when an individual fetch fails;
- try additional available comments when possible until the requested usable count is reached;
- record how many comments were requested, successfully retrieved, skipped, and failed;
- preserve failed IDs / failure reasons in safe diagnostic metadata;
- if some comments succeed, continue with a visible corpus-gap warning;
- if all selected comments fail because of network/API errors, raise an explicit ingestion failure rather than treating the corpus as empty.

Do not silently hide missing material.

### 2. Visible corpus / representativeness box

Surface corpus limits in the product UI and final brief.

Show:
- comments requested;
- comments successfully retrieved;
- failed retrievals;
- usable sources analyzed;
- exact-text duplicate clusters;
- source-type breakdown;
- excluded/degraded sources;
- explicit warning that regulatory comments are self-selected and are not representative of the general public.

Avoid calling exact-text clusters "distinct voices."

### 3. Current-status / freshness checking

Add a current-status layer separate from source interpretation.

Show:
- source document date;
- document type (proposal, final rule, notice, etc.);
- current regulatory status;
- last status-check date;
- warning when the analyzed source is withdrawn, superseded, amended, finalized, or otherwise stale.

Keep the historical source interpretation unchanged. The goal is to distinguish:
- what the analyzed document said at the time; from
- what is currently operative.

### 4. Remove confusing user-facing language

Clean up:
- `semantic verification is deferred to Chunk 6`;
- other legacy "Chunk" terminology that users can see;
- "duplicate form letters" if the implementation only performs exact-text clustering;
- "minority viewpoint" when prevalence was not actually measured.

Preferred wording for the old Chunk 6 note:

> Citation integrity checked. Semantic support still needs verification.

Preserve the distinction between deterministic citation-integrity checks and semantic verification.

### 5. Improve verification clarity

Make claims more atomic before semantic verification.

Instead of one compound claim containing several obligations, deadlines, or conditions, split it into separate claims where practical.

For `partially_supported` findings, show:
- what the evidence supports;
- what is not established or is overstated;
- supporting evidence;
- whether human review is required.

Do not treat a failed citation-integrity check as proof that the claim is false.

### 6. Redesign the final brief for leadership use

Keep the current detailed output as an Evidence / Audit Trail.

Add a leadership layer above it:

#### Policy brief
- What this policy does
- Current status / freshness
- Who is affected
- Key requirements
- Main reasons for support in analyzed material
- Main concerns
- Mixed / conflicting viewpoints
- Issues to watch
- Corpus limitations / representativeness
- Human-review status

Then provide:
- claim IDs;
- verification states;
- evidence IDs;
- exact source links;
- human edits;
- reviewer flags;
- final approval state.

The first screen should be readable quickly; the audit trail should remain one click away.

### 7. Finish current UX cleanup

Guided mode:
- when all user-facing sections are reviewed, hide `Accept section and continue`;
- leave `Build final brief` as the obvious next action.

Keep the three-pane review flow:
- Sections
- Findings
- Exact evidence

Continue visually distinguishing:
- supported;
- partially supported;
- needs human review;
- degraded / missing evidence;
- human edited;
- reviewer flagged.

### 8. Add policy revision comparison

Implement a minimal source-linked comparison between two policy versions.

Show:
- added language;
- removed language;
- changed thresholds;
- changed deadlines;
- changed affected stakeholders/programs;
- findings that may need refresh because of the revision.

This does not need to be a full legal redlining engine for the contest. It must be understandable, traceable, and evidence-linked.

### 9. Add one factual/news source

Current strong sources:
- Federal Register policy text;
- Regulations.gov public comments.

Add at least one factual-reporting source type, such as:
- GDELT;
- agency press releases;
- another clearly labeled factual news source.

Keep visible separation between:
- official policy;
- factual reporting;
- public opinion / stakeholder claims;
- AI-generated interpretation.

### 10. Keep PII claims accurate

Current automatic redaction should be described narrowly unless coverage expands.

Do not claim comprehensive PII detection unless it exists.

Preferred framing:

> PolicyTrace automatically redacts supported personal-information patterns before model analysis and marks degraded extraction for human review.

Expand detection later if time permits.

### 11. Full Microsoft Foundry contest validation

Before submission, run the complete real workflow with Microsoft Foundry:

Federal Register
→ Policy Interpreter
→ Regulations.gov comments
→ Response & Viewpoint Analyst
→ claim verification
→ human review
→ final brief
→ final approval

Test:
- Foundry API-key authentication;
- Foundry bearer-token authentication;
- bad credentials;
- malformed model output;
- Regulations.gov partial failures;
- PDF extraction degradation;
- duplicate comments;
- reviewer edit;
- reviewer flag;
- selective re-analysis;
- dependent refresh;
- final approval.

Save screenshots from a successful run for the contest submission.

## Demo flow

The contest demo should tell one simple story:

1. Load a real regulation.
2. Load real public comments.
3. Show the policy summary.
4. Click a finding and show its exact source evidence.
5. Show why commenters support or oppose parts of the policy.
6. Show corpus / representativeness limits.
7. Show current-status / freshness information.
8. Edit or flag a questionable AI claim.
9. Show dependent analysis becoming stale.
10. Refresh only affected sections.
11. Generate the leadership brief.
12. Drill into the evidence / audit trail.
13. Require final human approval.

## Definition of contest-ready

PolicyTrace is contest-ready when a judge can understand within a few minutes that:

- policy language is kept separate from public response and AI interpretation;
- important claims are traceable to exact evidence;
- semantic verification is distinct from citation integrity;
- conflicting viewpoints are preserved;
- source bias and representativeness are visible;
- missing/degraded material is disclosed;
- PII handling is demonstrated without overstating coverage;
- policy freshness/current status is visible;
- human edits and objections are preserved;
- selective re-analysis works;
- a final leadership brief is useful without losing the audit trail;
- Microsoft Foundry is used successfully in the contest path;
- final conclusions require human approval.

## Do not weaken

While implementing the plan, do not:
- touch `main`;
- close issue #9 without explicit approval;
- modify collaborator-owned legacy demo files without explicit authorization;
- weaken evidence gates;
- collapse citation integrity and semantic verification;
- hide retrieval failures or degraded extraction;
- overstate comment representativeness;
- remove final human approval for convenience.

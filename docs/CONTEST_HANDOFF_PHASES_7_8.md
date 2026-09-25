# PolicyTrace Contest Handoff — Phases 7–8

Date: 2026-09-24
Working branch: `fix/contest-phase1-comment-resilience`
Base branch: `playground/main-two`
Checkpoint commit before this handoff: `bea90e8fd4a8ea21be5226b7efbb838caf118218`
UI build: `build 23`
CI: PolicyTrace CI #402 — SUCCESS

## Purpose

This handoff records the contest-readiness work completed in Phases 7 and 8.

Core rule remains:

> No important AI claim without evidence, no evidence without a support check, and no final report without human review.

Historical handoff documents are intentionally preserved. Do not delete or collapse the earlier Phase 1–2, 3–4, or 5–6 handoffs; they are part of the project continuity record.

## Phase 7 — Policy revision comparison

Completed and manually accepted for contest readiness.

### Goal

Compare two authoritative Federal Register documents while preserving the distinction between:
- deterministic changed source language;
- existing PolicyTrace findings that may need refresh; and
- any legal/policy-effect interpretation, which the diff engine does **not** claim to establish.

### Backend

Primary implementation:

- `backend/revision_compare.py`
- `POST /api/revision-compare`
- `GET /api/revision-comparison`

The comparison produces:
- added text units;
- removed text units;
- changed text units;
- source locators;
- exact before/after text;
- official source URLs;
- heuristic change tags;
- existing claim IDs that may need refresh.

Current tags include:
- `deadline/date`;
- `threshold/number`;
- `stakeholder-scope language`;
- `text`.

Important invariant:

> Revision comparison identifies changed source language. It does not itself establish the legal or policy effect of the change.

### Matching / performance work

The first replacement matcher was too expensive because it could run `SequenceMatcher` across every old/new text-unit pair.

The shipped matcher now uses a bounded hybrid approach:
- exact matching first;
- rare four-word phrase anchors;
- monotonic anchor corridors;
- token-index candidate retrieval;
- cheap word-overlap filtering;
- bounded fuzzy comparison only for shortlisted candidates;
- confidence gating;
- no forced positional fallback for unrelated material.

A moved provision can be recovered as a changed pair even when the top-level diff initially emits delete/insert blocks.

Uncertain matches intentionally remain removed + added instead of being forced into a misleading changed pair.

### Reviewability / UI

The revision card supports:
- Substantive;
- Thresholds;
- Dates;
- Stakeholders;
- Text;
- All.

The default view is `Substantive`.

Changes are sorted to prioritize:
- affected existing claim IDs;
- threshold/date/stakeholder changes;
- substantive changes before obvious metadata/header noise.

The UI shows 25 results at a time with `Show more`.

Comparison timing and document-unit counts are exposed so slow real-document comparisons are visible rather than appearing hung.

### Pre-review comparison visibility

Build 16 fixed a UI bug where a completed comparison existed but the workspace stayed hidden until Guided/Rush review had started.

A revision comparison can now be inspected before starting the review workflow.

### Manual acceptance pair

Real comparison used:

- older/proposed: `2023-23381`
- newer/final: `2024-29354`
- shared RIN: `1615-AC70`

Observed real-run metrics:
- 251 changed;
- 806 added;
- 412 removed;
- 44 existing claim IDs flagged as possibly needing refresh;
- 692 source units -> 1086 source units;
- approximately 145 seconds comparison time on the test machine.

Useful substantive matches were present, including:
- rulemaking-purpose language;
- cap-gap/date language;
- material-change language;
- controlling-interest language.

### Known Phase 7 limitations

The comparison is contest-ready, not a production legal redlining engine.

Known limitations:
1. Some changed pairs are weak or locally misaligned.
2. Federal Register page/header/citation metadata can still appear in raw Text results.
3. Threshold/date/stakeholder filters are heuristic flags, not semantic legal conclusions.
4. A removed + added pair can still represent a conceptually revised provision when the matcher correctly refuses an uncertain changed pairing.
5. Performance is acceptable for the tested full documents but is not instant.

These limitations are disclosed by the product wording and do not invalidate the Phase 7 contest use case.

### Phase 7 acceptance

Manual acceptance: **PASS**

Accepted because the product demonstrates:
- deterministic full-document comparison;
- exact source receipts;
- visible before/after text;
- claim-refresh linkage;
- review filters;
- no legal-effect overclaim;
- acceptable real-document performance.

## Phase 8 — Related factual-reporting / media discovery

Completed and manually accepted for contest readiness.

### Goal

Add a clearly separated factual-reporting/media source layer without weakening the evidence model.

PolicyTrace must continue distinguishing:
- official policy;
- factual reporting / media source pointers;
- public opinion / stakeholder material;
- AI interpretation.

### Provider architecture

Phase 8 deliberately avoids depending on one external provider.

Current discovery chain:

1. Media Cloud historical search when an API key is configured;
2. GDELT DOC 2.0 for recent-news discovery;
3. Google News RSS as a best-effort fallback;
4. graceful empty result if all providers are unavailable.

Provider failure is non-fatal to the main policy analysis.

Examples of provider outcomes recorded by the app:
- Media Cloud skipped because no key is configured;
- GDELT rate-limited, SSL-failed, or temporarily unavailable;
- Google News RSS used successfully as fallback.

### Evidence boundary

PolicyTrace does **not** scrape arbitrary article bodies.

For discovered reporting, the stored text is limited to provider-supplied discovery material such as:
- headline/title;
- publisher/domain;
- publication date;
- source URL.

The UI and reports explicitly state that a headline/source pointer is **not a verified factual claim about the policy**.

This keeps the current evidence model intact and avoids pretending that unavailable article-body text has been verified.

### Historical / recent behavior

Media Cloud is treated as the historical-search provider when configured.

GDELT is treated as recent-context discovery rather than a dependable historical archive.

Google News RSS is a fallback and can return broad results; it is not treated as a verified article-body evidence source.

Provider-specific search windows are shown instead of one misleading aggregate search window.

### Media review section

Build 21 moved discovered media into the normal human review workflow.

The user-facing section list can include:

`Related media / factual reporting`

Each media item:
- is a source pointer;
- shows publisher/date metadata;
- offers `Open original article`;
- is labeled as discovery-only;
- does not enter normal policy-claim promotion logic.

The same media-review section works in the Rush review path.

### Media use / exclude control

Build 23 added explicit reviewer selection.

Discovered articles are included by default for speed.

The reviewer can choose:
- `Don't use article`; or
- `Use article`.

This is deterministic human selection state and does **not** trigger another AI call.

Behavior:
- selected media can appear in the Leadership Report media appendix;
- excluded media does not appear in that Leadership Report appendix;
- every discovered media source remains in the Evidence Audit Log;
- excluded items are marked `EXCLUDED BY REVIEWER`;
- included items are marked `USED IN REPORT`;
- selections survive the normal Rush re-sync when the same media set is retained.

### Media presentation cleanup

The initial large media block became redundant after media became a review section.

Current behavior:
- keep a compact provider/query/coverage summary;
- hide the duplicate article list in the top summary once review is active;
- review article links in the dedicated media section.

The previous Wayback/archive-history link was removed because Google News redirect URLs produced poor archive behavior and ugly report formatting.

Raw Google News redirect URLs are not printed in the Leadership Report.

Long audit URLs wrap so they do not stretch printed/PDF output.

### Final report placement

Media is supplemental context and is intentionally placed at the bottom of:
- the Leadership Report additions;
- the Evidence Audit Log additions.

The main reviewed policy findings remain primary.

### Rush-only user-facing workflow

Build 23 simplified the normal product path.

The user-facing start screen now exposes one route:

> Analyze everything, then review

The Guided backend remains in the codebase and test suite as existing tested functionality, but it is no longer presented as a competing normal user workflow.

Rationale:
- Rush produces the full analysis first;
- reviewers can still open, inspect, edit, flag, include/exclude material, and review each saved section;
- final human approval remains mandatory;
- this avoids unnecessary workflow choice and is faster for the intended contest/demo use case.

### Manual Phase 8 acceptance

Real run used Federal Register document:

`2024-20529`

The accepted end-to-end run demonstrated:
- 12 requested comments;
- 12 retrieved;
- 12 analyzed source records;
- zero comment retrieval failures;
- 4 PII-pattern redacted source records;
- 3 degraded source records / 3 degraded attachments;
- 8 discovered media source pointers;
- reviewer selected 3 of 8 media sources for the report;
- excluded media preserved in the audit;
- Leadership Report approved;
- Evidence Audit Log retained exact policy/comment evidence receipts and media selection receipts.

### Phase 8 acceptance

Manual acceptance: **PASS**

Accepted because the product demonstrates:
- resilient provider fallback;
- clear provider-path disclosure;
- factual-reporting/media separation from official policy and public opinion;
- no article-body verification overclaim;
- human source selection;
- selected/excluded provenance in the audit;
- clean Leadership Report placement;
- Rush review integration;
- final human approval.

## Final-output behavior at the Phase 7–8 checkpoint

### Leadership Report

The Leadership Report remains deterministic and reviewer-facing.

It includes:
- reviewed policy findings that pass the promotion gate;
- stable claim IDs;
- partial-support labels where applicable;
- review-limit disclosure;
- current-status/freshness context;
- corpus/representativeness limits;
- selected related-media source pointers at the bottom.

It does not include:
- raw evidence dumps;
- unevidenced AI findings;
- unresolved semantic findings;
- unresolved reviewer-flag findings;
- excluded media source pointers.

### Evidence Audit Log

The audit remains the receipt layer.

It preserves:
- every reviewed structured claim;
- included/blocked report-promotion state;
- verification notes;
- exact stored evidence passages;
- source metadata and URLs;
- reviewer flags/edits;
- policy freshness context;
- corpus limits;
- every discovered media source;
- media reviewer selection state.

Desired demo moment remains:

> You do not have to trust the AI. Here is the evidence trail.

## Files changed in Phases 7–8

Primary Phase 7 files:
- `backend/revision_compare.py`
- `backend/run_full_stack_guide.py`
- `backend/test_revision_compare.py`
- `backend/test_app_ui_contract.py`
- `frontend/app/index.html`
- `frontend/app/app.js`
- `frontend/app/styles.css`

Primary Phase 8 files:
- `backend/news_sources.py`
- `backend/models.py`
- `backend/selective_reanalysis.py`
- `backend/run_full_stack_guide.py`
- `backend/test_news_sources.py`
- `backend/test_app_ui_contract.py`
- `frontend/app/index.html`
- `frontend/app/app.js`
- `frontend/app/styles.css`

Collaborator-owned legacy demo files were not intentionally modified:
- `backend/api.py`
- `frontend/demo/app.js`
- `frontend/demo/index.html`
- `frontend/demo/README.md`

## Important build/checkpoint history

Relevant checkpoints include:

- Phase 7 initial comparison: `839225724a8adb7e60f0a4a30e38e2f02257cc12`
- candidate-first comparison optimization: `862c3ed...`
- comparison performance test: `d632923...`
- bounded hybrid matcher: `f97d340...`
- moved-pair recovery fix: `4d190586d9bcc27fafe4d116340bfb3ee2b31ab5`
- comparison timing fields: `94ae19eb42389474e236798fcf3f7a72eb274c6f`
- build 15 reviewability tests: `8478bdaac41acd8f70c2557734199fc05f129ef9`
- build 16 comparison-preview fix: `3003f87d014f0a7b2f370fb2e152a4fd1228dc96`
- build 18 multi-source media fallback checkpoint: `5512659af5dca6f3a8b5973cecb73a4e34e2325f`
- build 19 media/report presentation cleanup: `734c3c9f05ef9aaa78d4cb520aa0cff1f9833a8f`
- build 20 printable URL handling: `70f6c6d3810ab7ee07692e14c16ff2d9484e664e`
- build 21 media review-section integration: `58a5c7e29e69bba26f30bed675a997a7f6270a6b`
- build 22 duplicate-media-list cleanup: `e5db455334ad029defc9230881bf943f0f701bdc`
- build 23 Rush-only UI + media selection: `bea90e8fd4a8ea21be5226b7efbb838caf118218`

Current full-suite CI at this checkpoint:

`PolicyTrace CI #402 — SUCCESS`

## Separate human playground branch

A copy of the working product was created for human frontend/FastAPI experimentation:

`playground/main-three`

It was created from build-18 checkpoint:

`5512659af5dca6f3a8b5973cecb73a4e34e2325f`

Do not assume later Phase 8 fixes are present there unless explicitly copied later.

The main working branch remains:

`fix/contest-phase1-comment-resilience`

## Known remaining limitations

1. Media search relevance is still broad. Google News RSS can return adjacent-topic results.
2. Media taxonomy is still coarse; law-firm analysis, stakeholder statements, government communications, academic material, and journalism can all currently enter the broad factual-reporting/media bucket.
3. Media discovery verifies only the provider-supplied headline/title metadata, not article-body claims.
4. Media Cloud historical search requires an API key and was not required for the accepted Phase 8 run.
5. GDELT availability/rate limiting is unreliable and should remain optional/fallback behavior.
6. Revision comparison is deterministic and useful for review but is not a legal-effect engine.
7. Some revision changed-pair matches remain noisy.
8. Recent Errors still mixes persistent previous-session history with the current session.
9. PII detection remains intentionally narrow.
10. Exact-text duplicate clustering is not semantic/form-letter clustering.
11. Full Microsoft Foundry contest-path validation remains required.
12. There is no native app-generated PDF/export; current PDFs are user-created print/copy artifacts.

## Next phase — Phase 9: Policy Intake / Source Builder

The next major UX phase should turn the current source-loading controls into a one-stop intake flow.

### A. Federal Register search / document selection

Support both:
- direct document-number entry; and
- title/topic/agency search.

For search:
- return approximately the top 8 candidate Federal Register documents;
- show document number, title, agency, document type, date, RIN, comment deadline, and docket metadata when available;
- let the human choose the source document.

### B. Bounded AI topic preview

For candidate documents, optionally generate a short topic preview from a bounded official-text excerpt, for example the first approximately 1,000–2,000 characters.

The preview must:
- be labeled AI-generated;
- identify the official source/excerpt it is based on;
- not be treated as a verified legal conclusion.

### C. Deterministic latest/related-action suggestions

Do **not** let the AI independently decide that a document is the "latest."

Use deterministic official metadata first:
- RIN;
- docket ID;
- agency;
- publication date;
- Federal Register relationships.

AI may explain the likely relationship, but source/date metadata should establish chronology.

### D. Auto-detect public-comment docket

The Federal Register normalizer already retains `docket_ids`.

The intake UI should:
- auto-fill a detected Regulations.gov docket when one clear docket is present;
- let the user edit it;
- show a selector if multiple docket IDs are present;
- never silently fetch comments without user selection/confirmation.

### E. Source-selection checklist

After selecting the policy, present a one-stop checklist such as:

- Current status / later actions;
- Public comments;
- Related media;
- Revision comparison;
- Related/later Federal Register documents.

Then run the selected sources through the existing Rush review path.

### F. Report evidence threshold

Add a human-controlled report-inclusion standard without changing verifier results.

Suggested options:

#### Strict
Leadership Report includes only `supported` findings.

#### Balanced
Leadership Report can include `supported` + `partially_supported` findings with partial-support labels.

This should likely remain the default because it matches the current product behavior.

#### Exploratory
May surface unresolved / needs-human-review findings in a clearly separated exploratory section, but must **not** relabel them as supported and must not bypass final human review.

Important invariant:

> The evidence-threshold setting controls report inclusion/presentation. It never changes the verifier's actual result.

### G. Keep one user-facing workflow

Continue using:

> Analyze everything, then review

Do not reintroduce Guided as a competing normal UI path unless there is a specific demonstrated need.

## Contest-critical work after the Intake / Source Builder phase

Highest-priority remaining contest item:

### Full Microsoft Foundry validation

Run the complete live contest path with Microsoft Foundry and save screenshots/results.

Validate:
- Foundry API-key auth;
- Foundry bearer-token auth;
- bad credentials;
- live Federal Register policy;
- live Regulations.gov comments;
- media discovery fallback;
- current-status/freshness;
- revision comparison where applicable;
- Rush analysis;
- section review;
- reviewer edit/flag;
- media use/exclude;
- Leadership Report;
- Evidence Audit Log;
- final approval.

Other remaining polish:
- current-session vs historical Recent Errors;
- narrower / more accurate media source taxonomy;
- PII wording/detection improvements if time permits;
- semantic/form-letter clustering only if time permits;
- optional Claim-ID jump/search inside the audit log;
- deployment/demo hosting after local contest acceptance.

## Branch / merge rules

At this checkpoint:
- work remains on `fix/contest-phase1-comment-resilience`;
- `main` was not touched;
- issue #9 remains open;
- nothing should be merged without explicit user approval;
- do not close issue #9 without explicit user approval;
- preserve historical handoff files;
- do not modify collaborator-owned legacy demo files without explicit permission.

# PolicyTrace — Current Contest Handoff

Date: 2026-09-25  
Working branch: `fix/contest-phase1-comment-resilience`  
Accepted build marker: **build 27**  
Accepted pre-handoff checkpoint: `60088ce26ab8627993a262f69455dd977f228d54`

This is the current operational handoff for the contest build. It supplements, rather than replaces, the historical phase handoffs in this directory.

## Repository rules

- Do **not** modify or merge `main` without explicit user approval.
- Do **not** close GitHub issue #9 without explicit user approval.
- Preserve historical handoff documents.
- Do not modify collaborator-owned legacy demo files without explicit permission.
- Normal work remains on `fix/contest-phase1-comment-resilience`.
- Feature scope is frozen unless a real contest blocker is found.

## Contest

Contest: **Microsoft and CCI Innovation Challenge for Virginia**

Selected challenge: **Policy and Public Sentiment Analyst**

Challenge intent: connect authoritative policy text with news, opinions, public comments, and citizen feedback, and turn them into transparent, evidence-grounded policy insights.

Mandatory contest point: the solution must **leverage Microsoft Foundry** and solve one published challenge.

Judging criteria are equally weighted:

- 25% Solution Performance
- 25% Innovation
- 25% Economic Value & Societal Impact
- 25% Feasibility

Submission materials include:

- short project description;
- selected challenge;
- GitHub repository link;
- demo video;
- PowerPoint used in the video;
- explanation of goals, solution components / architecture, approach, and key learnings.

The video may not exceed 15 minutes.

Contest facts above were taken from the user-provided Microsoft / CCI challenge page and official-rules PDF.

## Product principle

Core rule:

> **Do not ask the user to trust the AI. Show the evidence trail.**

PolicyTrace separates:

- authoritative policy text;
- public opinion / submitted comments;
- factual-reporting source pointers;
- AI-generated claims;
- verification state;
- human review;
- final leadership output;
- Evidence Audit Log.

AI should not silently become the authority on chronology, evidence, or provenance.

## Current user workflow

Normal user path:

1. Search for or enter a Federal Register document.
2. Select the policy.
3. Inspect official metadata and bounded preview.
4. Detect / confirm the Regulations.gov docket.
5. Choose sources.
6. Run current-status / freshness checks.
7. Load public comments.
8. Discover related factual-reporting pointers.
9. Optionally compare a revision / related document.
10. Choose Strict / Balanced / Exploratory report standard.
11. Run **Analyze everything, then review**.
12. Inspect, edit, flag, include, or exclude findings.
13. Selectively refresh affected work when needed.
14. Produce the Leadership Report.
15. Produce the Evidence Audit Log.
16. Complete final human approval.
17. Save project JSON.

The older Guided backend remains tested but is not the normal user-facing workflow.

## Evidence safeguards

PolicyTrace currently includes:

- exact stored source passages;
- source IDs and URLs;
- evidence character offsets / locators;
- stable Claim IDs;
- deterministic citation-integrity checks;
- semantic claim verification;
- supported / partially supported / needs-human-review states;
- human edit / flag state;
- report-promotion gates;
- separate Leadership Report and Evidence Audit Log;
- blocked findings retained in the audit instead of silently disappearing.

Balanced mode may include partially supported findings, but they remain visibly labeled.

A finding with no cited evidence can be blocked from Leadership Report promotion while remaining visible in the Evidence Audit Log.

## Phase 9 / Intake Builder

Phase 9 is functionally accepted.

Implemented:

- Federal Register keyword search;
- direct document-number entry;
- Rules + Proposed Rules default search;
- optional Notices;
- bounded source preview;
- conservative Regulations.gov docket detection;
- missing RIN handled as a nonfatal limitation;
- related-document suggestions;
- optional source failures fail soft;
- Strict / Balanced / Exploratory report standards;
- project save / load;
- source-selection persistence;
- reproducible random comment sampling.

### Important docket rule

Federal Register docket-looking strings such as:

`Docket No. PTO-P-2025-0014`

must **not** automatically be treated as valid Regulations.gov comment dockets.

Only an explicit Regulations.gov pointer can safely autofill a comment docket.

## Revision comparison

This is one of the product's technically distinctive features.

It is not a simple line-by-line diff.

The matcher uses a bounded candidate-search strategy that includes:

- exact / strong matches first;
- distinctive / rare anchors;
- positional / corridor hints;
- candidate shortlist construction;
- bounded fuzzy comparison;
- moved / edited provision recovery;
- conservative fallback to added / removed when correspondence is weak.

Important rule:

> Revision comparison identifies text relationships. It does **not** claim legal effect.

Related Federal Register documents also cannot be suggested merely because they share an agency. Outside a same-RIN family, meaningful title / topic overlap is required.

This fixed the prior false suggestion involving `2026-01059`.

## Build 27 — random Regulations.gov comment sampling

Two sampling modes exist:

- **Earliest** — legacy behavior.
- **Random** — reproducible bounded random sampling.

Random mode:

- counts comments across applicable Regulations.gov source object IDs;
- combines them into one logical population;
- draws unique logical positions from a recorded seed;
- fetches only necessary pages;
- replaces failed / unusable selected comments using the same seeded RNG stream;
- records initial positions;
- records replacement positions;
- records final selected comment IDs;
- records population object IDs;
- records list pages fetched.

Direct random sampling is deliberately bounded to **5,000 comments per Regulations.gov source object** because of the live API paging window.

PolicyTrace does not silently approximate larger populations.

### Live Regulations.gov page-size bug

A live API check exposed that Regulations.gov rejects:

`page[size]=1`

The minimum accepted size is 5.

The implementation now uses `page[size]=5` for count requests and includes regression coverage that rejects invalid page sizes outside 5–250.

Current backend suite at the accepted build-27 checkpoint:

**260 tests passing**

## Latest live acceptance run

Primary Federal Register document:

`2025-19674`

Title:

**American AI Exports Program**

Regulations.gov docket:

`ITA-2025-0070`

Settings:

- current status: on;
- public comments: on;
- comments requested: 12;
- sampling: Random;
- related media: on;
- revision comparison: off;
- report standard: Balanced.

Live result:

- population: 227 submitted comments;
- sample: 12;
- seed: 0;
- retrieved: 12;
- analyzed: 12;
- retrieval failures: 0;
- unusable records: 0;
- PII-pattern redactions: 7;
- degraded records: 0;
- degraded attachments: 0.

Initial logical positions:

`217, 99, 195, 108, 11, 67, 131, 125, 104, 201, 213, 78`

The Evidence Audit Log records:

- sampling seed;
- both Regulations.gov population object IDs;
- initial positions;
- replacement positions;
- selected comment IDs;
- list pages fetched;
- reproducibility limitation.

The audit explicitly states that the same seed is reproducible while the population count and sort order remain unchanged. If the docket population changes, the same seed may select different positions or comment IDs.

The saved project JSON retained:

- `comment_sampling_method: "random"`;
- `comment_sampling_seed: 0`;
- `docket_id: "ITA-2025-0070"`;
- 12-comment maximum;
- Balanced report standard;
- comparison disabled;
- media exclusions.

Random-sampling live acceptance: **PASS**

## Representativeness rule

This warning must remain visible:

> These materials are not a representative sample of the general public and must not be generalized to population-wide opinion.

Random sampling is a fairer selection across the **submitted comment corpus**.

It does **not** make the submitted comments representative of general public opinion.

## Media / factual reporting

Media is supplemental context only.

PolicyTrace treats discovered news as:

**factual-reporting source pointers**

—not as verified article-body evidence.

Latest live provider behavior:

- Media Cloud skipped because no API key was configured;
- GDELT returned HTTP 429 and failed without retry;
- Google News RSS fallback succeeded;
- 8 source pointers were discovered;
- 7 were selected for the report;
- one unrelated source was excluded by the reviewer.

This failover completed without breaking the analysis.

## Current-status / freshness behavior

For `2025-19674`, Federal Register metadata did not provide a RIN.

Expected behavior:

**Status check unavailable**

—not a failed policy load.

PolicyTrace should say current status needs manual verification while allowing the rest of the analysis to continue.

## Microsoft Foundry

This is the major remaining contest validation requirement.

Foundry client:

`backend/foundry_client.py`

Expected setup:

- Microsoft Foundry **Models resource endpoint**;
- deployed model name;
- exactly one of:
  - API key;
  - bearer token.

Do **not** use a project URL containing `/api/projects/`.

Never paste credentials into chat and never commit them.

Still required for contest validation:

- live Foundry API-key authentication;
- live Foundry bearer-token authentication;
- bad credentials;
- malformed model output;
- full Federal Register → comments → verification → review → report path;
- reviewer edit / flag;
- selective refresh;
- media fallback;
- project save / load;
- Leadership Report;
- Evidence Audit Log;
- final approval;
- screenshots for the contest demo.

## Four-AI audit

Before Foundry validation, the user requested a four-AI independent review.

Each reviewer was asked to perform a read-only audit covering:

- contest compliance;
- runtime bugs;
- evidence integrity;
- random comment sampling;
- Microsoft Foundry readiness;
- security / privacy;
- innovation;
- economic / societal impact;
- feasibility;
- demo readiness.

When those reviews arrive:

1. collect all findings;
2. separate confirmed bugs from opinions / design preferences;
3. reproduce real problems;
4. fix only contest-relevant or genuinely important issues;
5. avoid feature expansion.

Feature scope remains frozen otherwise.

## Design lineage across the user's other projects

The user has several public projects whose design ideas influenced PolicyTrace.

### Read-Aloud-Main

Caches rendered audio by exact sentence text and re-renders only sentences that changed.

This is similar to PolicyTrace selective re-analysis:

> recompute only what changed.

### EquationWright

Uses:

- deterministic seeded generation;
- reproducibility;
- worked solutions;
- independent audit tooling;
- version / compatibility records;
- software-owned grading with optional AI tutoring.

This mirrors PolicyTrace's separation between AI interpretation and deterministic evidence / report state.

### LiDAR engine

Uses a scout-then-fill sampler:

- spend a small budget locating useful regions;
- concentrate expensive processing there.

That resembles the bounded candidate-search philosophy in the revision comparer.

The LiDAR tool also renders diagnostic views back through the engine to verify scene results rather than trusting generation blindly.

### text-to-3d

Its philosophy is:

> **The solver owns placement; Claude owns appearance.**

This closely matches the user's recurring architecture preference:

> deterministic software owns authoritative state; AI operates inside constrained boundaries.

### AIS Play TTRPG

Uses:

- software-owned dice;
- strict schemas;
- independent agents;
- filtered knowledge;
- deterministic state machine;
- checkpoints;
- idempotent messages;
- bounded recall;
- independent Chronicler verification.

The recurring philosophy is:

> AI proposes or interprets; deterministic software owns reality.

That same philosophy is central to PolicyTrace.

## User working style

The user prefers:

- practical explanations;
- direct Git Bash commands;
- screenshots / logs pasted back;
- minimal unnecessary abstraction;
- inspecting actual repo / code instead of speculation.

The user is comfortable authorizing work on the current working branch, but wants strong protection around `main`.

Do not merge or close issue #9 without explicit permission.

## Current next step

Do **not** add new features.

Next sequence:

**Four-AI review consolidation → verify real findings → fix genuine blockers only → Microsoft Foundry full live validation → contest demo / presentation preparation.**

PolicyTrace is near the finish line.


## 2026-09-25 independent-audit fixes

Two independent AI audits were compared against the actual current branch before
changes were made. Confirmed findings were fixed; speculative or false-positive
findings were not adopted blindly.

Applied fixes:

- Live-source review paths now refuse to fall back to the fictional deterministic
  verifier after a real policy has been loaded. Guided single-claim verification,
  Rush verification, and selective review/re-verification require a live provider
  whenever they would verify real loaded source material.
- A Rush final-approval override for unreviewed sections can no longer produce a
  Leadership Report that falsely says every included finding was individually
  reviewed. The report explicitly discloses the override while preserving the
  existing explicit-acknowledgement behavior.
- Microsoft Foundry timeout and malformed outer-response JSON errors are normalized
  into controlled provider failures so verification can route them to human review
  instead of leaking unexpected exception types.
- Regulations.gov docket document discovery now pages across document-object
  results instead of silently stopping at the first 100 records. Direct discovery
  remains bounded and refuses silent truncation at the paging boundary.
- Guided partial-support verification now preserves the verifier's structured
  "Supported" and "Not established" detail in the verification note, matching the
  batch verifier's audit quality.
- DOCX attachment handling checks the uncompressed size of
  `word/document.xml` before reading/parsing it, preventing a compact ZIP member
  from expanding without a decompression bound.
- The branch README and repository landing page now point reviewers to the actual
  build-27 product (`backend/run_app.py` / `frontend/app/`) rather than the
  historical fixture demo.

One reported "second edit is ignored" bug was verified as a false positive:
`edit_current_claim()` preserves the first AI wording in `original_text` but
updates `claim.text` on every edit.

Post-fix CI: PolicyTrace CI #476 passed. The full backend discovery reported
265 tests passing, followed by the provider-specific test subsets.

Still outstanding before contest submission:

- Perform and record the live Microsoft Foundry end-to-end validation.
- Test the selected Foundry deployment's JSON response-format compatibility,
  quota/rate-limit behavior, wrong credentials, wrong model/endpoint, and
  malformed/schema-invalid model output.
- Do not describe dependency refresh as a fresh AI interpretation pass: the
  current refresh path invalidates affected work and forces re-verification.
- Describe saved project JSON as the saved analysis setup/intake plan, not as a
  complete persisted reviewed AnalysisRun.
- Consider 429 retry/backoff only if the live Foundry rehearsal demonstrates a
  real need; do not add it speculatively during feature freeze.

# PolicyTrace Contest Handoff — Phase 9 / Build 27

Date: 2026-09-25
Working branch: `fix/contest-phase1-comment-resilience`
Base branch: `playground/main-two`
UI build: `build 27`

## Phase 9 status

Phase 9 Policy Intake / Source Builder is functionally accepted.

Completed:
- Federal Register search by words or document number;
- Rules / Proposed Rules by default, optional Notices;
- bounded official-source preview before analysis;
- conservative Regulations.gov docket detection;
- missing-RIN status is nonfatal;
- optional comments, media, comparison, and freshness sources fail soft with visible warnings;
- Strict / Balanced / Exploratory report standards;
- project JSON save/load without credentials;
- related-document suggestions require title/topic overlap unless the document is linked by RIN;
- Leadership Report and Evidence Audit Log remain separate outputs.

Build 26 acceptance confirmed that `2026-01059` is no longer auto-suggested for `2025-19674` merely because both involve Commerce-related material.

## Build 27 — reproducible comment sampling

Comment intake now supports two methods:

- `earliest`: legacy behavior, preserving compatibility with older saved projects.
- `random`: deterministic random sampling across the combined Regulations.gov comment population for all applicable source document object IDs.

Random sampling:
- counts comments for each Regulations.gov source object;
- combines those counts into one logical population;
- draws unique logical positions using a recorded seed;
- fetches only the list pages needed for those positions;
- replaces failed or unusable selected comments by drawing additional unused positions from the same seeded RNG stream;
- retains deterministic detail-result order;
- records the final selected comment IDs.

The comment fetch report now records:
- sampling method;
- seed;
- total population count;
- population object IDs;
- initial positions;
- replacement positions;
- selected comment IDs;
- list pages fetched;
- existing retrieval failures and unusable counts.

The Corpus & limitations panel shows the random-sample count, population size, seed, and positions.

The Leadership Report states the sampling method and keeps the representativeness warning.

The Evidence Audit Log adds a Comment sampling receipt containing the seed, positions, selected comment IDs, and pages fetched.

Project JSON stores the sampling method and seed. Schema-v1 projects without these fields continue to load as `earliest`.

## API boundary

Regulations.gov v4 allows direct paging with 250 results per page and page numbers 1 through 20. Build 27 therefore supports direct random sampling when each Regulations.gov source document has at most 5,000 comments.

If a source document has more than 5,000 comments:
- random comment acquisition is not silently approximated;
- the optional comment source fails soft with a disclosed warning;
- the reviewer can use `earliest` sampling instead.

Date-sliced random sampling for populations above 5,000 remains future work.

## Acceptance / tests

New regression coverage verifies:
- same seed -> same positions and comment IDs;
- different seeds -> different draws;
- no duplicate initial positions;
- deterministic replacement positions after detail failure;
- random sampling across multiple Regulations.gov source objects;
- >5,000 direct-page boundary is explicit;
- sampling method and seed persist in project JSON;
- older project files default to earliest;
- corpus and audit outputs retain sampling metadata;
- build 27 UI exposes the sampling controls and keeps the nonrepresentativeness warning.

At build 27 checkpoint, the full CI suite passes.

## Next work

Freeze feature work and proceed to Microsoft Foundry contest validation:
- Foundry API-key authentication;
- Foundry bearer-token authentication;
- bad credentials;
- malformed model output;
- real Federal Register + Regulations.gov run using random comment sampling;
- reviewer edit and flag;
- selective refresh;
- Leadership Report;
- Evidence Audit Log;
- final human approval;
- project save/load;
- contest screenshots.

## Branch rules

- Do not touch `main`.
- Do not merge without explicit user approval.
- Do not close issue #9 without explicit user approval.
- Do not modify collaborator-owned legacy demo files without explicit authorization.

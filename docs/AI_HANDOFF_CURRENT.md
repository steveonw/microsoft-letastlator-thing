# PolicyTrace - AI Handoff (Current)

Date: 2026-09-25
Purpose: preserve the latest contest state after the successful live Microsoft Foundry rehearsal so another AI can resume without reconstructing the session.

## Read this first

Repository: `steveonw/microsoft-letastlator-thing`

Working branch: `fix/contest-phase1-comment-resilience`

Latest code checkpoint: `3231f80996360912c6c1b27321ba3c8fee151370`

Branch head before this handoff refresh: `ba5969d76dce101e38ac2133ec02203000e1f49c`

Accepted UI marker: **build 27**

Repository rules still apply:

- Do not modify or merge original repo `main` without explicit user approval.
- Do not close GitHub issue #9 without explicit user approval.
- Preserve historical handoff files.
- Do not modify collaborator-owned legacy demo files without permission.
- Feature scope is frozen unless there is a real contest blocker.
- The user explicitly does **not** want a late rewrite of revision comparison just because it looks imperfect.
- Do not restart architecture work now. The project is in contest packaging / demo mode.

Primary technical handoff remains `docs/CONTEST_HANDOFF_CURRENT.md`.
This file is the latest AI-session handoff and supersedes older live-demo notes in this same file.

## Product invariant / demo message

Core invariant:

> No important AI claim without evidence, no evidence without a support check, no final report without human review.

Core demo line:

> **You do not have to trust the AI - here is the evidence trail.**

The product is neutral policy analysis, not political advocacy.

## Current live Microsoft Foundry state

The live deployment is:

- provider: Microsoft Foundry
- deployment/model: `gpt-5-mini`
- deployment type shown in Foundry: Global Standard
- working PolicyTrace endpoint: `https://policytrance.services.ai.azure.com`
- authentication used successfully: API key
- bearer token left blank

Do not store or request the actual key in source control or chat.

### Endpoint distinction

Do **not** use a Foundry project / Responses endpoint such as:

`https://policytrance.services.ai.azure.com/api/projects/proj-default/openai/v1/responses`

The current PolicyTrace Foundry client intentionally rejects `/api/projects/` endpoints and uses Chat Completions.

With the resource root above it constructs:

`https://policytrance.services.ai.azure.com/openai/v1/chat/completions`

Earlier project-endpoint attempts correctly failed with:

`POLICYTRACE_FOUNDRY_ENDPOINT must be a Microsoft Foundry Models resource endpoint, not a project endpoint, for Chat Completions`

After switching to the resource root, live analysis succeeded.

## Foundry proof captured

The Foundry playground successfully returned JSON equivalent to:

`{"policytrace_test":"ok"}`

Earlier Foundry Monitor checkpoint:

- 80 requests
- 290.2K total tokens

Latest Foundry Monitor checkpoint after the rehearsal:

- **109 total requests**
- **424.56K total tokens**
- **320.46K input tokens**
- **104.11K output tokens**
- **3,895 average tokens/request**

The increase between those two monitor snapshots was:

- +29 requests
- +134.36K tokens

Treat that delta as an estimate of the rehearsal only if no unrelated calls occurred between screenshots.

This is strong contest evidence that the deployed `gpt-5-mini` model actually processed PolicyTrace workload.

## Successful full live-demo rehearsal

Policy:

- Federal Register document: `2025-00636`
- title: **Framework for Artificial Intelligence Diffusion**
- RIN: `0694-AJ90`
- Regulations.gov docket: `BIS-2025-0001`
- report standard: Balanced
- current-status/freshness enabled
- public comments enabled
- related media enabled
- revision comparison disabled for this rehearsal
- provider: live Microsoft Foundry `gpt-5-mini`

The rehearsal completed the entire path successfully:

1. Federal Register source selection
2. source-package build before AI analysis
3. reproducible public-comment sampling
4. live Microsoft Foundry analysis
5. exact evidence display
6. supported / partially-supported / no-source verification states
7. human reviewer flag
8. section-by-section review
9. related-media curation
10. Leadership Report
11. Evidence Audit Log
12. explicit final human approval
13. audit log confirmed final status `approved`

Do not rerun this just to prove it again unless needed for the final video.

## Exact rehearsal sampling state

The rehearsal requested up to 12 comments, but the docket exposed only one submitted comment in the retrieved population.

Correct recorded values:

- requested up to: 12
- retrieved: 1
- analyzed: 1
- exact-text clusters: 1
- sampling method: random
- sample: 1/1
- sampling seed: `1953583223`
- selected comment: `BIS-2025-0001-0003`
- Regulations.gov population object: `09000064868c0462`
- initial logical position: 1
- replacement positions: none
- retrieval failures: 0
- unusable retrieved records: 0
- PII-pattern redactions: 0
- degraded source records: 0
- degraded attachments: 0

Do not describe this rehearsal as a 12-comment sample. It is a reproducible 1-of-1 sample.

The UI correctly warns that this material is not representative of the general public and must not be generalized to population-wide opinion.

## Verification examples used in the live demo

### Green / supported

The first plain-language finding about revised EAR controls and new AI-model-weight controls was supported by the Federal Register source.

The reviewer clicked the finding, saw the exact stored Federal Register passage in the `WHERE THIS COMES FROM` panel, and then opened the original Federal Register page.

This is a key demo moment.

### Orange / partially supported

The worldwide-license-requirement finding was marked `partially_supported`.

The verifier preserved:

- what the evidence supported
- what was not established
- suggested narrower wording

This is another strong demo moment because the verifier did not rubber-stamp the original model wording.

### No source / fail closed

Claim:

`claim-understanding-014`

The claim about License Exception LPP had:

- verification: `needs_human_review`
- report promotion: `BLOCKED`
- reason: no cited evidence
- evidence receipts: none

The reviewer flagged it during the rehearsal.

The rehearsal flag text was just `something`; this was only a practice run.
For the actual recorded demo use a clear reason such as:

`No cited evidence is attached to this finding, so it should not be promoted to the final report until supporting evidence is found.`

A second claim, `claim-provision-007`, was also blocked because no cited evidence was attached.

The final Leadership Report therefore recorded that **2 findings were withheld** from normal report promotion.

## Human-review / final-approval proof

The Evidence Audit Log after final approval records:

- analysis run: `rush-run-chunk4-2025-00636`
- final human review status: `approved`
- report standard: Balanced
- exact source passages and locators for evidence-backed claims
- reviewer flag preserved on `claim-understanding-014`
- blocked claim remained blocked
- final approval explicitly acknowledged the unresolved reviewer flag override

Important nuance:

The explicit final approval override did **not** promote the blocked claim into the Leadership Report.
The audit log preserves the override decision and the blocked finding.

This is an excellent demonstration of human accountability.

## Section-by-section rehearsal behavior

The live review showed:

- Plain-language explanation: mixture of supported, partially supported, and no-source finding
- Major provisions: mixture of supported, partially supported, and another blocked/no-source finding
- Potentially affected stakeholders: supported and partially supported claims
- Affected programs: no findings; system left the section empty rather than inventing content
- Public response in analyzed material: supported viewpoints from the single analyzed comment, with corpus limitation still visible
- Conflicting and emerging viewpoints: no findings; system did not manufacture a trend from insufficient material
- Related media / factual reporting: discovery pointers only, not article-body factual verification

## Related media state from the rehearsal

The rehearsal discovered 8 GDELT source pointers.

Important current result:

- Media Cloud: skipped because no Media Cloud key was configured
- GDELT: used, 8 recent source pointers discovered
- reviewer excluded **1** media pointer during the rehearsal
- **7** media pointers remained selected for the report

The excluded pointer was the Rador item:

`Calendarul evenimentelor , 25 septembrie - selectiuni | Agentia de presa Rador`

The audit log records that item as `EXCLUDED BY REVIEWER`.

Do not use the older statement that all 8 were excluded; that was from an earlier run and is stale.

Media claims remain discovery-only pointers:

- provider-supplied headline/title stored
- article body not ingested
- article body not verified
- human should open original source before relying on factual content

## Leadership Report proof

The final Leadership Report:

- was approved
- contains reviewed findings that passed report-promotion gates
- keeps partially supported findings visibly labelled
- says 2 findings were withheld because an evidence, verification, report-standard, or reviewer gate remained unresolved
- carries stable claim IDs linking report lines back to the Evidence Audit Log
- includes current-status/freshness and corpus limitations
- records 8 media items discovered and 7 selected for report

The report is the judge-facing output; the Evidence Audit Log is the traceable receipt layer.

## Saved project JSON from rehearsal

Latest saved setup file was created at:

`2026-09-25T09:05:54.914Z`

It preserves:

- primary document: `2025-00636`
- current status: true
- comments: true
- news: true
- comparison: false
- docket: `BIS-2025-0001`
- max comments: 12
- sampling method: random
- sampling seed: `1953583223`
- max articles: 8
- report standard: Balanced
- excluded media claim ID for the Rador pointer

Important terminology:

This JSON is an **intake/setup plan**, not a full persisted reviewed AnalysisRun.
Do not describe Save/Load as full-session persistence.

## Revision comparison status

The user previously ran revision comparison in a separate run, but that comparison run was not saved.

The user thinks the comparison output may be a little imperfect and explicitly does not want a late rewrite.

Current rule:

- do not change revision-comparison code unless it is a genuine contest blocker
- do not infer failure from a run where `include_comparison=false`
- if comparison is shown in the final demo, do one controlled known-good comparison run and capture it
- otherwise leave it out of the main live demo path

Correct description of the architecture:

- exact matches first
- unusual / rare phrase anchors and candidate retrieval
- position / corridor hints
- bounded fuzzy matching on a shortlist
- moved + edited provisions can be recovered
- weak matches remain removed + added
- deterministic comparison is separate from AI interpretation

Do not oversell it as simple line-by-line diffing.

## Current local run instructions

The user's local checkout is:

`C:\Users\steveon\microsoft-letastlator-thing`

Git Bash path:

`~/microsoft-letastlator-thing`

Startup:

```bash
cd ~/microsoft-letastlator-thing
git checkout fix/contest-phase1-comment-resilience
git pull
python -m pip install -r backend/requirements.txt
python backend/run_app.py
```

Open:

`http://127.0.0.1:8777/`

The current product UI is served from:

`frontend/app`

The older `frontend/demo/` is historical/reference only.

## Nonfatal live warnings

Console messages like:

`Ignoring wrong pointing object ...`

appeared while extracting PDF material.

They did not abort the run.
The main analysis returned HTTP 200 and the workflow completed.

Treat these as nonfatal PDF-parser noise unless a future run actually loses content or fails.

## Live validation status

Validated live:

- Foundry deployment exists
- `gpt-5-mini` responds in Foundry playground
- PolicyTrace accepts the Foundry provider configuration
- API-key auth works against the resource endpoint
- real Federal Register analysis works through Foundry
- comment intake / sampling works
- claim verification works
- partial-support notes work
- no-evidence deterministic citation gate works
- human flagging works
- section review works
- media inclusion/exclusion works
- Leadership Report works
- Evidence Audit Log works
- explicit unresolved-flag acknowledgement works
- final human approval works
- final audit log says `approved`
- Foundry Monitor records substantial real usage

Optional / incomplete if time permits:

- bearer-token auth has not been separately live-validated with API key unset
- deliberately bad credential has not been captured as a fresh demo screenshot
- malformed model-output handling is covered in tests but was not deliberately forced live
- revision comparison has not been re-captured in this current approved rehearsal

Do not risk the stable demo to satisfy optional items.

## Mirror repository state

Mirror repo:

`steveonw/jubilant-funicular`

Mirror `main` was previously synced to the exact tree of code checkpoint `3231f80996360912c6c1b27321ba3c8fee151370` at mirror commit:

`4d5df57be495591614115cc48e34f086d06de9b6`

Since then, this original working branch has gained documentation-only AI handoff commits.

Therefore the mirror is no longer guaranteed to include the latest handoff document changes.

Before final submission, if the mirror is the judge-facing repository, intentionally resync the final desired tree and verify it again.

## Exact polished demo path

Keep the recorded demo short.

Suggested sequence:

1. show build 27 and Microsoft Foundry `gpt-5-mini`
2. select `2025-00636`
3. show source package / docket / reproducible sampling before AI starts
4. run analysis
5. click one green supported finding
6. show exact evidence in `WHERE THIS COMES FROM`
7. open the original Federal Register page
8. return and click one orange partially-supported finding
9. show `Supported` vs `Not established`
10. show the no-source finding and flag it with a clear explanation
11. move quickly through remaining sections
12. point out empty sections rather than invented findings
13. show public-comment corpus limitation
14. exclude one noisy media pointer
15. build Leadership Report
16. show withheld-findings limitation and claim IDs
17. open Evidence Audit Log and show blocked flagged claim preserved
18. approve report with explicit unresolved-flag acknowledgement
19. show final audit log status `approved`
20. briefly show Foundry Monitor as proof of real deployment usage

Do not spend time re-demonstrating every claim.

## What comes next

The technical proof is complete enough for contest packaging.

Priority order:

1. record polished final video using the rehearsal path
2. make the PowerPoint / presentation
3. finish the contest project/submission page
4. freeze the GitHub version
5. intentionally sync the final judge-facing mirror if needed
6. capture final screenshots / proof
7. do one clean start-to-finish submission rehearsal
8. verify video, PPT, GitHub, and project-page links
9. submit before the contest deadline

Official contest deadline previously confirmed from the rules: **2026-09-25 at 11:30 PM ET**.

Do not spend the remaining time on speculative feature work.

## Current uploaded evidence worth preserving

Latest rehearsal evidence includes:

- PolicyTrace start / intake screens
- live Foundry running screen
- PolicyTrace review screen with supported and partially-supported findings
- click-through from evidence panel to original Federal Register page
- no-source / human-flag screen
- Major provisions screen
- Potentially affected stakeholders screen
- empty Affected programs screen
- Public response screen
- empty Conflicting and emerging viewpoints screen
- Related media screen and reviewer exclusion
- Leadership Report
- pre-approval Evidence Audit Log
- final approved Leadership Report
- final approved Evidence Audit Log
- saved setup JSON
- Foundry Monitor showing 109 requests / 424.56K tokens

These are conversation artifacts and are not assumed to be committed to GitHub.

## Immediate instruction to the next AI

Start by reading:

1. `docs/CONTEST_HANDOFF_CURRENT.md`
2. `docs/AI_HANDOFF_CURRENT.md`
3. current branch `fix/contest-phase1-comment-resilience`

Then continue with **video / PowerPoint / submission packaging**.

Do not restart development unless a real blocker appears.

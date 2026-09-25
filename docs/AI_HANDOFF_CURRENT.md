# PolicyTrace - AI Handoff (Current)

Date: 2026-09-25
Purpose: preserve the latest live Microsoft Foundry validation state and the immediate contest-demo context so another AI can resume without reconstructing the session.

## Read this first

Repository: `steveonw/microsoft-letastlator-thing`

Working branch: `fix/contest-phase1-comment-resilience`

Current branch checkpoint before this handoff: `3231f80996360912c6c1b27321ba3c8fee151370`

Accepted UI marker: **build 27**

Repository rules still apply:

- Do not modify or merge original repo `main` without explicit user approval.
- Do not close GitHub issue #9 without explicit user approval.
- Preserve historical handoff files.
- Do not modify collaborator-owned legacy demo files without permission.
- Feature scope is frozen unless there is a real contest blocker.
- The user explicitly does **not** want a late rewrite of revision comparison just because it looks imperfect.

Primary handoff remains `docs/CONTEST_HANDOFF_CURRENT.md`. This file adds the latest live Foundry state.

## Current live Microsoft Foundry state

The live model deployment is:

- provider: Microsoft Foundry
- deployment/model: `gpt-5-mini`
- deployment type shown in Foundry: Global Standard
- working resource endpoint entered in PolicyTrace: `https://policytrance.services.ai.azure.com`
- authentication used successfully: API key
- bearer token left blank

Do not store or request the actual key in source control or chat.

### Important endpoint distinction

A Foundry project/Responses endpoint such as:

`https://policytrance.services.ai.azure.com/api/projects/proj-default/openai/v1/responses`

is **not** the endpoint expected by the current PolicyTrace Foundry client.

The client intentionally rejects endpoints containing `/api/projects/` and currently uses Chat Completions. With the resource root above it constructs:

`https://policytrance.services.ai.azure.com/openai/v1/chat/completions`

The earlier project-endpoint attempts correctly failed with:

`POLICYTRACE_FOUNDRY_ENDPOINT must be a Microsoft Foundry Models resource endpoint, not a project endpoint, for Chat Completions`

After switching to the resource root, the real analysis request succeeded.

## Foundry proof captured

The Foundry playground successfully answered the sanity prompt with JSON equivalent to:

`{"policytrace_test":"ok"}`

The Microsoft Foundry deployment Monitor later showed:

- **290.2K total tokens**
- **80 requests**

This is strong contest evidence that the deployed `gpt-5-mini` model actually processed the PolicyTrace workload rather than only appearing in configuration.

Keep the Foundry Monitor screenshot/report as submission/demo evidence.

## Latest real PolicyTrace Foundry run

The successful uploaded run used:

- Federal Register document: `2025-00636`
- title: **Framework for Artificial Intelligence Diffusion**
- RIN: `0694-AJ90`
- Regulations.gov docket: `BIS-2025-0001`
- report standard: Balanced
- current-status/freshness check enabled
- public comments enabled
- related media enabled
- API provider: live Microsoft Foundry `gpt-5-mini`

The run completed through the product workflow and reached final human approval.

The Evidence Audit Log records:

- analysis run `rush-run-chunk4-2025-00636`
- final human review status: approved
- supported findings
- partially supported findings with explicit supported/not-established explanations
- findings blocked from report promotion when citation/evidence integrity failed
- exact evidence passages, source IDs, locators, URLs, verification notes, and reviewer state

This is a strong demonstration of the product invariant:

> No important AI claim without evidence, no evidence without a support check, no final report without human review.

## Public-comment result in this run

The intake requested up to 12 comments, but this docket exposed only one submitted comment in the retrieved population.

PolicyTrace therefore correctly reported:

- requested up to 12
- retrieved 1
- analyzed 1
- random sample 1/1
- sampling seed `2207298060`
- selected comment `BIS-2025-0001-0003`
- no retrieval failures
- no unusable retrieved records
- no PII-pattern redactions
- no degraded source records/attachments

Do not describe this run as a 12-comment sample. It is a 1-of-1 sample with a recorded seed and reproducibility receipt.

## Related media result

The run attempted the multi-source news discovery path.

For this run:

- Media Cloud was skipped because no Media Cloud key was configured.
- GDELT returned 8 recent source pointers.
- The reviewer excluded all 8 from use.
- The audit correctly describes media results as headline/source discovery pointers, not verified article-body factual claims.

This is acceptable product behavior and should not be rewritten late.

## Revision comparison - important clarification

The user has a **separate run** in which revision comparison was enabled and executed. The user feels the comparison output may look a little imperfect, but explicitly does not want a late change unless it becomes a real demo blocker.

The uploaded saved project JSON from the Foundry run described above is **not** the comparison run. It contains:

- `comparison_document_number: "2026-06851"`
- `include_comparison: false`

So that JSON proves only that a comparison document value was present while comparison was disabled for that particular run.

Do not use that JSON to conclude the comparison algorithm failed.

Also remember that `GET /api/revision-comparison` returning HTTP 200 does not prove a comparison exists; the backend can validly return `{"available": false}`.

If revisiting comparison before submission:

1. inspect the user's separate comparison-run screenshot/report first;
2. distinguish UI presentation/matching quality from an actual functional failure;
3. make no code change unless the issue is a genuine contest/demo blocker;
4. if necessary, demo a known-good comparison run or leave comparison out of the live path rather than destabilizing build 27.

## Local run state / Git Bash

The user's local checkout is at:

`C:\Users\steveon\microsoft-letastlator-thing`

In Git Bash the practical path is:

`~/microsoft-letastlator-thing`

Normal startup:

```bash
cd ~/microsoft-letastlator-thing
git checkout fix/contest-phase1-comment-resilience
git pull
python -m pip install -r backend/requirements.txt
python backend/run_app.py
```

Open:

`http://127.0.0.1:8777/`

The live console confirmed the current frontend is served from:

`frontend/app`

The log showed initial Foundry endpoint failures followed by a successful:

`POST /api/intake/run -> 200`

and then successful review/report endpoints including Rush review, reanalysis review, Leadership Report, Evidence Audit Log, and final approval.

## PDF extraction warnings seen live

The console emitted messages like:

`Ignoring wrong pointing object ...`

while processing PDF material.

These warnings did **not** abort the run. The main analysis subsequently returned HTTP 200 and the workflow completed. Treat them as nonfatal PDF parsing noise unless a future run actually loses source content or fails.

## What has been validated live vs. what remains

Validated live:

- Foundry deployment exists
- `gpt-5-mini` responds in Foundry playground
- PolicyTrace accepts the Foundry provider configuration
- API-key authentication works against the resource endpoint
- real Federal Register analysis works through Foundry
- claim verification executes
- human review executes
- Leadership Report works
- Evidence Audit Log works
- final human approval works
- comment sampling receipt works
- Foundry Monitor records real usage

Still optional / incomplete if time permits:

- bearer-token authentication has not yet been separately live-validated with API key unset
- an intentionally bad credential has not yet been captured as a fresh live failure screenshot
- malformed model-output handling is covered in code/tests but was not deliberately forced in this live deployment
- preserve a screenshot/report from the user's separate known comparison run if comparison will be shown in the demo
- capture the cleanest final screenshots for the contest video / presentation

Do not risk the stable demo simply to satisfy optional validation items.

## Useful demo narrative

A compact live-demo sequence is:

1. choose an authoritative Federal Register policy;
2. build the source package before spending AI calls;
3. run analysis through Microsoft Foundry;
4. show an AI finding;
5. click through to its exact source passage;
6. show verifier status, including a partially supported or blocked example;
7. perform/confirm human review;
8. build the Leadership Report;
9. open the Evidence Audit Log;
10. complete final human approval;
11. briefly show Foundry Monitor as proof of the real provider integration.

Core line:

> **You do not have to trust the AI - here is the evidence trail.**

## Uploaded evidence from this session

The user supplied these artifacts during the live validation session:

- `PolicyTracepreslect.pdf` - intake/provider screen showing Microsoft Foundry, `gpt-5-mini`, resource endpoint, source-builder workflow, and policy search/intake state
- `PolicyTracemain sellection thing.pdf` - reviewed run summary for `2025-00636`
- `policytrace-2025-00636.json` - saved intake/setup plan; credentials intentionally absent
- `PolicyTracemicrosoft trace log.pdf` - Evidence Audit Log from the approved live Foundry run
- `Microsoft Foundry stats.pdf` - deployment Monitor showing 290.2K tokens and 80 requests

These were conversation uploads and are not assumed to be committed to the repository.

## Immediate recommendation for the next AI/session

Start by reading:

1. `docs/CONTEST_HANDOFF_CURRENT.md`
2. this file
3. the current branch at `fix/contest-phase1-comment-resilience`

Do not restart architecture work.

The priority is now **contest packaging, screenshots/video, and only true blockers**.

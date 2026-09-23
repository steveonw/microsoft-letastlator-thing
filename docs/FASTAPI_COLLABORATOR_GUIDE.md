# FastAPI Collaborator Guide — Production Path for PolicyTrace

This guide is for the teammate working on `backend/api.py` and `frontend/demo/`.

The goal is **not** to replace your FastAPI work. Your FastAPI app is the production shell we want to keep. The separate full-stack reference in PR #36 exists to show the backend behavior and API contract that can be ported into your app gradually.

## 1. The product we are building

PolicyTrace is an AI-assisted policy-analysis workspace for government analysts.

The finished workflow should connect:

```text
policy input
    ↓
trusted ingestion / normalization
    ↓
Microsoft Foundry AI analysis
    ↓
evidence grounding
    ↓
claim verification
    ↓
Guided or Rush human review
    ↓
selective correction / refresh
    ↓
traceable final brief
```

The core rule is:

> No important AI claim without evidence, no evidence without a support check, and no final report without human review.

## 2. What your FastAPI work already gives us

`backend/api.py` already establishes several good production choices:

- FastAPI is the application server.
- The UI is served from the same application.
- `AnalysisRun` is the shared response shape.
- `GET /api/analysis` proves Python backend → browser rendering.
- The existing UI already has the three-pane mental model:
  - analysis steps
  - current analysis / claims
  - evidence
- The page already exposes the human-review actions visually.

Keep those choices.

The current endpoint is intentionally small:

```text
GET /api/analysis
```

It currently returns a checked-in Federal Register fixture analysis. That is a good smoke test, but it is not the final data flow.

## 3. Merge conflict resolution

The branch `fix/fastapi-demo-conflicts-and-guide` resolves the literal conflict markers that were present in:

- `frontend/demo/app.js`
- `frontend/demo/index.html`
- `frontend/demo/README.md`

The resolution deliberately keeps **both useful sides**:

### From the FastAPI work
- use `/api/analysis`
- run through Uvicorn/FastAPI
- serve at `/demo/`
- label the source as the Federal Register demo

### From the Guided UI work
- keep review controls
- keep browser persistence for the current bridge implementation
- keep Reset review
- keep Clarify / Edit / Flag / Next behavior
- keep source/evidence rendering

This is only a conflict cleanup. It does **not** try to move all production state to FastAPI in one jump.

## 4. Important next architectural change: server-authoritative state

The current frontend still mutates review state in browser `localStorage`.

That was useful for the earlier demo, but the target architecture is:

```text
Browser
   ↓ action request
FastAPI
   ↓
authoritative AnalysisRun
   ↓
validated updated AnalysisRun
   ↓
Browser renders response
```

The browser should eventually stop being the source of truth.

Why:
- Guided and Rush need one shared engine.
- selective re-analysis needs dependency state.
- final human approval must be trustworthy.
- refreshing the browser should not invent a separate workflow state.
- the final brief must be built from the authoritative reviewed analysis.

## 5. Port the reference contract in small stages

Do **not** copy `backend/run_full_stack_guide.py` wholesale into `api.py`.

Use it as a behavior reference and move capability into FastAPI incrementally.

### Stage A — source input

Add real policy input first.

Target routes:

```text
POST /api/source/load
POST /api/source/comments
```

Suggested request shapes:

```json
{
  "document_number": "2024-20529"
}
```

```json
{
  "docket_id": "BIS-2024-0047",
  "max_comments": 12
}
```

Behavior:

```text
Federal Register document number
        ↓
fetch_and_normalize()
        ↓
run_policy_interpreter()
        ↓
authoritative AnalysisRun
```

Then:

```text
Regulations.gov docket
        ↓
fetch_comments_for_docket()
        ↓
source_from_response_record()
        ↓
run_response_viewpoint_analyst()
        ↓
combine with current policy analysis
```

Keep policy input and related-response input visually separate.

### Stage B — Guided actions

Target routes:

```text
POST /api/guided/begin
POST /api/guided/clarify
POST /api/guided/edit
POST /api/guided/flag
POST /api/guided/verify
POST /api/guided/next
```

Important rule:

> Only explicit Next advances Guided Mode.

Frontend buttons should call the API and re-render the returned `AnalysisRun`.

### Stage C — Rush Mode

Target routes:

```text
POST /api/rush/run
POST /api/rush/open
POST /api/rush/final
POST /api/rush/approve
```

Rush should:
- run the same analysis pipeline
- preserve intermediate sections
- stop at `final_review_status=in_review`
- never auto-approve
- allow a human to open a section for review

### Stage D — selective re-analysis

Target routes:

```text
POST /api/reanalysis/step
POST /api/reanalysis/refresh
POST /api/reanalysis/review
```

Behavior:
- replace only the chosen step
- preserve unrelated/upstream work
- mark only transitive dependents `needs_refresh`
- refresh in dependency order
- revoke previous final approval after changes

### Stage E — final brief

Target route:

```text
POST /api/brief
```

The final brief must be assembled only from reviewed/accepted material.

It must not introduce new substantive claims.

## 6. Input UI we ultimately want

The contest demo needs a real starting point, not preloaded data.

### Policy input

```text
Choose policy input

[ Federal Register ]
Document number: 2024-20529

[ Paste text ]

[ Upload file ]
PDF / TXT / DOCX / JSON
```

Federal Register is the required polished path for the hackathon.

Paste/upload can be added after the core real-source path is stable.

### Related sources

Keep them separate from policy input:

```text
Public comments
Regulations.gov docket: BIS-2024-0047

Later:
News
Correspondence
Survey
Other supporting documents
```

Keep source types explicit:

```text
official policy        → OFFICIAL_POLICY
public comment         → PUBLIC_OPINION
news/reporting         → FACTUAL_REPORTING
organization statement→ STAKEHOLDER_CLAIM
AI finding             → AI_INTERPRETATION
human edit             → HUMAN_INTERPRETATION
```

## 7. UI direction

Your existing three-column UI is aligned with the product vision.

Keep this mental model:

```text
+----------------+-------------------------+------------------+
| Analysis Steps | Current Analysis        | Evidence         |
|                |                         |                  |
| Policy         | claim / explanation     | exact passage    |
| Provisions     |                         | source type      |
| Stakeholders   | edit / verify / flag    | locator          |
| Response       |                         | verification     |
| Verification   | human notes             | source link      |
| Brief          |                         |                  |
+----------------+-------------------------+------------------+
```

Add above it:

```text
SOURCE INPUT
Federal Register | Paste | Upload

RELATED MATERIAL
Regulations.gov comments
```

And add mode entry:

```text
[ Begin Guided ]   [ Run Rush ]
```

The judge should be able to understand where the information came from without reading code.

## 8. Statuses the UI should make visible

Do not hide these states:

### Claim verification
- supported
- partially supported
- needs clarification
- unsupported
- needs human review

### Human review
- not reviewed
- in review
- reviewed
- approved

### Step state
- draft
- verified
- needs refresh

### Source information type
Examples:
- OFFICIAL_POLICY
- PUBLIC_OPINION
- FACTUAL_REPORTING
- AI_INTERPRETATION
- HUMAN_INTERPRETATION

This separation is a major part of the challenge.

## 9. Evidence handling

Evidence is not decorative text.

The authoritative contract requires:

```text
source.raw_text[start_offset:end_offset] == evidence.snippet
```

Do not create frontend behavior that edits evidence text.

A claim can fail semantic verification even when its citation is mechanically valid.

Likewise:

**a broken citation does not automatically mean the claim is false.**

A citation-integrity failure should remain visible for human review.

## 10. Public response design

Do not reduce comments to one positive/negative score.

The UI should eventually expose lenses like:

- reasons for support
- concerns / objections
- questions / misunderstandings
- mixed / neutral responses
- minority / conflicting viewpoints
- emerging issues when supported

Also show the representativeness note.

Example:

```text
Analyzed 12 supplied comments.
These comments should not automatically be treated as representative of
the general population.
```

## 11. PII and source trust

The current ingestion path includes a PII gate, but live testing exposed two issues that are being hardened separately:

- sentence-ending email addresses can evade the current regex
- some PDFs can produce badly glued text / Unicode ligatures

Do not add frontend text claiming a source is "safe" or "fully redacted."

Render the actual backend `pii_redaction_status` if we decide to expose it.

## 12. Provider / credential behavior

For local development, PolicyTrace supports:
- OpenRouter
- OpenAI
- Microsoft Foundry
- deterministic offline fixtures

The contest **requires Microsoft Foundry**, so the final demo must use Foundry for a real core workflow.

Secrets must:
- never be committed
- never appear in `AnalysisRun`
- never be returned by provider-status endpoints
- stay in environment/process memory or an appropriate secret store

Do not persist provider secrets in browser `localStorage`.

## 13. Reference implementation

PR #36:

```text
guide/full-stack-reference
```

contains a working reference for:

- real Federal Register source load
- Regulations.gov comments
- provider configuration
- Guided Mode
- Rush Mode
- Chunk 9 selective re-analysis
- final brief
- evidence rendering

Use it to understand behavior and endpoint responses.

It is intentionally **not** the final frontend and intentionally does not replace your FastAPI work.

## 14. Primary hackathon demo case

Build toward this one case first:

```text
Federal Register:
2024-20529

Regulations.gov docket:
BIS-2024-0047
```

The final browser experience should demonstrate:

```text
enter source
   ↓
load policy
   ↓
policy interpretation + evidence
   ↓
load comments
   ↓
viewpoint analysis + representativeness
   ↓
verification
   ↓
human review
   ↓
correct one section
   ↓
selective refresh
   ↓
final brief
   ↓
human approval
```

One reliable real workflow is more valuable than many half-connected sources.

## 15. Suggested implementation order for your area

1. Resolve current frontend conflict markers.
2. Confirm current FastAPI fixture demo runs.
3. Keep `GET /api/analysis` as a simple smoke-test route.
4. Add authoritative in-memory analysis state.
5. Add real Federal Register input route.
6. Add Guided API routes and move review mutations off localStorage.
7. Add Regulations.gov comment input.
8. Add Rush routes.
9. Add selective re-analysis routes.
10. Add final brief route.
11. Connect Microsoft Foundry for the contest path.
12. Polish loading/errors/progress.

Do not try to do all twelve in a single commit.

## 16. Local smoke test

From repository root:

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn api:app --app-dir backend --reload
```

Open:

```text
http://127.0.0.1:8000/demo/
```

Also inspect:

```text
http://127.0.0.1:8000/api/analysis
http://127.0.0.1:8000/docs
```

For the current conflict-cleanup branch, verify:

- page loads without JavaScript syntax errors
- Federal Register demo AnalysisRun renders
- claim selection changes the Evidence pane
- Clarify/Edit/Flag work on the current step
- Next is the only action that advances
- Reset clears local review state
- no `<<<<<<<`, `=======`, or `>>>>>>>` markers remain

## 17. Collaboration boundaries

The teammate working on FastAPI/frontend owns this production integration area.

Other backend work should avoid overwriting it.

Likewise, while porting from PR #36:
- use the reference implementation as a contract
- reuse existing backend engines
- do not duplicate the analysis logic in JavaScript
- do not create a second incompatible `AnalysisRun` format

The Python backend should own analysis semantics; the frontend should display state and send explicit human actions.

## 18. End state

We are aiming for:

```text
INPUT
  ↓
FASTAPI
  ↓
TRUSTED INGESTION
  ↓
MICROSOFT FOUNDRY
  ↓
AUTHORITATIVE AnalysisRun
  ↓
EVIDENCE + VERIFICATION
  ↓
GUIDED / RUSH HUMAN REVIEW
  ↓
SELECTIVE CORRECTION
  ↓
TRACEABLE FINAL BRIEF
```

Your FastAPI work is the correct place for the production HTTP/UI integration. The reference guide exists to help you reach this end state without having to invent the workflow contract from scratch.

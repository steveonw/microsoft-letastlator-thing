# Target FastAPI Contract

This is the endpoint contract demonstrated by PR #36 and intended to be ported into the production FastAPI app.

It is a **target contract**. Not every route exists on `main` yet.

## Response conventions

For workflow actions, success should normally return the authoritative `AnalysisRun`.

Recommended error mapping:

```text
400  invalid request or invalid workflow state
404  unknown route/resource
502  external source/model provider failure
```

FastAPI may use:

```json
{"detail": "message"}
```

The PR #36 reference server uses:

```json
{"error": "message"}
```

The frontend helper should tolerate either during transition.

---

## Current smoke-test route

### GET /api/analysis

Returns the current authoritative `AnalysisRun`.

Current production implementation on `main` builds the checked-in Federal Register fixture.

Target behavior later: return current in-memory analysis state.

---

## Provider configuration

### GET /api/provider

Returns provider status only, never secrets.

Example shape:

```json
{
  "kind": "foundry",
  "model": "deployment-name",
  "base_url": "",
  "endpoint": "https://example.services.ai.azure.com/...",
  "has_api_key": true,
  "has_bearer_token": false,
  "has_regulations_api_key": true,
  "credentials_storage": "process_memory_only"
}
```

### POST /api/provider

Request:

```json
{
  "kind": "foundry",
  "model": "deployment-name",
  "endpoint": "https://...",
  "api_key": "...",
  "bearer_token": "",
  "regulations_api_key": "..."
}
```

Rules:

- OpenRouter requires API key.
- OpenAI requires API key + model.
- Foundry requires endpoint + model + exactly one of API key or bearer token.
- Secrets must never be returned.
- For contest use, Microsoft Foundry is the required core provider path.

### POST /api/provider/clear

Request:

```json
{}
```

Clears provider credentials from process memory and returns safe provider status.

---

## Source input

### POST /api/source/load

Request:

```json
{
  "document_number": "2024-20529"
}
```

Behavior:

```text
Federal Register
    ↓
fetch_and_normalize
    ↓
Policy Interpreter
    ↓
authoritative AnalysisRun
```

Success: `AnalysisRun`

Expected 400 examples:
- empty document number
- no live model provider configured

Expected 502 examples:
- Federal Register retrieval failure
- model provider failure

State effect:
- set current policy document
- set current policy analysis
- clear previous response/comment analysis
- replace current analysis
- clear stale final approval/brief state

### POST /api/source/comments

Request:

```json
{
  "docket_id": "BIS-2024-0047",
  "max_comments": 12
}
```

Validation:
- policy must already be loaded
- Regulations.gov API key required
- `max_comments` integer 1–100

Success: combined policy + response `AnalysisRun`

Expected 400 examples:
- no policy loaded
- missing API key
- bad max_comments
- no usable comments returned

Expected 502:
- Regulations.gov retrieval failure
- response-analysis model failure

---

## Reset

### POST /api/reset

Request:

```json
{
  "mode": "guided"
}
```

For Guided mode, reset review state from the currently loaded source analysis.

The real loaded source should remain loaded.

---

## Guided Mode

### POST /api/guided/begin

Request:

```json
{}
```

or:

```json
{
  "step_id": "step-id"
}
```

Success: Guided `AnalysisRun` with a current step in review.

### POST /api/guided/clarify

Request:

```json
{
  "note": "Keep proposed-rule wording."
}
```

Success: updated `AnalysisRun`

### POST /api/guided/edit

Request:

```json
{
  "claim_id": "claim-id",
  "text": "Human-edited claim text"
}
```

Required state effects:
- preserve original text
- mark as `human_interpretation`
- require re-verification
- keep human review in progress

### POST /api/guided/flag

Request:

```json
{
  "claim_id": "claim-id",
  "note": "Needs another look"
}
```

`note` may be empty/optional.

### POST /api/guided/verify

Request:

```json
{
  "claim_id": "claim-id"
}
```

Success: updated `AnalysisRun`

Provider failure should not silently become supported/unsupported. Preserve the claim for human review.

### POST /api/guided/next

Request:

```json
{}
```

Rule:

> This is the only Guided action that advances to the next step.

Invalid state should return 400.

---

## Rush Mode

### POST /api/rush/run

Request:

```json
{}
```

Behavior:
- use the currently loaded real policy/response analysis if present
- run the same core pipeline
- stop at mandatory final human review

Success:
- `mode = "rush"`
- `final_review_status = "in_review"`
- never auto-approved

### POST /api/rush/open

Request:

```json
{
  "step_id": "step-id"
}
```

Opens one Rush step for human review.

### POST /api/rush/final

Request:

```json
{}
```

Returns from step-level review to Rush final review.

### POST /api/rush/approve

Request:

```json
{}
```

Must only succeed from the valid final-review state.

Approval is always explicit human action.

---

## Selective re-analysis

These routes depend on the Chunk 9 engine from PR #35.

### POST /api/reanalysis/step

Reference request:

```json
{
  "step_id": "step-id",
  "text": "replacement first-claim text"
}
```

The guide uses replacement text to demonstrate behavior. Production regeneration can later call the appropriate analysis engine.

Required invariants:
- change selected step only
- preserve unrelated/upstream steps
- increment regenerated step version
- mark transitive dependents `needs_refresh`
- revoke previous final approval
- require human re-review

### POST /api/reanalysis/refresh

Request:

```json
{
  "step_id": "step-id"
}
```

Must enforce dependency order.

### POST /api/reanalysis/review

Request:

```json
{
  "step_id": "step-id"
}
```

Should not allow a `needs_refresh` step to be marked reviewed before refresh.

---

## Final brief

### POST /api/brief

Request:

```json
{}
```

Success: updated `AnalysisRun` containing the assembled brief step/output.

Rules:
- refuse while dependent work is stale
- assemble only reviewed/accepted material
- preserve claim/evidence traceability
- do not introduce new substantive claims

---

## Future input routes

Not yet defined as a stable contract:

- pasted policy text
- file upload
- direct policy URL
- news input

Add those after the Federal Register + Regulations.gov path is stable.

# First Three Commits

The collaborator guide contains the full roadmap. This file narrows the immediate work to three small commits.

Do not attempt Rush, comments, Chunk 9, uploads, and Foundry UI all at once.

## Commit 1 — FastAPI owns one AnalysisRun

### Goal

Stop treating the browser's `localStorage` copy as the long-term authority.

Add a small application state holder in Python.

Conceptually:

```python
class AppState:
    analysis: AnalysisRun
    document: NormalizedPolicyDocument | None
    policy_analysis: AnalysisRun | None
    response_analysis: AnalysisRun | None
```

For this commit, it is fine to initialize `analysis` from the existing fixture.

### Required behavior

```text
GET /api/analysis
       ↓
returns current server-side AnalysisRun
```

Do not add persistence/database work yet.

### Acceptance criteria

- `/api/analysis` returns valid `AnalysisRun`
- browser still renders it
- restarting Uvicorn resets in-memory state
- no secrets are stored in `AnalysisRun`
- existing fixture smoke test still works

### Known limitation

This is single-process, demo-oriented state. It is not yet multi-user persistence.

That is acceptable for the hackathon MVP if documented.

---

## Commit 2 — Real Federal Register input

### Goal

Turn the production UI from a preloaded demo into the actual product.

Add:

```text
POST /api/source/load
```

Request:

```json
{
  "document_number": "2024-20529"
}
```

Wire it to the existing backend:

```text
document number
    ↓
fetch_and_normalize()
    ↓
run_policy_interpreter()
    ↓
AnalysisRun
    ↓
server state
    ↓
browser
```

### Frontend

Add a small source-input area above the existing three-pane workspace:

```text
Federal Register document
[ 2024-20529 ] [ Load + Analyze ]
```

Do not redesign the whole page.

### Acceptance criteria

- enter `2024-20529`
- click Load + Analyze
- request goes to FastAPI
- returned analysis becomes server authority
- three-pane UI renders real Policy Interpreter steps
- source evidence opens/renders
- second policy load replaces prior policy state
- old response/comment analysis is cleared

### Error behavior

Show backend error text in the UI.

Do not replace the page with a stack trace.

---

## Commit 3 — Move Guided Begin + Next to FastAPI

### Goal

Prove the human-review state machine can be server-authoritative before porting every Guided action.

Add:

```text
POST /api/guided/begin
POST /api/guided/next
```

Use the existing backend Guided functions.

### Frontend

Replace browser mutation for these two actions with API calls:

```text
button click
    ↓
POST action
    ↓
server updates AnalysisRun
    ↓
browser replaces state.analysis with response
    ↓
render
```

### Required rule

**Only `/api/guided/next` advances the current Guided step.**

### Acceptance criteria

- Begin starts review on server
- reload fetches the server's current Guided state
- Next advances exactly one step
- future steps stay locked
- invalid Next returns a visible 400-style error
- no duplicate request is sent by double-clicking

---

## After these three commits

Then port, in this order:

1. Guided Clarify/Edit/Flag/Verify
2. Regulations.gov comments
3. Rush
4. selective re-analysis
5. final brief
6. Foundry production/demo provider UX
7. paste/upload inputs
8. optional news/revision features

The reason for this order is simple:

```text
real input
   +
server authority
   +
one real human workflow
```

creates the actual PolicyTrace product spine.

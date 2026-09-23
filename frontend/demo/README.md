<<<<<<< HEAD
# PolicyTrace Guided Mode demo

This dependency-free demo now exercises the Chunk 7 human review loop over the fictional `shared/sample-analysis.json`.

Run from the repository root:
=======
# PolicyTrace demo frontend

This dependency-free UI renders an `AnalysisRun` returned by the Python backend.
The FastAPI app serves the page and exposes `GET /api/analysis` on the same
origin. That endpoint runs the existing Federal Register normalization and
evidence builder against the checked-in fixture, so the demo works offline.

## Run it locally

From the repository root:
>>>>>>> fb898af (Adding Fast API initializer)

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn api:app --app-dir backend --reload
```

Open <http://127.0.0.1:8000/demo/>. The API response is available at
<http://127.0.0.1:8000/api/analysis>, and FastAPI's interactive API docs are
at <http://127.0.0.1:8000/docs>.

<<<<<<< HEAD
```text
http://localhost:8000/frontend/demo/
```

Guided Mode behavior:
- future steps are locked until the human advances
- **Show Sources** is always visible in the evidence panel for the selected claim
- **Clarify** stores a reviewer note
- **Edit** preserves `original_text`, marks the claim as `human_interpretation`, and requires re-verification
- **Verify** surfaces the saved verification result; live model re-verification is available through the backend Guided Mode runner
- **Flag for Review** persists the selected claim ID and optional note
- **Next** is the only action that advances `current_step_id`
- edits, notes, flags, and progress persist in browser `localStorage`
- **Reset review** clears the local demo state

For a persisted JSON workflow, use `backend/run_guided_review.py`. The `verify` action can call Foundry, OpenAI, or OpenRouter.
=======
The page renders:

- the policy title and mode
- analysis steps
- the selected step's AI output
- structured claims
- verification/confidence badges
- claim-linked evidence snippets and source locations
- the final human-review status

Click an analysis step on the left, then click a claim in the center to inspect its evidence on the right.

The claim is a narrow demo claim about text present in the source; it is
marked for human review. The Clarify/Edit/Verify/Next buttons are disabled
placeholders for later Guided Mode work.
>>>>>>> fb898af (Adding Fast API initializer)

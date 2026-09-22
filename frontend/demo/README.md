# PolicyTrace Guided Mode demo

This dependency-free demo now exercises the Chunk 7 human review loop over the fictional `shared/sample-analysis.json`.

Run from the repository root:

```bash
python -m http.server 8000
```

Then open:

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

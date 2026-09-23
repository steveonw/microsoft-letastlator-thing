# PolicyTrace FastAPI demo frontend

This dependency-free UI renders an `AnalysisRun` from the Python FastAPI backend while preserving the existing Guided Mode review interactions in the browser.

The current FastAPI endpoint is intentionally small:

```text
GET /api/analysis
```

It builds a traceable analysis from the checked-in Federal Register fixture. This is the production-frontend foundation, not yet the complete PolicyTrace API.

## Run it locally

From the repository root:

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn api:app --app-dir backend --reload
```

Open:

```text
http://127.0.0.1:8000/demo/
```

Useful endpoints:

```text
http://127.0.0.1:8000/api/analysis
http://127.0.0.1:8000/docs
```

## What works today

The page renders:

- the policy title and mode
- analysis steps
- the selected step's AI output
- structured claims
- verification/confidence badges
- claim-linked evidence snippets and source locations
- the final human-review status

Guided browser behavior is also preserved:

- future steps are locked until the human advances
- **Clarify** stores a reviewer note
- **Edit** preserves `original_text`, marks the claim `human_interpretation`, and requires re-verification
- **Verify** shows the currently saved verification result
- **Flag for Review** stores the selected claim ID and optional note
- **Next** is the only browser action that advances `current_step_id`
- edits, notes, flags, and progress persist in browser `localStorage`
- **Reset review** clears local review state and reloads fresh API data

These browser-only Guided actions are a temporary bridge. The target architecture is server-authoritative state through FastAPI.

## Where this should go next

The reference implementation in PR #36 shows the backend contract to port into this FastAPI app without replacing this UI.

Recommended progression:

1. Keep this FastAPI app as the production API shell.
2. Move authoritative Guided state from browser-only mutation to FastAPI routes.
3. Add real source input:
   - Federal Register document number
   - Regulations.gov docket
   - later paste/upload/URL input
4. Add Rush Mode.
5. Add selective re-analysis and dependency refresh.
6. Add final brief assembly.
7. Use Microsoft Foundry for the contest AI path.

See `docs/FASTAPI_COLLABORATOR_GUIDE.md` for the full integration map.

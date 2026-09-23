# PolicyTrace FastAPI workspace

The demo UI uses the FastAPI app in `backend/api.py`. FastAPI owns the active `AnalysisRun`; browser refreshes fetch it again from `/api/analysis`. The state and provider credentials are held in one server process, so a restart clears them and simultaneous users share them.

## Run

From the repository root:

```bash
python -m pip install -r backend/requirements.txt
python -m uvicorn api:app --app-dir backend --reload
```

Open `http://127.0.0.1:8000/demo/`. The initial workspace shows a checked-in Federal Register evidence fixture. Configure Microsoft Foundry in **Provider settings** (or use the matching environment variables) to analyze a new source. OpenAI and OpenRouter remain available as test providers. Secrets are sent only to the local API and are never placed in the returned analysis or browser storage.

## Source switcher

The single source control switches between:

- **Document ID** — Federal Register document number, such as `2024-20529`.
- **URL** — Federal Register links use official ingestion; other public HTTP or HTTPS URLs are imported as unverified source material.
- **Paste text** — optional title and policy text, marked unverified.
- **Upload file** — PDF, TXT, Markdown, HTML, or normalized PolicyTrace JSON, up to 5 MB. Uploaded content is marked unverified.

Public comments remain a related material action because they augment the currently loaded Federal Register policy. A Regulations.gov API key is required. Comment counts must be between 1 and 100.

## Workflow

The browser calls FastAPI for Guided review, Rush analysis, selective reanalysis, refresh, final brief assembly, and approval. The server returns the complete updated `AnalysisRun` after each action. Only **Next step** advances Guided review. Rush stops at final human review and requires explicit approval. The three-pane view shows analysis steps, claims, verification status, and the exact linked evidence.

The API route shapes and lifecycle rules are documented in `docs/fastapi-packet/`.

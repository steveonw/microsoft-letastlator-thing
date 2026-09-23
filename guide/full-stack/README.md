# PolicyTrace Full-Stack Reference

This folder is a **reference implementation**, not the production frontend.

It exists on the playground stack so the frontend/backend collaborator can inspect a working end-to-end pattern without inheriting the experimental UI itself.

## What it demonstrates

The browser is intentionally thin:

- selected step/claim IDs are browser UI state
- the Python process owns the authoritative `AnalysisRun`
- every mutation is an HTTP request
- every successful mutation returns the complete updated `AnalysisRun`
- the browser replaces its local copy and renders again

Implemented guide routes:

```text
GET  /api/analysis
GET  /api/provider

POST /api/provider
POST /api/provider/clear

POST /api/source/load
POST /api/source/comments

POST /api/reset

POST /api/guided/begin
POST /api/guided/clarify
POST /api/guided/edit
POST /api/guided/flag
POST /api/guided/verify
POST /api/guided/next

POST /api/rush/run
POST /api/rush/open
POST /api/rush/final
POST /api/rush/approve

POST /api/reanalysis/step
POST /api/reanalysis/refresh
POST /api/reanalysis/review

POST /api/brief
```

The human FastAPI implementation can keep these action boundaries while replacing this standard-library HTTP server.

## Local API keys

The reference UI accepts runtime credentials for:

- OpenRouter
- OpenAI
- Microsoft Foundry
- Regulations.gov

Secrets are:

- entered in password fields
- sent only to the local `127.0.0.1` server
- kept in Python process memory
- never written to repository files
- never included in `GET /api/provider`
- never included in `AnalysisRun`
- discarded when the process stops or when **Clear credentials** is clicked

The Regulations.gov key is used by the local live-comment route only. It is passed directly to the existing Regulations.gov client from process memory and is not serialized into the AnalysisRun.

## Run

From the repository root:

```bash
PYTHONPATH=backend python backend/run_full_stack_guide.py
```

Then open:

```text
http://127.0.0.1:8777/
```

No provider credentials are required. The default deterministic verifier is enough to exercise all flows.

## Real-source flow to try

The page starts with fictional guide data so no credentials are required for a quick demo.

For a real source:

1. Choose OpenRouter, OpenAI, or Microsoft Foundry and enter the provider settings.
2. If you want public comments, also enter a Regulations.gov API key.
3. Under **Policy source**, enter a Federal Register document number such as `2024-20529`.
4. Click **Load + Analyze Policy**.
5. Optionally enter a Regulations.gov docket such as `BIS-2024-0047`, choose a comment limit, and click **Load + Analyze Comments**.
6. Continue with Guided or Rush. Those modes now use the loaded real-source AnalysisRun instead of rebuilding the fictional fixture.

The live path uses the existing repository functions:

```text
Federal Register document number
   ↓
fetch_and_normalize
   ↓
run_policy_interpreter
   ↓
authoritative AnalysisRun
   ↓
optional fetch_comments_for_docket
   ↓
run_response_viewpoint_analyst
   ↓
Guided / Rush / verification / Chunk 9 / final brief
```

The deterministic demo provider cannot perform live interpretation because its canned verifier only understands claim-verification prompts. A real configured model provider is therefore required for **Load + Analyze Policy**.

## Guided flow to try

1. Reset Guided.
2. Begin Guided.
3. Select the current claim.
4. Clarify, edit, flag, or verify.
5. Click Next.
6. Repeat.

Only **Next** advances Guided Mode.

## Rush flow to try

1. Click **Run Rush**.
2. Open any saved step.
3. Edit/flag/verify using the same review controls.
4. Return to Rush Final Review.
5. Explicitly approve.

Rush never auto-approves.

## Chunk 9 flow to try

1. Re-analyze a step.
2. Observe transitive dependent steps become `needs_refresh`.
3. Try to build the brief: it is blocked while stale work exists.
4. Refresh stale steps in dependency order.
5. Verify + mark each regenerated section reviewed.
6. Build Final Brief.

The brief copies reviewed claim text and trace IDs rather than inventing new policy claims.

## What to copy into the real app

Copy the **architecture**, not necessarily this HTML:

```text
button click
   ↓
POST action
   ↓
Python workflow function
   ↓
validated AnalysisRun
   ↓
JSON response
   ↓
state.analysis = response
   ↓
render
```

The production FastAPI layer should eventually replace the in-memory state with proper persistence and authentication.

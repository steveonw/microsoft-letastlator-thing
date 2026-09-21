# PolicyTrace dummy frontend

This is intentionally a dependency-free UI for visualizing the fictional `shared/sample-analysis.json` created in Chunk 1.

It is **not** the final frontend stack. Its job is to prove that the shared data contract can drive a useful PolicyTrace-style interface before we add real APIs, AI, or Azure services.

## Run it locally

From the repository root:

```bash
python -m http.server 8000
```

Then open:

```text
http://localhost:8000/frontend/demo/
```

The demo reads:

```text
shared/sample-analysis.json
```

and renders:

- the policy title and mode
- analysis steps
- the selected step's AI output
- structured claims
- verification/confidence badges
- claim-linked evidence snippets and source locations
- the final human-review status

Click an analysis step on the left, then click a claim in the center to inspect its evidence on the right.

The Clarify/Edit/Verify/Next buttons are deliberately disabled placeholders. Their behavior belongs to later Guided Mode chunks.

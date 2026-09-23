# PolicyTrace FastAPI Collaborator Packet

This packet is for the teammate building the production HTTP/UI integration in:

- `backend/api.py`
- `frontend/demo/`

It complements `docs/FASTAPI_COLLABORATOR_GUIDE.md`.

The packet is intentionally implementation-focused: what exists, what lives on which branch, what to build first, the target API contract, state rules, and the smoke tests that define "working."

## Start here

Read these in order:

1. [BRANCH_DEPENDENCY_MAP.md](BRANCH_DEPENDENCY_MAP.md)
2. [FIRST_3_COMMITS.md](FIRST_3_COMMITS.md)
3. [API_CONTRACT.md](API_CONTRACT.md)
4. [STATE_RULES.md](STATE_RULES.md)
5. [FRONTEND_REQUEST_PATTERN.md](FRONTEND_REQUEST_PATTERN.md)
6. [INTEGRATION_SMOKE_TEST.md](INTEGRATION_SMOKE_TEST.md)

## The production goal

Keep the existing FastAPI app and three-pane UI, but move workflow authority to Python:

```text
INPUT
  ↓
FASTAPI
  ↓
trusted ingestion
  ↓
Microsoft Foundry
  ↓
authoritative AnalysisRun
  ↓
evidence + verification
  ↓
Guided / Rush human review
  ↓
selective correction
  ↓
traceable final brief
```

## The first milestone

Do not try to port every reference endpoint at once.

The first real product milestone is:

> From the production browser UI, enter Federal Register document `2024-20529`, have FastAPI fetch and analyze it, and render the returned real Policy Interpreter `AnalysisRun` in the existing three-pane interface.

Once that works, move Guided state server-side.

## Reference vs production

- **Production shell:** `main` + the teammate's FastAPI/frontend work
- **Conflict cleanup + this packet:** PR #37
- **Chunk 9 engine:** PR #35
- **Full-stack behavior reference:** PR #36
- **Verifier malformed-response resilience:** PR #34

PR #36 is a reference implementation, not the production frontend. Reuse backend engines and behavior; do not duplicate its custom HTTP server in FastAPI.

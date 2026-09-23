# Branch and PR Dependency Map

This is the most important context before importing code.

## Current layout

```text
main
└─ human FastAPI/frontend foundation
   └─ PR #37
      fix/fastapi-demo-conflicts-and-guide
      - resolves frontend conflict markers
      - keeps backend/api.py unchanged
      - adds collaborator documentation/tests

fix/verifier-response-resilience
└─ PR #34
   - malformed/chatty verifier response recovery
   - batch continues after bad verifier output

playground/main-two
└─ feature/chunk-9-selective-reanalysis
   └─ PR #35
      - selective re-analysis
      - transitive dependency invalidation
      - final brief assembler
      - NOT merged to main

feature/chunk-9-selective-reanalysis
└─ guide/full-stack-reference
   └─ PR #36
      - full-stack behavior reference
      - real source input
      - Guided / Rush
      - Chunk 9 routes
      - provider configuration
      - NOT merged to main
```

## Important consequence

Do not assume a function used by PR #36 is available on `main`.

Before adding an import to `backend/api.py`:

1. Find which branch currently contains the function.
2. Confirm whether it already exists on the branch you are coding against.
3. If it comes from PR #35 or PR #36, coordinate how that dependency will enter the production branch instead of copying a second implementation.

## Source of truth by concern

| Concern | Best reference |
|---|---|
| Production FastAPI shell | `main:backend/api.py` |
| Production demo UI | `main:frontend/demo/` |
| Conflict-cleaned demo UI | PR #37 |
| Guided engine | existing backend Guided modules on the relevant branch |
| Rush engine | existing backend Rush modules on the relevant branch |
| Selective re-analysis | PR #35 |
| Final brief | PR #35 |
| Full API behavior | PR #36 |
| Real Federal Register input wiring | PR #36 |
| Real Regulations.gov input wiring | PR #36 |
| Provider process-memory handling | PR #36 |
| Verifier malformed-output resilience | PR #34 |

## Do not do this

Do not copy large blocks of business logic into JavaScript.

Do not create another incompatible `AnalysisRun` schema.

Do not duplicate Chunk 9 logic inside `api.py`.

Do not merge or close PRs/issues as part of frontend integration without explicit team authorization.

## Integration strategy

Treat the production FastAPI app as the transport layer:

```text
FastAPI route
    ↓
existing PolicyTrace backend function
    ↓
validated AnalysisRun
    ↓
JSON response
```

The production frontend should consume that shared contract and render it.

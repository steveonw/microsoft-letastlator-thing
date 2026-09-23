# FastAPI Integration Smoke Test

Use this as a manual checklist while the production FastAPI app is being wired.

Do not wait until the end to test the whole workflow.

## A. Base server

- [ ] `python -m uvicorn api:app --app-dir backend --reload` starts
- [ ] `http://127.0.0.1:8000/` redirects to `/demo/`
- [ ] `/demo/` loads without JavaScript syntax errors
- [ ] `/api/analysis` returns valid `AnalysisRun`
- [ ] `/docs` loads FastAPI's API documentation
- [ ] no merge-conflict markers remain in frontend files

## B. Existing UI

- [ ] policy title renders
- [ ] analysis step list renders
- [ ] selecting a claim updates the Evidence pane
- [ ] evidence source link works when a URL exists
- [ ] verification status/confidence render
- [ ] source information type renders

## C. Real Federal Register input

Use:

```text
2024-20529
```

- [ ] document number can be entered in browser
- [ ] Load + Analyze calls FastAPI
- [ ] FastAPI fetches/normalizes the source
- [ ] Policy Interpreter runs
- [ ] returned `AnalysisRun` becomes server state
- [ ] policy explanation renders
- [ ] major provisions render
- [ ] stakeholder analysis renders
- [ ] affected programs render
- [ ] exact evidence renders
- [ ] loading a different policy clears old response analysis

## D. Guided Mode

- [ ] Begin is server-side
- [ ] only Next advances
- [ ] Clarify does not advance
- [ ] Edit does not advance
- [ ] Flag does not advance
- [ ] Verify does not advance
- [ ] human edit preserves original text
- [ ] human edit changes information type to `human_interpretation`
- [ ] human edit requires re-verification
- [ ] invalid Next returns a useful error
- [ ] browser refresh retrieves server state instead of inventing a new state

## E. Public comments

Use:

```text
BIS-2024-0047
max_comments: 12
```

- [ ] policy must be loaded first
- [ ] missing Regulations.gov key gives a useful error
- [ ] comments load
- [ ] attachment text is included where available
- [ ] unusable placeholder-only sources are not treated as substantive comments
- [ ] representativeness note is visible
- [ ] no single sentiment score is presented
- [ ] reasons for support/concern/questions/conflicting views render
- [ ] PII status is not overstated

## F. Rush Mode

- [ ] Run Rush uses currently loaded real source
- [ ] duplicate clicks do not send duplicate runs
- [ ] provider failure does not destroy completed work
- [ ] Rush stops at human final review
- [ ] Rush does not auto-approve
- [ ] opening a step for review works
- [ ] returning to final review works
- [ ] approval requires explicit click

## G. Selective re-analysis

- [ ] selected step can be re-analyzed
- [ ] upstream/unrelated steps stay unchanged
- [ ] only transitive dependents become `needs_refresh`
- [ ] previous final approval is revoked
- [ ] refresh order is enforced
- [ ] refreshed work requires review
- [ ] stale work cannot be silently included in final brief

## H. Final brief

- [ ] brief builds only after required review/refresh conditions are satisfied
- [ ] brief content is traceable to reviewed claims/evidence
- [ ] assembler does not add new substantive claims
- [ ] final approval remains a human action

## I. Microsoft Foundry

This is contest-critical.

- [ ] Foundry endpoint configured
- [ ] Foundry model/deployment configured
- [ ] exactly one supported credential path configured
- [ ] credentials are not returned by API
- [ ] Policy Interpreter successfully runs through Foundry
- [ ] Response/Viewpoint Analyst successfully runs through Foundry
- [ ] Claim Verifier successfully runs through Foundry
- [ ] one full BIS demo run succeeds using Foundry

## J. Error / resilience

- [ ] external timeout produces readable UI message
- [ ] one verifier provider failure falls back to human review
- [ ] one bad verifier reply does not abort remaining claims
- [ ] buttons are disabled while a long request is active
- [ ] 400 errors explain invalid workflow state
- [ ] 502 errors identify external/provider failure without exposing secrets

## K. Security

- [ ] no API key in Git
- [ ] no API key in `AnalysisRun`
- [ ] no API key in `localStorage`
- [ ] no API key echoed by provider status
- [ ] no API key included in screenshots/demo video
- [ ] any key pasted into a chat/shared log is rotated

## Demo-ready definition

A fresh user can:

```text
enter 2024-20529
    ↓
load/analyze policy
    ↓
load BIS-2024-0047 comments
    ↓
inspect viewpoints + evidence
    ↓
verify/edit/flag
    ↓
advance Guided or run Rush
    ↓
correct one section
    ↓
refresh dependencies
    ↓
build brief
    ↓
human approve
```

without touching the terminal except to start the server.

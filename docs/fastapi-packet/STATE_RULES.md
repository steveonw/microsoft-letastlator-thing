# State Lifecycle Rules

These rules keep FastAPI, Guided, Rush, re-analysis, and the final brief consistent.

## 1. Loading a new policy

When a new policy is successfully loaded:

```text
set document
set policy_analysis
clear response_analysis
replace current analysis
clear stale final approval
clear stale brief state
```

Do not keep comments from a previous policy attached to a new one.

## 2. Loading comments

Requirements:
- policy document already loaded
- policy analysis already loaded
- Regulations.gov key available
- comment count valid

On success:

```text
policy_analysis
      +
response_analysis
      ↓
combined Guided AnalysisRun
```

Do not treat the supplied comments as representative of the general public.

## 3. Human edit

Editing a claim must:

- preserve `original_text` if not already set
- replace `text`
- set `information_type = human_interpretation`
- set `verification_status = needs_human_review`
- add a verification note explaining that re-verification is required
- mark the containing review as in progress

Editing the text must not silently preserve a previous "supported" status.

## 4. Guided progression

Only explicit human `Next` advances.

These must not advance:
- Clarify
- Edit
- Flag
- Verify
- selecting another visible step

Future steps should remain unavailable until permitted by the Guided state machine.

## 5. Verification failures

Distinguish:

```text
citation-integrity failure
≠
semantic unsupported
```

If evidence cannot be mechanically validated, do not infer that the claim is false.

If a model/provider call fails, do not infer a verification status.

Safe fallback:

```text
needs_human_review
```

## 6. Rush

Rush uses the same analysis engine.

Rush may automate progression, but must stop at:

```text
final_review_status = in_review
```

It never auto-approves.

Final approval requires explicit human action.

## 7. Selective re-analysis

Re-analyzing one step must:

- preserve upstream work
- preserve unrelated sibling work
- replace the selected step
- increment that step's version
- reopen it for human review
- mark transitive downstream dependents `needs_refresh`
- revoke any previous final approval

Do not refresh the whole analysis by default.

## 8. Refresh order

A stale step cannot be refreshed before stale dependencies it depends on.

The backend should enforce dependency order.

The frontend may disable impossible buttons, but backend validation remains authoritative.

## 9. Final brief

The Brief Assembler:

- uses reviewed/accepted material only
- preserves claim IDs/evidence IDs where designed
- must not introduce new substantive factual/analytical claims
- refuses to build while required work remains `needs_refresh`

## 10. Credentials

Provider/API credentials are configuration, not analysis state.

Never place secrets in:
- `AnalysisRun`
- source records
- review notes
- localStorage
- frontend-rendered provider status
- logs intended for sharing

For the hackathon demo, process-memory credentials are acceptable.

## 11. Server restart

Current MVP target is in-memory state.

Therefore:

```text
server restart
    ↓
session state lost
```

Document this limitation.

Do not pretend it is durable multi-user persistence.

## 12. Multiple browser users

One global in-memory state means different users can affect the same state.

For a controlled hackathon demo, this can be acceptable.

For production, state must eventually be scoped per user/session/project and persisted appropriately.

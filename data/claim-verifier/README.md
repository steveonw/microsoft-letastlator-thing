# Chunk 6 claim-verifier fixtures

The response fixture in this directory is used only for deterministic offline CI.

It maps claim IDs produced by the checked-in Chunk 4 offline Policy Interpreter fixture
to structured Claim Verifier responses. It is not presented as an independent model
evaluation or as a current legal conclusion.

Run the full offline path:

```bash
python backend/run_policy_interpreter.py \
  --offline \
  --output /tmp/policytrace-offline-interpreter.json

python backend/run_claim_verifier.py \
  --offline \
  --input /tmp/policytrace-offline-interpreter.json \
  --output /tmp/policytrace-offline-verified.json
```

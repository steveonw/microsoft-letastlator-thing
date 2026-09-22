# Chunk 3 evidence layer

Chunk 3 turns normalized source text into reusable PolicyTrace `Evidence` objects.

The first implementation deliberately uses **deterministic literal retrieval** instead of adding another AI call or requiring Azure infrastructure immediately.

## Flow

```text
Normalized Federal Register document
        |
        v
literal evidence lookup
        |
        v
exact source snippet
+ source ID
+ locator
+ character offsets
+ retrieval timestamp
        |
        v
PolicyTrace Evidence object
        |
        v
Claim.evidence_ids[]
```

The important invariant is:

```text
source.raw_text[evidence.start_offset:evidence.end_offset]
    == evidence.snippet
```

That means a citation can be inspected and mechanically checked before an AI verifier is ever asked whether the passage semantically supports a claim.

## Demo

From the repository root:

```bash
python backend/build_evidence_demo.py
```

The demo:

1. fetches Federal Register document `2024-20529`
2. normalizes it using the Chunk 2 pipeline
3. finds a real passage containing `artificial intelligence`
4. creates a shared `Source`
5. creates an exact `Evidence` record
6. creates a narrow demo `Claim` whose `evidence_ids` points to that evidence
7. validates the resulting `AnalysisRun`

Default output:

```text
data/evidence/2024-20529.chunk3-demo.json
```

The demo claim is intentionally not a substantive policy interpretation. Chunk 3 proves the citation plumbing; the Policy Interpreter begins making policy findings in Chunk 4.

## Azure AI Search

The evidence object and offset rules are designed so Azure AI Search can later replace the simple literal retrieval step without changing the rest of the contract.

For the hackathon MVP, getting exact traceable evidence working first is more important than making Azure AI Search a blocker for Chunk 3.

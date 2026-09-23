# Chunk 5 — Response & Viewpoint Analyst

Chunk 5 analyzes the reasons and viewpoints present in supplied response material without treating those materials as representative of the general public.

The MVP starts with Regulations.gov public comments. The live ingester now requests comment attachments as well, so attachment-only submissions such as "See attached file(s)" can contribute their actual text when Regulations.gov exposes a supported TXT, HTML, PDF, or DOCX file. The contract also supports selected stakeholder statements and factual reporting while keeping those source categories visibly separate.

## What the analyst surfaces

- reasons for support
- concerns / objections
- questions / misunderstandings
- mixed / neutral reactions
- minority / conflicting viewpoints
- emerging issues only when dates/order actually support a time-based finding
- a mandatory representativeness note

The model is not asked for a single sentiment score.

## Source boundaries

Each finding must declare one response source type:

- `public_opinion`
- `stakeholder_claim`
- `factual_reporting`

A finding cannot blend those categories. Every finding must cite exact quotes and source IDs. Normal Python code rejects fabricated quotes, missing sources, and source-type mismatches before an `AnalysisRun` is accepted.

Response claims remain:

- `information_type = ai_interpretation`
- `verification_status = needs_human_review`
- `step.status = draft`

Semantic support verification is still Chunk 6.

## Duplicate and representativeness handling

Every response source with retrieved substantive content gets an exact-text duplicate cluster ID. Placeholder-only records such as `See attached file(s)` are excluded from duplicate clustering and from the model prompt until their substantive content is successfully retrieved. The representativeness note reports supplied records, records actually analyzed, unique exact-text clusters, and how many records were excluded because content was not retrieved.

This is intentionally conservative: exact duplicate clustering catches obvious repeated text, but it does not claim to identify all coordinated or templated campaigns.

The system explicitly states that the analyzed material is not a representative sample of the general public.

## PII / input safety

External response text is treated as untrusted data. Before it is passed to the analyst, obvious email addresses and phone numbers appearing inside comment text or extracted attachment text are redacted. Regulations.gov identity fields such as first and last name are not imported into the PolicyTrace response record.

Attachment downloads are limited to the official `downloads.regulations.gov` HTTPS host, capped at 15 MB per downloaded representation, and extracted text is capped at 50,000 characters per attachment. When Regulations.gov offers multiple representations, PolicyTrace prefers TXT/HTML before PDF/DOCX. The download request uses browser-style headers because the Regulations.gov download CDN can reject custom/non-browser user-agent strings. Unsupported, inaccessible, scanned/image-only, or otherwise unextractable attachments are skipped with a visible runtime warning rather than silently treated as retrieved evidence.

## Offline demo

The checked-in response fixtures are **synthetic**. They exist only to exercise the workflow without presenting invented statements as real public comments.

Run:

```bash
python backend/run_response_analysis.py --offline
```

The output is written to:

```text
data/response-analysis/2024-20529.chunk5-analysis.json
```

## Live Regulations.gov + model run

Regulations.gov requires an API key in the `X-Api-Key` header for live API access.

Set:

```bash
export REGULATIONS_GOV_API_KEY="your-key"
```

Then use either the temporary OpenAI test provider:

```bash
export OPENAI_API_KEY="your-key"
export POLICYTRACE_OPENAI_MODEL="your-model"
python backend/run_response_analysis.py --provider openai
```

or Microsoft Foundry when the hackathon resource is available:

```bash
export POLICYTRACE_FOUNDRY_ENDPOINT="..."
export POLICYTRACE_FOUNDRY_MODEL="..."
export POLICYTRACE_FOUNDRY_API_KEY="..."
python backend/run_response_analysis.py --provider foundry
```

The live default docket is `BIS-2024-0047`, linked to the historical 2024 BIS proposed-rule demo source.

## Scope

Chunk 5 does not claim that sampled comments represent population-wide opinion, does not infer a political recommendation, and does not decide what the policy itself says. Policy meaning stays in the Chunk 4 Policy Interpreter.


## OpenRouter free-model test path

While Microsoft Foundry access is pending, Chunk 5 can also use OpenRouter's free-model router.

Set:

```bash
export OPENROUTER_API_KEY="your-key"
export REGULATIONS_GOV_API_KEY="your-regulations-gov-key"
```

Then run:

```bash
python backend/run_response_analysis.py --provider openrouter
```

The default OpenRouter model is `openrouter/free`. To pin a specific free model, set:

```bash
export POLICYTRACE_OPENROUTER_MODEL="provider/model:free"
```

OpenRouter is only a local/live integration-testing path. Microsoft Foundry remains the hackathon target.

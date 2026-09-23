# PolicyTrace

**Planning-stage concept**

PolicyTrace is an AI-assisted policy analysis workspace designed to help people understand what a policy says, who it may affect, how people are responding, and what evidence supports each conclusion.

The core idea is not to let AI produce an unexplained answer. PolicyTrace should keep the evidence visible, distinguish different kinds of information, and keep a human analyst responsible for the final interpretation.

## Two analysis workflows

PolicyTrace is planned around two complementary ways to work.

### 1. Rush Analysis

Rush Analysis is for users who want a fast first draft.

```text
Policy / Regulation / Proposal
            |
            v
     AI Policy Analysis
            |
            v
 Public Response Analysis
            |
            v
 Evidence + Citation Check
            |
            v
      Draft Policy Brief
            |
            v
        Human Review
```

The AI performs the initial workflow automatically and returns a structured draft.

A Rush Analysis may include:

- Plain-language policy summary
- Major provisions
- Potentially affected stakeholder groups
- Related public comments or feedback
- Recurring concerns and questions
- News/reporting themes when available
- Minority or conflicting viewpoints
- Citations for important claims
- Verification status for cited claims
- Areas of uncertainty
- Draft analyst briefing

Rush mode is intended to save time, not replace human review.

---

### 2. Guided Analysis

Guided Analysis is the more careful workflow.

Instead of completing the whole analysis at once, the AI and human move through the policy step by step.

```text
                 POLICY
                    |
                    v
              AI analyzes step
                    |
                    v
              Evidence checker
                    |
                    v
               Human review
              /      |       \
        Clarify     Edit      Next
            |         |         |
            +----> AI revises   |
                      |          |
                      +----------+
                            |
                     Next analysis step
```

The human controls when the analysis advances.

At each step, the user should be able to:

- **Clarify** — explain what they meant or correct the AI's interpretation
- **Edit** — directly change a finding or description
- **Verify** — ask a separate verification pass to compare a claim against its source
- **Show Sources** — inspect the supporting policy text, comment, article, or record
- **Next** — accept the current step and continue

Possible Guided Analysis steps:

1. Identify and understand the policy
2. Review the policy's stated purpose
3. Identify major provisions
4. Identify potentially affected stakeholders
5. Review public response
6. Review conflicting and minority viewpoints
7. Verify important claims and citations
8. Build the final briefing

The important design principle is:

> **The human decides when to move to the next step.**

The AI should present its current interpretation and allow correction before continuing.

## Claim and citation verification

Chunk 6 adds a separate Claim Verifier pass. Before semantic verification, PolicyTrace re-checks deterministic citation integrity (claim → evidence → source, exact snippet/offset consistency). Only claims that pass that gate are sent to the verifier model.

The verifier receives the claim text plus cited evidence and source metadata, but not the original analyst reasoning. It returns one of the shared verification statuses plus a short explanation and, when useful, an optional narrower wording suggestion. The original claim is never silently rewritten, and human review remains required.

Important AI-generated claims should not stand alone.

A claim should carry its supporting evidence and a verification result.

Example:

```text
Claim:
Covered institutions must retain specified records for seven years.

Source:
Section 8(b), page 14

Source type:
OFFICIAL_POLICY

Verification:
SUPPORTED

Confidence:
High
```

A separate verification pass should ask:

> Does the cited source actually support the claim being made?

Possible verification results:

- **Supported**
- **Partially supported**
- **Needs clarification**
- **Unsupported**
- **Needs human review**

If a source supports only part of a claim, the system should narrow or rewrite the claim rather than quietly treating it as verified.

## Keep information types separate

PolicyTrace should clearly distinguish the origin and status of information.

Potential categories include:

- **OFFICIAL_POLICY** — direct legislative or regulatory language
- **OFFICIAL_CONTEXT** — agency or government explanatory material
- **FACTUAL_REPORTING** — factual claims from news/reporting sources
- **PUBLIC_OPINION** — comments, correspondence, surveys, or other expressed views
- **STAKEHOLDER_CLAIM** — claims from businesses, associations, advocacy groups, or other organizations
- **AI_INTERPRETATION** — conclusions generated by the system
- **HUMAN_INTERPRETATION** — analyst-added conclusions
- **UNVERIFIED** — information found but not adequately supported

This separation helps prevent public opinion, reporting, and AI interpretation from being mistaken for official policy language.

## Public sentiment: explain the reasons, not just a score

PolicyTrace should not reduce public response to a single positive/negative number.

Instead of:

```text
60% positive
40% negative
```

the system should surface the reasons behind reactions.

Example:

```text
Recurring concern: Implementation cost

What the analyzed feedback says:
Several businesses mention software, staffing, and reporting costs.

Evidence:
- 12 public comments
- 4 news reports
- 2 stakeholder statements

Minority viewpoint:
Some commenters argue that long-term savings may outweigh initial costs.

Representativeness:
This feedback should not automatically be treated as representative of the entire population.
```

## Planned UI concept

The main workspace can be organized into three areas:

```text
+----------------+------------------------------+----------------+
| Analysis Steps | Main Analysis                | Evidence       |
|                |                              |                |
| 1. Policy      | Current AI interpretation    | Source text    |
| 2. Purpose     |                              | Citations      |
| 3. Provisions  | Clarify / Edit / Verify      | Verification   |
| 4. Stakeholder | Show Sources / Next          | status         |
| 5. Reaction    |                              |                |
| 6. Evidence    | Human notes and corrections  |                |
| 7. Brief       |                              |                |
+----------------+------------------------------+----------------+
```

The intended mental model is:

- **Left:** where the analyst is in the process
- **Center:** what the human and AI are currently working on
- **Right:** why the system believes the current claim

## Human oversight

PolicyTrace is intended to assist human analysis, not make final policy judgments on its own.

The human analyst should be able to:

- Inspect original sources
- Correct AI interpretations
- Add missing context
- Preserve disagreement and minority viewpoints
- Reject weak evidence
- Mark findings as reviewed
- Approve the final briefing

The final output should make clear which findings were AI-generated, which were human-edited, and what evidence supports them.

## Initial MVP direction

The first version does not need every data source or every possible analysis feature.

A focused MVP could demonstrate:

```text
Input a policy
      |
      v
Explain the policy
      |
      v
Identify key provisions and stakeholders
      |
      v
Analyze a small set of public comments/news
      |
      v
Group recurring concerns and viewpoints
      |
      v
Attach and verify citations
      |
      v
Human review
      |
      v
Evidence-grounded policy brief
```

Later versions can add additional government APIs, revision comparison, larger-scale public feedback analysis, saved projects, richer search, and more advanced briefing tools.

## Guiding principle

**No important AI claim without evidence, and no evidence without checking that it actually supports the claim.**

PolicyTrace should help analysts move faster while keeping sources visible, uncertainty explicit, and humans in control.


## Current backend milestone

Chunks 1–8 now have backend implementations:

1. Shared analysis contract
2. Federal Register ingestion
3. Exact evidence grounding
4. Policy Interpreter
5. Response & Viewpoint Analyst
6. Claim Verifier
7. Guided Mode human review loop
8. Rush Mode + mandatory final review

The Claim Verifier can be run against an existing AnalysisRun:

```bash
python backend/run_claim_verifier.py --offline \
  --input /tmp/policytrace-offline-interpreter.json
```

For live model verification, use `--provider foundry`, `openai`, or `openrouter`. Microsoft Foundry remains the intended hackathon demo provider.


## Guided Mode actions

Chunk 7 adds explicit human-controlled review actions over an existing AnalysisRun. The workflow never advances automatically; only the `next` action changes the current step.

```bash
python backend/run_guided_review.py begin --input analysis.json
python backend/run_guided_review.py clarify --input analysis.json --text "Keep proposed-rule wording."
python backend/run_guided_review.py edit --input analysis.json --claim-id claim-1 --text "Revised claim text"
python backend/run_guided_review.py flag --input analysis.json --claim-id claim-1 --text "Needs another look"
python backend/run_guided_review.py verify --provider openrouter --input analysis.json --claim-id claim-1
python backend/run_guided_review.py next --input analysis.json
```

The demo frontend mirrors these review controls and persists edits/notes/progress locally for the browser demo.


## Rush Mode

Chunk 8 can run the shared policy-analysis, response-analysis, and claim-verification pipeline automatically while preserving every intermediate step. Automation stops with `final_review_status=in_review`; it never approves the result on its own.

Offline demo:

```bash
python backend/run_rush_analysis.py run --offline
```

Live OpenRouter example:

```bash
python backend/run_rush_analysis.py run --provider openrouter
```

A reviewer can open any saved section without losing the Rush draft:

```bash
python backend/run_rush_analysis.py open \
  --input data/rush/2024-20529.chunk8-analysis.json \
  --step-id step-major-provisions
```

Once a section is open, the existing Guided Mode edit, flag, clarify, and verify actions can be used against that same JSON. Return to the mandatory final-review gate with:

```bash
python backend/run_rush_analysis.py final \
  --input data/rush/2024-20529.chunk8-analysis.json
```

Final approval is a separate explicit human action:

```bash
python backend/run_rush_analysis.py approve \
  --input data/rush/2024-20529.chunk8-analysis.json
```

Selective section re-analysis and dependency refresh are handled in Chunk 9.

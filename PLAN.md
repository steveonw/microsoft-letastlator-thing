# PolicyTrace Hackathon Build Plan

This document breaks PolicyTrace into small, testable pieces so the team can build one part at a time and see how the pieces connect.

## Big picture

```text
                      +------------------+
                      |   Policy Input   |
                      +---------+--------+
                                |
                                v
                      +------------------+
                      | Normalize Source |
                      | + split sections |
                      +---------+--------+
                                |
                                v
                      +------------------+
                      | Evidence / Source|
                      |      Store       |
                      +---------+--------+
                                |
                                v
              +-----------------------------------+
              |      Shared Analysis Pipeline     |
              |                                   |
              |  1. Understand policy             |
              |  2. Extract major provisions      |
              |  3. Identify stakeholders         |
              |  4. Analyze public response       |
              |  5. Build themes/viewpoints       |
              |  6. Verify claims + citations     |
              |  7. Build draft brief             |
              +----------------+------------------+
                               |
                     +---------+---------+
                     |                   |
                     v                   v
              +-------------+     +-------------+
              | Guided Mode |     |  Rush Mode  |
              | human pauses|     | auto-advance|
              | each step   |     | same steps  |
              +------+------+     +------+------+
                     |                   |
                     +---------+---------+
                               |
                               v
                    +---------------------+
                    | Human Final Review  |
                    | flag / edit / rerun |
                    +----------+----------+
                               |
                               v
                    +---------------------+
                    | Traceable Final Brief|
                    +---------------------+
```

Rush and Guided are not separate analysis engines. They use the same step-based pipeline.

- **Guided Mode** pauses after each step for human review.
- **Rush Mode** moves through the same steps automatically, but always stops for mandatory final human review.
- Any single step can later be re-run without starting the entire analysis over.

## Selective re-analysis

```text
Human finds a problem in Step 3
            |
            v
     Reanalyze Step 3
            |
            v
      Verify Step 3
            |
            v
   Save updated result
            |
            v
Mark dependent later steps
      as NEEDS REFRESH
            |
            v
Refresh only what is affected
```

Example: changing the stakeholder analysis should not force the policy text extraction to run again.

---

## Recommended source stack

For the hackathon, use a small number of sources well instead of trying to integrate everything at once.

### MVP sources

**Federal Register**  
https://www.federalregister.gov/developers/documentation/api/v1

Use for:
- proposed rules
- final rules
- notices
- official agency text
- dates and agency metadata

**Regulations.gov**  
https://open.gsa.gov/api/regulationsgov/

Use for:
- regulatory dockets
- supporting documents
- public comments
- citizen/stakeholder feedback tied to a rule

**GDELT Project**  
https://gdeltproject.org/

Use for:
- news coverage
- media discussion around the policy
- broader public-information context

### Second policy pathway

**Congress.gov API**  
https://api.congress.gov/

Use for:
- bills
- bill metadata
- actions
- amendments
- legislative history

Add this after the regulation workflow is working.

### Supporting / optional sources

**GovInfo**  
https://www.govinfo.gov/

Use as an authoritative backup/source for official government documents and historical material.

**Data.gov**  
https://data.gov/

Use to discover supporting government datasets when a policy analysis needs factual context. Do not make this a required part of the first demo.

---

## Microsoft pieces

**Azure AI Search**  
https://learn.microsoft.com/en-us/azure/search/

Role:
- index normalized policy text, comments, and news evidence
- chunk documents
- retrieve the most relevant evidence for each analysis step
- support traceable claim-to-source retrieval

**Microsoft Foundry**  
https://learn.microsoft.com/en-us/azure/foundry/

Role:
- run the analysis prompts/workflows
- generate structured findings
- run the separate claim-verification pass
- support evaluation/tracing as the project grows

**Microsoft Responsible AI tools and practices**  
https://www.microsoft.com/en-us/ai/tools-practices

Role:
- guide transparency
- keep humans in control
- communicate uncertainty
- preserve conflicting/minority viewpoints
- avoid overstating public sentiment

**Microsoft Fabric — optional for MVP**  
https://learn.microsoft.com/en-us/fabric/

If used, give it one clear job:
- ingest/store/normalize data from the government/news sources before indexing it in Azure AI Search

Do not make Fabric a blocker for the first working demo.

---

## AI roles and non-AI gates

For the MVP, PolicyTrace should use a small number of **role-specific AI workflows**, not a collection of autonomous agents talking to one another. The same underlying model can perform different roles with different prompts and structured outputs while normal application code controls sequencing and state.

### AI Role 1 — Policy Interpreter

Purpose:
- explain the policy in plain language
- extract major provisions
- identify potentially affected stakeholders
- identify affected programs when the source supports that finding

Input scope:
- `OFFICIAL_POLICY`
- `OFFICIAL_CONTEXT`

The Policy Interpreter should not use public comments, stakeholder statements, or news reporting to decide what the policy itself says. Its findings are stored as `AI_INTERPRETATION` claims linked to official evidence.

### AI Role 2 — Response & Viewpoint Analyst

Purpose:
- analyze the reasons and viewpoints present in public comments, stakeholder statements, and reporting
- preserve disagreement instead of compressing everything into one sentiment score

Use one structured analysis pass with multiple lenses rather than separate mandatory "pro" and "con" agents:

```text
Response & Viewpoint Analyst
        |
        +--> reasons for support
        +--> concerns / objections
        +--> questions / misunderstandings
        +--> mixed / neutral responses
        +--> minority / conflicting viewpoints
        +--> emerging issues when time data supports it
```

This avoids forcing a false support-vs-opposition binary and avoids extra model calls by default. An optional later counter-view audit may ask whether a meaningful viewpoint was missed, but it is not required for every MVP run.

Keep source categories separate in the output. A public comment, stakeholder claim, and factual news report should not be blended into a single source type.

The analyst must include a representativeness note when the available material cannot support population-wide conclusions.

### AI Role 3 — Evidence Verifier

Purpose:
- judge whether a real cited passage supports a specific claim
- return one of the shared verification statuses
- explain non-supported or partially supported results
- suggest narrower wording when useful without silently replacing the original claim

The AI verifier runs **after** deterministic evidence-integrity checks. It should receive only the claim, source type, exact evidence passage, and locator needed for the verification task rather than the first AI's full reasoning.

### AI Role 4 — Brief Assembler

Purpose:
- assemble reviewed findings into a coherent analyst briefing
- produce different levels of detail, such as a detailed analyst brief or shorter leadership summary, from the same reviewed evidence

The Brief Assembler must not introduce a new factual or analytical claim that is not already represented in reviewed/accepted findings. New analysis must go back through the normal analysis and verification pipeline first.

### Human Analyst — final authority

The human analyst is not an AI role and remains the final decision-maker.

The human can:
- inspect sources
- accept, edit, reject, or flag claims
- request verification
- re-run a selected step
- add context
- approve the final briefing

Neither Guided nor Rush mode may mark the final analysis approved without the human review state.

### Non-AI components

Some important jobs should remain normal software rather than model calls.

**Source Normalizer**
- fetch and normalize source metadata/text
- split documents into usable sections/chunks
- preserve exact locations and offsets

**PII / Input Safety Gate**
- track whether public-feedback material has been checked/redacted for personal information
- treat external text as untrusted data rather than instructions

**Workflow Controller**
- decide which step runs next
- enforce Guided/Rush behavior
- track dependencies and `NEEDS_REFRESH`
- prevent unreviewed output from being treated as final

**Evidence Integrity Checker**
- confirm cited source IDs and evidence IDs exist
- confirm exact snippets occur in the stored source text
- validate stored character offsets
- reject broken evidence links before an AI verifier is called

Verification therefore has two layers:

```text
Claim + citation
      |
      v
DETERMINISTIC EVIDENCE INTEGRITY CHECK
Does the evidence exist?
Does the source exist?
Does the exact passage match the stored source text/offsets?
      |
   pass / fail
      |
      v
AI EVIDENCE VERIFIER
Does this real passage actually support this claim?
      |
      v
supported / partially supported / needs clarification /
unsupported / needs human review
```

This keeps mechanical checks in code and reserves model calls for questions that require language judgment.

---

## Source flow

```text
        OFFICIAL POLICY / RULE TEXT
          Federal Register
          Congress.gov
          GovInfo
                |
                v
        +-------------------+
        | Normalize / Chunk |
        +---------+---------+
                  |
                  v
        +-------------------+
        | Azure AI Search   |
        | Evidence Index    |
        +---------+---------+
                  |
      +-----------+-----------+
      |                       |
      v                       v
Regulations.gov             GDELT
Public comments             News/reporting
Stakeholder feedback        Media context
      |                       |
      +-----------+-----------+
                  |
                  v
          Microsoft Foundry
       Analyze -> Verify -> Brief
                  |
                  v
          HUMAN FINAL REVIEW
```

## Source types inside PolicyTrace

Keep source types visibly separate:

```text
OFFICIAL_POLICY
  Federal Register
  Congress.gov
  GovInfo

OFFICIAL_CONTEXT
  agency supporting material
  Data.gov datasets when relevant

PUBLIC_OPINION
  Regulations.gov public comments

FACTUAL_REPORTING
  news/reporting discovered through GDELT

STAKEHOLDER_CLAIM
  statements from organizations/groups

AI_INTERPRETATION
  PolicyTrace-generated analysis

HUMAN_INTERPRETATION
  analyst edits or conclusions
```

The system should never present public comments, stakeholder statements, news reporting, or AI interpretation as though they were official policy language.

---

## Work chunks

### Chunk 1 — Project skeleton + shared data shape

**Goal:** Agree on the smallest objects every later piece will use.

Define simple structures for:
- policy/source
- analysis step
- claim
- citation/evidence
- verification status
- human review status

**Done when:** We can load one fake/sample analysis as structured data and display/log it consistently.

**Why first:** Every other piece needs a common shape.

---

### Chunk 2 — Policy input + source normalization

**Goal:** Get one policy into the system reliably.

Start with one regulation workflow:
- load a rule from **Federal Register**
- optionally connect its docket/material from **Regulations.gov**
- preserve title/source/agency/date metadata
- split into usable sections/chunks
- keep section/page/source references where possible

After this works, add **Congress.gov** as a second policy pathway.

**Done when:** A policy becomes structured source material the analysis pipeline can reference.

---

### Chunk 3 — Evidence + citation layer

**Goal:** Make evidence a first-class object, not an afterthought.

For each evidence item keep:
- source
- exact supporting snippet
- section/page/location
- source type
- retrieval metadata

Use **Azure AI Search** to index and retrieve normalized evidence when practical for the demo.

**Done when:** A claim can point to a specific piece of evidence and the user can inspect it.

---

### Chunk 4 — Core policy analysis steps

**Goal:** Build the first useful AI analysis over the policy itself using the **Policy Interpreter** role.

Initial steps:
1. Plain-language explanation
2. Major provisions
3. Potentially affected stakeholders
4. Affected programs when the official source supports that finding

The Policy Interpreter should use official policy/context sources to determine what the policy says. Public comments, stakeholder claims, and reporting must not alter the description of the official policy.

Each result should be structured, labeled as AI interpretation, and linked to official evidence.

Use **Microsoft Foundry** for the analysis workflow if available.

**Done when:** One policy can move through these steps and produce inspectable, evidence-linked results without mixing public reaction into the policy interpretation.

---

### Chunk 5 — Public response + viewpoints

**Goal:** Use the **Response & Viewpoint Analyst** to explain the range of reactions in the supplied material without pretending they represent everyone.

Start with:
- **Regulations.gov** public comments
- selected stakeholder statements when useful
- a small amount of news/reporting when useful; GDELT can be added after the core path is stable

Use one structured model call with multiple explicit lenses rather than mandatory separate "pro" and "con" calls.

Surface:
- reasons for support
- concerns / objections
- questions / misunderstandings
- mixed or neutral responses
- conflicting or minority viewpoints
- emerging issues when dates/time-series data support the claim
- representativeness warning

Keep public opinion, stakeholder claims, and factual reporting visibly separate.

**Done when:** The app can explain *why* people in the analyzed material are reacting, preserve conflicting/minority views, and show which source type supports each finding without reducing the material to one sentiment score.

---

### Chunk 6 — Claim verification

**Goal:** Check whether important claims are actually supported by their cited evidence using both deterministic checks and an AI verifier.

First run the **Evidence Integrity Checker** in normal code:
- cited source exists
- cited evidence exists
- exact snippet exists in the stored source text when raw text is available
- stored character offsets reproduce the exact snippet
- broken references fail before any model call

Then run the **Evidence Verifier** AI over the real claim + evidence passage.

Statuses:
- Supported
- Partially supported
- Needs clarification
- Unsupported
- Needs human review

The AI verifier should not receive the first analyst's full reasoning. It should judge the claim against the supplied evidence, explain non-supported outcomes, and may suggest narrower wording without silently overwriting the original claim.

**Done when:** Broken citations are rejected deterministically and a separate AI verification pass can judge whether valid evidence actually supports the claim.

---

### Chunk 7 — Guided Mode

**Goal:** Put the human inside the analysis loop.

At each step provide:
- Show Sources
- Clarify
- Edit
- Verify
- Flag for Review
- Next

The AI must not advance until the human chooses **Next**.

**Done when:** A user can complete the analysis one step at a time and their edits/clarifications persist.

---

### Chunk 8 — Rush Mode + final human review

**Goal:** Let AI speed-run the exact same pipeline.

Rush Mode:
- runs the shared steps automatically
- saves every intermediate section
- performs verification
- never marks the analysis complete by itself
- ends at **Human Final Review Required**

The final review should let the user open any step, flag it, edit it, or re-run only that section.

**Done when:** Rush can generate a full draft while still forcing at least one human review stage.

---

### Chunk 9 — Selective re-analysis + final brief

**Goal:** Make corrections cheap and keep the report traceable.

If a step changes:
- keep unaffected earlier work
- mark dependent later sections as **Needs Refresh**
- let the human refresh only affected sections

Then use the **Brief Assembler** to build the final briefing from reviewed/accepted findings.

The Brief Assembler may reorganize and summarize reviewed material, but it must not introduce new factual or analytical claims that have not already passed through the normal evidence/verification workflow.

The same reviewed findings can later support different presentation depths, such as:
- detailed analyst brief
- shorter leadership summary

**Done when:** A user can fix one bad section without restarting the whole analysis and can produce a traceable final report whose claims all come from reviewed findings.

---

## Suggested build order

```text
1 Skeleton/data shapes
        |
        v
2 Federal Register / Regulations.gov input
        |
        v
3 Evidence + Azure AI Search
        |
        v
4 Policy Interpreter with Foundry
        |
        +----------------+
        |                |
        v                v
5 Multi-lens        6 Deterministic integrity
  response analysis   + AI verification
(Regulations first)       |
        |                |
        +-------+--------+
                |
                v
          7 Guided Mode
                |
                v
           8 Rush Mode
                |
                v
     9 Re-analysis + Brief
                |
                v
       Add Congress.gov path
```

Chunks 5 and 6 can be worked on in parallel once Chunks 1–4 are stable.

## Hackathon scope rule

A chunk does not need to solve the whole real-world problem. It only needs to work well enough to prove the interaction and connect cleanly to the next piece.

For the demo, prefer:
- a few reliable sources over dozens of integrations
- traceable claims over lots of generated prose
- one strong end-to-end workflow over many unfinished features
- Fabric only if it clearly simplifies ingestion/storage

## Core product rule

> No important AI claim without evidence, no evidence without a support check, and no final report without human review.

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

**Goal:** Build the first useful AI pipeline over the policy itself.

Initial steps:
1. Plain-language explanation
2. Major provisions
3. Potentially affected stakeholders

Each result should be structured and linked to evidence.

Use **Microsoft Foundry** for the analysis workflow if available.

**Done when:** One policy can move through these steps and produce inspectable results.

---

### Chunk 5 — Public response + viewpoints

**Goal:** Add a small set of outside reactions without pretending they represent everyone.

Start with:
- **Regulations.gov** public comments
- **GDELT** news/reporting
- selected stakeholder statements when useful

Surface:
- recurring concerns
- recurring support/reasons
- questions/misunderstandings
- conflicting or minority viewpoints
- representativeness warning

**Done when:** The app can explain *why* people in the analyzed material are reacting, with source links.

---

### Chunk 6 — Claim verification

**Goal:** Check whether important claims are actually supported by their cited evidence.

Statuses:
- Supported
- Partially supported
- Needs clarification
- Unsupported
- Needs human review

The verifier should receive the claim plus the underlying retrieved evidence and decide whether the evidence actually supports it.

**Done when:** A separate verification pass can inspect a claim + evidence and return a visible status.

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

Then assemble the final brief from reviewed sections.

**Done when:** A user can fix one bad section without restarting the whole analysis and can produce a traceable final report.

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
4 Core analysis with Foundry
        |
        +----------------+
        |                |
        v                v
5 Public response   6 Verification
(Regulations/GDELT)     |
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

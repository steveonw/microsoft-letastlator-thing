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

Start small:
- paste policy text and/or load one known source
- preserve title/source metadata
- split into usable sections/chunks
- keep section/page/source references where possible

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

**Done when:** A claim can point to a specific piece of evidence and the user can inspect it.

---

### Chunk 4 — Core policy analysis steps

**Goal:** Build the first useful AI pipeline over the policy itself.

Initial steps:
1. Plain-language explanation
2. Major provisions
3. Potentially affected stakeholders

Each result should be structured and linked to evidence.

**Done when:** One policy can move through these steps and produce inspectable results.

---

### Chunk 5 — Public response + viewpoints

**Goal:** Add a small set of outside reactions without pretending they represent everyone.

Analyze a manageable demo dataset such as:
- public comments
- selected news/reporting
- stakeholder statements

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
2 Policy input
        |
        v
3 Evidence/citations
        |
        v
4 Core analysis
        |
        +----------------+
        |                |
        v                v
5 Public response   6 Verification
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
```

Chunks 5 and 6 can be worked on in parallel once Chunks 1–4 are stable.

## Hackathon scope rule

A chunk does not need to solve the whole real-world problem. It only needs to work well enough to prove the interaction and connect cleanly to the next piece.

For the demo, prefer:
- a few reliable sources over dozens of integrations
- traceable claims over lots of generated prose
- one strong end-to-end workflow over many unfinished features

## Core product rule

> No important AI claim without evidence, no evidence without a support check, and no final report without human review.

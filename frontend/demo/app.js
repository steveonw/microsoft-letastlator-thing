const SAMPLE_PATH = "../../shared/sample-analysis.json";

const state = {
  analysis: null,
  selectedStepId: null,
  selectedClaimId: null,
};

function humanize(value) {
  if (!value) return "—";
  return value.replaceAll("_", " ");
}

function byId(id) {
  return document.getElementById(id);
}

function findSource(sourceId) {
  return state.analysis.sources.find((source) => source.id === sourceId);
}

function findEvidence(evidenceId) {
  return state.analysis.evidence.find((item) => item.id === evidenceId);
}

function selectedStep() {
  return state.analysis.steps.find((step) => step.id === state.selectedStepId);
}

function selectStep(stepId) {
  state.selectedStepId = stepId;
  const step = selectedStep();
  state.selectedClaimId = step?.claims?.[0]?.id ?? null;
  render();
}

function selectClaim(claimId) {
  state.selectedClaimId = claimId;
  renderClaims();
  renderEvidence();
}

function renderHeader() {
  const analysis = state.analysis;
  byId("policy-title").textContent = analysis.policy.title;
  byId("policy-meta").textContent =
    `${analysis.policy.jurisdiction} · ${analysis.policy.version ?? "no version"} · run ${analysis.id}`;
  byId("mode").textContent = analysis.mode;
  byId("review-status").textContent = humanize(analysis.final_review_status);
}

function renderSteps() {
  const container = byId("steps");
  container.replaceChildren();
  byId("step-count").textContent = String(state.analysis.steps.length);

  state.analysis.steps.forEach((step, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className =
      "step-button" + (step.id === state.selectedStepId ? " active" : "");
    button.addEventListener("click", () => selectStep(step.id));

    const number = document.createElement("span");
    number.className = "step-index";
    number.textContent = String(index + 1);

    const copy = document.createElement("span");

    const name = document.createElement("div");
    name.className = "step-name";
    name.textContent = step.title;

    const status = document.createElement("div");
    status.className = "step-state";
    status.textContent = humanize(step.status);

    copy.append(name, status);
    button.append(number, copy);
    container.append(button);
  });
}

function renderAnalysis() {
  const step = selectedStep();
  if (!step) return;

  byId("step-kind").textContent = humanize(step.kind);
  byId("step-title").textContent = step.title;
  byId("step-status").textContent = humanize(step.status);
  byId("ai-output").textContent = step.ai_output ?? "No AI output saved for this step.";

  renderClaims();
  renderEvidence();
}

function renderClaims() {
  const step = selectedStep();
  const container = byId("claims");
  container.replaceChildren();

  if (!step.claims.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No claims recorded for this step.";
    container.append(empty);
    return;
  }

  step.claims.forEach((claim) => {
    const card = document.createElement("article");
    card.className =
      "claim-card" + (claim.id === state.selectedClaimId ? " active" : "");
    card.tabIndex = 0;
    card.addEventListener("click", () => selectClaim(claim.id));
    card.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectClaim(claim.id);
      }
    });

    const text = document.createElement("div");
    text.className = "claim-text";
    text.textContent = claim.text;

    const meta = document.createElement("div");
    meta.className = "claim-meta";

    const type = document.createElement("span");
    type.className = "claim-type";
    type.textContent = humanize(claim.information_type);

    const verify = document.createElement("span");
    verify.className = `verify ${claim.verification_status}`;
    verify.textContent = humanize(claim.verification_status);

    const confidence = document.createElement("span");
    confidence.className = "claim-type";
    confidence.textContent = `${claim.confidence} confidence`;

    meta.append(type, verify, confidence);
    card.append(text, meta);
    container.append(card);
  });
}

function renderEvidence() {
  const step = selectedStep();
  const claim = step?.claims.find((item) => item.id === state.selectedClaimId);
  const container = byId("evidence");
  container.replaceChildren();

  const evidenceItems = (claim?.evidence_ids ?? [])
    .map(findEvidence)
    .filter(Boolean);

  byId("evidence-count").textContent = String(evidenceItems.length);

  if (!claim || !evidenceItems.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "This claim does not have linked evidence yet.";
    container.append(empty);
    return;
  }

  evidenceItems.forEach((item) => {
    const source = findSource(item.source_id);
    const card = document.createElement("article");
    card.className = "evidence-card";

    const sourceName = document.createElement("div");
    sourceName.className = "evidence-source";
    sourceName.textContent = source?.title ?? item.source_id;

    const quote = document.createElement("blockquote");
    quote.textContent = item.snippet;

    const locator = document.createElement("div");
    locator.className = "evidence-locator";
    locator.textContent = item.locator
      ? `${item.locator} · ${humanize(source?.information_type)}`
      : humanize(source?.information_type);

    card.append(sourceName, quote, locator);
    container.append(card);
  });
}

function render() {
  renderHeader();
  renderSteps();
  renderAnalysis();
}

async function loadAnalysis() {
  try {
    const response = await fetch(SAMPLE_PATH);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    state.analysis = await response.json();
    state.selectedStepId =
      state.analysis.current_step_id ?? state.analysis.steps[0]?.id ?? null;

    const step = selectedStep();
    state.selectedClaimId = step?.claims?.[0]?.id ?? null;

    render();
  } catch (error) {
    document.body.innerHTML = `
      <div class="error">
        <strong>Could not load the sample analysis.</strong>
        <p>Run this demo through a local web server from the repository root rather than opening the HTML file directly.</p>
        <code>python -m http.server 8000</code>
        <p>Then open <code>http://localhost:8000/frontend/demo/</code>.</p>
        <small>${String(error)}</small>
      </div>
    `;
  }
}

loadAnalysis();

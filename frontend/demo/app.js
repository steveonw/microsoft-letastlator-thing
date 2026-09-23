const ANALYSIS_PATH = "/api/analysis";
const STORAGE_KEY = "policytrace-guided-demo";

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

function persist() {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(state.analysis));
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

function selectedClaim() {
  return selectedStep()?.claims.find((claim) => claim.id === state.selectedClaimId);
}

function firstUnreviewedStepId() {
  return state.analysis.steps.find(
    (step) => !["reviewed", "approved"].includes(step.human_review.status),
  )?.id ?? null;
}

function canOpenStep(stepId) {
  const currentId = state.analysis.current_step_id;
  if (!currentId) return true;
  const currentIndex = state.analysis.steps.findIndex((step) => step.id === currentId);
  const targetIndex = state.analysis.steps.findIndex((step) => step.id === stepId);
  return targetIndex <= currentIndex;
}

function selectStep(stepId) {
  if (!canOpenStep(stepId)) return;
  state.selectedStepId = stepId;
  const step = selectedStep();
  state.selectedClaimId = step?.claims?.[0]?.id ?? null;
  render();
}

function selectClaim(claimId) {
  state.selectedClaimId = claimId;
  renderClaims();
  renderEvidence();
  renderReviewBar();
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
    button.disabled = !canOpenStep(step.id);
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
    status.textContent =
      `${humanize(step.status)} · ${humanize(step.human_review.status)}`;

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
  byId("step-status").textContent = humanize(step.human_review.status);
  byId("ai-output").textContent = step.ai_output ?? "No AI output saved for this step.";

  renderClaims();
  renderEvidence();
  renderReviewBar();
}

function renderClaims() {
  const step = selectedStep();
  const container = byId("claims");
  container.replaceChildren();

  if (!step?.claims.length) {
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
    if (step.human_review.flagged_claim_ids.includes(claim.id)) {
      card.classList.add("flagged");
    }
    card.tabIndex = 0;
    card.addEventListener("click", () => selectClaim(claim.id));

    const text = document.createElement("div");
    text.className = "claim-text";
    text.textContent = claim.text;

    const meta = document.createElement("div");
    meta.className = "claim-meta";
    [humanize(claim.information_type), humanize(claim.verification_status), `${claim.confidence} confidence`]
      .forEach((label, i) => {
        const span = document.createElement("span");
        span.className = i === 1 ? `verify ${claim.verification_status}` : "claim-type";
        span.textContent = label;
        meta.append(span);
      });

    if (claim.verification_note) {
      const note = document.createElement("div");
      note.className = "verification-note";
      note.textContent = claim.verification_note;
      card.append(text, meta, note);
    } else {
      card.append(text, meta);
    }
    container.append(card);
  });
}

function renderEvidence() {
  const claim = selectedClaim();
  const container = byId("evidence");
  container.replaceChildren();

  const evidenceItems = (claim?.evidence_ids ?? []).map(findEvidence).filter(Boolean);
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

    if (source?.url) {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noreferrer";
      link.textContent = "Open source";
      link.className = "source-link";
      card.append(sourceName, quote, locator, link);
    } else {
      card.append(sourceName, quote, locator);
    }
    container.append(card);
  });
}

function ensureCurrentReview() {
  const current = state.analysis.steps.find(
    (step) => step.id === state.analysis.current_step_id,
  );
  if (current && current.human_review.status === "not_reviewed") {
    current.human_review.status = "in_review";
  }
}

function clarify() {
  const step = selectedStep();
  if (!step || step.id !== state.analysis.current_step_id) return;
  const note = prompt("Add a clarification for this step:");
  if (!note?.trim()) return;
  step.human_review.notes.push(`Clarification: ${note.trim()}`);
  step.human_review.status = "in_review";
  persist();
  render();
}

function editClaim() {
  const step = selectedStep();
  const claim = selectedClaim();
  if (!step || !claim || step.id !== state.analysis.current_step_id) return;
  const next = prompt("Edit this claim:", claim.text);
  if (!next?.trim() || next.trim() === claim.text) return;
  if (!claim.original_text) claim.original_text = claim.text;
  claim.text = next.trim();
  claim.information_type = "human_interpretation";
  claim.verification_status = "needs_human_review";
  claim.verification_note = "Human edit requires re-verification.";
  if (!step.human_review.edited_claim_ids.includes(claim.id)) {
    step.human_review.edited_claim_ids.push(claim.id);
  }
  step.human_review.status = "in_review";
  step.status = "draft";
  step.version += 1;
  persist();
  render();
}

function flagClaim() {
  const step = selectedStep();
  const claim = selectedClaim();
  if (!step || !claim || step.id !== state.analysis.current_step_id) return;
  if (!step.human_review.flagged_claim_ids.includes(claim.id)) {
    step.human_review.flagged_claim_ids.push(claim.id);
  }
  const note = prompt("Optional reason for flagging this claim:");
  if (note?.trim()) {
    step.human_review.notes.push(`Flagged ${claim.id}: ${note.trim()}`);
  }
  step.human_review.status = "in_review";
  persist();
  render();
}

function verifyClaim() {
  const step = selectedStep();
  const claim = selectedClaim();
  if (!step || !claim || step.id !== state.analysis.current_step_id) return;
  alert(
    claim.verification_note
      ? `${humanize(claim.verification_status)}\n\n${claim.verification_note}`
      : `Current verification status: ${humanize(claim.verification_status)}.\n\nLive re-verification is available through backend/run_guided_review.py verify.`,
  );
}

function nextStep() {
  const currentId = state.analysis.current_step_id;
  if (!currentId || state.selectedStepId !== currentId) return;

  const index = state.analysis.steps.findIndex((step) => step.id === currentId);
  const current = state.analysis.steps[index];
  current.human_review.status = "reviewed";

  const next = state.analysis.steps[index + 1];
  if (next) {
    state.analysis.current_step_id = next.id;
    if (next.human_review.status === "not_reviewed") {
      next.human_review.status = "in_review";
    }
    state.selectedStepId = next.id;
    state.selectedClaimId = next.claims?.[0]?.id ?? null;
  } else {
    state.analysis.current_step_id = null;
    state.selectedStepId = current.id;
  }

  persist();
  render();
}

function renderReviewBar() {
  const step = selectedStep();
  const claim = selectedClaim();
  const isCurrent = step?.id === state.analysis.current_step_id;
  byId("clarify-btn").disabled = !isCurrent;
  byId("edit-btn").disabled = !isCurrent || !claim;
  byId("verify-btn").disabled = !isCurrent || !claim;
  byId("flag-btn").disabled = !isCurrent || !claim;
  byId("next-btn").disabled = !isCurrent;

  const notes = step?.human_review.notes ?? [];
  byId("review-notes").textContent = notes.length
    ? notes.join(" · ")
    : isCurrent
      ? "Review this step. Only Next advances the workflow."
      : "Open the current step to continue guided review.";
}

function render() {
  renderHeader();
  renderSteps();
  renderAnalysis();
}

async function loadAnalysis() {
  try {
    const response = await fetch(ANALYSIS_PATH);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const fresh = await response.json();

    const saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      try {
        const parsed = JSON.parse(saved);
        state.analysis = parsed.id === fresh.id ? parsed : fresh;
      } catch {
        state.analysis = fresh;
      }
    } else {
      state.analysis = fresh;
    }

    if (state.analysis.mode !== "guided") state.analysis.mode = "guided";
    state.analysis.current_step_id ??= firstUnreviewedStepId();
    ensureCurrentReview();

    state.selectedStepId =
      state.analysis.current_step_id ?? state.analysis.steps[0]?.id ?? null;
    state.selectedClaimId = selectedStep()?.claims?.[0]?.id ?? null;

    byId("reset-btn").addEventListener("click", () => {
      localStorage.removeItem(STORAGE_KEY);
      location.reload();
    });
    byId("clarify-btn").addEventListener("click", clarify);
    byId("edit-btn").addEventListener("click", editClaim);
    byId("verify-btn").addEventListener("click", verifyClaim);
    byId("flag-btn").addEventListener("click", flagClaim);
    byId("next-btn").addEventListener("click", nextStep);

    persist();
    render();
  } catch (error) {
    document.body.innerHTML = `
      <div class="error">
        <strong>Could not load the analysis.</strong>
        <p>Start the FastAPI server from the repository root:</p>
        <code>python -m uvicorn api:app --app-dir backend --reload</code>
        <p>Then open <code>http://127.0.0.1:8000/demo/</code>.</p>
        <small>${String(error)}</small>
      </div>
    `;
  }
}

loadAnalysis();

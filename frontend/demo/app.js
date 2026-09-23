const state = {
  analysis: null,
  provider: null,
  busy: false,
  input: "id",
  selectedStepId: null,
  selectedClaimId: null,
  reviewAction: null,
};

const byId = (id) => document.getElementById(id);
const humanize = (value) => value ? value.replaceAll("_", " ") : "—";

async function api(path, payload, rawFile) {
  const options = payload === undefined && !rawFile ? {} : { method: "POST" };
  if (rawFile) {
    options.headers = { "Content-Type": rawFile.type || "application/octet-stream" };
    options.body = rawFile;
  } else if (payload !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(payload);
  }
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = data.detail ?? data.error ?? `HTTP ${response.status}`;
    throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg).join("; ") : String(detail));
  }
  return data;
}

function showMessage(message, error = false) {
  const box = byId("message");
  box.hidden = !message;
  box.textContent = message || "";
  box.classList.toggle("message-error", error);
}

function selectedStep() {
  return state.analysis?.steps.find((step) => step.id === state.selectedStepId);
}

function selectedClaim() {
  return selectedStep()?.claims.find((claim) => claim.id === state.selectedClaimId);
}

function setAnalysis(analysis, resetSelection = false) {
  state.analysis = analysis;
  const previous = resetSelection ? null : state.selectedStepId;
  state.selectedStepId = analysis.current_step_id
    ?? (analysis.steps.some((step) => step.id === previous) ? previous : analysis.steps[0]?.id ?? null);
  const step = selectedStep();
  if (!step?.claims.some((claim) => claim.id === state.selectedClaimId)) {
    state.selectedClaimId = step?.claims[0]?.id ?? null;
  }
  render();
}

function setBusy(value) {
  state.busy = value;
  render();
}

async function analysisAction(path, payload, working, success, rawFile, resetSelection = false) {
  if (state.busy) return;
  setBusy(true);
  showMessage(working);
  try {
    setAnalysis(await api(path, payload, rawFile), resetSelection);
    showMessage(success);
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    setBusy(false);
  }
}

function canOpenStep(stepId) {
  if (!state.analysis) return false;
  if (state.analysis.mode === "rush") return true;
  const steps = state.analysis.steps;
  const target = steps.findIndex((step) => step.id === stepId);
  const current = steps.findIndex((step) => step.id === state.analysis.current_step_id);
  if (current >= 0) return target <= current;
  const firstPending = steps.findIndex((step) => !["reviewed", "approved"].includes(step.human_review.status));
  return firstPending < 0 || target <= firstPending;
}

function selectStep(stepId) {
  if (!canOpenStep(stepId) || state.busy) return;
  if (state.analysis.mode === "rush" && state.analysis.current_step_id !== stepId) {
    analysisAction("/api/rush/open", { step_id: stepId }, "Opening step…", "Step opened for review.");
    return;
  }
  state.selectedStepId = stepId;
  state.selectedClaimId = selectedStep()?.claims[0]?.id ?? null;
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
  byId("policy-meta").textContent = `${analysis.policy.jurisdiction} · ${analysis.policy.version ?? "source review"} · ${analysis.sources.length} source${analysis.sources.length === 1 ? "" : "s"}`;
  byId("mode").textContent = humanize(analysis.mode);
  byId("review-status").textContent = humanize(analysis.final_review_status);
}

function renderProvider() {
  const provider = state.provider;
  const indicator = byId("provider-indicator");
  indicator.textContent = provider?.kind && provider.kind !== "none"
    ? `${provider.kind === "foundry" ? "Microsoft Foundry" : humanize(provider.kind)} · ${provider.model}`
    : "Provider not configured";
  indicator.classList.toggle("connected", Boolean(provider && provider.kind !== "none"));
}

function renderSteps() {
  const container = byId("steps");
  container.replaceChildren();
  byId("step-count").textContent = String(state.analysis.steps.length);
  state.analysis.steps.forEach((step, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = `step-button${step.id === state.selectedStepId ? " active" : ""}`;
    button.disabled = state.busy || !canOpenStep(step.id);
    button.addEventListener("click", () => selectStep(step.id));
    const number = document.createElement("span");
    number.className = "step-index";
    number.textContent = String(index + 1);
    const copy = document.createElement("span");
    const name = document.createElement("span");
    name.className = "step-name";
    name.textContent = step.title;
    const status = document.createElement("span");
    status.className = "step-state";
    status.textContent = `${humanize(step.status)} · ${humanize(step.human_review.status)}`;
    copy.append(name, status);
    button.append(number, copy);
    container.append(button);
  });
}

function renderAnalysis() {
  const step = selectedStep();
  byId("step-kind").textContent = humanize(step?.kind);
  byId("step-title").textContent = step?.title ?? "Select a step";
  byId("step-status").textContent = humanize(step?.human_review.status);
  byId("ai-output").textContent = step?.ai_output || "No analysis output saved for this step.";
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
    const card = document.createElement("button");
    card.type = "button";
    card.className = `claim-card${claim.id === state.selectedClaimId ? " active" : ""}${step.human_review.flagged_claim_ids.includes(claim.id) ? " flagged" : ""}`;
    card.disabled = state.busy;
    card.addEventListener("click", () => selectClaim(claim.id));
    const text = document.createElement("span");
    text.className = "claim-text";
    text.textContent = claim.text;
    const meta = document.createElement("span");
    meta.className = "claim-meta";
    [humanize(claim.information_type), humanize(claim.verification_status), `${claim.confidence} confidence`].forEach((label, index) => {
      const badge = document.createElement("span");
      badge.className = index === 1 ? `verify ${claim.verification_status}` : "claim-type";
      badge.textContent = label;
      meta.append(badge);
    });
    card.append(text, meta);
    if (claim.verification_note) {
      const note = document.createElement("span");
      note.className = "verification-note";
      note.textContent = claim.verification_note;
      card.append(note);
    }
    container.append(card);
  });
}

function renderEvidence() {
  const claim = selectedClaim();
  const container = byId("evidence");
  container.replaceChildren();
  const items = (claim?.evidence_ids ?? []).map((id) => state.analysis.evidence.find((item) => item.id === id)).filter(Boolean);
  byId("evidence-count").textContent = String(items.length);
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "This claim does not have linked evidence yet.";
    container.append(empty);
    return;
  }
  items.forEach((item) => {
    const source = state.analysis.sources.find((entry) => entry.id === item.source_id);
    const card = document.createElement("article");
    card.className = "evidence-card";
    const name = document.createElement("div");
    name.className = "evidence-source";
    name.textContent = source?.title ?? item.source_id;
    const quote = document.createElement("blockquote");
    quote.textContent = item.snippet;
    const locator = document.createElement("div");
    locator.className = "evidence-locator";
    locator.textContent = [item.locator, humanize(source?.information_type)].filter(Boolean).join(" · ");
    card.append(name, quote, locator);
    if (source?.url) {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      link.textContent = "Open source ↗";
      link.className = "source-link";
      card.append(link);
    }
    container.append(card);
  });
}

function renderReviewBar() {
  const analysis = state.analysis;
  const step = selectedStep();
  const claim = selectedClaim();
  const guided = analysis.mode === "guided";
  const rush = analysis.mode === "rush";
  const activeStep = Boolean(step && step.id === analysis.current_step_id);
  const current = guided && activeStep;
  const atRushFinal = rush && !analysis.current_step_id && analysis.final_review_status === "in_review";
  const hasStaleWork = analysis.steps.some((item) => item.status === "needs_refresh");
  const hasReviewedWork = analysis.final_review_status === "approved" || analysis.steps.some((item) => ["reviewed", "approved"].includes(item.human_review.status));
  const setDisabled = (id, disabled) => { byId(id).disabled = state.busy || disabled; };
  setDisabled("clarify-btn", !current);
  setDisabled("edit-btn", !current || !claim);
  setDisabled("verify-btn", !activeStep || !claim);
  setDisabled("flag-btn", !current || !claim);
  setDisabled("next-btn", !current);
  setDisabled("begin-btn", !guided || Boolean(analysis.current_step_id));
  setDisabled("rush-btn", !state.provider || state.provider.kind === "none");
  setDisabled("reset-btn", false);
  setDisabled("rush-final-btn", !rush || !analysis.current_step_id);
  setDisabled("approve-btn", !atRushFinal || hasStaleWork);
  setDisabled("brief-btn", hasStaleWork || !hasReviewedWork);
  setDisabled("reanalyze-btn", !step?.claims.length);
  setDisabled("refresh-btn", !step || step.status !== "needs_refresh");
  setDisabled("review-step-btn", !step || step.status === "needs_refresh" || step.claims.some((item) => item.verification_status === "needs_human_review"));
  ["clarify-btn", "edit-btn", "flag-btn", "next-btn"].forEach((id) => { byId(id).hidden = !guided; });
  byId("verify-btn").hidden = !guided && !(rush && activeStep);
  ["rush-final-btn", "approve-btn"].forEach((id) => { byId(id).hidden = !rush; });
  const notes = step?.human_review.notes ?? [];
  byId("review-notes").textContent = notes.length ? notes.join(" · ")
    : current ? "Review this step. Only Next advances Guided mode."
    : atRushFinal ? "Rush stopped for explicit human approval."
    : rush ? "Open a step to inspect it, then return to final review."
    : "Begin Guided to review the analysis.";
}

function render() {
  document.querySelectorAll(".source-card button, .workspace-toolbar button, .topbar button").forEach((button) => {
    if (state.busy) button.disabled = true;
    else if (!["begin-btn", "rush-btn", "reset-btn"].includes(button.id)) button.disabled = false;
  });
  renderProvider();
  if (!state.analysis) return;
  renderHeader();
  renderSteps();
  renderAnalysis();
}

function selectInput(kind) {
  state.input = kind;
  document.querySelectorAll(".input-tab").forEach((tab) => {
    const active = tab.dataset.input === kind;
    tab.classList.toggle("active", active);
    tab.setAttribute("aria-selected", String(active));
    tab.tabIndex = active ? 0 : -1;
  });
  document.querySelectorAll(".input-panel").forEach((panel) => { panel.hidden = panel.id !== `input-${kind}`; });
  byId("source-submit").disabled = state.busy;
}

function openReviewDialog(action, title, label, value = "") {
  state.reviewAction = action;
  byId("review-dialog-title").textContent = title;
  byId("review-field-label").textContent = label;
  byId("review-input").value = value;
  byId("review-dialog").showModal();
  byId("review-input").focus();
}

async function submitSource(event) {
  event.preventDefault();
  if (state.busy) return;
  if (state.input === "id") {
    const documentNumber = byId("document-number").value.trim();
    if (!documentNumber) return showMessage("Enter a Federal Register document number.", true);
    return analysisAction("/api/source/load", { document_number: documentNumber }, "Loading Federal Register source and analyzing policy…", "Policy analysis is ready.", null, true);
  }
  if (state.input === "url") {
    const url = byId("source-url").value.trim();
    if (!url) return showMessage("Enter a public policy URL.", true);
    return analysisAction("/api/source/url", { url }, "Fetching URL and analyzing policy…", "Policy analysis is ready.", null, true);
  }
  if (state.input === "text") {
    const text = byId("policy-text").value.trim();
    if (!text) return showMessage("Paste policy text to analyze.", true);
    return analysisAction("/api/source/text", { text, title: byId("text-title").value.trim() || null }, "Analyzing pasted policy text…", "Policy analysis is ready.", null, true);
  }
  const file = byId("policy-file").files[0];
  if (!file) return showMessage("Choose a file to upload.", true);
  if (file.size > 5_000_000) return showMessage("The source exceeds the 5 MB demo limit.", true);
  const path = `/api/source/file?filename=${encodeURIComponent(file.name)}`;
  return analysisAction(path, null, "Reading file and analyzing policy…", "Policy analysis is ready.", file, true);
}

function renderProviderForm() {
  const foundry = byId("provider-kind").value === "foundry";
  byId("provider-endpoint-row").hidden = !foundry;
  byId("provider-token-row").hidden = !foundry;
  byId("provider-base-row").hidden = foundry;
}

async function submitProvider(event) {
  event.preventDefault();
  if (state.busy) return;
  const payload = {
    kind: byId("provider-kind").value,
    model: byId("provider-model").value.trim(),
    endpoint: byId("provider-endpoint").value.trim(),
    base_url: byId("provider-base").value.trim(),
    api_key: byId("provider-key").value.trim(),
    bearer_token: byId("provider-token").value.trim(),
    regulations_api_key: byId("regulations-key").value.trim(),
  };
  setBusy(true);
  try {
    state.provider = await api("/api/provider", payload);
    ["provider-key", "provider-token", "regulations-key"].forEach((id) => { byId(id).value = ""; });
    byId("provider-dialog").close();
    showMessage("Provider saved for this server session.");
  } catch (error) {
    showMessage(error.message, true);
  } finally {
    setBusy(false);
  }
}

function bindEvents() {
  const tabs = Array.from(document.querySelectorAll(".input-tab"));
  tabs.forEach((tab, index) => {
    tab.addEventListener("click", () => selectInput(tab.dataset.input));
    tab.addEventListener("keydown", (event) => {
      const delta = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
      if (!delta) return;
      event.preventDefault();
      const next = tabs[(index + delta + tabs.length) % tabs.length];
      selectInput(next.dataset.input);
      next.focus();
    });
  });
  byId("source-form").addEventListener("submit", submitSource);
  byId("comments-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const docketId = byId("docket-id").value.trim();
    const count = Number(byId("comment-count").value);
    if (!docketId || !Number.isInteger(count) || count < 1 || count > 100) return showMessage("Enter a docket ID and a comment count from 1 to 100.", true);
    analysisAction("/api/source/comments", { docket_id: docketId, max_comments: count }, `Loading up to ${count} public comments…`, "Public comments added to the analysis.");
  });
  byId("provider-open").addEventListener("click", () => {
    if (state.provider?.kind !== "none") {
      byId("provider-kind").value = state.provider.kind;
      byId("provider-model").value = state.provider.model || "";
      byId("provider-endpoint").value = state.provider.endpoint || "";
      byId("provider-base").value = state.provider.base_url || "";
    }
    renderProviderForm();
    byId("provider-dialog").showModal();
  });
  byId("provider-close").addEventListener("click", () => byId("provider-dialog").close());
  byId("provider-kind").addEventListener("change", renderProviderForm);
  byId("provider-form").addEventListener("submit", submitProvider);
  byId("provider-clear").addEventListener("click", async () => {
    if (state.busy) return;
    setBusy(true);
    try {
      state.provider = await api("/api/provider/clear", {});
      ["provider-key", "provider-token", "regulations-key"].forEach((id) => { byId(id).value = ""; });
      byId("provider-dialog").close();
      showMessage("Provider credentials cleared.");
    } catch (error) { showMessage(error.message, true); }
    finally { setBusy(false); }
  });
  byId("reset-btn").addEventListener("click", () => analysisAction("/api/reset", { mode: "guided" }, "Resetting review…", "Guided review reset."));
  byId("begin-btn").addEventListener("click", () => analysisAction("/api/guided/begin", {}, "Beginning Guided review…", "Guided review is ready."));
  byId("rush-btn").addEventListener("click", () => analysisAction("/api/rush/run", {}, "Running analysis and verification…", "Rush analysis is ready for final human review."));
  byId("clarify-btn").addEventListener("click", () => openReviewDialog("clarify", "Clarify this step", "Clarification note"));
  byId("edit-btn").addEventListener("click", () => openReviewDialog("edit", "Edit claim", "Revised claim", selectedClaim()?.text ?? ""));
  byId("flag-btn").addEventListener("click", () => openReviewDialog("flag", "Flag claim", "Reason (optional)"));
  byId("verify-btn").addEventListener("click", () => analysisAction("/api/guided/verify", { claim_id: state.selectedClaimId }, "Verifying claim…", "Verification result updated."));
  byId("next-btn").addEventListener("click", () => analysisAction("/api/guided/next", {}, "Advancing review…", "Moved to the next step."));
  byId("rush-final-btn").addEventListener("click", () => analysisAction("/api/rush/final", {}, "Returning to final review…", "Final review is ready."));
  byId("approve-btn").addEventListener("click", () => analysisAction("/api/rush/approve", {}, "Recording approval…", "Rush analysis approved."));
  byId("brief-btn").addEventListener("click", () => analysisAction("/api/brief", {}, "Building traceable brief…", "Final brief added to the analysis."));
  byId("reanalyze-btn").addEventListener("click", () => openReviewDialog("reanalyze", "Replace first claim", "Replacement claim", selectedStep()?.claims[0]?.text ?? ""));
  byId("refresh-btn").addEventListener("click", () => analysisAction("/api/reanalysis/refresh", { step_id: state.selectedStepId }, "Refreshing dependent step…", "Step refreshed; review its claims."));
  byId("review-step-btn").addEventListener("click", () => analysisAction("/api/reanalysis/review", { step_id: state.selectedStepId }, "Marking step reviewed…", "Step marked reviewed."));
  byId("review-close").addEventListener("click", () => byId("review-dialog").close());
  byId("review-cancel").addEventListener("click", () => byId("review-dialog").close());
  byId("review-form").addEventListener("submit", (event) => {
    event.preventDefault();
    const value = byId("review-input").value.trim();
    const action = state.reviewAction;
    if (["clarify", "edit", "reanalyze"].includes(action) && !value) return showMessage("Enter text before saving.", true);
    byId("review-dialog").close();
    if (action === "clarify") analysisAction("/api/guided/clarify", { note: value }, "Saving clarification…", "Clarification saved.");
    if (action === "edit") analysisAction("/api/guided/edit", { claim_id: state.selectedClaimId, text: value }, "Saving claim edit…", "Claim edited; re-verification is required.");
    if (action === "flag") analysisAction("/api/guided/flag", { claim_id: state.selectedClaimId, note: value }, "Flagging claim…", "Claim flagged for review.");
    if (action === "reanalyze") analysisAction("/api/reanalysis/step", { step_id: state.selectedStepId, text: value }, "Updating selected step…", "Step updated; dependent work needs refresh.");
  });
}

async function initialize() {
  bindEvents();
  selectInput("id");
  try {
    const [analysis, provider] = await Promise.all([api("/api/analysis"), api("/api/provider")]);
    state.provider = provider;
    setAnalysis(analysis, true);
    if (provider.kind === "none") showMessage("Configure a model provider to analyze a new policy.");
  } catch (error) {
    showMessage(`Could not load the workspace: ${error.message}`, true);
    byId("policy-title").textContent = "Workspace unavailable";
  }
}

initialize();

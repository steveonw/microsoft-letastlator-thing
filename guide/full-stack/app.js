const state = {
  analysis: null,
  selectedStepId: null,
  selectedClaimId: null,
  provider: null,
};

function byId(id) { return document.getElementById(id); }
function humanize(value) { return value ? value.replaceAll("_", " ") : "—"; }

async function api(path, body = null) {
  const options = body === null
    ? {}
    : {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)};
  const response = await fetch(path, options);
  const payload = await response.json();
  if (!response.ok) throw new Error(payload.error || ("HTTP " + response.status));
  return payload;
}

function message(text, error = false) {
  const box = byId("message");
  box.textContent = text;
  box.className = error ? "message error" : "message";
}

function currentStep() {
  return state.analysis?.steps.find(step => step.id === state.selectedStepId) ?? null;
}

function currentClaim() {
  return currentStep()?.claims.find(claim => claim.id === state.selectedClaimId) ?? null;
}

function syncSelection() {
  const steps = state.analysis?.steps ?? [];
  const selectable = steps.filter(step => step.kind !== "draft_brief");
  if (!selectable.some(step => step.id === state.selectedStepId)) {
    state.selectedStepId =
      state.analysis?.current_step_id && selectable.some(step => step.id === state.analysis.current_step_id)
        ? state.analysis.current_step_id
        : selectable[0]?.id ?? null;
  }
  const step = currentStep();
  if (!step?.claims.some(claim => claim.id === state.selectedClaimId)) {
    state.selectedClaimId = step?.claims?.[0]?.id ?? null;
  }
}

function findEvidence(id) {
  return state.analysis.evidence.find(item => item.id === id);
}
function findSource(id) {
  return state.analysis.sources.find(item => item.id === id);
}

function renderProvider() {
  const p = state.provider;
  if (!p) return;
  byId("provider-badge").textContent = p.kind;
  const pieces = [
    p.kind,
    p.model || null,
    p.has_api_key ? "API key loaded" : null,
    p.has_bearer_token ? "bearer loaded" : null,
    p.has_regulations_api_key ? "Regulations key loaded" : null,
    "memory only",
  ].filter(Boolean);
  byId("provider-status").textContent = pieces.join(" · ");
}

function render() {
  if (!state.analysis) return;
  syncSelection();
  const analysis = state.analysis;
  byId("mode-badge").textContent = analysis.mode;
  byId("final-review").textContent = humanize(analysis.final_review_status);

  const normalSteps = analysis.steps.filter(step => step.kind !== "draft_brief");
  byId("step-count").textContent = String(normalSteps.length);
  const list = byId("steps");
  list.replaceChildren();

  normalSteps.forEach(step => {
    const button = document.createElement("button");
    button.className = "step-button" +
      (step.id === state.selectedStepId ? " active" : "") +
      (step.status === "needs_refresh" ? " needs_refresh" : "");
    button.innerHTML =
      "<strong>" + step.title + "</strong>" +
      "<small>" + step.id + "</small>" +
      "<small>v" + step.version + " · " + humanize(step.status) +
      " · " + humanize(step.human_review.status) + "</small>";
    button.onclick = async () => {
      if (analysis.mode === "rush") {
        try {
          state.analysis = await api("/api/rush/open", {step_id: step.id});
          message("Opened " + step.id + " for Rush review.");
        } catch (error) {
          message(String(error), true);
        }
      }
      state.selectedStepId = step.id;
      state.selectedClaimId = step.claims?.[0]?.id ?? null;
      render();
    };
    list.append(button);
  });

  const step = currentStep();
  byId("step-kind").textContent = step ? humanize(step.kind) : "Select a step";
  byId("step-title").textContent = step?.title ?? "—";
  byId("step-status").textContent = step ? humanize(step.status) : "—";
  byId("ai-output").textContent = step?.ai_output ?? "";
  byId("step-version").textContent = step?.version ?? "—";
  byId("human-status").textContent = humanize(step?.human_review?.status);
  byId("depends-on").textContent = step?.depends_on?.join(", ") || "none";
  byId("current-step").textContent =
    analysis.current_step_id === step?.id ? "yes" : "no";

  const claims = byId("claims");
  claims.replaceChildren();
  (step?.claims ?? []).forEach(claim => {
    const div = document.createElement("div");
    div.className = "claim" + (claim.id === state.selectedClaimId ? " active" : "");
    div.innerHTML =
      "<strong>" + claim.text + "</strong>" +
      "<div class='claim-meta'>" + claim.id + " · " +
      humanize(claim.verification_status) + " · " +
      humanize(claim.information_type) + "</div>";
    div.onclick = () => {
      state.selectedClaimId = claim.id;
      render();
    };
    claims.append(div);
  });

  const claim = currentClaim();
  const evidenceBox = byId("evidence");
  evidenceBox.replaceChildren();
  const evidenceIds = claim?.evidence_ids ?? [];
  byId("evidence-count").textContent = String(evidenceIds.length);
  evidenceIds.forEach(id => {
    const evidence = findEvidence(id);
    const source = evidence ? findSource(evidence.source_id) : null;
    const div = document.createElement("div");
    div.className = "evidence-item";
    div.innerHTML =
      "<strong>" + (source?.title ?? "Unknown source") + "</strong>" +
      "<div class='muted'>" + id + " · " + humanize(source?.information_type) + "</div>" +
      "<blockquote>" + (evidence?.snippet ?? "Missing evidence") + "</blockquote>";
    evidenceBox.append(div);
  });

  const notes = byId("review-notes");
  notes.replaceChildren();
  const reviewNotes = step?.human_review?.notes ?? [];
  if (!reviewNotes.length) {
    notes.textContent = "No review notes.";
  } else {
    reviewNotes.forEach(note => {
      const div = document.createElement("div");
      div.textContent = note;
      notes.append(div);
    });
  }

  const brief = analysis.steps.find(item => item.kind === "draft_brief");
  byId("brief-output").textContent = brief?.ai_output ?? "No final brief yet.";

  byId("refresh").disabled = step?.status !== "needs_refresh";
  byId("review-reanalysis").disabled = !step || step.status === "needs_refresh";
}

async function load() {
  try {
    const [analysis, provider] = await Promise.all([
      api("/api/analysis"),
      api("/api/provider"),
    ]);
    state.analysis = analysis;
    state.provider = provider;
    renderProvider();
    render();
    message("Guide loaded.");
  } catch (error) {
    message(String(error), true);
  }
}

async function action(path, body, success) {
  try {
    state.analysis = await api(path, body);
    render();
    message(success);
  } catch (error) {
    message(String(error), true);
  }
}

byId("save-provider").onclick = async () => {
  try {
    state.provider = await api("/api/provider", {
      kind: byId("provider-kind").value,
      model: byId("provider-model").value,
      base_url: byId("provider-base-url").value,
      endpoint: byId("provider-endpoint").value,
      api_key: byId("provider-api-key").value,
      bearer_token: byId("provider-bearer").value,
      regulations_api_key: byId("regulations-key").value,
    });
    byId("provider-api-key").value = "";
    byId("provider-bearer").value = "";
    byId("regulations-key").value = "";
    renderProvider();
    message("Provider settings loaded into local process memory.");
  } catch (error) {
    message(String(error), true);
  }
};

byId("clear-provider").onclick = async () => {
  try {
    state.provider = await api("/api/provider/clear", {});
    renderProvider();
    message("Local provider credentials cleared.");
  } catch (error) {
    message(String(error), true);
  }
};

byId("guided-reset").onclick = () =>
  action("/api/reset", {mode: "guided"}, "Guided demo reset.");
byId("guided-begin").onclick = () =>
  action("/api/guided/begin", {}, "Guided review started.");
byId("rush-run").onclick = () =>
  action("/api/rush/run", {}, "Rush pipeline completed and stopped at human review.");
byId("rush-final").onclick = () =>
  action("/api/rush/final", {}, "Returned to Rush final review.");
byId("rush-approve").onclick = () =>
  action("/api/rush/approve", {}, "Rush final review explicitly approved.");
byId("build-brief").onclick = () =>
  action("/api/brief", {}, "Traceable final brief assembled.");

byId("clarify").onclick = () => {
  const note = prompt("Clarification note:");
  if (note) action("/api/guided/clarify", {note}, "Clarification saved.");
};

byId("edit").onclick = () => {
  const claim = currentClaim();
  if (!claim) return message("Select a claim first.", true);
  const text = prompt("Edit claim:", claim.text);
  if (text) action("/api/guided/edit", {claim_id: claim.id, text}, "Claim edited.");
};

byId("verify").onclick = () => {
  const claim = currentClaim();
  if (!claim) return message("Select a claim first.", true);
  action("/api/guided/verify", {claim_id: claim.id}, "Selected claim verified.");
};

byId("flag").onclick = () => {
  const claim = currentClaim();
  if (!claim) return message("Select a claim first.", true);
  const note = prompt("Optional flag note:", "") ?? "";
  action("/api/guided/flag", {claim_id: claim.id, note}, "Claim flagged.");
};

byId("next").onclick = () =>
  action("/api/guided/next", {}, "Advanced only because the human clicked Next.");

byId("reanalyze").onclick = () => {
  const step = currentStep();
  if (!step) return message("Select a step first.", true);
  if (!step.claims?.length) return message("Selected step has no claims.", true);
  const text = prompt("Replacement first-claim text:", step.claims[0].text);
  if (text) {
    action(
      "/api/reanalysis/step",
      {step_id: step.id, text},
      "Re-analysis replaced only " + step.id + " and invalidated its dependents."
    );
  }
};

byId("refresh").onclick = () => {
  const step = currentStep();
  if (!step) return;
  action(
    "/api/reanalysis/refresh",
    {step_id: step.id},
    "Refreshed " + step.id + "."
  );
};

byId("review-reanalysis").onclick = () => {
  const step = currentStep();
  if (!step) return;
  action(
    "/api/reanalysis/review",
    {step_id: step.id},
    "Re-verified and marked " + step.id + " reviewed."
  );
};

load();

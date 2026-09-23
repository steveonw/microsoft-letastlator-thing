/*
 * PolicyTrace app.
 *
 * Talks to the backend over HTTP. There is no client-side copy of the review
 * rules: the server decides what is allowed, and a refusal is displayed rather
 * than prevented, because "the system would not let me approve unreviewed
 * work" is the thing worth showing.
 */

const API = "";

let run = null;
let selectedStepId = null;
let selectedClaimId = null;
let editingClaimId = null;

const byId = (id) => document.getElementById(id);

const WORDING = {
  draft: "not reviewed yet",
  verified: "checked",
  needs_refresh: "out of date",
  not_reviewed: "not reviewed yet",
  in_review: "being reviewed",
  reviewed: "reviewed",
  approved: "approved",
  supported: "supported by the source",
  partially_supported: "partly supported",
  unsupported: "not supported by the source",
  needs_clarification: "unclear",
  needs_human_review: "needs your decision",
  ai_interpretation: "written by AI",
  human_interpretation: "your wording",
};

const say = (value) => WORDING[value] ?? String(value ?? "").replace(/_/g, " ");

function banner(message, kind = "info") {
  const el = byId("banner");
  if (!message) {
    el.hidden = true;
    return;
  }
  el.textContent = message;
  el.className = `banner ${kind}`;
  el.hidden = false;
}

async function api(path, payload) {
  try {
    const response = await fetch(`${API}${path}`, {
      method: payload === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || data.error) {
      banner(data.error || `Request failed (${response.status})`, "refused");
      return null;
    }
    banner("");
    return data.analysis ?? data;
  } catch (error) {
    banner(`Cannot reach the server: ${error.message}`, "refused");
    return null;
  }
}

const steps = () => run?.steps ?? [];
const stepById = (id) => steps().find((s) => s.id === id) ?? null;
const currentStep = () =>
  stepById(selectedStepId) ?? stepById(run?.current_step_id) ?? null;

const contentSteps = () =>
  steps().filter((step) => !["verification", "draft_brief"].includes(step.kind));

function allContentReviewed() {
  const items = contentSteps();
  return (
    items.length > 0 &&
    items.every(
      (step) =>
        step.status !== "needs_refresh" &&
        ["reviewed", "approved"].includes(step.human_review?.status)
    )
  );
}

function stepDisplayStatus(step) {
  if (step.status === "needs_refresh") return step.status;
  return step.human_review?.status ?? step.status;
}

function claimsOf(step) {
  return step?.claims ?? [];
}

function selectedClaim() {
  return claimsOf(currentStep()).find((c) => c.id === selectedClaimId) ?? null;
}

function evidenceById(id) {
  return (run?.evidence ?? []).find((e) => e.id === id) ?? null;
}

function sourceById(id) {
  return (run?.sources ?? []).find((s) => s.id === id) ?? null;
}

function render() {
  const started = Boolean(run);
  byId("start-screen").hidden = started;
  byId("workspace").hidden = !started;
  if (!started) return;

  byId("mode-pill").textContent =
    run.mode === "rush" ? "analyze then review" : "section by section";

  byId("policy-title").textContent = run.policy?.title ?? "Policy";
  const bits = [run.policy?.jurisdiction, run.policy?.version].filter(Boolean);
  byId("policy-meta").textContent = bits.join(" · ");
  byId("review-state").textContent = say(run.final_review_status);

  renderSections();
  renderFindings();
  renderEvidence();
  renderActions();
}

function renderSections() {
  const list = byId("section-list");
  list.replaceChildren();

  steps()
    .filter((step) => !["verification", "draft_brief"].includes(step.kind))
    .forEach((step, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "section-item";
    if (step.id === currentStep()?.id) button.classList.add("active");
    if (step.status === "needs_refresh") button.classList.add("stale");

    const title = document.createElement("span");
    title.className = "section-name";
    title.textContent = `${index + 1}. ${step.title}`;

    const displayStatus = stepDisplayStatus(step);
    const status = document.createElement("span");
    status.className = `tag ${displayStatus}`;
    status.textContent = say(displayStatus);

    button.append(title, status);

    const edits = step.human_review?.edited_claim_ids ?? [];
    if (edits.length) {
      const edited = document.createElement("span");
      edited.className = "tag edited";
      edited.textContent = `${edits.length} edited by you`;
      button.append(edited);
    }

    button.addEventListener("click", async () => {
      const opened =
        run.mode === "rush"
          ? await api("/api/rush/open", { step_id: step.id })
          : await api("/api/guided/begin", { step_id: step.id });
      if (!opened) return;

      run = opened;
      selectedStepId = step.id;
      selectedClaimId = null;
      editingClaimId = null;
      render();
    });
    list.append(button);
  });
}

function renderFindings() {
  const step = currentStep();
  const list = byId("claim-list");
  list.replaceChildren();

  byId("section-title").textContent = step?.title ?? "Findings";
  const statusPill = byId("section-status");
  statusPill.textContent = step ? say(step.status) : "";
  statusPill.className = `pill ${step?.status ?? ""}`;

  byId("section-note").textContent =
    step?.status === "needs_refresh"
      ? "You changed something this section depends on. Refresh it before reviewing."
      : "";

  if (!step) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = allContentReviewed()
      ? "All sections are reviewed. Build the final brief when you are ready."
      : "Select a section to continue reviewing.";
    list.append(empty);
    return;
  }

  if (!claimsOf(step).length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "No findings in this section.";
    list.append(empty);
    return;
  }

  claimsOf(step).forEach((claim) => {
    list.append(renderClaimCard(claim, step));
  });
}

function renderClaimCard(claim, step) {
  const card = document.createElement("article");
  card.className = "claim";
  if (claim.id === selectedClaimId) card.classList.add("selected");

  const top = document.createElement("div");
  top.className = "claim-top";

  const status = document.createElement("span");
  status.className = `verdict ${claim.verification_status}`;
  status.textContent = say(claim.verification_status);
  top.append(status);

  const missingEvidence = !(claim.evidence_ids ?? []).length;
  if (missingEvidence) {
    const warn = document.createElement("span");
    warn.className = "verdict no-evidence";
    warn.textContent = "no source found";
    top.append(warn);
  }

  const flagged = (step.human_review?.flagged_claim_ids ?? []).includes(claim.id);
  if (flagged) {
    const tag = document.createElement("span");
    tag.className = "verdict needs_human_review";
    tag.textContent = "flagged by you";
    top.append(tag);
  }

  const edited = (step.human_review?.edited_claim_ids ?? []).includes(claim.id);
  if (edited || claim.information_type === "human_interpretation") {
    const tag = document.createElement("span");
    tag.className = "verdict human";
    tag.textContent = "your wording";
    top.append(tag);
  }

  card.append(top);

  if (claim.id === editingClaimId) {
    card.append(renderEditor(claim));
  } else {
    const text = document.createElement("p");
    text.className = "claim-text";
    text.textContent = claim.text;
    card.append(text);
  }

  if (claim.original_text && claim.id !== editingClaimId) {
    const was = document.createElement("p");
    was.className = "was";
    was.textContent = `AI originally wrote: ${claim.original_text}`;
    card.append(was);
  }

  if (claim.verification_note) {
    const note = document.createElement("p");
    note.className = "claim-note";
    note.textContent = claim.verification_note;
    card.append(note);
  }

  card.addEventListener("click", () => {
    if (editingClaimId === claim.id) return;
    selectedClaimId = claim.id;
    render();
  });

  return card;
}

function renderEditor(claim) {
  const wrap = document.createElement("div");
  wrap.className = "editor";

  const area = document.createElement("textarea");
  area.value = claim.text;
  area.rows = 4;
  area.addEventListener("click", (event) => event.stopPropagation());

  const row = document.createElement("div");
  row.className = "editor-actions";

  const save = document.createElement("button");
  save.type = "button";
  save.className = "primary";
  save.textContent = "Save wording";
  save.addEventListener("click", async (event) => {
    event.stopPropagation();
    const text = area.value.trim();
    if (!text) {
      banner("A finding cannot be empty.", "refused");
      return;
    }
    const updated = await saveEdit(claim.id, text);
    if (updated) {
      run = updated;
      editingClaimId = null;
      render();
    }
  });

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "ghost";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", (event) => {
    event.stopPropagation();
    editingClaimId = null;
    render();
  });

  row.append(save, cancel);
  wrap.append(area, row);
  setTimeout(() => area.focus(), 0);
  return wrap;
}

function renderEvidence() {
  const container = byId("evidence-list");
  container.replaceChildren();

  const claim = selectedClaim();
  if (!claim) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Select a finding to see the source text it came from.";
    container.append(empty);
    return;
  }

  const items = (claim.evidence_ids ?? []).map(evidenceById).filter(Boolean);
  if (!items.length) {
    const empty = document.createElement("p");
    empty.className = "empty warn";
    empty.textContent =
      "No source passage is attached to this finding. Treat it as unverified.";
    container.append(empty);
    return;
  }

  items.forEach((item) => {
    const source = sourceById(item.source_id);
    const card = document.createElement("article");
    card.className = "evidence";

    const kind = document.createElement("span");
    kind.className = `tag type-${source?.information_type ?? "unknown"}`;
    kind.textContent = say(source?.information_type);

    const name = document.createElement("div");
    name.className = "evidence-source";
    name.textContent = source?.title ?? item.source_id;

    const quote = document.createElement("blockquote");
    quote.textContent = item.snippet;

    const where = document.createElement("div");
    where.className = "evidence-where";
    where.textContent = item.locator ?? "";

    card.append(kind, name, quote, where);

    if (source?.url) {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Open the original document";
      card.append(link);
    }
    container.append(card);
  });
}

async function ensureSectionOpen(step) {
  if (!step) return false;
  if (run.current_step_id === step.id) return true;

  const opened =
    run.mode === "rush"
      ? await api("/api/rush/open", { step_id: step.id })
      : await api("/api/guided/begin", { step_id: step.id });

  if (opened) {
    run = opened;
    return true;
  }
  return false;
}

function renderActions() {
  const bar = byId("actions");
  bar.replaceChildren();

  const step = currentStep();
  const claim = selectedClaim();
  const guided = run.mode === "guided";

  const add = (label, handler, className = "") => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = className;
    button.textContent = label;
    button.addEventListener("click", handler);
    bar.append(button);
    return button;
  };

  const addBuildBrief = () => {
    add("Build final brief", async () => {
      const updated = await api("/api/brief", {});
      if (updated) {
        run = updated;
        selectedStepId = null;
        selectedClaimId = null;
        showBrief();
      }
    }, "primary");
  };

  if (!step) {
    if (allContentReviewed()) addBuildBrief();
    return;
  }

  if (step.status === "needs_refresh") {
    add("Refresh this section", async () => {
      const updated = await api("/api/reanalysis/refresh", { step_id: step.id });
      if (updated) { run = updated; render(); }
    }, "primary");
    return;
  }

  if (claim) {
    add("Edit wording", () => {
      editingClaimId = claim.id;
      render();
    });

    add("Check this finding", async () => {
      if (!(await ensureSectionOpen(step))) return;
      const updated = await api("/api/guided/verify", { claim_id: claim.id });
      if (updated) { run = updated; render(); }
    });

    const alreadyFlagged = (step.human_review?.flagged_claim_ids ?? []).includes(claim.id);
    add(alreadyFlagged ? "Flagged" : "Flag a problem", async () => {
      if (alreadyFlagged) return;
      const note = window.prompt(
        "What is wrong with this finding? Add a short note, or leave it blank."
      );
      if (note === null) return;
      if (!(await ensureSectionOpen(step))) return;
      const updated = await api("/api/guided/flag", {
        claim_id: claim.id,
        note,
      });
      if (updated) { run = updated; render(); }
    });
  }

  if (guided) {
    add("Accept section and continue", async () => {
      const updated = await api("/api/guided/next", {});
      if (updated) {
        run = updated;
        selectedStepId = null;
        selectedClaimId = null;
        render();
      }
    }, "primary");
  } else {
    add("Check all and mark section reviewed", async () => {
      const updated = await api("/api/reanalysis/review", { step_id: step.id });
      if (updated) {
        run = updated;
        selectedStepId = step.id;
        render();
      }
    }, "primary");
  }

  if (allContentReviewed()) addBuildBrief();
}

async function saveEdit(claimId, text) {
  if (run.mode === "guided") {
    if (!(await ensureSectionOpen(currentStep()))) return null;
    return api("/api/guided/edit", { claim_id: claimId, text });
  }
  return api("/api/reanalysis/step", {
    step_id: currentStep().id,
    claim_id: claimId,
    text,
    human_edited: true,
  });
}

function showBrief() {
  const brief = steps().find((s) => s.kind === "draft_brief");
  byId("brief-text").textContent = brief?.ai_output ?? "(the brief is empty)";

  const content = contentSteps();
  const reviewed = content.filter((s) =>
    ["reviewed", "approved"].includes(s.human_review?.status)
  );
  const skipped = content.length - reviewed.length;

  const notice = byId("brief-notice");
  const approve = byId("approve-brief");

  if (run.final_review_status === "approved") {
    notice.textContent =
      "Analysis complete. You approved the final brief. You can copy the brief, go back to inspect the review, or choose Start over for another policy.";
    notice.hidden = false;
    approve.disabled = true;
    approve.textContent = "Approved";
  } else {
    approve.disabled = false;
    approve.textContent = "Approve final brief";
    if (skipped > 0) {
      notice.textContent =
        `This brief covers ${reviewed.length} of ${content.length} sections. ` +
        `${skipped} section${skipped === 1 ? " is" : "s are"} missing because ` +
        `you have not reviewed ${skipped === 1 ? "it" : "them"} yet.`;
      notice.hidden = false;
    } else {
      notice.hidden = true;
    }
  }

  byId("workspace").hidden = true;
  byId("brief-screen").hidden = false;
}

const PROVIDER_HELP = {
  deterministic:
    "Runs the built-in sample analysis. No credentials, no network calls, " +
    "useful for trying the review flow.",
  openrouter:
    "Needs an API key. Model and base URL fall back to sensible defaults if " +
    "you leave them blank.",
  openai: "Needs an API key and a model name.",
  foundry:
    "Needs the endpoint URL and a model, plus exactly one of an API key or a " +
    "bearer token. Do not fill in both.",
};

function syncProviderFields() {
  const kind = byId("provider-kind").value;
  document.querySelectorAll("[data-for]").forEach((field) => {
    const applies = field.dataset.for.split(" ").includes(kind);
    field.hidden = !applies;
  });
  byId("provider-help").textContent = PROVIDER_HELP[kind] ?? "";
}

async function saveProvider() {
  const kind = byId("provider-kind").value;
  const apiKey = byId("provider-key").value.trim();
  const bearer = byId("provider-bearer").value.trim();

  if (kind === "foundry" && Boolean(apiKey) === Boolean(bearer)) {
    banner(
      "Foundry needs exactly one credential: an API key or a bearer token, " +
        "not both and not neither.",
      "refused"
    );
    return;
  }

  const payload = {
    kind,
    model: byId("provider-model").value.trim(),
    base_url: byId("provider-base-url").value.trim(),
    endpoint: byId("provider-endpoint").value.trim(),
    api_key: apiKey,
    bearer_token: bearer,
    regulations_api_key: byId("regs-key").value.trim(),
  };

  const status = await api("/api/provider", payload);
  if (!status) return;

  const parts = [`Saved: ${status.kind}`];
  if (status.model) parts.push(status.model);
  if (status.has_api_key) parts.push("API key set");
  if (status.has_bearer_token) parts.push("bearer token set");
  if (status.has_regulations_api_key) parts.push("Regulations.gov key set");
  byId("provider-state").textContent = parts.join(" · ");
  banner("Settings saved. They stay in this server's memory only.", "info");
}

async function loadPolicy() {
  const documentNumber = byId("doc-number").value.trim();
  if (!documentNumber) {
    banner("Enter a Federal Register document number.", "refused");
    return;
  }
  banner(`Fetching and analyzing ${documentNumber}. This can take a minute.`);
  const updated = await api("/api/source/load", {
    document_number: documentNumber,
  });
  if (updated) {
    run = updated;
    selectedStepId = null;
    selectedClaimId = null;
    render();
  }
}

async function loadComments() {
  const docketId = byId("docket-id").value.trim();
  if (!docketId) {
    banner("Enter a Regulations.gov docket ID.", "refused");
    return;
  }
  banner(`Fetching comments from ${docketId}. This can take a minute.`);
  const updated = await api("/api/source/comments", {
    docket_id: docketId,
    max_comments: Number(byId("max-comments").value) || 12,
  });
  if (updated) {
    run = updated;
    render();
  }
}

async function start(mode) {
  const reset = await api("/api/reset", { mode });
  if (!reset) return;

  let started;
  if (mode === "rush") {
    const first = (reset.steps ?? []).find(
      (step) => !["verification", "draft_brief"].includes(step.kind)
    );
    started = first
      ? await api("/api/rush/open", { step_id: first.id })
      : reset;
  } else {
    started = await api("/api/guided/begin", {});
  }

  if (started) {
    run = started;
    selectedStepId = started.current_step_id ?? null;
    selectedClaimId = null;
    render();
  }
}

function boot() {
  byId("start-guided").addEventListener("click", () => start("guided"));
  byId("start-rush").addEventListener("click", () => start("rush"));

  byId("save-provider").addEventListener("click", saveProvider);
  byId("provider-kind").addEventListener("change", syncProviderFields);
  syncProviderFields();
  byId("load-policy").addEventListener("click", loadPolicy);
  byId("load-comments").addEventListener("click", loadComments);

  byId("restart").addEventListener("click", () => {
    run = null;
    selectedStepId = null;
    selectedClaimId = null;
    editingClaimId = null;
    byId("brief-screen").hidden = true;
    banner("");
    render();
  });

  byId("back-to-work").addEventListener("click", () => {
    byId("brief-screen").hidden = true;
    byId("workspace").hidden = false;
    selectedStepId = null;
    render();
  });

  byId("approve-brief").addEventListener("click", async () => {
    const updated = await api("/api/final/approve", {});
    if (updated) {
      run = updated;
      showBrief();
    }
  });

  byId("copy-brief").addEventListener("click", async () => {
    const text = byId("brief-text").textContent ?? "";
    try {
      await navigator.clipboard.writeText(text);
      banner("Final brief copied to the clipboard.");
    } catch (error) {
      banner("Could not copy the brief automatically. Select the text and copy it manually.", "refused");
    }
  });

  render();
}

document.addEventListener("DOMContentLoaded", boot);

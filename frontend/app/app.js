/*
 * PolicyTrace app.
 *
 * Talks to the backend over HTTP. There is no client-side copy of the review
 * rules: the server decides what is allowed, and a refusal is displayed rather
 * than prevented, because "the system would not let me approve unreviewed
 * work" is the thing worth showing.
 */

const API = "";
const CLIENT_ERROR_KEY = "policytrace-client-errors";

let run = null;
let selectedStepId = null;
let selectedClaimId = null;
let editingClaimId = null;
let flaggingClaimId = null;
let corpusStatus = null;
let policyStatus = null;
let revisionComparison = null;
let newsStatus = null;
let revisionFilter = "substantive";
let revisionVisibleCount = 25;
let reportView = "leadership";
let auditLogText = null;
let apiRequestInFlight = false;

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

function rememberClientError(message) {
  const errorId =
    `CLIENT-${Date.now().toString(36).toUpperCase()}-` +
    Math.random().toString(36).slice(2, 8).toUpperCase();
  const entry = {
    error_id: errorId,
    timestamp: new Date().toISOString(),
    message,
  };

  try {
    const existing = JSON.parse(localStorage.getItem(CLIENT_ERROR_KEY) || "[]");
    const items = Array.isArray(existing) ? existing : [];
    items.push(entry);
    localStorage.setItem(CLIENT_ERROR_KEY, JSON.stringify(items.slice(-50)));
  } catch (_error) {
    // Error tracking must never create a second user-facing error.
  }
  return errorId;
}

function recentClientErrors() {
  try {
    const value = JSON.parse(localStorage.getItem(CLIENT_ERROR_KEY) || "[]");
    return Array.isArray(value) ? value : [];
  } catch (_error) {
    return [];
  }
}

function banner(message, kind = "info") {
  const el = byId("banner");
  if (!message) {
    el.hidden = true;
    return;
  }

  let shown = message;
  if (kind === "refused" && !shown.includes("Error ID:")) {
    const errorId = rememberClientError(shown);
    shown = `${shown} Error ID: ${errorId}`;
  }

  el.textContent = shown;
  el.className = `banner ${kind}`;
  el.hidden = false;
}

async function api(path, payload) {
  const isWrite = payload !== undefined;
  if (isWrite && apiRequestInFlight) {
    banner("PolicyTrace is still working on the previous request. Please wait.", "info");
    return null;
  }

  if (isWrite) {
    apiRequestInFlight = true;
    document.body.classList.add("busy");
    byId("stage")?.setAttribute("aria-busy", "true");
  }

  try {
    const response = await fetch(`${API}${path}`, {
      method: payload === undefined ? "GET" : "POST",
      headers: { "Content-Type": "application/json" },
      body: payload === undefined ? undefined : JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok || data.error) {
      const errorId = data.error_id ? ` Error ID: ${data.error_id}` : "";
      banner(
        `${data.error || `Request failed (${response.status})`}${errorId}`,
        "refused"
      );
      return null;
    }
    banner("");
    return data.analysis ?? data;
  } catch (error) {
    banner(`Cannot reach the server: ${error.message}`, "refused");
    return null;
  } finally {
    if (isWrite) {
      apiRequestInFlight = false;
      document.body.classList.remove("busy");
      byId("stage")?.removeAttribute("aria-busy");
    }
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

/*
 * One line telling the reviewer what to do in this section. Without it the
 * screen is a wall of status words with no next action, which reads as stuck.
 */
function sectionGuidance(step) {
  if (step.status === "needs_refresh") {
    return "You changed something this section depends on. Refresh it before reviewing.";
  }

  const reviewed = ["reviewed", "approved"].includes(step.human_review?.status);
  if (reviewed) {
    const remaining = contentSteps().filter(
      (item) => !["reviewed", "approved"].includes(item.human_review?.status)
    );
    return remaining.length
      ? `Reviewed. ${remaining.length} section${remaining.length === 1 ? "" : "s"} left: pick one on the left.`
      : "Every section is reviewed. Build the final brief below.";
  }

  const flagged = (step.human_review?.flagged_claim_ids ?? []).length;
  if (flagged) {
    return `${flagged} finding${flagged === 1 ? " is" : "s are"} flagged. You can still mark this section reviewed; final approval will require the flag to be resolved or explicitly acknowledged.`;
  }

  return "Click a finding to see the source text behind it. When you are satisfied, mark the section reviewed.";
}

function stepDisplayStatus(step) {
  if (step.status === "needs_refresh") return step.status;
  return step.human_review?.status ?? step.status;
}

function flagReason(step, claimId) {
  const prefix = `Flagged ${claimId}: `;
  const notes = step?.human_review?.notes ?? [];
  for (let index = notes.length - 1; index >= 0; index -= 1) {
    if (notes[index].startsWith(prefix)) {
      return notes[index].slice(prefix.length).trim();
    }
  }
  return "";
}

function unresolvedFlagCount() {
  return contentSteps().reduce(
    (count, step) => count + (step.human_review?.flagged_claim_ids ?? []).length,
    0
  );
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

function renderComparisonPreview() {
  if (!revisionComparison?.available && !newsStatus?.available) return;

  byId("workspace").hidden = false;
  byId("review-columns").hidden = true;
  byId("review-actionbar").hidden = true;

  const from = revisionComparison?.from_document || {};
  byId("policy-title").textContent =
    from.title || policyStatus?.document_number || "Loaded policy";
  byId("policy-meta").textContent = [
    from.document_number ? `Federal Register ${from.document_number}` : "",
    revisionComparison?.to_document?.document_number
      ? `compared with ${revisionComparison.to_document.document_number}`
      : "",
  ].filter(Boolean).join(" · ");

  renderPolicyStatus();
  renderRevisionComparison();
  renderNewsStatus();
  renderCorpusStatus();
}

function render() {
  const started = Boolean(run);
  byId("start-screen").hidden = started;
  byId("workspace").hidden =
    !started && !revisionComparison?.available && !newsStatus?.available;
  byId("review-columns").hidden = !started;
  byId("review-actionbar").hidden = !started;
  if (!started) {
    byId("mode-pill").textContent =
      revisionComparison?.available || newsStatus?.available
        ? "sources ready"
        : "not started";
    if (revisionComparison?.available || newsStatus?.available) {
      renderComparisonPreview();
    }
    return;
  }

  byId("mode-pill").textContent =
    run.mode === "rush" ? "analyze then review" : "section by section";

  byId("policy-title").textContent = run.policy?.title ?? "Policy";
  const bits = [run.policy?.jurisdiction, run.policy?.version].filter(Boolean);
  byId("policy-meta").textContent = bits.join(" · ");
  byId("review-state").textContent = say(run.final_review_status);
  renderPolicyStatus();
  renderRevisionComparison();
  renderNewsStatus();
  renderCorpusStatus();

  renderSections();
  renderFindings();
  renderEvidence();
  renderActions();
}

function renderPolicyStatus() {
  const card = byId("policy-status-card");
  if (!card) return;

  if (!policyStatus || (!policyStatus.document_number && !policyStatus.rin)) {
    card.hidden = true;
    return;
  }

  card.hidden = false;
  const metrics = byId("policy-status-metrics");
  metrics.replaceChildren(
    metric("source document", policyStatus.document_number || "—"),
    metric("document type", policyStatus.document_type || "—"),
    metric("source date", policyStatus.source_publication_date || "—"),
    metric("RIN", policyStatus.rin || "—")
  );

  const warning = byId("policy-status-warning");
  const health = byId("policy-status-health");
  if (!policyStatus.available) {
    health.textContent = "status check unavailable";
    health.className = "pill corpus-gap";
    warning.textContent = policyStatus.freshness_message || "";
  } else if (policyStatus.later_material_action_found) {
    health.textContent = "later action found";
    health.className = "pill status-later";
    warning.textContent = policyStatus.freshness_message || "";
  } else {
    health.textContent = "status checked";
    health.className = "pill corpus-ok";
    warning.textContent = policyStatus.freshness_message || "";
  }

  const laterFr = policyStatus.later_federal_register_documents || [];
  const allFr = policyStatus.federal_register_documents || [];
  const detail = [
    policyStatus.status_label ? `Status: ${policyStatus.status_label}` : "",
    policyStatus.agenda_stage ? `Agenda stage: ${policyStatus.agenda_stage}` : "",
    policyStatus.rin_status ? `RIN status: ${policyStatus.rin_status}` : "",
    `Federal Register matches for RIN: ${allFr.length}`,
    `Later Federal Register documents: ${laterFr.length}`,
    policyStatus.checked_at ? `Checked: ${policyStatus.checked_at}` : "",
  ].filter(Boolean);
  byId("policy-status-detail").textContent = detail.join(" · ");

  const link = byId("policy-status-link");
  if (policyStatus.source_url) {
    link.href = policyStatus.source_url;
    link.hidden = false;
  } else {
    link.hidden = true;
  }
}

async function refreshPolicyStatus() {
  const status = await api("/api/source/policy/status");
  if (!status) return null;
  policyStatus = status;
  if (run) renderPolicyStatus();
  return status;
}

function shortText(value, max = 240) {
  const text = String(value || "").replace(/\s+/g, " ").trim();
  return text.length > max ? `${text.slice(0, max - 1)}…` : text;
}

function revisionLooksLikeHeaderNoise(change) {
  const text = `${change.before_text || ""} ${change.after_text || ""}`
    .replace(/\s+/g, " ")
    .trim();
  if (!text) return false;

  const patterns = [
    /^Federal Register,? Volume \d+/i,
    /^\[?Federal Register Volume \d+/i,
    /^Vol\.\s*\d+$/i,
    /^No\.\s*\d+$/i,
    /^\[?Page\s+\d+\]?$/i,
    /^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),?$/i,
    /^(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}$/i,
    /^Part\s+[IVXLC]+$/i,
  ];
  return patterns.some((pattern) => pattern.test(text));
}

function revisionMatchesFilter(change) {
  if (revisionFilter === "all") return true;
  if (revisionFilter === "substantive") return !revisionLooksLikeHeaderNoise(change);
  if (revisionFilter === "threshold") {
    return (change.tags || []).includes("threshold/number");
  }
  if (revisionFilter === "date") {
    return (change.tags || []).includes("deadline/date");
  }
  if (revisionFilter === "stakeholder") {
    return (change.tags || []).includes("stakeholder-scope language");
  }
  if (revisionFilter === "text") {
    return (change.tags || []).includes("text");
  }
  return true;
}

function revisionSortKey(change) {
  if (revisionLooksLikeHeaderNoise(change)) return 9;
  if ((change.potentially_affected_claim_ids || []).length) return 0;
  if ((change.tags || []).includes("threshold/number")) return 1;
  if ((change.tags || []).includes("deadline/date")) return 2;
  if ((change.tags || []).includes("stakeholder-scope language")) return 3;
  if (change.kind === "changed") return 4;
  if (change.kind === "removed") return 5;
  return 6;
}

function renderRevisionComparison() {
  const card = byId("revision-card");
  if (!card) return;
  if (!revisionComparison?.available) {
    card.hidden = true;
    return;
  }

  card.hidden = false;
  const from = revisionComparison.from_document || {};
  const to = revisionComparison.to_document || {};
  byId("revision-metrics").replaceChildren(
    metric("changed", revisionComparison.changed_count || 0),
    metric("added", revisionComparison.added_count || 0),
    metric("removed", revisionComparison.removed_count || 0),
    metric(
      "claims may need refresh",
      (revisionComparison.potentially_affected_claim_ids || []).length
    ),
    metric(
      "comparison time",
      revisionComparison.comparison_seconds == null
        ? "—"
        : `${revisionComparison.comparison_seconds}s`
    ),
    metric(
      "document units",
      `${revisionComparison.from_unit_count || 0} → ${revisionComparison.to_unit_count || 0}`
    )
  );

  const health = byId("revision-health");
  const affected = revisionComparison.potentially_affected_claim_ids || [];
  health.textContent = affected.length
    ? "review existing findings"
    : "comparison ready";
  health.className = `pill ${affected.length ? "corpus-gap" : "corpus-ok"}`;

  byId("revision-warning").textContent = revisionComparison.warning || "";
  const shared = revisionComparison.shared_rins || [];
  const tags = Object.entries(revisionComparison.tag_counts || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${key}: ${value}`)
    .join(" · ");
  byId("revision-detail").textContent = [
    `${from.document_number || "?"} → ${to.document_number || "?"}`,
    shared.length ? `Shared RIN: ${shared.join(", ")}` : "Shared RIN not confirmed",
    tags ? `Change flags: ${tags}` : "",
    affected.length ? `May need refresh: ${affected.join(", ")}` : "",
  ].filter(Boolean).join(" · ");

  const allChanges = [...(revisionComparison.changes || [])]
    .sort((a, b) => {
      const rank = revisionSortKey(a) - revisionSortKey(b);
      if (rank !== 0) return rank;
      return String(a.id || "").localeCompare(String(b.id || ""));
    });
  const filteredChanges = allChanges.filter(revisionMatchesFilter);
  const visibleChanges = filteredChanges.slice(0, revisionVisibleCount);

  const shown = byId("revision-shown");
  shown.textContent =
    `Showing ${visibleChanges.length} of ${filteredChanges.length} matching changes` +
    (revisionFilter === "substantive"
      ? " · obvious Federal Register header metadata hidden"
      : "");

  for (const button of document.querySelectorAll("[data-revision-filter]")) {
    button.classList.toggle(
      "active",
      button.dataset.revisionFilter === revisionFilter
    );
  }

  const list = byId("revision-changes");
  list.replaceChildren();
  for (const change of visibleChanges) {
    const item = document.createElement("details");
    item.className = "revision-change";
    const summary = document.createElement("summary");
    summary.textContent =
      `${say(change.kind)} · ${(change.tags || []).join(", ")}` +
      `${change.potentially_affected_claim_ids?.length
        ? ` · refresh: ${change.potentially_affected_claim_ids.join(", ")}`
        : ""}`;
    item.append(summary);

    if (change.before_text) {
      const before = document.createElement("p");
      before.className = "revision-before";
      before.textContent = `Before: ${shortText(change.before_text)}`;
      item.append(before);
    }
    if (change.after_text) {
      const after = document.createElement("p");
      after.className = "revision-after";
      after.textContent = `After: ${shortText(change.after_text)}`;
      item.append(after);
    }

    const links = document.createElement("p");
    links.className = "muted small";
    if (change.before_url) {
      const link = document.createElement("a");
      link.href = change.before_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Older source";
      links.append(link);
    }
    if (change.after_url) {
      if (links.childNodes.length) links.append(" · ");
      const link = document.createElement("a");
      link.href = change.after_url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Newer source";
      links.append(link);
    }
    item.append(links);
    list.append(item);
  }

  const more = byId("revision-show-more");
  more.hidden = revisionVisibleCount >= filteredChanges.length;
  more.textContent = more.hidden
    ? "Show more"
    : `Show 25 more (${filteredChanges.length - revisionVisibleCount} remaining)`;
}

async function refreshRevisionComparison() {
  const data = await api("/api/revision-comparison");
  if (!data) return null;
  revisionComparison = data;
  if (run) renderRevisionComparison();
  return data;
}

async function compareRevision() {
  const documentNumber = byId("revision-doc-number").value.trim();
  if (!documentNumber) {
    banner("Enter a second Federal Register document number.", "refused");
    return;
  }
  banner(`Comparing the loaded policy with ${documentNumber}.`);
  const data = await api("/api/revision-compare", {
    document_number: documentNumber,
  });
  if (!data) return;
  revisionComparison = data;
  revisionFilter = "substantive";
  revisionVisibleCount = 25;
  if (run) {
    renderRevisionComparison();
  } else {
    renderComparisonPreview();
  }
  banner("Revision comparison ready. Review changed language and refresh flags.", "info");
}

function renderNewsStatus() {
  const card = byId("news-card");
  if (!card) return;
  if (!newsStatus?.available) {
    card.hidden = true;
    return;
  }

  card.hidden = false;
  const sources = newsStatus.sources || [];
  byId("news-health").textContent = sources.length
    ? "factual-reporting pointers found"
    : "no recent coverage found";
  byId("news-health").className =
    `pill ${sources.length ? "corpus-ok" : "corpus-gap"}`;

  byId("news-metrics").replaceChildren(
    metric("articles", sources.length),
    metric("provider", newsStatus.provider || "GDELT"),
    metric("window start", newsStatus.window_start || "—"),
    metric("window end", newsStatus.window_end || "—")
  );
  byId("news-warning").textContent = newsStatus.limitation || "";
  const attempts = (newsStatus.provider_attempts || [])
    .map((attempt) => `${attempt.provider}: ${attempt.status} — ${attempt.detail}`)
    .join(" · ");
  byId("news-detail").textContent = [
    `Query: ${newsStatus.query || "—"}`,
    newsStatus.checked_at ? `Checked: ${newsStatus.checked_at}` : "",
    attempts ? `Provider path: ${attempts}` : "",
  ].filter(Boolean).join(" · ");

  const list = byId("news-list");
  list.replaceChildren();
  for (const source of sources) {
    const item = document.createElement("article");
    item.className = "news-item";

    const tag = document.createElement("span");
    tag.className = "tag type-factual_reporting";
    tag.textContent = "factual reporting";

    const title = document.createElement("strong");
    title.textContent = source.title || "Untitled article";

    const meta = document.createElement("p");
    meta.className = "muted small";
    meta.textContent = [
      source.agency || "",
      source.published_at || "",
    ].filter(Boolean).join(" · ");

    item.append(tag, title, meta);
    if (source.url) {
      const link = document.createElement("a");
      link.href = source.url;
      link.target = "_blank";
      link.rel = "noopener";
      link.textContent = "Open original article";
      item.append(link);

      const archive = document.createElement("a");
      archive.href = `https://web.archive.org/web/*/${source.url}`;
      archive.target = "_blank";
      archive.rel = "noopener";
      archive.textContent = "View archive history";
      item.append(" · ", archive);
    }
    list.append(item);
  }
}

async function refreshNewsStatus() {
  const data = await api("/api/news/status");
  if (!data) return null;
  newsStatus = data;
  if (run) renderNewsStatus();
  return data;
}

async function discoverNews() {
  const query = byId("news-query").value.trim();
  const maxArticles = Number(byId("max-news").value || 8);
  banner("Searching historical and recent factual-reporting sources.");
  const data = await api("/api/news", {
    query,
    max_articles: maxArticles,
  });
  if (!data) return;
  newsStatus = data;
  if (run) {
    renderNewsStatus();
  } else {
    renderComparisonPreview();
  }
  const count = (data.sources || []).length;
  banner(
    count
      ? `Found ${count} factual-reporting source pointer${count === 1 ? "" : "s"}.`
      : "No related reporting was returned by the available discovery sources.",
    "info"
  );
}

function metric(label, value) {
  const item = document.createElement("div");
  item.className = "corpus-metric";

  const number = document.createElement("strong");
  number.textContent = String(value ?? "—");

  const name = document.createElement("span");
  name.textContent = label;

  item.append(number, name);
  return item;
}

function renderCorpusStatus() {
  const card = byId("corpus-card");
  if (!card) return;

  if (!corpusStatus?.available) {
    card.hidden = true;
    return;
  }

  card.hidden = false;
  const metrics = byId("corpus-metrics");
  metrics.replaceChildren(
    metric("requested", corpusStatus.requested_count),
    metric("retrieved", corpusStatus.retrieved_count),
    metric("analyzed", corpusStatus.analyzed_source_count),
    metric("exact-text clusters", corpusStatus.exact_text_cluster_count),
    metric("retrieval failures", corpusStatus.failed_retrieval_count)
  );

  const hasGap =
    Number(corpusStatus.failed_retrieval_count || 0) > 0 ||
    Number(corpusStatus.unusable_retrieval_count || 0) > 0 ||
    Number(corpusStatus.degraded_source_count || 0) > 0;
  const health = byId("corpus-health");
  health.textContent = hasGap ? "corpus has disclosed gaps" : "retrieval complete";
  health.className = `pill ${hasGap ? "corpus-gap" : "corpus-ok"}`;

  byId("corpus-warning").textContent =
    corpusStatus.representativeness_warning || "";

  const types = Object.entries(corpusStatus.source_type_counts || {})
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => `${say(key)}: ${value}`)
    .join(" · ");

  const details = [
    corpusStatus.docket_id ? `Docket: ${corpusStatus.docket_id}` : "",
    `Unusable retrieved: ${corpusStatus.unusable_retrieval_count || 0}`,
    `PII-pattern redactions: ${corpusStatus.pii_redacted_count || 0}`,
    `Degraded source records: ${corpusStatus.degraded_source_count || 0}`,
    `Degraded attachments: ${corpusStatus.degraded_attachment_count || 0}`,
    types ? `Source types: ${types}` : "",
  ].filter(Boolean);
  byId("corpus-detail").textContent = details.join(" · ");
}

async function refreshCorpusStatus() {
  const status = await api("/api/source/comments/status");
  if (!status) return null;
  corpusStatus = status;
  if (run) renderCorpusStatus();
  return status;
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
      flaggingClaimId = null;
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
  const display = step ? stepDisplayStatus(step) : "";
  statusPill.textContent = step ? say(display) : "";
  statusPill.className = `pill ${display}`;

  byId("section-note").textContent = step ? sectionGuidance(step) : "";

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

  if (claim.id === flaggingClaimId) {
    card.append(renderFlagEditor(claim));
  }

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

  if (flagged) {
    const reviewerNote = document.createElement("p");
    reviewerNote.className = "claim-note";
    reviewerNote.textContent =
      `Reviewer flag: ${flagReason(step, claim.id) || "Reason not recorded."}`;
    card.append(reviewerNote);
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

function renderFlagEditor(claim) {
  const wrap = document.createElement("div");
  wrap.className = "editor";

  const area = document.createElement("textarea");
  area.rows = 3;
  area.placeholder = "Explain what is wrong with this finding.";
  area.addEventListener("click", (event) => event.stopPropagation());

  const row = document.createElement("div");
  row.className = "editor-actions";

  const save = document.createElement("button");
  save.type = "button";
  save.className = "primary";
  save.textContent = "Save flag";
  save.addEventListener("click", async (event) => {
    event.stopPropagation();
    const note = area.value.trim();
    if (!note) {
      banner("Explain what is wrong before flagging this finding.", "refused");
      return;
    }
    if (!(await ensureSectionOpen(currentStep()))) return;
    const updated = await api("/api/guided/flag", {
      claim_id: claim.id,
      note,
    });
    if (updated) {
      run = updated;
      flaggingClaimId = null;
      render();
    }
  });

  const cancel = document.createElement("button");
  cancel.type = "button";
  cancel.className = "ghost";
  cancel.textContent = "Cancel";
  cancel.addEventListener("click", (event) => {
    event.stopPropagation();
    flaggingClaimId = null;
    render();
  });

  row.append(save, cancel);
  wrap.append(area, row);
  setTimeout(() => area.focus(), 0);
  return wrap;
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
        reportView = "leadership";
        auditLogText = null;
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
      flaggingClaimId = null;
      editingClaimId = claim.id;
      render();
    });

    add("Check this finding", async () => {
      if (!(await ensureSectionOpen(step))) return;
      const updated = await api("/api/guided/verify", { claim_id: claim.id });
      if (updated) { run = updated; render(); }
    });

    const alreadyFlagged = (step.human_review?.flagged_claim_ids ?? []).includes(claim.id);
    const flagButton = add(alreadyFlagged ? "Flagged" : "Flag a problem", () => {
      if (alreadyFlagged) return;
      editingClaimId = null;
      flaggingClaimId = claim.id;
      render();
    });
    flagButton.disabled = alreadyFlagged;
  }

  if (guided) {
    const reviewed = ["reviewed", "approved"].includes(step.human_review?.status);
    if (!(reviewed && allContentReviewed())) {
      add("Accept section and continue", async () => {
        const updated = await api("/api/guided/next", {});
        if (updated) {
          run = updated;
          selectedStepId = null;
          selectedClaimId = null;
          render();
        }
      }, "primary");
    }
  } else {
    add("Check all and mark section reviewed", async () => {
      const updated = await api("/api/reanalysis/review", { step_id: step.id });
      if (updated) {
        run = updated;
        const next = contentSteps().find(
          (item) =>
            item.id !== step.id &&
            !["reviewed", "approved"].includes(item.human_review?.status)
        );
        selectedClaimId = null;
        editingClaimId = null;
        flaggingClaimId = null;
        if (next) {
          selectedStepId = next.id;
          await ensureSectionOpen(next);
        } else {
          selectedStepId = step.id;
        }
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

function leadershipReportText() {
  const brief = steps().find((s) => s.kind === "draft_brief");
  return brief?.ai_output ?? "(the leadership report is empty)";
}

function renderFinalOutput() {
  const audit = reportView === "audit";
  byId("report-title").textContent =
    audit ? "Evidence Audit Log" : "Leadership Report";
  byId("report-description").textContent = audit
    ? "The receipt layer: every reviewed claim, verification state, reviewer action, and exact stored evidence passage."
    : "A concise leadership-facing report assembled only from reviewed, evidence-backed findings. Claim IDs link every line to the audit log.";
  byId("brief-text").textContent = audit
    ? (auditLogText ?? "Loading the evidence audit log…")
    : leadershipReportText();

  byId("show-leadership").classList.toggle("active", !audit);
  byId("show-audit").classList.toggle("active", audit);
  byId("copy-brief").textContent = audit ? "Copy audit log" : "Copy report";
  byId("approve-brief").hidden = audit;
}

async function showAuditLog() {
  const data = await api("/api/audit-log");
  if (!data?.text) return;
  auditLogText = data.text;
  reportView = "audit";
  renderFinalOutput();
}

function showBrief() {
  const content = contentSteps();
  const reviewed = content.filter((s) =>
    ["reviewed", "approved"].includes(s.human_review?.status)
  );
  const skipped = content.length - reviewed.length;

  const notice = byId("brief-notice");
  const approve = byId("approve-brief");
  const flagged = unresolvedFlagCount();

  if (run.final_review_status === "approved") {
    notice.textContent =
      "Analysis complete. You approved the leadership report. The Evidence Audit Log remains available as the traceable receipt layer.";
    notice.hidden = false;
    approve.disabled = true;
    approve.textContent = "Approved";
  } else {
    approve.disabled = false;
    approve.textContent =
      flagged > 0
        ? "Approve report with unresolved flags…"
        : "Approve leadership report";
    if (skipped > 0) {
      notice.textContent =
        `This report covers ${reviewed.length} of ${content.length} sections. ` +
        `${skipped} section${skipped === 1 ? " is" : "s are"} missing because ` +
        `you have not reviewed ${skipped === 1 ? "it" : "them"} yet.`;
      notice.hidden = false;
    } else if (flagged > 0) {
      notice.textContent =
        `There ${flagged === 1 ? "is" : "are"} ${flagged} unresolved reviewer flag` +
        `${flagged === 1 ? "" : "s"}. Flagged findings are withheld from the leadership report and preserved in the Evidence Audit Log. ` +
        "Final approval requires an explicit acknowledgement.";
      notice.hidden = false;
    } else {
      notice.hidden = true;
    }
  }

  renderFinalOutput();
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
    media_cloud_api_key: byId("mediacloud-key").value.trim(),
  };

  const status = await api("/api/provider", payload);
  if (!status) return;

  const parts = [`Saved: ${status.kind}`];
  if (status.model) parts.push(status.model);
  if (status.has_api_key) parts.push("API key set");
  if (status.has_bearer_token) parts.push("bearer token set");
  if (status.has_regulations_api_key) parts.push("Regulations.gov key set");
  if (status.has_media_cloud_api_key) parts.push("Media Cloud key set");
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
    run = null;
    selectedStepId = null;
    selectedClaimId = null;
    editingClaimId = null;
    flaggingClaimId = null;
    corpusStatus = null;
    revisionComparison = null;
    newsStatus = null;
    policyStatus = await refreshPolicyStatus();
    const title = updated.policy?.title || documentNumber;
    byId("source-state").textContent =
      `Policy ready: ${title}. Load public comments if you want them, then choose a review mode above.`;
    byId("mode-pill").textContent = "ready to choose";
    banner("Live policy loaded. Choose Guided or Rush when your sources are ready.", "info");
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
    run = null;
    selectedStepId = null;
    selectedClaimId = null;
    editingClaimId = null;
    flaggingClaimId = null;
    const count = Number(byId("max-comments").value) || 12;
    const status = await refreshCorpusStatus();
    const retrieved = status?.retrieved_count ?? "unknown";
    const failures = status?.failed_retrieval_count ?? 0;
    byId("source-state").textContent =
      `Policy and public comments are ready: ${retrieved} retrieved from up to ${count} requested` +
      `${failures ? `, with ${failures} disclosed retrieval failure${failures === 1 ? "" : "s"}` : ""}. ` +
      "Choose Guided or Rush above.";
    byId("mode-pill").textContent = "ready to choose";
    banner("Live comments analyzed. Corpus limits are tracked for review.", "info");
  }
}

async function showRecentErrors() {
  let serverErrors = [];
  let logFile = ".policytrace/errors.jsonl";

  try {
    const response = await fetch(`${API}/api/errors`);
    const data = await response.json();
    if (response.ok) {
      serverErrors = Array.isArray(data.errors) ? data.errors : [];
      logFile = data.log_file || logFile;
    }
  } catch (_error) {
    // The local browser log below is still useful when the server is down.
  }

  const combined = [
    ...serverErrors.map((entry) => ({ ...entry, source: "server" })),
    ...recentClientErrors().map((entry) => ({ ...entry, source: "browser" })),
  ]
    .sort((a, b) => String(b.timestamp).localeCompare(String(a.timestamp)))
    .slice(0, 50);

  const lines = combined.length
    ? combined.map((entry) => {
        const route = entry.path ? ` ${entry.method || ""} ${entry.path}` : "";
        const status = entry.status ? ` [${entry.status}]` : "";
        const type = entry.error_type ? ` ${entry.error_type}` : "";
        return (
          `${entry.timestamp || ""}  ${entry.error_id || "unknown"}${status}${type}${route}\n` +
          `${entry.message || ""}`
        );
      })
    : ["No errors have been recorded yet."];

  byId("error-log-text").textContent = lines.join("\n\n");
  byId("error-log-file").textContent =
    `Server log: ${logFile} · Browser-only errors are kept in this Opera profile.`;
  byId("error-dialog").showModal();
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
    if (!policyStatus) await refreshPolicyStatus();
    if (!revisionComparison) await refreshRevisionComparison();
    if (!newsStatus) await refreshNewsStatus();
    if (!corpusStatus) await refreshCorpusStatus();
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
  byId("compare-revision").addEventListener("click", compareRevision);
  byId("discover-news").addEventListener("click", discoverNews);
  for (const button of document.querySelectorAll("[data-revision-filter]")) {
    button.addEventListener("click", () => {
      revisionFilter = button.dataset.revisionFilter || "substantive";
      revisionVisibleCount = 25;
      renderRevisionComparison();
    });
  }
  byId("revision-show-more").addEventListener("click", () => {
    revisionVisibleCount += 25;
    renderRevisionComparison();
  });
  byId("load-comments").addEventListener("click", loadComments);
  byId("recent-errors").addEventListener("click", showRecentErrors);
  byId("close-errors").addEventListener("click", () => {
    byId("error-dialog").close();
  });

  byId("restart").addEventListener("click", () => {
    run = null;
    selectedStepId = null;
    selectedClaimId = null;
    editingClaimId = null;
    flaggingClaimId = null;
    corpusStatus = null;
    policyStatus = null;
    revisionComparison = null;
    newsStatus = null;
    revisionFilter = "substantive";
    revisionVisibleCount = 25;
    reportView = "leadership";
    auditLogText = null;
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

  byId("show-leadership").addEventListener("click", () => {
    reportView = "leadership";
    renderFinalOutput();
  });

  byId("show-audit").addEventListener("click", showAuditLog);

  byId("approve-brief").addEventListener("click", async () => {
    const flagged = unresolvedFlagCount();
    let acknowledgeFlags = false;
    if (flagged > 0) {
      acknowledgeFlags = window.confirm(
        `There are ${flagged} unresolved reviewer flag` +
          `${flagged === 1 ? "" : "s"}. Approve anyway and record that override?`
      );
      if (!acknowledgeFlags) return;
    }

    const updated = await api("/api/final/approve", {
      acknowledge_flags: acknowledgeFlags,
    });
    if (updated) {
      run = updated;
      auditLogText = null;
      reportView = "leadership";
      showBrief();
    }
  });

  byId("copy-brief").addEventListener("click", async () => {
    const text = byId("brief-text").textContent ?? "";
    try {
      await navigator.clipboard.writeText(text);
      banner(
        reportView === "audit"
          ? "Evidence Audit Log copied to the clipboard."
          : "Leadership Report copied to the clipboard."
      );
    } catch (error) {
      banner("Could not copy this output automatically. Select the text and copy it manually.", "refused");
    }
  });

  render();
}

document.addEventListener("DOMContentLoaded", boot);

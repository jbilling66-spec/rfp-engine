/* The thin client (B37/D3): the SERVER decides status, this file only
   renders what it is handed. esc() wraps EVERY interpolation — model
   text especially. Polling: 2s on the job strip while a job runs. */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));

const STAGE_COLOR = {
  intake: "plan", research: "plan", gate_1: "draft", planning: "plan",
  gate_2: "draft", drafting: "draft", validation: "draft",
  review: "done", declined: "stop",
  // W2a (B134): gate_0 is a stage; corrupt is the server's override —
  // an unknown key fell through to plan-blue, so both read as healthy
  gate_0: "draft", corrupt: "stop",
};
// the run footer's own vocabulary (run-log schema): a waiting run is
// amber, an open one blue, anything else red; completed is not shown
const RUN_COLOR = { in_flight: "plan", awaiting_gate: "draft",
  awaiting_gap: "draft", failed: "stop", aborted: "stop", corrupt: "stop" };
// P30a (B139): the nine stations the stage track draws — pinned equal to
// the server's PIPELINE by a contract test; position and sort come from
// the server's stage_n, this list only names the segments
const STAGE_ORDER = ["intake", "gate_0", "research", "gate_1", "planning",
  "gate_2", "drafting", "validation", "review"];

function stageTrack(stage, labeled) {
  // from the CURRENT stage only — a replanned pursuit honestly reads
  // "drafting" again; declined / corrupt draw nothing (the stop chip)
  const at = STAGE_ORDER.indexOf(stage);
  if (at < 0) return "";
  const segs = STAGE_ORDER.map((name, i) => {
    const state = i < at ? "done" : (i === at ? "current" : "todo");
    return `<span class="seg" data-state="${state}"><span class="lbl">${esc(name)}</span></span>`;
  }).join("");
  const cls = labeled ? "track labeled" : "track";
  return `<div class="${cls}" role="img" aria-label="stage ${at + 1} of ${STAGE_ORDER.length}: ${esc(stage)}">${segs}</div>`;
}

let OPERATOR = null;
let OPERATOR_ROLE = null;  // the session's role — the server records it,
                          // the shell never sends one (P27, M-9)
let JOB_TIMER = null;

// W2a (B134): one typed error for every door — the status decides what
// the shell does (401 → sign in again), the detail is what it says
class ApiError extends Error {
  constructor(status, detail) { super(detail); this.status = status; }
}

async function api(path, opts = {}) {
  // raw: a file body goes as the browser types it — no JSON header
  const { raw, ...rest } = opts;
  const res = await fetch(path, {
    headers: raw ? {} : { "Content-Type": "application/json" },
    ...rest,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.detail || `${res.status} on ${path}`);
  }
  return res.json();
}

function toast(msg, sticky = false) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("sticky", sticky);
  t.hidden = false;
  if (!sticky) setTimeout(() => { t.hidden = true; }, 3200);
  else t.onclick = () => { t.hidden = true; };
}

// -- dialogs (W2a, B134) ---------------------------------------------------
// One opener and one closer own focus: the element that opened a dialog
// gets it back on close; Tab stays inside; Esc closes — except the
// sign-in dialog, which is required (nothing to go back to).

const FOCUSABLE = 'button:not([disabled]),input:not([disabled]):not([hidden]),'
  + 'select:not([disabled]),textarea:not([disabled]),a[href],[tabindex]:not([tabindex="-1"])';
let DIALOG_RETURN = null;

function openDialog(id) {
  const ov = $(id);
  if (!ov.hidden) return;
  DIALOG_RETURN = document.activeElement;
  ov.hidden = false;
  const first = ov.querySelector(FOCUSABLE);
  if (first) first.focus();
}

function closeDialog(id) {
  const ov = $(id);
  ov.hidden = true;
  if (DIALOG_RETURN && typeof DIALOG_RETURN.focus === "function") DIALOG_RETURN.focus();
  DIALOG_RETURN = null;
}

document.addEventListener("keydown", (e) => {
  const ov = Array.from(document.querySelectorAll(".overlay")).find((o) => !o.hidden);
  if (!ov) return;
  if (e.key === "Escape") {
    if (ov.id === "opOverlay") return;
    e.preventDefault(); closeDialog(ov.id); return;
  }
  if (e.key !== "Tab") return;
  const items = Array.from(ov.querySelectorAll(FOCUSABLE))
    .filter((x) => x.offsetParent !== null);
  if (!items.length) { e.preventDefault(); return; }
  const first = items[0], last = items[items.length - 1];
  const at = document.activeElement;
  if (!ov.contains(at)) { e.preventDefault(); first.focus(); }
  else if (e.shiftKey && at === first) { e.preventDefault(); last.focus(); }
  else if (!e.shiftKey && at === last) { e.preventDefault(); first.focus(); }
});

// -- session ---------------------------------------------------------------

async function bootSession() {
  const s = await api("/api/session");
  OPERATOR = s.operator;
  OPERATOR_ROLE = s.role;
  ROUTE_TARGETS = s.roles || [];
  // the declarable roles come from the server — one copy of the enum;
  // nothing preselected: the blank option is the human's to leave
  $("opRole").innerHTML = '<option value="">— choose your role —</option>'
    + (s.roles || []).map((r) =>
      `<option value="${esc(r)}">${esc(r.replace(/_/g, " "))}</option>`).join("");
  renderWho();
  if (!OPERATOR) openDialog("opOverlay");
  await resumeJobs();
}

function renderWho() {
  $("whoName").textContent = OPERATOR || "not signed in";
  $("whoRole").textContent = OPERATOR_ROLE
    ? OPERATOR_ROLE.replace(/_/g, " ") : "";
  $("signInBtn").hidden = Boolean(OPERATOR);
}

$("signInBtn").onclick = () => { openDialog("opOverlay"); };
$("opGo").onclick = async () => {
  try {
    const out = await api("/api/session", {
      method: "POST", body: JSON.stringify({ name: $("opName").value,
                                             role: $("opRole").value }),
    });
    OPERATOR = out.operator;
    OPERATOR_ROLE = out.role;
    renderWho();
    closeDialog("opOverlay");
  } catch (e) { toast(e.message); }
};

// -- effort (P27 wave 1, D13): one active clock per screen -----------------
// Foreground, focused time with a decision screen open: paused while the
// tab is hidden or the window blurred, cut after 90 s without input (the
// schema's own idle figure). Gate decisions carry BOTH figures — the
// measured active_ms and the human's confirmed_minutes, prefilled from it
// (accepting the default is one click); leaving the review surface posts
// a passive review_session. The role is the session's: nothing here
// names one. Estimated, and labeled so wherever displayed.

const IDLE_MS = 90000;
const CLOCK = { start: null, banked: 0, lastInput: 0, running: false };
let REVIEW_PID = null;       // the pursuit whose review surface is open
let MINUTES_TIMER = null;

function clockStart() {
  CLOCK.banked = 0; CLOCK.start = Date.now();
  CLOCK.lastInput = Date.now(); CLOCK.running = true;
}
function clockPause() {
  if (!CLOCK.running) return;
  CLOCK.banked += Date.now() - CLOCK.start; CLOCK.running = false;
}
function clockResume() {
  if (CLOCK.running || CLOCK.start === null) return;
  CLOCK.start = Date.now(); CLOCK.lastInput = Date.now(); CLOCK.running = true;
}
function clockActiveMs() {
  return Math.round(CLOCK.banked
    + (CLOCK.running ? Date.now() - CLOCK.start : 0));
}
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState === "hidden") clockPause(); else clockResume();
});
window.addEventListener("blur", clockPause);
window.addEventListener("focus", clockResume);
for (const ev of ["keydown", "pointerdown", "input"]) {
  document.addEventListener(ev, () => { CLOCK.lastInput = Date.now();
                                        clockResume(); }, true);
}
setInterval(() => {
  if (CLOCK.running && Date.now() - CLOCK.lastInput > IDLE_MS) clockPause();
}, 5000);

function gateClockOpen(minutesId) {
  // the field shows the running figure as its placeholder; a typed value
  // is the human's number and is never overwritten
  clockStart();
  const field = $(minutesId);
  field.value = "";
  clearInterval(MINUTES_TIMER);
  MINUTES_TIMER = setInterval(() => {
    field.placeholder = String(Math.round(clockActiveMs() / 60000));
  }, 10000);
}

function gateEffort(minutesId) {
  clearInterval(MINUTES_TIMER);
  const ms = clockActiveMs();
  const typed = $(minutesId).value;
  return { active_ms: ms,
           confirmed_minutes: typed === "" ? Math.round(ms / 60000)
                                           : Math.max(0, Math.round(Number(typed))) };
}

function flushReviewEffort() {
  // passive: the measured span only, posted when the reviewer leaves;
  // sub-5-second visits are not sessions
  if (!REVIEW_PID) return;
  const pid = REVIEW_PID;
  REVIEW_PID = null;
  const ms = clockActiveMs();
  clockPause();
  if (ms < 5000) return;
  fetch(`/api/pursuits/${encodeURIComponent(pid)}/effort`, {
    method: "POST", keepalive: true,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ measurement: "passive", active_ms: ms,
                           scope: "pursuit", gate: "review_loop" }),
  }).catch(() => {});
}
window.addEventListener("pagehide", flushReviewEffort);

// -- board -----------------------------------------------------------------

// P30a 5 (B139): the board keeps the server's rows and re-renders on sort
// or filter. Order is the server's station number (stage_n — pipeline
// order, furthest first; declined then corrupt last), id, or cost; the
// filter keeps the stages that wait on a person. Ties break on id.
let BOARD = null;
let BOARD_WAITING = false;
const WAITING = new Set(["gate_0", "gate_1", "gate_2", "review"]);
const cost = (r) => ((r.totals || {}).cost_usd || 0);
function stageRank(r) {
  return r.stage_n ?? (r.stage === "declined" ? -1 : -2);
}
const byId = (a, b) => a.pursuit_id.localeCompare(b.pursuit_id);
const byStage = (a, b) => (stageRank(b) - stageRank(a)) || byId(a, b);
const byCost = (a, b) => (cost(b) - cost(a)) || byId(a, b);

async function loadBoard() {
  BOARD = await api("/api/pursuits");
  renderBoard();
}

function renderBoard() {
  if (!BOARD) return;
  const waiting = BOARD.filter((r) => WAITING.has(r.stage));
  const shown = (BOARD_WAITING ? waiting : BOARD).slice();
  shown.sort({ stage: byStage, id: byId, cost: byCost }[$("boardSort").value] || byStage);
  $("boardFilter").textContent = `waiting on you (${waiting.length})`;
  $("boardFilter").setAttribute("aria-pressed", String(BOARD_WAITING));
  $("boardFilter").classList.toggle("active", BOARD_WAITING);
  $("boardCount").textContent = `${shown.length} of ${BOARD.length}`;
  const empty = BOARD.length ? "nothing is waiting on you" : "no pursuits yet";
  $("boardRows").innerHTML = shown.length ? shown.map((r) => `
    <div class="row" data-pid="${esc(r.pursuit_id)}">
      <span class="id">${esc(r.pursuit_id)}</span>
      ${r.buyer_name ? `<span class="buyer">${esc(r.buyer_name)}</span>` : ""}
      <span class="chip ${esc(STAGE_COLOR[r.stage] || "plan")}">${esc(r.stage)}</span>
      ${r.packaging && r.packaging.blocked
        ? '<span class="chip stop">BLOCKED</span>' : ""}
      ${r.last_run_status && r.last_run_status !== "completed"
        ? `<span class="chip ${esc(RUN_COLOR[r.last_run_status] || "stop")}">run ${esc(r.last_run_status)}</span>`
        : ""}
      ${(r.torn || []).map((t) =>
        `<span class="chip draft">torn: ${esc(t)}</span>`).join("")}
      <div class="meta">${esc(r.next)}
        ${r.open_gaps ? ` &middot; ${esc(r.open_gaps)} open gap(s)` : ""}
        &middot; $${esc((r.totals.cost_usd).toFixed(4))}
        <span title="run totals, not a registered metric">(run totals)</span>
      </div>
      ${stageTrack(r.stage, false)}
    </div>`).join("") : `<div class="meta">${empty}</div>`;
  for (const el of $("boardRows").querySelectorAll(".row")) {
    el.onclick = () => { location.hash = `#/pursuit/${el.dataset.pid}`; };
  }
}

// -- detail ----------------------------------------------------------------

async function loadDetail(pid) {
  const d = await api(`/api/pursuits/${encodeURIComponent(pid)}`);
  $("detailTitle").textContent = d.pursuit_id;
  $("detailTrack").innerHTML = stageTrack(d.stage, true);
  // P30a 4 (B139): the rail — every line is the server's word
  $("crumbPid").textContent = d.pursuit_id;
  $("railNext").textContent = d.next;
  $("railStage").textContent = d.stage_n
    ? `Stage ${d.stage_n} of ${d.stage_count}` : d.stage;
  $("railGaps").textContent = d.open_gaps ? `${d.open_gaps} open` : "none open";
  $("railGates").innerHTML = ["gate_0", "gate_1", "gate_2"].map((g) => {
    const rec = (d.gates || {})[g];
    const word = rec
      ? `decided by ${esc(rec.by)} &middot; ${esc(rec.at)}`
      : (g === "gate_1" && d.stage === "declined"
        ? "declined" : '<span class="muted">not yet</span>');
    return `<div class="gate-row"><span class="mono">${esc(g)}</span><span>${word}</span></div>`;
  }).join("");
  $("detailFacts").innerHTML =
    (d.buyer_name ? `buyer <b>${esc(d.buyer_name)}</b>` : "buyer not named yet")
    + ` &middot; cost $${esc(d.totals.cost_usd.toFixed(4))} (run totals)`
    + (d.packaging ? ` &middot; packaging ${d.packaging.blocked
        ? '<span class="chip stop">BLOCKED</span>'
        : '<span class="chip done">clear</span>'}` : "");
  const acts = [];
  acts.push(`<button id="advanceBtn">Advance</button>`);
  // buttons appear only when the SERVER says the precondition holds —
  // and the server refuses independently either way
  if (d.stage === "gate_0") {
    acts.push(`<button id="gate0Btn">Review intake (Gate 0)</button>`);
  }
  if (d.stage === "gate_1") {
    acts.push(`<button id="gate1Btn">Decide Gate 1</button>`);
  }
  if (d.stage === "gate_2") {
    acts.push(`<button id="gate2Btn">Decide Gate 2</button>`);
  }
  if (d.stage === "review") {
    acts.push(`<button id="reviewBtn">Open review</button>`);
  }
  acts.push(`<label class="ghost upload">upload to inbox
    <input id="upl" type="file" hidden></label>`);
  $("detailActions").innerHTML = acts.join("");
  $("advanceBtn").onclick = () => submitAdvance(pid);
  if ($("gate0Btn")) $("gate0Btn").onclick = () => openGate0(pid);
  if ($("gate1Btn")) $("gate1Btn").onclick = () => openGate1(pid);
  if ($("gate2Btn")) $("gate2Btn").onclick = () => openGate2(pid);
  if ($("reviewBtn")) {
    $("reviewBtn").onclick = () => { location.hash = `#/review/${pid}`; };
  }
  $("upl").onchange = () => uploadFile(pid);
  await loadFinish(pid, d);
  await loadPursuitPings(pid, d);
  await loadShares(pid);
  wireOutcome(pid);
  await loadRuns(pid);
  $("detailSections").innerHTML = (d.sections || []).map((s) => `
    <div class="row">
      <span class="id">${esc(s.section_id)}</span>
      ${s.draft_status
        ? `<span class="chip plan">${esc(s.draft_status)}</span>` : ""}
      <div class="meta">${esc(s.title)}
        ${(s.gaps || []).map((g) =>
          ` &middot; gap ${esc(g.gap_id || "")} ${esc(g.status)}`).join("")}
      </div>
    </div>`).join("");
}

// -- the finish panel (P27 wave 1): render, downloads, write-back, hand
// completion. The SERVER names the preconditions (detail.finishing); the
// panel keys on them and every door refuses independently.

async function loadFinish(pid, d) {
  const f = d.finishing || {};
  $("detailFinish").hidden = !f.reviewable;
  if (!f.reviewable) return;
  $("finishActions").innerHTML =
    `<button id="renderBtn">Render documents</button>`
    + `<button id="wbPreviewBtn" class="ghost">Preview write-back</button>`
    + (f.hand_fill_lane
        ? `<button id="handFillBtn" class="ghost">Complete by hand</button>`
        : "");
  $("renderBtn").onclick = () => renderDocuments(pid);
  $("wbPreviewBtn").onclick = () => previewWriteback(pid);
  if ($("handFillBtn")) $("handFillBtn").onclick = () => openHandFill(pid);
  await loadDownloads(pid, f);
}

async function loadDownloads(pid, f) {
  const dl = await api(`/api/pursuits/${encodeURIComponent(pid)}/downloads`);
  // one whole path literal per line: the door-coverage pin reads them whole
  // P0-22: this helper was ALSO named `dl` — a parse-time SyntaxError
  // that kept the whole workbench script from loading (pilot-2.3 … 2.5)
  const href = (name) =>
    `/api/pursuits/${encodeURIComponent(pid)}/download/${encodeURIComponent(name)}`;
  const link = (name) => `<a class="dl" href="${href(name)}">${esc(name)}</a>`;
  // W2b 5 (B136): what the file carries, from the bundle's hygiene block
  const hygiene = (name) => {
    const h = (dl.hygiene || {})[name];
    if (!h) return `<div class="meta hygiene">hygiene not recorded</div>`;
    return `<div class="meta hygiene">creator ${esc(String(h.creator || "—"))}
      &middot; ${esc(String(h.revision_marks))} revision mark(s)
      &middot; ${esc(String(h.comment_parts))} comment part(s)
      &middot; identity ${esc(String(h.firm_identity))}</div>`;
  };
  $("finishDownloads").innerHTML =
    `<div class="dlhead">To the buyer</div>`
    + (dl.to_the_buyer.length
        ? dl.to_the_buyer.map((n) => link(n) + hygiene(n)).join("")
        : `<div class="meta">nothing shippable yet</div>`)
    + (dl.refused || []).map((r) =>
        `<div class="meta withheld">withheld${r.status === "drifted"
          ? ' <span class="chip draft">stale</span>' : ""} — ${esc(r.name)}: ${
          esc(r.reason)}</div>`).join("")
    + `<div class="dlhead">Internal — do not send</div>`
    + (dl.internal_do_not_send.length
        ? dl.internal_do_not_send.map(link).join("")
        : `<div class="meta">nothing rendered yet</div>`)
    + (f.bundle ? `<div class="meta">bundle composed ${esc(f.bundle.composed_at)}
        by ${esc(f.bundle.composed_by)} — ${esc(String(f.bundle.produced))}
        produced, ${esc(String(f.bundle.refused))} refused</div>` : "");
}

async function renderDocuments(pid) {
  try {
    await api(`/api/pursuits/${encodeURIComponent(pid)}/export`,
              { method: "POST", body: JSON.stringify({ lane: "both" }) });
    toast("documents rendered — the bundle recomposed", true);
    routeFromHash();
  } catch (e) { toast(e.message, true); }
}

function factsSummary(file) {
  // the three lanes' facts differ in shape; render what each carries,
  // the full record under detail
  const rows = [];
  for (const cell of file.cells || []) {
    rows.push(`<div class="meta">${esc(cell.cell || cell.slot_id || "")}
      <span class="chip ${cell.decision === "written" ? "done" : "draft"}">${
      esc(cell.decision)}</span> ${esc(cell.reason || "")}</div>`);
  }
  for (const s of file.sections || []) {
    rows.push(`<div class="meta">${esc(s.slot_id)}
      <span class="chip ${s.decision === "filled" ? "done" : "draft"}">${
      esc(s.decision)}</span></div>`);
  }
  return `<div class="gaprow"><b>${esc(file.lane || "")} ${esc(
      file.output_file || file.working_copy || file.file || "")}</b>
    ${rows.join("")}
    ${file.buyer_copy_produced === false
      ? `<div class="meta withheld">buyer copy withheld — ${esc(
          (file.remaining_by_hand || []).length)} hand item(s) and ${esc(
          (file.remaining_guidance || []).length)} section(s) remain</div>`
      : ""}
    <details><summary>detail</summary>
      <pre>${esc(JSON.stringify(file, null, 2))}</pre></details></div>`;
}

async function previewWriteback(pid) {
  try {
    const p = await api(
      `/api/pursuits/${encodeURIComponent(pid)}/writeback/preview`);
    $("wbBody").innerHTML = (p.files || []).map(factsSummary).join("")
      + (p.refused || []).map((r) => `<div class="gaprow withheld">
          ${esc(r.lane)} ${esc(r.file)}: refused — ${esc(r.reason)}</div>`)
        .join("");
    // the confirm door is two steps: it opens only behind a rendered preview
    $("wbConfirm").disabled = false;
    $("wbConfirm").onclick = () => confirmWriteback(pid);
    openDialog("writebackOverlay");
  } catch (e) { toast(e.message, true); }
}

async function confirmWriteback(pid) {
  $("wbConfirm").disabled = true;
  try {
    const out = await api(
      `/api/pursuits/${encodeURIComponent(pid)}/writeback/confirm`,
      { method: "POST", body: "{}" });
    closeDialog("writebackOverlay");
    toast(`write-back done — ${out.bundle.deliverables.length} deliverable(s) recorded`, true);
    routeFromHash();
    if (out.flywheel !== undefined) showLearned(out.flywheel);
  } catch (e) { toast(e.message, true); }
}

// hand completion: the catalogue drives the form — a record is one entry,
// a table is rows of entries, the inline line is one value
let HF_SLOTS = {};

function hfInputs(slot, entry, idx) {
  return slot.fields.map((f) => `<label class="hf">${esc(f.label)}
    <input class="hfv" data-slot="${esc(slot.slot_id)}" data-idx="${idx}"
           data-key="${esc(f.key)}" value="${esc((entry || {})[f.key] || "")}"
           ${f.type === "numeric" ? 'inputmode="decimal"' : ""}></label>`)
    .join("");
}

function renderHandFill(pid, h) {
  HF_SLOTS = {};
  $("hfBody").innerHTML = h.slots.map((s) => {
    HF_SLOTS[s.slot_id] = s;
    const chip = `<span class="chip ${s.status === "filled" ? "done" : "draft"}">${
      esc(s.status)}</span>`;
    let body;
    if (s.shape === "record") {
      body = hfInputs(s, s.value, 0);
    } else if (s.shape === "table") {
      const rows = (s.value && s.value.length) ? s.value : [{}];
      body = `<div class="hfrows" data-slot="${esc(s.slot_id)}">`
        + rows.map((r, i) => `<div class="hfrow">${hfInputs(s, r, i)}</div>`)
          .join("")
        + `</div><button class="ghost hfAdd" data-slot="${esc(s.slot_id)}">Add row</button>`;
    } else {
      body = `<input class="hfv" data-slot="${esc(s.slot_id)}" data-inline="1"
                     value="${esc(s.value || "")}">`;
    }
    return `<div class="gaprow"><b>${esc(s.docx_anchor || s.slot_id)}</b> ${chip}
      ${(s.missing || []).length
        ? `<span class="meta">owed: ${esc(s.missing.join(", "))}</span>` : ""}
      ${body}</div>`;
  }).join("");
  for (const btn of document.querySelectorAll(".hfAdd")) {
    btn.onclick = () => {
      const slot = HF_SLOTS[btn.dataset.slot];
      const box = document.querySelector(`.hfrows[data-slot="${btn.dataset.slot}"]`);
      box.insertAdjacentHTML("beforeend",
        `<div class="hfrow">${hfInputs(slot, {}, box.children.length)}</div>`);
    };
  }
  $("hfSave").onclick = () => saveHandFill(pid);
}

function collectHandFill() {
  const values = {};
  for (const el of document.querySelectorAll("#hfBody .hfv")) {
    const slot = el.dataset.slot;
    const shape = (HF_SLOTS[slot] || {}).shape;
    if (el.dataset.inline) { values[slot] = el.value; continue; }
    if (shape === "record") {
      values[slot] = values[slot] || {};
      values[slot][el.dataset.key] = el.value;
    } else {
      values[slot] = values[slot] || [];
      const i = Number(el.dataset.idx);
      values[slot][i] = values[slot][i] || {};
      values[slot][i][el.dataset.key] = el.value;
    }
  }
  for (const k of Object.keys(values)) {
    if (Array.isArray(values[k])) values[k] = values[k].filter(Boolean);
  }
  return values;
}

async function openHandFill(pid) {
  try {
    const h = await api(
      `/api/pursuits/${encodeURIComponent(pid)}/writeback/hand-fill`);
    renderHandFill(pid, h);
    openDialog("handFillOverlay");
  } catch (e) { toast(e.message, true); }
}

async function saveHandFill(pid) {
  try {
    const out = await api(
      `/api/pursuits/${encodeURIComponent(pid)}/writeback/hand-fill`,
      { method: "PUT", body: JSON.stringify({ values: collectHandFill() }) });
    renderHandFill(pid, out);
    toast("values saved — run the write-back to land them", true);
  } catch (e) { toast(e.message, true); }
}

// -- share links (P27 wave 1): mint, hand out, revoke ---------------------
// The list door is operator-gated and carries the secret tokens: this
// panel shows them as the URL the guest opens — that is the door's
// purpose. Expiry is a naive UTC timestamp, the server clock's own form.

async function loadShares(pid) {
  let links;
  try {
    links = await api(`/api/pursuits/${encodeURIComponent(pid)}/share`);
  } catch (e) { $("detailShares").hidden = true; return; }
  $("detailShares").hidden = false;
  const url = (l) => `${location.origin}/share/${l.token}`;
  $("shareRows").innerHTML = links.length ? links.map((l) => `
    <div class="gaprow">
      <b>${esc(l.label)}</b>
      <span class="meta">${esc(l.link_id)} &middot; expires ${esc(l.expires_at)}
        &middot; by ${esc(l.created_by)}</span>
      ${l.revoked
        ? `<span class="chip stop">revoked</span>`
        : `<span class="chip done">live</span>
           <input class="shareUrl" readonly value="${esc(url(l))}">
           <button class="ghost shareCopy" data-url="${esc(url(l))}">Copy link</button>
           <button class="ghost danger shareRevoke" data-id="${esc(l.link_id)}">Revoke</button>`}
    </div>`).join("") : `<div class="meta">no guest links yet</div>`;
  for (const b of document.querySelectorAll(".shareCopy")) {
    b.onclick = () => navigator.clipboard.writeText(b.dataset.url)
      .then(() => toast("link copied"))
      .catch(() => toast("copy failed — select the link and copy it", true));
  }
  for (const b of document.querySelectorAll(".shareRevoke")) {
    b.onclick = async () => {
      try {
        const id = encodeURIComponent(b.dataset.id);
        await api(`/api/pursuits/${encodeURIComponent(pid)}/share/${id}/revoke`,
                  { method: "POST", body: "{}" });
        toast(`${b.dataset.id} revoked`);
        loadShares(pid);
      } catch (e) { toast(e.message, true); }
    };
  }
  $("shareNewBtn").onclick = () => { openDialog("shareOverlay"); };
  $("shGo").onclick = async () => {
    const days = Math.max(1, Math.min(30, Number($("shDays").value) || 7));
    const expires_at = new Date(Date.now() + days * 86400000)
      .toISOString().slice(0, 19);
    try {
      const link = await api(`/api/pursuits/${encodeURIComponent(pid)}/share`, {
        method: "POST",
        body: JSON.stringify({ label: $("shLabel").value, expires_at }),
      });
      closeDialog("shareOverlay");
      $("shLabel").value = "";
      toast(`${link.link_id} created — ${url(link)}`, true);
      loadShares(pid);
    } catch (e) { toast(e.message, true); }
  };
}

// -- gaps and pings (P27 wave 1): the inbox that used to be curl-only ----
// Escalation is the SERVER's clock (P2-47); rows render what they carry.

// who a gap can be routed to: the session door's declarable roles — the
// shell never names a role (M-9), it renders the list it is handed
let ROUTE_TARGETS = [];

function pingRow(p, pid) {
  const answered = Boolean(p.answered_at);
  return `<div class="gaprow" data-ping="${esc(p.ping_id)}">
    <b>${esc(p.ping_id)}</b>
    ${pid ? "" : `<a href="#/pursuit/${esc(p.pursuit_id)}">${esc(p.pursuit_id)}</a>`}
    <span class="meta">${esc(p.section_id)} &middot; to ${esc(p.route_to)}
      &middot; by ${esc(p.by)} &middot; ${esc(p.pinged_at)}</span>
    ${answered ? `<span class="chip done">answered</span>`
      : p.escalated ? `<span class="chip stop">escalated</span>`
      : `<span class="chip draft">${esc(String(p.age_hours))} h open</span>`}
    <div class="q">${esc(p.question)}</div>
    ${answered
      ? `<div class="prose">${esc(p.answer || "")}</div>`
      : `<div class="commentbox">
           <input class="pingAnswer" maxlength="4000" placeholder="the answer">
           <label class="hint"><input type="checkbox" class="pingPropose">
             propose a KB card</label>
           <button class="pingGo" data-pid="${esc(p.pursuit_id || pid)}"
                   data-ping="${esc(p.ping_id)}">Answer</button>
         </div>`}
  </div>`;
}

function wirePingAnswers(reload) {
  for (const btn of document.querySelectorAll(".pingGo")) {
    btn.onclick = async () => {
      const box = btn.closest(".commentbox");
      try {
        const pid = encodeURIComponent(btn.dataset.pid);
        const ping = encodeURIComponent(btn.dataset.ping);
        await api(`/api/pursuits/${pid}/pings/${ping}/answer`, {
          method: "POST",
          body: JSON.stringify({
            answer: box.querySelector(".pingAnswer").value,
            propose_card: box.querySelector(".pingPropose").checked }),
        });
        toast(`${btn.dataset.ping} answered`);
        reload();
      } catch (e) { toast(e.message, true); }
    };
  }
}

async function loadPingInbox() {
  const rows = await api("/api/pings");
  $("pingRows").innerHTML = rows.length
    ? rows.map((p) => pingRow(p, null)).join("")
    : `<div class="meta">no pings anywhere</div>`;
  wirePingAnswers(loadPingInbox);
}

async function loadPursuitPings(pid, d) {
  const sections = d.sections || [];
  $("detailPings").hidden = !sections.length;
  if (!sections.length) return;
  const open = [];
  for (const s of sections) {
    for (const g of s.gaps || []) {
      if (g.status === "open") open.push({ ...g, section_id: s.section_id });
    }
  }
  $("pursuitGapRows").innerHTML = open.map((g) => `
    <div class="gaprow">
      <b>${esc(g.gap_id)}</b> <span class="meta">${esc(g.section_id)} &middot; ${esc(g.kind || "")}</span>
      <div class="q">${esc(g.question_to_human || "")}</div>
      <div class="commentbox">
        <select class="routeTo">
          <option value="">— route to —</option>
          ${ROUTE_TARGETS.map((r) => `<option value="${r}">${esc(r.replace(/_/g, " "))}</option>`).join("")}
        </select>
        <button class="ghost pingBtn" data-gap="${esc(g.gap_id)}">Ping an SME</button>
      </div>
    </div>`).join("") || `<div class="meta">no open gaps</div>`;
  for (const btn of document.querySelectorAll(".pingBtn")) {
    btn.onclick = async () => {
      const route_to = btn.closest(".commentbox").querySelector(".routeTo").value;
      if (!route_to) { toast("choose who to route it to"); return; }
      try {
        const gap = encodeURIComponent(btn.dataset.gap);
        await api(`/api/pursuits/${encodeURIComponent(pid)}/gaps/${gap}/ping`,
                  { method: "POST", body: JSON.stringify({ route_to }) });
        toast(`${btn.dataset.gap} pinged to ${route_to}`);
        routeFromHash();
      } catch (e) { toast(e.message, true); }
    };
  }
  $("gapSection").innerHTML = `<option value="">— section —</option>`
    + sections.map((s) => `<option value="${esc(s.section_id)}">${esc(s.title)}</option>`).join("");
  $("gapGo").onclick = async () => {
    try {
      await api(`/api/pursuits/${encodeURIComponent(pid)}/gaps`, {
        method: "POST",
        body: JSON.stringify({ section_id: $("gapSection").value,
                               question: $("gapQuestion").value }),
      });
      $("gapQuestion").value = "";
      toast("gap opened on the live plan");
      routeFromHash();
    } catch (e) { toast(e.message, true); }
  };
  const inbox = await api(`/api/pursuits/${encodeURIComponent(pid)}/pings`);
  $("pursuitPingRows").innerHTML = inbox.length
    ? inbox.map((p) => pingRow(p, pid)).join("")
    : `<div class="meta">no pings on this pursuit</div>`;
  wirePingAnswers(routeFromHash);
}

// -- the outcome (P27 wave 1): one pursuit-level event -----------------------
// The result vocabulary is the feedback-event schema's; nothing preselected.
const OUTCOME_RESULTS = ["won", "lost", "shortlisted", "withdrawn", "no_decision"];

function wireOutcome(pid) {
  $("ocResult").innerHTML = `<option value="">— result —</option>`
    + OUTCOME_RESULTS.map((r) => `<option value="${r}">${esc(r.replace(/_/g, " "))}</option>`).join("");
  $("outcomeBtn").onclick = () => { openDialog("outcomeOverlay"); };
  $("ocGo").onclick = async () => {
    const body = { result: $("ocResult").value };
    if ($("ocFeedback").value) body.buyer_feedback = $("ocFeedback").value;
    if ($("ocScore").value) body.score_received = $("ocScore").value;
    try {
      await api(`/api/pursuits/${encodeURIComponent(pid)}/outcome`,
                { method: "POST", body: JSON.stringify(body) });
      closeDialog("outcomeOverlay");
      toast(`outcome recorded: ${body.result}`, true);
    } catch (e) { toast(e.message, true); }
  };
}

async function uploadFile(pid) {
  const file = $("upl").files[0];
  if (!file) return;
  await api(
    `/api/pursuits/${encodeURIComponent(pid)}/inbox/${encodeURIComponent(file.name)}`,
    { method: "PUT", body: file, raw: true });
  toast(`stored ${file.name}`);
}

async function submitAdvance(pid) {
  try {
    const job = await api(`/api/pursuits/${encodeURIComponent(pid)}/jobs`, {
      method: "POST", body: JSON.stringify({ kind: "advance" }),
    });
    watchJob(job.id, pid);
  } catch (e) { toast(e.message); }
}

// W2a (B134): the strip survives — a failed tick is counted, not fatal
// (three in a row give up by name); boot re-attaches to a live job; Cancel
// renders only when the server says the job is cancellable.
let JOB_FAILS = 0;

function renderJobStrip(job) {
  const mins = job.at ? Math.max(0, Math.round((Date.now() - Date.parse(job.at)) / 60000)) : null;
  $("jobMsg").textContent =
    `${job.kind} · ${job.pursuit} · ${job.state} — ${job.message}`
    + (mins === null ? "" : ` (${mins} min)`);
  $("jobCancel").hidden = !job.cancellable;
}

async function cancelJob(jobId) {
  await api(`/api/jobs/${encodeURIComponent(jobId)}/cancel`, { method: "POST" });
  toast("cancel requested — the job stops at its next check");
}

async function resumeJobs() {
  const jobs = await api("/api/jobs");
  const live = jobs.find((j) => ["queued", "running"].includes(j.state));
  if (live) watchJob(live.id, live.pursuit);
}

function watchJob(jobId, pid) {
  clearInterval(JOB_TIMER);
  JOB_FAILS = 0;
  $("jobStrip").hidden = false;
  $("jobCancel").onclick = () => cancelJob(jobId);
  JOB_TIMER = setInterval(async () => {
    let job;
    try {
      job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
      JOB_FAILS = 0;
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        clearInterval(JOB_TIMER); failed(e); return;
      }
      if (++JOB_FAILS < 3) return;
      clearInterval(JOB_TIMER);
      toast(`lost the job — ${e.message}; reload to re-attach`, true);
      return;
    }
    renderJobStrip(job);
    if (!["queued", "running"].includes(job.state)) {
      clearInterval(JOB_TIMER);
      setTimeout(() => { $("jobStrip").hidden = true; }, 3500);
      toast(`${job.kind}: ${job.state} — ${job.message}`, true); // sticky
      routeFromHash();
    }
  }, 2000);
}

// -- the review surface (F9: mark + one-line reason, detail on demand) -----

const MARK_COLOR = { block: "stop", review: "draft", advisory: "plan",
                     waived: "draft", ok: "done" };

async function loadReview(pid) {
  const m = await api(`/api/pursuits/${encodeURIComponent(pid)}/review`);
  if (REVIEW_PID !== pid) { REVIEW_PID = pid; clockStart(); }
  $("reviewTitle").textContent = `${m.pursuit_id} — revision ${m.revision_n}`;
  $("reviewBack").href = `#/pursuit/${encodeURIComponent(pid)}`;
  $("reviewBack").textContent = pid;  // P30a 4: the crumb names the pursuit
  $("reviewFacts").innerHTML =
    `packaging ${m.packaging.blocked
      ? `<span class="chip stop">BLOCKED (${esc(String(
          m.packaging.tier1_blocks))})</span>`
      : '<span class="chip done">clear</span>'}
     &middot; validated ${esc(m.validated_at)}`;
  $("reviewSections").innerHTML = m.sections.map((s) => `
    <div class="row" data-sid="${esc(s.section_id)}">
      <b>${esc(s.title)}</b>
      ${s.draft_status
        ? `<span class="chip plan">${esc(s.draft_status)}</span>` : ""}
      ${(s.slots || []).map((sl) =>
        `<div class="prose">${esc(sl.prose)}</div>`).join("")}
      ${(s.marks || []).map((k) => `
        <div class="mark">
          <span class="chip ${esc(MARK_COLOR[k.mark] || "plan")}">${esc(k.mark)}</span>
          <span class="line">${esc(k.line)}</span>
          ${k.mark === "block" && k.claim_id
            ? `<button class="ghost waiveBtn" data-claim="${esc(k.claim_id)}"
                 data-line="${esc(k.line)}">Waive</button>` : ""}
          <details><summary>detail</summary>
            <pre>${esc(JSON.stringify(k.detail, null, 2))}</pre>
          </details>
        </div>`).join("")}
      ${(s.pending || []).map((p) => `
        <div class="pendingnote">pending ${esc(p.kind)} ${esc(p.cid)}:
          ${esc(p.text || p.after || "")}
          ${p.provenance === "external"
            ? `<span class="chip plan">guest: ${esc(p.display_name || "")}</span>
               ${(p.screen_flags || []).length
                 ? `<span class="chip stop">flagged by the injection screen</span>` : ""}
               <button class="ghost pendInclude" data-cid="${esc(p.cid)}">Include</button>
               <button class="ghost pendDismiss" data-cid="${esc(p.cid)}">Dismiss</button>`
            : `(applies at next revise)
               <button class="ghost pendWithdraw" data-cid="${esc(p.cid)}">Withdraw</button>`}
        </div>
      `).join("")}
      ${(m.last_round && m.last_round.revised.includes(s.section_id))
        ? `<div class="revisedrow">revised in round ${esc(String(m.last_round.n))}
             <button class="ghost revAccept" data-sid="${esc(s.section_id)}">Accept revision</button>
             <button class="ghost revReject" data-sid="${esc(s.section_id)}">Reject revision</button>
           </div>` : ""}
      <div class="commentbox">
        <input class="cmt" placeholder="comment for the revision agent">
        <button class="cmtGo" data-sid="${esc(s.section_id)}">Comment</button>
      </div>
    </div>`).join("");
  for (const btn of document.querySelectorAll(".cmtGo")) {
    btn.onclick = async () => {
      const input = btn.closest(".commentbox").querySelector(".cmt");
      try {
        await api(`/api/pursuits/${encodeURIComponent(pid)}/comments`, {
          method: "POST",
          body: JSON.stringify({ kind: "comment",
                                 section_id: btn.dataset.sid,
                                 text: input.value }),
        });
        input.value = "";
        loadReview(pid);
      } catch (e) { toast(e.message); }
    };
  }
  for (const btn of document.querySelectorAll(".waiveBtn")) {
    btn.onclick = () => openWaiver(pid, btn.dataset.claim, btn.dataset.line);
  }
  // the review-loop doors (P27 wave 1, the owner's call): guest comments
  // reach the revision agent ONLY when included; internal pendings can be
  // withdrawn; an agent revision is accepted or rejected per section
  const pend = (cls, fn) => {
    for (const btn of document.querySelectorAll(cls)) {
      btn.onclick = async () => {
        try { await fn(btn.dataset.cid); loadReview(pid); }
        catch (e) { toast(e.message, true); }
      };
    }
  };
  const p = encodeURIComponent(pid);
  pend(".pendInclude", (cid) =>
    api(`/api/pursuits/${p}/comments/${encodeURIComponent(cid)}/include`,
        { method: "POST", body: "{}" }));
  pend(".pendDismiss", (cid) =>
    api(`/api/pursuits/${p}/comments/${encodeURIComponent(cid)}/dismiss`,
        { method: "POST", body: "{}" }));
  pend(".pendWithdraw", (cid) =>
    api(`/api/pursuits/${p}/comments/${encodeURIComponent(cid)}`,
        { method: "DELETE" }));
  for (const [cls, kind] of [[".revAccept", "accept"], [".revReject", "reject"]]) {
    for (const btn of document.querySelectorAll(cls)) {
      btn.onclick = async () => {
        try {
          await api(`/api/pursuits/${encodeURIComponent(pid)}/events`, {
            method: "POST",
            body: JSON.stringify({ kind, section_id: btn.dataset.sid }) });
          toast(`${kind}ed the revision of ${btn.dataset.sid}`);
          loadReview(pid);
        } catch (e) { toast(e.message, true); }
      };
    }
  }
  $("acceptBtn").onclick = async () => {
    flushReviewEffort();
    try {
      const out = await api(`/api/pursuits/${encodeURIComponent(pid)}/accept`,
                            { method: "POST", body: "{}" });
      toast("accepted — every drafted section is now final", true);
      location.hash = `#/pursuit/${encodeURIComponent(pid)}`;
      showLearned(out.flywheel);  // over the pursuit it lands on
    } catch (e) { toast(e.message, true); }
  };
  $("reviseBtn").onclick = async () => {
    flushReviewEffort();  // the span before the round is its own session
    try {
      const job = await api(
        `/api/pursuits/${encodeURIComponent(pid)}/revise`,
        { method: "POST", body: JSON.stringify({}) });
      watchJob(job.id, pid);
    } catch (e) { toast(e.message); }
  };
  wireRounds(pid, m);
}

// -- the learn report (P27 wave 2, W2b 4, B136; B122 §9c) -------------------
// Accept and write-back confirm each return the flywheel's report under
// `flywheel`: what was routed, what became a proposal, what was skipped
// and why, what was withheld because identifying material was found. The
// shell used to toast a fixed line and drop it. It is a transient response,
// not a read model, so it renders once, as a dialog, over the pursuit the
// action lands on. Withheld items show a COUNT of locations, never text.
function learnedLines(report) {
  const n = (v) => (Array.isArray(v) ? v.length : 0);
  if (!report) return ['<div class="meta">no learn report on this response</div>'];
  if (report.error) {
    return [`<div class="honesty">the flywheel failed — the step itself stood: ${esc(
      String(report.error))}</div>`];
  }
  const lines = [];
  if (typeof report.skipped === "string") {
    lines.push(`<div><b>skipped</b> &mdash; ${esc(report.skipped)}</div>`);
  }
  if (report.routed !== undefined) {
    lines.push(`<div><b>${esc(String(n(report.routed)))}</b> edit(s) routed</div>`);
  }
  if (report.proposals !== undefined || report.gap_proposals !== undefined) {
    const total = n(report.proposals) + n(report.gap_proposals);
    lines.push(`<div><b>${esc(String(total))}</b> proposal(s) for the steward
      &mdash; the Knowledge base tab</div>`);
  }
  if (report.signals_written !== undefined) {
    lines.push(`<div><b>${esc(String(n(report.signals_written)))}</b> card signal(s) written</div>`);
  }
  if (report.skipped && typeof report.skipped === "object") {
    for (const [what, why] of Object.entries(report.skipped)) {
      lines.push(`<div class="learn-skip"><b>skipped</b> ${esc(what)} &mdash; ${esc(String(why))}</div>`);
    }
  }
  if (n(report.blocked)) {
    lines.push(`<div class="honesty"><b>${esc(String(n(report.blocked)))}</b> item(s) withheld
      &mdash; identifying material was found, so nothing was written</div>`);
    for (const b of report.blocked) {
      lines.push(`<div class="learn-skip">${esc(String(b.event_id || b.gap_id || b.slot_id || ""))}
        &mdash; ${esc(String(n(b.locations)))} location(s)</div>`);
    }
  }
  if (!lines.length) lines.push('<div class="meta">nothing to learn from this one</div>');
  return lines;
}

function showLearned(report) {
  $("learnedBody").innerHTML = learnedLines(report).join("");
  openDialog("learnedOverlay");
}

// -- the operations view (P27 wave 2, W2b 3, B136) --------------------------
// Composed in the browser from three doors that already exist — the board
// rows (stage, last run, totals, torn, corrupt, revision), the jobs journal
// and the health line — so there is no new read model to pin and nothing
// the server does not already say. "needs attention" is a reading of those
// rows, not a stored state: corrupt, a torn lane, a last run that is neither
// completed nor waiting on a human, an orphaned or errored job, a run in
// flight. The row links into the pursuit, whose Runs panel has the detail.
const OPS_QUIET_RUNS = new Set(["completed", "awaiting_gate", "awaiting_gap"]);
let OPS = null;

async function loadOps() {
  const [health, pursuits, jobs] = await Promise.all([
    api("/api/health"), api("/api/pursuits"), api("/api/jobs")]);
  $("opsHealth").innerHTML =
    `<b>${esc(String(health.mode))}</b> &middot; engine ${esc(String(health.version))}
     &middot; sign-in ${esc(String(health.auth_mode))}
     &middot; ${esc(String(pursuits.length))} pursuit(s)
     &middot; ${esc(String(jobs.length))} job(s) in the journal`;
  const latest = {};  // the newest job per pursuit (the door lists newest first)
  for (const j of jobs) if (!latest[j.pursuit]) latest[j.pursuit] = j;
  const attention = [];
  for (const r of pursuits) {
    if (r.corrupt) attention.push([r.pursuit_id, "corrupt — a file the engine cannot read",
                                   "its row names the file; the recovery runbook has the steps"]);
    for (const t of (r.torn || [])) attention.push(
      [r.pursuit_id, `torn ${t} lane`, "repaired on its next write; the Runs panel shows the tail"]);
    if (r.last_run_status === "in_flight") attention.push(
      [r.pursuit_id, "a run in flight", "a job is working; the strip follows it"]);
    else if (r.last_run_status && !OPS_QUIET_RUNS.has(r.last_run_status)) attention.push(
      [r.pursuit_id, `last run ${r.last_run_status}`, "open the pursuit's Runs panel"]);
  }
  for (const j of jobs) {
    if (j.state === "orphaned" || j.state === "error") attention.push(
      [j.pursuit, `${j.kind} job ${j.state}`, j.message || ""]);
  }
  $("opsAttention").hidden = !attention.length;
  $("opsAttnRows").innerHTML = attention.map(([pid, what, where]) =>
    `<div class="attn"><a href="#/pursuit/${encodeURIComponent(pid)}">${esc(pid)}</a>
       &mdash; ${esc(what)} <span class="muted">&middot; ${esc(where)}</span></div>`).join("");
  OPS = { pursuits, latest };
  renderOps();
}

function renderOps() {
  if (!OPS) return;
  const key = $("opsSort").value;
  const rows = OPS.pursuits.slice();
  const jobAt = (r) => ((OPS.latest[r.pursuit_id] || {}).at || "");
  const by = {
    stage: byStage,  // P30a 5: pipeline order (the server's stage_n), not alphabetical
    run: (a, b) => String(a.last_run_status || "").localeCompare(String(b.last_run_status || "")),
    cost: byCost,
    job: (a, b) => jobAt(b).localeCompare(jobAt(a)),
  }[key] || ((a, b) => 0);
  rows.sort(by);
  $("opsRows").innerHTML = rows.length ? rows.map((r) => {
    const j = OPS.latest[r.pursuit_id];
    return `<div class="row" data-pid="${esc(r.pursuit_id)}">
      <span class="id">${esc(r.pursuit_id)}</span>
      <span class="chip ${STAGE_COLOR[r.stage] || "plan"}">${esc(r.stage)}</span>
      ${r.last_run_status ? `<span class="chip ${RUN_COLOR[r.last_run_status]
        || (r.last_run_status === "completed" ? "done" : "stop")}">run ${esc(r.last_run_status)}</span>` : ""}
      ${(r.torn || []).map((t) => `<span class="chip draft">torn: ${esc(t)}</span>`).join("")}
      <div class="meta">${r.revision_n !== undefined ? `revision ${esc(String(r.revision_n))} &middot; ` : ""}
        $${esc(cost(r).toFixed(4))} (run totals)
        ${j ? ` &middot; last job ${esc(j.kind)} ${esc(j.state)} by ${esc(String(j.by || ""))} at ${esc(String(j.at || ""))}` : " &middot; no jobs yet"}
      </div>
    </div>`;
  }).join("") : '<div class="meta">no pursuits yet</div>';
  $("opsRows").querySelectorAll(".row[data-pid]").forEach((row) => {
    row.onclick = () => { location.hash = `#/pursuit/${encodeURIComponent(row.dataset.pid)}`; };
  });
}

// -- the run log, read in the browser (P27 wave 2, W2b 2, B136) ------------
// The back-end human's view of what the agents did (B113 §10a). The runs
// door lists the index; the records door returns the raw log — digest-clean
// by construction (the writer never persists prompts or matched text), so
// the shell renders what it is given and persists nothing. One summary line
// per record, built from the record's own keys by type; the raw record on
// demand.
function runSummary(r) {
  const money = (v) => (typeof v === "number" ? `$${v.toFixed(4)}` : "");
  switch (r.record_type) {
    case "run_start": case "run_end": case "cost_rollup": {
      const run = r.run || {};
      const totals = run.totals || {};
      return [run.mode, run.status, run.engine_version && `engine ${run.engine_version}`,
              totals.cost_usd !== undefined && `${money(totals.cost_usd)} total`]
        .filter(Boolean).join(" · ");
    }
    case "agent_call": {
      const t = r.tokens || {};
      return [r.agent, r.model, money(r.cost_usd),
              t.input !== undefined && `${t.input} in / ${t.output || 0} out`,
              r.target && r.target.section_id].filter(Boolean).join(" · ");
    }
    case "tool_call": return r.tool || "";
    case "kb_retrieval": {
      const kb = r.kb || {};
      const n = (v) => (Array.isArray(v) ? v.length : (v || 0));
      return [kb.step, `${n(kb.cards_returned)} returned`, `${n(kb.cards_opened)} opened`,
              `${n(kb.cards_cited)} cited`, kb.empty_result && "empty result"]
        .filter(Boolean).join(" · ");
    }
    case "gate": {
      const g = r.gate || {};
      return [g.which, g.decision, g.actor && `by ${g.actor}`,
              g.auto_approved && "auto-approved"].filter(Boolean).join(" · ");
    }
    case "validation": {
      const v = r.validation || {};
      return [v.check, v.result, v.claim_tier && `tier ${v.claim_tier}`,
              v.waived_by && `waived by ${v.waived_by}`].filter(Boolean).join(" · ");
    }
    case "gap": {
      const g = r.gap || {};
      return [g.gap_id, g.resolution || g.reason].filter(Boolean).join(" · ");
    }
    case "artifact": {
      const a = r.artifact || {};
      return [a.kind, a.revision_n !== undefined && `revision ${a.revision_n}`]
        .filter(Boolean).join(" · ");
    }
    case "error": {
      const e = r.error || {};
      return [e.code, e.message, e.recoverable ? "recoverable" : "not recoverable",
              e.action_taken && `action: ${e.action_taken}`].filter(Boolean).join(" · ");
    }
    default: return r.notes || "";
  }
}

async function loadRuns(pid) {
  const rows = $("runRows");
  const records = $("runRecords");
  const tools = $("runTools");
  records.hidden = true; tools.hidden = true;
  records.innerHTML = "";
  const runs = await api(`/api/pursuits/${encodeURIComponent(pid)}/runs`);
  rows.innerHTML = runs.length ? runs.map((r) => {
    const color = RUN_COLOR[r.status] || (r.status === "completed" ? "done" : "stop");
    const totals = r.totals || {};
    return `<div class="row runrow" data-run="${esc(r.run_id)}">
      <span class="id">${esc(r.run_id)}</span>
      <span class="chip ${color}">${esc(r.status)}</span>
      ${r.torn_tail ? '<span class="chip draft">torn tail</span>' : ""}
      <span class="meta">${esc(String(r.mode || ""))} &middot; ${esc(String(
        r.records))} record(s)${totals.cost_usd !== undefined
        ? ` &middot; $${esc(Number(totals.cost_usd).toFixed(4))}` : ""}</span>
    </div>`;
  }).join("") : '<div class="meta">no runs yet</div>';
  rows.querySelectorAll(".runrow").forEach((row) => {
    row.onclick = guarded(async () => {
      rows.querySelectorAll(".runrow").forEach((o) => o.classList.toggle("active", o === row));
      const run = encodeURIComponent(row.dataset.run);
      const log = await api(`/api/pursuits/${encodeURIComponent(pid)}/runs/${run}`);
      const kinds = [...new Set(log.map((r) => r.record_type))];
      $("runKind").innerHTML = ['<option value="">all</option>']
        .concat(kinds.map((k) => `<option value="${esc(k)}">${esc(k)}</option>`)).join("");
      records.innerHTML = log.length ? log.map((r) => `
        <div class="row logrow" data-kind="${esc(r.record_type)}">
          <span class="mono">${esc(String(r.ts || ""))}</span>
          <span class="chip plan">${esc(r.record_type)}</span>
          <span class="muted">${esc(String(r.stage || ""))}</span>
          <span>${esc(runSummary(r))}</span>
          <details><summary>raw</summary><pre>${esc(JSON.stringify(r, null, 1))}</pre></details>
        </div>`).join("") : '<div class="meta">an empty run log</div>';
      tools.hidden = false;
      records.hidden = false;
      $("runKind").onchange = () => {
        const want = $("runKind").value;
        records.querySelectorAll(".logrow").forEach((l) => {
          l.hidden = Boolean(want) && l.dataset.kind !== want;
        });
      };
    });
  });
}

// -- the revision history (P27 wave 2, W2b 1b, B136) ------------------------
// The server computes the diff (WP8: before from the archived rev{n-1}
// envelope, after from rev{n}); the shell lists the rounds in the order the
// door returns them and renders each pair as text. Nothing is preselected:
// the current prose above stays the primary surface, the history is on
// demand. The control shows only when the server names a last round.
function wireRounds(pid, m) {
  const box = $("reviewRounds");
  box.hidden = true;
  box.innerHTML = "";
  $("roundsBtn").hidden = !m.last_round;
  $("roundsBtn").onclick = guarded(async () => {
    if (!box.hidden) { box.hidden = true; return; }
    const rounds = await api(
      `/api/pursuits/${encodeURIComponent(pid)}/revisions`);
    box.innerHTML = rounds.length ? rounds.map((r) => {
      const revised = r.sections.filter((s) => s.outcome === "revised").length;
      return `<div class="row roundrow" data-n="${esc(String(r.round_n))}">
        <span class="id">round ${esc(String(r.round_n))}</span>
        <span class="meta">${esc(String(revised))} of ${esc(String(
          r.sections.length))} section(s) revised &middot; by ${esc(
          r.actor || "—")} &middot; ${esc(r.at || "")}</span>
        <div class="diffbox"></div>
      </div>`;
    }).join("") : '<div class="meta">no rounds yet</div>';
    box.hidden = false;
    box.querySelectorAll(".roundrow").forEach((row) => {
      row.onclick = guarded(async (e) => {
        if (e.target.closest(".diffbox")) return;  // reading, not toggling
        const pane = row.querySelector(".diffbox");
        if (pane.innerHTML) { pane.innerHTML = ""; return; }
        const n = encodeURIComponent(row.dataset.n);
        const out = await api(`/api/pursuits/${encodeURIComponent(pid)}/revisions/${n}`);
        pane.innerHTML = out.diff.length ? out.diff.map((d) => `
          <div class="diff-row"><b>${esc(d.section_id)}</b>${d.slot_id
            ? ` <span class="muted">${esc(String(d.slot_id))}</span>` : ""}
            <div class="diff-pair">
              <div><div class="difflbl">before</div><div class="prose">${esc(d.before)}</div></div>
              <div><div class="difflbl">after</div><div class="prose">${esc(d.after)}</div></div>
            </div></div>`).join("")
          : '<div class="meta">no text changed in this round</div>';
      });
    });
  });
}

// -- waivers (P27 wave 1): a Tier-1 block, overridden on the record -------
// The reason IS the record: required by the server, surfaced (never
// refused) when it reads as boilerplate. The role is the session's.

function openWaiver(pid, claimId, line) {
  $("wvClaim").textContent = `${claimId} — ${line}`;
  $("wvReason").value = "";
  openDialog("waiverOverlay");
  $("wvGo").onclick = async () => {
    try {
      const out = await api(`/api/pursuits/${encodeURIComponent(pid)}/waivers`, {
        method: "POST",
        body: JSON.stringify({ claim_id: claimId, reason: $("wvReason").value }),
      });
      closeDialog("waiverOverlay");
      toast(out.warnings.length
        ? `waived — ${out.warnings.join("; ")}` : "waived — on the record", true);
      loadReview(pid);
    } catch (e) { toast(e.message, true); }
  };
}

// -- gates -----------------------------------------------------------------

async function openGate0(pid) {
  const m = await api(`/api/pursuits/${encodeURIComponent(pid)}/gate0`);
  $("g0Body").innerHTML =
    (m.red_flags || []).map((f) =>
      `<div class="gaprow"><span class="honesty">flag</span>
        ${esc(f.kind)} — ${esc(f.detail || "")}</div>`).join("")
    + (m.forecast ? `<div class="gaprow"><span class="chip">estimate</span>
        drafting this pursuit &asymp; $${esc(String(m.forecast.cost_usd_estimate))}
        (${esc(String(m.forecast.unit_count))} ${esc(m.forecast.unit)};
        an assumption-based scale indicator, never a quote)</div>` : "")
    + `<h3 class="hint">The engine read the package as:</h3>`
    + (m.assumptions || []).map((a, i) => `
      <div class="gaprow" data-field="${esc(a.field)}">
        <b>${esc(a.field)}</b> = ${esc(JSON.stringify(a.value))}
        <span class="chip">${esc(a.source)}</span>
        ${a.source === "model"
          ? `<input class="g0fix" data-field="${esc(a.field)}"
               placeholder="correct to… (blank = confirm)">`
          : ""}
      </div>`).join("")
    + ((m.gaps || []).length ? `<h3 class="hint">Questions
        (answer or skip — none of these block):</h3>` : "")
    + (m.gaps || []).map((g) => `
      <div class="gaprow" data-gap="${esc(g.gap_id)}">
        <span class="chip">${esc(g.origin)}</span>
        ${esc(g.question_to_human)}
        ${g.status === "open"
          ? `<input class="g0ans" data-gap="${esc(g.gap_id)}"
               placeholder="answer (blank = leave open)">
             <label><input type="checkbox" class="g0skip"
               value="${esc(g.gap_id)}"> skip</label>`
          : `<span class="chip">${esc(g.status)}</span>
             ${esc(g.answer || "")}`}
      </div>`).join("");
  openDialog("gate0Overlay");
  gateClockOpen("g0Minutes");
  $("g0Approve").onclick = () => decideGate0(pid, true);
  $("g0Reject").onclick = () => decideGate0(pid, false);
}

async function decideGate0(pid, approve) {
  const corrections = [...document.querySelectorAll(".g0fix")]
    .filter((el) => el.value.trim())
    .map((el) => ({ field: el.dataset.field, value: el.value.trim() }));
  const answers = [...document.querySelectorAll(".g0ans")]
    .filter((el) => el.value.trim())
    .map((el) => ({ gap_id: el.dataset.gap, answer: el.value.trim() }));
  const skips = [...document.querySelectorAll(".g0skip:checked")]
    .map((el) => el.value);
  const body = { notes: $("g0Notes").value || undefined,
                 effort: gateEffort("g0Minutes") };
  if (!approve) body.decision = "rejected";
  else if (corrections.length || answers.length || skips.length) {
    body.decision = "approved_with_edits";
    body.corrections = corrections;
    body.answers = answers;
    body.skips = skips;
  } else body.decision = "approved";
  try {
    const out = await api(`/api/pursuits/${encodeURIComponent(pid)}/gate0`,
                          { method: "POST", body: JSON.stringify(body) });
    closeDialog("gate0Overlay");
    toast(`Gate 0: ${out.decision}`, true);
    routeFromHash();
  } catch (e) { toast(e.message); }
}

async function openGate1(pid) {
  const m = await api(`/api/pursuits/${encodeURIComponent(pid)}/gate1`);
  $("g1Body").innerHTML = (m.red_flags || []).map((f) =>
    `<div class="gaprow"><span class="honesty">flag</span>
      ${esc(f.kind)} — ${esc(f.detail || "")}</div>`).join("")
    + (m.candidates || []).map((c) => `
    <div class="gaprow" data-cid="${esc(c.candidate_id)}">
      <b>${esc(c.candidate_id)}</b> ${esc(c.theme)}
      ${c.status === "killed"
        ? `<span class="chip stop">killed</span>
           <div class="q">${esc(c.kill_reason || "")}</div>`
        : `<label><input type="checkbox" class="g1kill"
             value="${esc(c.candidate_id)}"> kill</label>`}
      <div class="q">${esc(c.rationale || "")}
        &middot; cites: ${esc((c.cites || []).join(", "))}</div>
    </div>`).join("");
  openDialog("gate1Overlay");
  gateClockOpen("g1Minutes");
  $("g1Approve").onclick = () => decideGate1(pid, true);
  $("g1Reject").onclick = () => decideGate1(pid, false);
}

async function decideGate1(pid, approve) {
  const kills = [...document.querySelectorAll(".g1kill:checked")]
    .map((el) => el.value);
  const body = { notes: $("g1Notes").value || undefined,
                 collapse: $("g1Collapse").checked,
                 effort: gateEffort("g1Minutes") };
  if (!approve) body.decision = "rejected";
  else if (kills.length) {
    body.decision = "approved_with_edits";
    body.edits = { kill: kills };
  } else body.decision = "approved";
  try {
    const out = await api(`/api/pursuits/${encodeURIComponent(pid)}/gate1`,
                          { method: "POST", body: JSON.stringify(body) });
    closeDialog("gate1Overlay");
    toast(`Gate 1: ${out.decision}`, true);
    if (out.job) watchJob(out.job, pid);
    else routeFromHash();
  } catch (e) { toast(e.message); }
}

async function openGate2(pid) {
  const m = await api(`/api/pursuits/${encodeURIComponent(pid)}/gate2`);
  // the plan summary is ALWAYS shown — approving unseen is the UAT C2 bug
  $("g2Body").innerHTML =
    (m.honesty ? `<p class="honesty">${esc(m.honesty)}</p>` : "")
    + `<p class="hint">path ${esc(m.path)} &middot;
       ${esc(String(m.sections.length))} sections &middot;
       coverage: ${esc(JSON.stringify(m.coverage_summary))}</p>`
    + m.sections.map((s) => `
      <div class="gaprow">
        <b>${esc(s.title)}</b> (${esc(String(s.slot_count))} slots)
        ${s.gaps.map((g) => `
          <div class="q">${esc(g.question_to_human || "")}</div>
          ${g.status === "open" ? `
          <select class="g2dispose" data-section="${esc(s.section_id)}"
                  data-gap="${esc(g.gap_id)}">
            <option value="">— the human disposes; nothing preselected —</option>
            ${g.options.map((o) =>
              `<option value="${esc(o)}">${esc(o)}</option>`).join("")}
          </select>
          <input class="g2note" data-gap="${esc(g.gap_id)}"
                 placeholder="answer / reframe direction / note">`
          : `<span class="chip plan">${esc(g.status)}</span>`}
        `).join("")}
      </div>`).join("")
    + (m.obligations || []).map((o) => `
      <div class="oblig">${esc(o.title)}
        <span class="chip ${o.status === "covered" ? "done"
          : o.status === "waived" ? "draft" : "stop"}">${esc(o.status)}</span>
        ${o.status === "gapped" ? `<label><input type="checkbox"
          class="g2waive" value="${esc(o.id)}"> waive</label>
          <input class="g2waivenote" data-id="${esc(o.id)}"
                 placeholder="waive reason (required)">` : ""}
      </div>`).join("");
  openDialog("gate2Overlay");
  gateClockOpen("g2Minutes");
  $("g2Approve").onclick = () => decideGate2(pid, true);
  $("g2Reject").onclick = () => decideGate2(pid, false);
}

async function decideGate2(pid, approve) {
  const body = { notes: $("g2Notes").value || undefined,
                 effort: gateEffort("g2Minutes") };
  if (!approve) body.decision = "rejected";
  else {
    const dispose = [];
    for (const sel of document.querySelectorAll(".g2dispose")) {
      if (!sel.value) continue;
      const note = document.querySelector(
        `.g2note[data-gap="${sel.dataset.gap}"]`).value;
      const item = { section_id: sel.dataset.section,
                     gap_id: sel.dataset.gap, action: sel.value };
      if (sel.value === "answered") item.answer = note;
      else if (note) item.note = note;
      dispose.push(item);
    }
    const waives = [...document.querySelectorAll(".g2waive:checked")]
      .map((el) => ({ id: el.value,
                      note: document.querySelector(
                        `.g2waivenote[data-id="${el.value}"]`).value }));
    const edits = {};
    if (dispose.length) edits.dispose = dispose;
    if (waives.length) edits.waive_obligations = waives;
    body.decision = Object.keys(edits).length
      ? "approved_with_edits" : "approved";
    if (Object.keys(edits).length) body.edits = edits;
  }
  try {
    const out = await api(`/api/pursuits/${encodeURIComponent(pid)}/gate2`,
                          { method: "POST", body: JSON.stringify(body) });
    closeDialog("gate2Overlay");
    toast(`Gate 2: ${out.decision}${out.frozen ? " — plan frozen" : ""}`,
          true);
    routeFromHash();
  } catch (e) { toast(e.message); }
}

// -- new pursuit -----------------------------------------------------------

$("newPursuitBtn").onclick = () => { openDialog("newOverlay"); };
document.querySelectorAll("[data-close]").forEach((b) => {
  b.onclick = () => { closeDialog(b.closest(".overlay").id); };
});
$("npGo").onclick = async () => {
  try {
    const out = await api("/api/pursuits", {
      method: "POST",
      body: JSON.stringify({ pursuit_id: $("npId").value.trim() }),
    });
    closeDialog("newOverlay");
    location.hash = `#/pursuit/${out.pursuit_id}`;
  } catch (e) { toast(e.message); }
};

// -- knowledge base (c20) --------------------------------------------------

async function loadKb() {
  const params = new URLSearchParams({
    q: $("kbSearch").value, layer: $("kbLayer").value,
    staleness: $("kbStale").value,
  });
  const [cards, proposals, accepted] = await Promise.all([
    api(`/api/kb/cards?${params}`),
    api("/api/kb/proposals?status=proposed"),
    api("/api/kb/proposals?status=accepted"),
  ]);

  // P26c: a steward approves a VISIBLE change (S4) — every row shows the
  // diff, where it came from, and where it lands if accepted. A fact
  // card asks for the fields a human must vouch for.
  const diffRows = (diff) => Object.entries(diff || {}).map(([key, change]) => `
        <div class="diff-row"><b>${esc(key)}</b>:
          ${change.before != null ? `<span class="muted">${esc(String(change.before))}</span> &rarr; ` : ""}
          <span>${esc(String(change.after ?? ""))}</span></div>`).join("");
  const sourceLine = (s) => [
    s.pursuit_id ? `pursuit ${esc(s.pursuit_id)}` : "",
    (s.event_ids || []).length ? `events ${esc(s.event_ids.join(", "))}` : "",
    s.section_id ? `section ${esc(s.section_id)}` : "",
    s.gap_id ? `gap ${esc(s.gap_id)}` : "",
    s.slot_id ? `slot ${esc(s.slot_id)}` : "",
    s.artifact ? esc(s.artifact) : "",
    s.operator ? `by ${esc(s.operator)}` : "",
  ].filter(Boolean).join(" &middot; ");

  // The steward's inbox sits ABOVE the library: v1 buried approval in a
  // terminal, so imported content stayed invisible to every draft.
  $("kbProposals").innerHTML = proposals.proposals.length
    ? `<div class="row"><b>${proposals.proposals.length} awaiting your review</b>` +
      proposals.proposals.map((p) => `
        <div class="mark" data-proposal="${esc(p.proposal_id)}">
          <span>${esc(p.kind)} &middot; ${esc(p.target)} &middot; from ${esc(p.source.door)}
            ${p.source.external ? '<span class="chip stop">guest-originated</span>' : ""}</span>
          <div><b>lands in:</b> ${esc(p.home.label)}</div>
          <div class="muted">${sourceLine(p.source)}</div>
          <div class="muted">${esc(p.note || "")}</div>
          ${diffRows(p.diff)}
          ${p.home.needs_fill.length ? `<div class="row">
            ${p.home.needs_fill.map((f) => `<label>${esc(f)}
              <input data-fill="${esc(f)}"${f.endsWith("date") ? ' type="date"' : ""}></label>`).join(" ")}
            <span class="muted">a fact card needs a human to vouch for it</span></div>` : ""}
          <button data-accept="${esc(p.proposal_id)}">accept</button>
          <button data-reject="${esc(p.proposal_id)}" class="ghost">reject</button>
        </div>`).join("") + "</div>"
    : "";

  // Steward notes (P26c): an accepted proposal with no card to land on
  // IS the note the drafter reads — shown here so accepting one is
  // never nothing.
  const notes = accepted.proposals.filter((p) => p.home.kind === "note");
  $("kbNotes").innerHTML = notes.length
    ? `<div class="row"><b>${notes.length} steward note${notes.length === 1 ? "" : "s"} the drafter reads</b>` +
      notes.map((p) => `
        <div class="mark">
          <span>[${esc(p.target.replace(/_/g, " "))}]</span>
          ${diffRows(p.diff)}
          <div class="muted">accepted by ${esc((p.decided || {}).by || "")} &middot; ${esc((p.decided || {}).at || "")}</div>
        </div>`).join("") + "</div>"
    : "";

  $("kbRows").innerHTML = cards.cards.map((c) => `
    <div class="row">
      <div><b>${esc(c.title)}</b> <span class="muted">${esc(c.kb_id)}</span>
        ${c.staleness ? `<span class="chip stop">${esc(c.staleness.replace("_", " "))}</span>` : ""}
        ${c.edit_survival != null ? `<span class="chip">survival ${esc(c.edit_survival)}</span>` : ""}
        ${c.deprecated ? `<span class="chip stop">deprecated</span>` : ""}
        ${(c.lessons || []).length ? `<span class="chip">${c.lessons.length} lesson${c.lessons.length === 1 ? "" : "s"}</span>` : ""}
      </div>
      <div class="muted">${esc(c.summary)}</div>
      ${c.notes.map((n) => `<div class="mark">${esc(n)}</div>`).join("")}
    </div>`).join("") || `<p class="muted">no cards match</p>`;

  $("kbProposals").querySelectorAll("[data-accept]").forEach((b) =>
    b.onclick = () => decideProposal(b.dataset.accept, "accepted"));
  $("kbProposals").querySelectorAll("[data-reject]").forEach((b) =>
    b.onclick = () => decideProposal(b.dataset.reject, "rejected"));
}

async function decideProposal(id, decision) {
  const body = { decision };
  // P26c: the fills a fact card needs ride with the accept
  const mark = document.querySelector(`[data-proposal="${CSS.escape(id)}"]`);
  const fills = {};
  if (mark) mark.querySelectorAll("[data-fill]").forEach((input) => {
    if (input.value) fills[input.dataset.fill] = input.value;
  });
  if (Object.keys(fills).length) body.fills = { [id]: fills };
  await api(`/api/kb/proposals/${id}/decide`, {
    method: "POST", body: JSON.stringify(body),
  });
  await loadKb();
}

// -- telemetry (c21) -------------------------------------------------------

function metricRow(m) {
  // Three-state rendering: a value, a count when the sample is too small
  // to state a rate, or ABSENT carrying why. Never a defaulted zero.
  let figure;
  if (m.status === "absent") {
    figure = `<span class="muted">not available — ${esc(m.absent_reason)}</span>`;
  } else if (m.status === "count_only") {
    figure = `<b>${esc(m.display)}</b> <span class="muted">(too few to state a rate)</span>`;
  } else {
    figure = `<b>${esc(m.value)}</b> <span class="muted">${esc(m.unit || "")} · n=${esc(m.n)}</span>`;
  }
  return `
    <div class="row">
      <div>${esc(m.name || m.metric_id)}
        ${m.estimated ? `<span class="chip">estimated</span>` : ""}
        ${m.rate_card_version ? `<span class="chip">rates ${esc(m.rate_card_version)}</span>` : ""}
      </div>
      <div>${figure}</div>
      ${m.caveat ? `<div class="mark">${esc(m.caveat)}</div>` : ""}
    </div>`;
}

async function loadTelemetry(which) {
  const bench = which === "bench";
  $("telProd").classList.toggle("active", !bench);
  $("telBench").classList.toggle("active", bench);
  const data = await api(bench ? "/api/telemetry/bench" : "/api/telemetry");

  let head = "";
  if (bench) {
    head = data.release
      ? `<div class="row"><b>${esc(data.release.engine_version)}</b> —
           ${data.release.eval_pass_state ? "eval gates pass" :
             `BLOCKED: ${esc((data.release.blocking_failures || []).join(", "))}`}
         <div class="muted">bench results never enter a production series</div></div>`
      : `<p class="muted">${esc(data.release_absent_reason || "no release record")}</p>`;
  }
  $("telNote").textContent = bench
    ? "Bench and eval results — recorded separately by design."
    : "Derived from the records on every load; nothing here is stored.";
  $("telRows").innerHTML = head + data.metrics.map(metricRow).join("");
}

// -- assistant (P14) -------------------------------------------------------
// One session per tab visit; the server holds the transcript — this
// pane only renders what it is handed. esc() on EVERY interpolation.

let ASSISTANT_SESSION = null;

function asstMeta(s) {
  $("asstSpend").textContent =
    `$${Number(s.spent_usd ?? 0).toFixed(2)} of ` +
    `$${Number(s.ceiling_usd ?? 0).toFixed(2)}`;
}

function asstChips(items, cls) {
  if (!items || !items.length) return "";
  return `<div class="asst-chips">${items.map((c) =>
    `<span class="chip ${cls}">${esc(c)}</span>`).join("")}</div>`;
}

function asstBubble(role, inner) {
  return `<div class="asst-msg ${role}">${inner}</div>`;
}

function renderAsstRecord(r) {
  if (r.type === "user") return asstBubble("me", esc(r.text));
  if (r.type === "assistant")
    return asstBubble("bot", esc(r.text) + asstChips(r.citations, "plan"));
  if (r.type === "decline")
    return asstBubble("bot",
      `<span class="asst-decline">Outside my grounding: ` +
      `${esc(r.topic)}</span>`);
  return "";
}

function asstAppend(html) {
  const thread = $("asstThread");
  thread.insertAdjacentHTML("beforeend", html);
  thread.scrollTop = thread.scrollHeight;
}

async function loadAssistantUsage() {
  const el = $("asstUsage");
  if (!el) return;
  try {
    const u = await api("/api/assistant/usage");
    if (u.note) { el.textContent = `lane: ${u.note}`; return; }
    const tools = Object.entries(u.tools)
      .map(([n, c]) => `${n}×${c}`).join(", ");
    el.textContent =
      `lane to date: ${u.session_count} session(s), ${u.calls} model ` +
      `call(s), $${u.cost_usd.toFixed(4)}` +
      (u.injection_flags ? ` · ${u.injection_flags} screen flag(s)` : "") +
      (u.tool_refusals ? ` · ${u.tool_refusals} tool refusal(s)` : "") +
      (tools ? ` · tools: ${tools}` : "");
  } catch (e) { el.textContent = ""; }
}

async function loadAssistant() {
  try {
    if (!ASSISTANT_SESSION) {
      const s = await api("/api/assistant/session", {
        method: "POST", body: "{}",
      });
      ASSISTANT_SESSION = s.session_id;
      asstMeta(s);
      $("asstThread").innerHTML = "";
    } else {
      const s = await api(`/api/assistant/session/${ASSISTANT_SESSION}`);
      asstMeta(s);
      $("asstThread").innerHTML =
        s.transcript.map(renderAsstRecord).join("");
      $("asstThread").scrollTop = $("asstThread").scrollHeight;
    }
    await loadAssistantUsage();
  } catch (e) { toast(e.message, true); }
}

async function sendAssistant() {
  const box = $("asstInput");
  const text = box.value.trim();
  if (!text || !ASSISTANT_SESSION) return;
  box.disabled = true;
  $("asstSend").disabled = true;
  asstAppend(asstBubble("me", esc(text)));
  asstAppend(`<div class="asst-msg bot pending" id="asstPending">` +
             `<span class="pulse"></span> working…</div>`);
  try {
    const out = await api(
      `/api/assistant/session/${ASSISTANT_SESSION}/message`,
      { method: "POST", body: JSON.stringify({ message: text }) });
    $("asstPending").remove();
    const trail = (out.tool_trail || []).map((t) =>
      t.status === "ok" ? t.tool : `${t.tool} (refused)`);
    let inner;
    if (out.reply.action === "answer") {
      inner = esc(out.reply.text) + asstChips(out.reply.citations, "plan");
    } else {
      inner = `<span class="asst-decline">Outside my grounding: ` +
              `${esc(out.reply.topic)}</span>`;
    }
    asstAppend(asstBubble("bot", inner + asstChips(trail, "draft")));
    if ((out.screen_flags || []).length) {
      toast(`screen flagged ${out.screen_flags.length} pattern(s) in ` +
            `retrieved content — noted on the session log`, true);
    }
    asstMeta(out);
    box.value = "";
    loadAssistantUsage();
  } catch (e) {
    const pending = $("asstPending");
    if (pending) pending.remove();
    toast(e.message, true);
  } finally {
    box.disabled = false;
    $("asstSend").disabled = false;
    box.focus();
  }
}

// -- routing ---------------------------------------------------------------

function showView(name) {
  document.querySelectorAll(".view").forEach((v) =>
    v.classList.toggle("show", v.id === `view-${name}`));
}

// W2a (B134): the sidebar highlight and the tab title follow the hash,
// so a deep link lands lit and named — not only a click
function setNav(view, title) {
  document.querySelectorAll("#mainNav a").forEach((a) =>
    a.classList.toggle("active", a.dataset.view === view));
  document.title = `${title} — RFP Engine`;
}

async function routeFromHash() {
  const r = location.hash.match(/^#\/review\/(.+)$/);
  if (REVIEW_PID && !(r && r[1] === REVIEW_PID)) flushReviewEffort();
  if (r) {
    setNav("board", `Review ${r[1]}`); showView("review");
    await loadReview(r[1]); return;
  }
  const m = location.hash.match(/^#\/pursuit\/(.+)$/);
  if (m) {
    setNav("board", m[1]); showView("detail"); await loadDetail(m[1]); return;
  }
  if (location.hash.startsWith("#/pings")) {
    setNav("pings", "Pings"); showView("pings"); await loadPingInbox(); return;
  }
  if (location.hash.startsWith("#/kb")) {
    setNav("kb", "Knowledge base"); showView("kb"); await loadKb(); return;
  }
  if (location.hash.startsWith("#/assistant")) {
    setNav("assistant", "Assistant"); showView("assistant");
    await loadAssistant(); return;
  }
  if (location.hash.startsWith("#/telemetry")) {
    setNav("telemetry", "Telemetry"); showView("telemetry");
    await loadTelemetry("system"); return;
  }
  if (location.hash.startsWith("#/ops")) {
    setNav("ops", "Operations"); showView("ops"); await loadOps(); return;
  }
  setNav("board", "Pursuits"); showView("board"); await loadBoard();
}

function wireNavExtras() {
  ["kbSearch", "kbLayer", "kbStale"].forEach((id) => {
    const el = $(id);
    if (el) el.oninput = el.onchange = () => loadKb();
  });
  if ($("asstSend")) $("asstSend").onclick = () => sendAssistant();
  if ($("asstInput")) $("asstInput").onkeydown = (e) => {
    if (e.key === "Enter") sendAssistant();
  };
  if ($("telProd")) $("telProd").onclick = () => loadTelemetry("system");
  if ($("opsSort")) $("opsSort").onchange = () => renderOps();
  if ($("boardSort")) $("boardSort").onchange = () => renderBoard();
  if ($("boardFilter")) $("boardFilter").onclick = () => {
    BOARD_WAITING = !BOARD_WAITING; renderBoard();
  };
  if ($("telBench")) $("telBench").onclick = () => loadTelemetry("bench");
}

// -- one error path (W2a, B134) --------------------------------------------
// Every entry point the shell exposes — a route, a dialog opener, an
// upload, a decision — runs guarded: a 401 reopens the sign-in dialog
// (the session is gone), anything else is a sticky toast carrying the
// server's own detail. A failed load never leaves a blank view.

function failed(e) {
  if (e instanceof ApiError && e.status === 401) {
    OPERATOR = null; OPERATOR_ROLE = null; renderWho();
    openDialog("opOverlay");
    toast("your session ended — sign in to continue", true);
    return;
  }
  toast(e.message, true);
}

function guarded(fn) {
  return async function (...args) {
    try { return await fn.apply(this, args); } catch (e) { failed(e); }
  };
}

routeFromHash = guarded(routeFromHash);
bootSession = guarded(bootSession);
openGate0 = guarded(openGate0);
openGate1 = guarded(openGate1);
openGate2 = guarded(openGate2);
uploadFile = guarded(uploadFile);
decideProposal = guarded(decideProposal);
loadShares = guarded(loadShares);
loadReview = guarded(loadReview);
loadKb = guarded(loadKb);
loadTelemetry = guarded(loadTelemetry);
cancelJob = guarded(cancelJob);

wireNavExtras();

window.addEventListener("hashchange", routeFromHash);
bootSession().then(routeFromHash);

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
};

let OPERATOR = null;
let OPERATOR_ROLE = null;  // the session's role — the server records it,
                          // the shell never sends one (P27, M-9)
let JOB_TIMER = null;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} on ${path}`);
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
  if (!OPERATOR) $("opOverlay").hidden = false;
}

function renderWho() {
  $("whoName").textContent = OPERATOR || "not signed in";
  $("whoRole").textContent = OPERATOR_ROLE
    ? OPERATOR_ROLE.replace(/_/g, " ") : "";
  $("signInBtn").hidden = Boolean(OPERATOR);
}

$("signInBtn").onclick = () => { $("opOverlay").hidden = false; };
$("opGo").onclick = async () => {
  try {
    const out = await api("/api/session", {
      method: "POST", body: JSON.stringify({ name: $("opName").value,
                                             role: $("opRole").value }),
    });
    OPERATOR = out.operator;
    OPERATOR_ROLE = out.role;
    renderWho();
    $("opOverlay").hidden = true;
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

async function loadBoard() {
  const rows = await api("/api/pursuits");
  $("boardRows").innerHTML = rows.length ? rows.map((r) => `
    <div class="row" data-pid="${esc(r.pursuit_id)}">
      <span class="id">${esc(r.pursuit_id)}</span>
      <span class="chip ${esc(STAGE_COLOR[r.stage] || "plan")}">${esc(r.stage)}</span>
      ${r.packaging && r.packaging.blocked
        ? '<span class="chip stop">BLOCKED</span>' : ""}
      <div class="meta">${esc(r.next)}
        ${r.open_gaps ? ` &middot; ${esc(r.open_gaps)} open gap(s)` : ""}
        &middot; $${esc((r.totals.cost_usd).toFixed(4))}
        <span title="run totals, not a registered metric">(run totals)</span>
      </div>
    </div>`).join("") : '<div class="meta">no pursuits yet</div>';
  for (const el of $("boardRows").querySelectorAll(".row")) {
    el.onclick = () => { location.hash = `#/pursuit/${el.dataset.pid}`; };
  }
}

// -- detail ----------------------------------------------------------------

async function loadDetail(pid) {
  const d = await api(`/api/pursuits/${encodeURIComponent(pid)}`);
  $("detailTitle").textContent = d.pursuit_id;
  $("detailFacts").innerHTML =
    `stage <b>${esc(d.stage)}</b> &middot; next: ${esc(d.next)}`
    + (d.buyer_name ? ` &middot; buyer <b>${esc(d.buyer_name)}</b>` : "")
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
  acts.push(`<label class="ghost" style="border:1px solid var(--line);
    border-radius:6px;padding:7px 14px;cursor:pointer">upload to inbox
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
  const dl = (name) =>
    `/api/pursuits/${encodeURIComponent(pid)}/download/${encodeURIComponent(name)}`;
  const link = (name) => `<a class="dl" href="${dl(name)}">${esc(name)}</a>`;
  $("finishDownloads").innerHTML =
    `<div class="dlhead">To the buyer</div>`
    + (dl.to_the_buyer.length ? dl.to_the_buyer.map(link).join("")
        : `<div class="meta">nothing shippable yet</div>`)
    + (dl.refused || []).map((r) =>
        `<div class="meta withheld">withheld — ${esc(r.name)}: ${
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
    $("writebackOverlay").hidden = false;
  } catch (e) { toast(e.message, true); }
}

async function confirmWriteback(pid) {
  $("wbConfirm").disabled = true;
  try {
    const out = await api(
      `/api/pursuits/${encodeURIComponent(pid)}/writeback/confirm`,
      { method: "POST", body: "{}" });
    $("writebackOverlay").hidden = true;
    toast(`write-back done — ${out.bundle.deliverables.length} deliverable(s)
      recorded`, true);
    routeFromHash();
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
    $("handFillOverlay").hidden = false;
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
  $("shareNewBtn").onclick = () => { $("shareOverlay").hidden = false; };
  $("shGo").onclick = async () => {
    const days = Math.max(1, Math.min(30, Number($("shDays").value) || 7));
    const expires_at = new Date(Date.now() + days * 86400000)
      .toISOString().slice(0, 19);
    try {
      const link = await api(`/api/pursuits/${encodeURIComponent(pid)}/share`, {
        method: "POST",
        body: JSON.stringify({ label: $("shLabel").value, expires_at }),
      });
      $("shareOverlay").hidden = true;
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
  $("outcomeBtn").onclick = () => { $("outcomeOverlay").hidden = false; };
  $("ocGo").onclick = async () => {
    const body = { result: $("ocResult").value };
    if ($("ocFeedback").value) body.buyer_feedback = $("ocFeedback").value;
    if ($("ocScore").value) body.score_received = $("ocScore").value;
    try {
      await api(`/api/pursuits/${encodeURIComponent(pid)}/outcome`,
                { method: "POST", body: JSON.stringify(body) });
      $("outcomeOverlay").hidden = true;
      toast(`outcome recorded: ${body.result}`, true);
    } catch (e) { toast(e.message, true); }
  };
}

async function uploadFile(pid) {
  const file = $("upl").files[0];
  if (!file) return;
  const res = await fetch(
    `/api/pursuits/${encodeURIComponent(pid)}/inbox/${encodeURIComponent(file.name)}`,
    { method: "PUT", body: file });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    toast(body.detail || "upload failed");
    return;
  }
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

function watchJob(jobId, pid) {
  clearInterval(JOB_TIMER);
  $("jobStrip").hidden = false;
  JOB_TIMER = setInterval(async () => {
    const job = await api(`/api/jobs/${encodeURIComponent(jobId)}`);
    $("jobMsg").textContent =
      `${job.kind} · ${job.state} — ${job.message}`;
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
      await api(`/api/pursuits/${encodeURIComponent(pid)}/accept`,
                { method: "POST", body: "{}" });
      toast("accepted — every drafted section is now final", true);
      location.hash = `#/pursuit/${encodeURIComponent(pid)}`;
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
}

// -- waivers (P27 wave 1): a Tier-1 block, overridden on the record -------
// The reason IS the record: required by the server, surfaced (never
// refused) when it reads as boilerplate. The role is the session's.

function openWaiver(pid, claimId, line) {
  $("wvClaim").textContent = `${claimId} — ${line}`;
  $("wvReason").value = "";
  $("waiverOverlay").hidden = false;
  $("wvGo").onclick = async () => {
    try {
      const out = await api(`/api/pursuits/${encodeURIComponent(pid)}/waivers`, {
        method: "POST",
        body: JSON.stringify({ claim_id: claimId, reason: $("wvReason").value }),
      });
      $("waiverOverlay").hidden = true;
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
  $("gate0Overlay").hidden = false;
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
    $("gate0Overlay").hidden = true;
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
  $("gate1Overlay").hidden = false;
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
    $("gate1Overlay").hidden = true;
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
  $("gate2Overlay").hidden = false;
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
    $("gate2Overlay").hidden = true;
    toast(`Gate 2: ${out.decision}${out.frozen ? " — plan frozen" : ""}`,
          true);
    routeFromHash();
  } catch (e) { toast(e.message); }
}

// -- new pursuit -----------------------------------------------------------

$("newPursuitBtn").onclick = () => { $("newOverlay").hidden = false; };
document.querySelectorAll("[data-close]").forEach((b) => {
  b.onclick = () => { b.closest(".overlay").hidden = true; };
});
$("npGo").onclick = async () => {
  try {
    const out = await api("/api/pursuits", {
      method: "POST",
      body: JSON.stringify({ pursuit_id: $("npId").value.trim() }),
    });
    $("newOverlay").hidden = true;
    location.hash = `#/pursuit/${out.pursuit_id}`;
  } catch (e) { toast(e.message); }
};

// -- knowledge base (c20) --------------------------------------------------

async function loadKb() {
  const params = new URLSearchParams({
    q: $("kbSearch").value, layer: $("kbLayer").value,
    staleness: $("kbStale").value,
  });
  const [cards, proposals] = await Promise.all([
    fetch(`/api/kb/cards?${params}`).then((r) => r.json()),
    fetch("/api/kb/proposals?status=proposed").then((r) => r.json()),
  ]);

  // The steward's inbox sits ABOVE the library: v1 buried approval in a
  // terminal, so imported content stayed invisible to every draft.
  $("kbProposals").innerHTML = proposals.proposals.length
    ? `<div class="row"><b>${proposals.proposals.length} awaiting your review</b>` +
      proposals.proposals.map((p) => `
        <div class="mark">
          <span>${esc(p.kind)} &middot; ${esc(p.kb_id || "—")} &middot;
                from ${esc(p.source.door)}</span>
          <div class="muted">${esc(p.note || "")}</div>
          <button data-accept="${esc(p.proposal_id)}">accept</button>
          <button data-reject="${esc(p.proposal_id)}" class="ghost">reject</button>
        </div>`).join("") + "</div>"
    : "";

  $("kbRows").innerHTML = cards.cards.map((c) => `
    <div class="row">
      <div><b>${esc(c.title)}</b> <span class="muted">${esc(c.kb_id)}</span>
        ${c.staleness ? `<span class="chip stop">${esc(c.staleness.replace("_", " "))}</span>` : ""}
        ${c.edit_survival != null ? `<span class="chip">survival ${esc(c.edit_survival)}</span>` : ""}
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
  const res = await fetch(`/api/kb/proposals/${id}/decide`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ decision }),
  });
  if (!res.ok) { alert((await res.json()).detail); return; }
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
  const data = await fetch(bench ? "/api/telemetry/bench" : "/api/telemetry")
    .then((r) => r.json());

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

async function routeFromHash() {
  const r = location.hash.match(/^#\/review\/(.+)$/);
  if (REVIEW_PID && !(r && r[1] === REVIEW_PID)) flushReviewEffort();
  if (r) { showView("review"); await loadReview(r[1]); return; }
  const m = location.hash.match(/^#\/pursuit\/(.+)$/);
  if (m) { showView("detail"); await loadDetail(m[1]); return; }
  if (location.hash.startsWith("#/pings")) {
    showView("pings"); await loadPingInbox(); return;
  }
  if (location.hash.startsWith("#/kb")) { showView("kb"); await loadKb(); return; }
  if (location.hash.startsWith("#/assistant")) {
    showView("assistant"); await loadAssistant(); return;
  }
  if (location.hash.startsWith("#/telemetry")) {
    showView("telemetry"); await loadTelemetry("system"); return;
  }
  showView("board"); await loadBoard();
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
  if ($("telBench")) $("telBench").onclick = () => loadTelemetry("bench");
  document.querySelectorAll("#mainNav a").forEach((a) =>
    a.onclick = () => document.querySelectorAll("#mainNav a").forEach((x) =>
      x.classList.toggle("active", x === a)));
}
wireNavExtras();

window.addEventListener("hashchange", routeFromHash);
bootSession().then(routeFromHash);

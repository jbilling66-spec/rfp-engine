/* The guest review page (P27 wave 1, B110). The SAME URL that serves
   this shell serves the guest's JSON model to an API caller; the shell
   is static and never resolves the token — this page's own fetch is the
   one access-logged view. Thin: the server has already stripped every
   internal (waiver names, costs, pending internals); this file renders
   what it is handed. esc() wraps EVERY interpolation. */
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
}[c]));
const MARK_COLOR = { block: "stop", review: "draft", advisory: "plan",
                     waived: "draft", ok: "done" };

function toast(msg, sticky = false) {
  const t = $("toast");
  t.textContent = msg;
  t.classList.toggle("sticky", sticky);
  t.hidden = false;
  if (!sticky) setTimeout(() => { t.hidden = true; }, 3200);
  else t.onclick = () => { t.hidden = true; };
}

async function api(path, opts = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json",
               "Accept": "application/json" },
    ...opts,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `${res.status} on ${path}`);
  }
  return res.json();
}

// the guest's two doors, as the door index writes them — the token is
// the page's own path segment, and the JSON model lives at the same URL
const DOORS = { view: "/share/{token}", comments: "/share/{token}/comments" };
const TOKEN = location.pathname.split("/")[2] || "";
const door = (name) => DOORS[name].replace("{token}", encodeURIComponent(TOKEN));

function rememberedName() {
  try { return sessionStorage.getItem("guest_display_name") || ""; }
  catch (e) { return ""; }
}
function rememberName(name) {
  try { sessionStorage.setItem("guest_display_name", name); } catch (e) {}
}

function renderYourComments(list) {
  $("yourComments").hidden = !(list && list.length);
  $("yourCommentRows").innerHTML = (list || []).map((c) => `
    <div class="row"><span class="id">${esc(c.section_id)}</span>
      <span class="meta">${esc(c.display_name)} · ${esc(c.at)}</span>
      <div class="prose">${esc(c.text)}</div></div>`).join("");
}

async function loadGuest() {
  let m;
  try {
    m = await api(door("view"));
  } catch (e) {
    $("shareTitle").textContent = "This link cannot be opened";
    $("shareError").hidden = false;
    $("shareError").textContent = e.message;
    return;
  }
  $("shareTitle").textContent = `${m.pursuit_id} — revision ${m.revision_n}`;
  $("shareHead").hidden = false;
  $("shareHead").innerHTML =
    `shared as <b>${esc(m.share.label)}</b> &middot; link expires ${
      esc(m.share.expires_at)} &middot; validated ${esc(m.validated_at)}`;
  $("shareNote").hidden = false;
  const name = rememberedName();
  $("shareSections").innerHTML = m.sections.map((s) => `
    <div class="row" data-sid="${esc(s.section_id)}">
      <b>${esc(s.title)}</b>
      ${(s.slots || []).map((sl) =>
        `<div class="prose">${esc(sl.prose)}</div>`).join("")}
      ${(s.marks || []).map((k) => `
        <div class="mark">
          <span class="chip ${esc(MARK_COLOR[k.mark] || "plan")}">${esc(k.mark)}</span>
          <span class="line">${esc(k.line)}</span>
        </div>`).join("")}
      <div class="commentbox guestbox">
        <input class="gname" maxlength="60" placeholder="your name"
               value="${esc(name)}">
        <input class="gcmt" maxlength="2000" placeholder="your comment on this section">
        <button class="gGo" data-sid="${esc(s.section_id)}">Send comment</button>
      </div>
    </div>`).join("");
  renderYourComments(m.your_comments);
  for (const btn of document.querySelectorAll(".gGo")) {
    btn.onclick = () => postComment(btn);
  }
}

async function postComment(btn) {
  const box = btn.closest(".guestbox");
  const display_name = box.querySelector(".gname").value.trim();
  const text = box.querySelector(".gcmt").value;
  btn.disabled = true;
  try {
    const out = await api(door("comments"), {
      method: "POST",
      body: JSON.stringify({ display_name, text,
                             section_id: btn.dataset.sid }),
    });
    rememberName(display_name);
    box.querySelector(".gcmt").value = "";
    toast(out.note || `comment ${out.cid} recorded`, true);
    await loadGuest();
  } catch (e) { toast(e.message, true); }
  finally { btn.disabled = false; }
}

loadGuest();

// Architecture #125: the synthetic Project 3 to-do page for first_app_p3.py's controls, written from Product's
// FINAL v3.1 (c2a5ddbd) S3-S6 and QA #32's rows (specs-rows.json d7690a0e). Not a build. The checker replaces the
// one VARIANT line to plant one fault per control copy; "clean" must PASS every row it runs.
//   Row plants (QA's W builds, same faults):
//   inner_html        W1: item text set through innerHTML (E-5)
//   utf16_length      W2: limits counted with s.length, not code points (UNI-UI, L3)
//   no_dir_auto       W3: no dir=auto on item text and the who-name (UNI-UI rtl)
//   idle_callback     W4: the list renders only through requestIdleCallback, no fallback (WebKit J-2; conditional)
//   no_banner         W5: a write that gets no answer is put back with no M6 banner (D-2)
//   no_live_busy      W6: busy texts in plain non-live elements, no A5/A8/A9 (V3-BUSY)
//   late_pending      W7: pending texts appear about 2 s late (V3-PEND)
//   no_hints          W8: no M16/M17 hints (V3-LIMITS)
//   immediate_delete  W9: Delete sends the DELETE at once, no confirmation step (V3-DEL)
//   empty_on_failure  PL-26: a failed load shows the empty-list text M11 instead of M9 (CR-3)
//   Traffic-gate plants (Security G1: literal *.invalid constants, nothing computed; controls only):
//   plant_worker, plant_websocket, plant_eventsource, plant_beacon, plant_redirect, plant_prefetch
"use strict";
const VARIANT = "clean";

const M = {
  m1: "Type an item first.",
  m2: (n) => `Too long: ${n} characters. The limit is 200.`,
  m4: "Type your name first.",
  m5: (n) => `Too long: ${n} characters. The limit is 50.`,
  m6: "Can't reach the server. Your change could not be confirmed. Reload before retrying.",
  m8: "That item was already deleted.",
  m9: "Can't reach the server. The list couldn't be loaded.",
  m10: "Loading the list…",
  m11: "No items yet. Add the first one above.",
  m12: "Trying again…",
  m13: "Adding…",
  m14: (status) => `The server refused the change (error ${status}).`,
  m15: "This browser won't remember your name after a reload.",
  m16: "Shown next to the items you add. Up to 50 characters. This browser remembers it.",
  m17: "Up to 200 characters.",
  m18: (text) => `Delete "${text}"?`,
  m19: "Saving…",
  m20: "Deleting…",
  a1: "Item added.", a2: "Item deleted.", a3: "List loaded.", a4: "Name saved.", a5: "Adding…",
  a6: "Change saved.", a7: "Loading the list again…", a8: "Saving…", a9: "Deleting…",
};
const NAME_KEY = "todo.name";
const $ = (id) => document.getElementById(id);
const count = (s) => (VARIANT === "utf16_length" ? s.length : Array.from(s).length);
const blank = (s) => s.trim() === "";
const later = (fn) => (VARIANT === "late_pending" ? setTimeout(fn, 2000) : fn());

let name = null;
let items = [];
let listState = "loading"; // loading | failed | ok
let loading = false;
let adding = false;
let bannerSeq = 0;
let openStep = null; // id of the row whose delete confirmation step is open
const busy = new Set();
const rows = new Map();

// ---- requests and the typed success oracle (S5, S6)
function isItem(it) {
  return it !== null && typeof it === "object" && !Array.isArray(it)
    && Object.keys(it).length === 4 && typeof it.id === "number" && Number.isInteger(it.id)
    && typeof it.text === "string" && typeof it.added_by === "string" && typeof it.done === "boolean";
}
function isObject(v) { return v !== null && typeof v === "object" && !Array.isArray(v); }

async function api(method, path, body) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 10000);
  try {
    const opts = { method, cache: "no-store", signal: ctl.signal };
    if (body !== undefined) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
    const r = await fetch(path, opts);
    const text = await r.text();
    let data;
    try { data = JSON.parse(text); } catch (e) { data = undefined; }
    return { status: r.status, data };
  } catch (e) {
    return { status: 0, data: undefined };
  } finally {
    clearTimeout(timer);
  }
}
function serverError(r) {
  return isObject(r.data) && typeof r.data.error === "string" && r.data.error.trim() !== "" ? r.data.error : null;
}

// ---- live regions
let announceTimer = null;
function announce(text) {
  const el = $("announcer");
  clearTimeout(announceTimer);
  if (el.textContent === text) {
    el.textContent = "";
    setTimeout(() => { el.textContent = text; }, 100);
  } else {
    el.textContent = text;
  }
  announceTimer = setTimeout(() => { if (el.textContent === text) el.textContent = ""; }, 5000);
}
function busyAnnounce(text) { if (VARIANT !== "no_live_busy") announce(text); }
function clearBusyAnnouncement(text) { if ($("announcer").textContent === text) $("announcer").textContent = ""; }
function setBanner(text) { bannerSeq += 1; $("banner").textContent = text; }
function clearBannerAfter(seqAtStart) { if (bannerSeq === seqAtStart) $("banner").textContent = ""; }
function setNotice(text) { $("notice").textContent = text; }
function writeFailed() { if (VARIANT !== "no_banner") setBanner(M.m6); }

// ---- who line and name form
function validName(s) { return typeof s === "string" && !blank(s) && count(s) <= 50; }
function showWho() {
  $("whoami-name").textContent = name;
  if (VARIANT === "no_dir_auto") $("whoami-name").removeAttribute("dir");
  $("whoami").hidden = false;
  $("name-form").hidden = true;
}
function openNameForm(first) {
  $("whoami").hidden = true;
  $("name-form").hidden = false;
  $("name-cancel").hidden = first;
  $("name-box").value = first ? "" : name;
  setFieldMsg("name", "");
  $("name-box").focus();
  if (!first) $("name-box").select();
}
function setFieldMsg(which, text) {
  $(`${which}-msg`).textContent = text;
  if (text) $(`${which}-box`).setAttribute("aria-invalid", "true");
  else $(`${which}-box`).removeAttribute("aria-invalid");
}
function remember(s) {
  try { localStorage.setItem(NAME_KEY, s); $("storage-note").hidden = true; }
  catch (e) { $("storage-note").textContent = M.m15; $("storage-note").hidden = false; }
}

// ---- rows (keyed by id, updated in place)
function makeRow(item) {
  const id = item.id;
  const li = document.createElement("li");
  li.dataset.id = String(id);
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.id = `cb-${id}`;
  const label = document.createElement("label");
  label.htmlFor = cb.id;
  label.className = "item-text";
  label.id = `text-${id}`;
  if (VARIANT !== "no_dir_auto") label.dir = "auto";
  const by = document.createElement("span");
  by.className = "item-by";
  by.id = `by-${id}`;
  const bdi = document.createElement("bdi");
  bdi.className = "item-by-name";
  by.append("added by ", bdi);
  cb.setAttribute("aria-describedby", by.id);
  const status = document.createElement("span");
  status.className = "item-status";
  status.id = `st-${id}`;
  if (VARIANT !== "no_live_busy") status.setAttribute("role", "status");
  const del = document.createElement("button");
  del.type = "button";
  del.className = "delete";
  del.textContent = "Delete";
  const yes = document.createElement("button");
  yes.type = "button";
  yes.className = "confirm";
  yes.textContent = "Yes, delete";
  yes.setAttribute("aria-describedby", status.id);
  yes.hidden = true;
  const keep = document.createElement("button");
  keep.type = "button";
  keep.className = "keep";
  keep.textContent = "Keep";
  keep.setAttribute("aria-describedby", status.id);
  keep.hidden = true;
  cb.addEventListener("click", (ev) => {
    if (busy.has(id)) { ev.preventDefault(); return; }
    toggle(id, cb.checked);
  });
  del.addEventListener("click", () => {
    if (busy.has(id)) return;
    if (VARIANT === "immediate_delete") confirmDelete(id); else openDeleteStep(id);
  });
  keep.addEventListener("click", () => { if (!busy.has(id)) closeDeleteStep(id, true); });
  yes.addEventListener("click", () => { if (!busy.has(id)) confirmDelete(id); });
  li.addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && openStep === id && !busy.has(id) && !ev.isComposing) closeDeleteStep(id, true);
  });
  li.append(cb, label, by, status, del, yes, keep);
  const r = { li, cb, label, bdi, status, del, yes, keep, item: null };
  rows.set(id, r);
  updateRow(r, item);
  return r;
}
function updateRow(r, item) {
  r.item = item;
  if (VARIANT === "inner_html") r.label.innerHTML = item.text; else r.label.textContent = item.text;
  r.bdi.textContent = item.added_by;
  r.cb.checked = item.done;
  r.li.classList.toggle("done", item.done);
  r.del.setAttribute("aria-label", `Delete ${item.text}`);
  r.yes.setAttribute("aria-label", `Yes, delete ${item.text}`);
  r.keep.setAttribute("aria-label", `Keep ${item.text}`);
}
function renderList() {
  const ul = $("list");
  const status = $("list-status");
  const failed = listState === "failed" && VARIANT !== "empty_on_failure";
  $("load-failed").hidden = !failed;
  if (listState === "loading") { status.textContent = rows.size ? "" : M.m10; return; }
  if (listState === "failed") {
    if (VARIANT === "empty_on_failure") { status.textContent = M.m11; for (const r of rows.values()) r.li.remove(); rows.clear(); }
    else { status.textContent = ""; $("load-failed-text").textContent = M.m9; ul.hidden = true; }
    return;
  }
  ul.hidden = false;
  const keepIds = new Set(items.map((x) => x.id));
  for (const [id, r] of rows) if (!keepIds.has(id)) { r.li.remove(); rows.delete(id); }
  let prev = null;
  for (const item of items) {
    const r = rows.get(item.id) || makeRow(item);
    if (r.item !== item) updateRow(r, item);
    if (prev ? prev.nextSibling !== r.li : ul.firstChild !== r.li) {
      if (prev) prev.after(r.li); else ul.prepend(r.li);
    }
    prev = r.li;
  }
  status.textContent = items.length ? "" : M.m11;
}
function showList() { if (VARIANT === "idle_callback") requestIdleCallback(renderList); else renderList(); }
function focusAfterRemoval(index) {
  const list = [...rows.values()].map((r) => r.cb);
  if (list[index]) list[index].focus(); else if (list.length) list[list.length - 1].focus(); else $("item-box").focus();
}

// ---- loading
async function load(fromTryAgain) {
  if (loading) return null;
  loading = true;
  const wasFailed = listState === "failed";
  if (wasFailed) {
    $("load-failed-text").textContent = "";
    $("try-again").textContent = M.m12;
    $("try-again").setAttribute("aria-disabled", "true");
    announce(M.a7);
  } else if (!rows.size) {
    listState = "loading";
    showList();
  }
  const seq = bannerSeq;
  const r = await api("GET", "/api/items");
  loading = false;
  $("try-again").textContent = "Try again";
  $("try-again").removeAttribute("aria-disabled");
  const ok = r.status >= 200 && r.status < 300 && isObject(r.data) && Array.isArray(r.data.items)
    && r.data.items.every(isItem);
  if (ok) {
    items = r.data.items.slice().sort((a, b) => a.id - b.id);
    listState = "ok";
    showList();
    if (fromTryAgain) { clearBannerAfter(seq); $("item-box").focus(); }
    announce(M.a3);
    return true;
  }
  const hadFocus = $("list-area").contains(document.activeElement);
  listState = "failed";
  showList();
  const err = r.status >= 400 && r.status < 500 ? serverError(r) : null;
  if (err !== null) $("load-failed-text").textContent = err;
  if (hadFocus) $("try-again").focus();
  return false;
}

// ---- writes
async function addItem(text) {
  adding = true;
  later(() => { if (adding) { $("add-button").textContent = M.m13; } });
  $("add-button").disabled = true;
  $("item-box").readOnly = true;
  busyAnnounce(M.a5);
  setNotice("");
  const seq = bannerSeq;
  const r = await api("POST", "/api/items", { text, added_by: name });
  adding = false;
  $("add-button").textContent = "Add";
  $("add-button").disabled = false;
  $("item-box").readOnly = false;
  if (r.status >= 200 && r.status < 300 && isObject(r.data) && isItem(r.data.item)) {
    clearBannerAfter(seq);
    $("item-box").value = "";
    setFieldMsg("item", "");
    if (listState !== "ok") await load(false);
    else { items.push(r.data.item); showList(); }
    announce(M.a1);
  } else if (r.status >= 400 && r.status < 500) {
    clearBusyAnnouncement(M.a5);
    setFieldMsg("item", serverError(r) || M.m14(r.status));
  } else {
    clearBusyAnnouncement(M.a5);
    writeFailed();
  }
  $("item-box").focus();
}

async function toggle(id, done) {
  const r0 = rows.get(id);
  busy.add(id);
  r0.li.setAttribute("aria-busy", "true");
  later(() => { if (busy.has(id)) r0.status.textContent = M.m19; });
  busyAnnounce(M.a8);
  setNotice("");
  const seq = bannerSeq;
  const r = await api("PATCH", `/api/items/${id}`, { done });
  busy.delete(id);
  r0.li.removeAttribute("aria-busy");
  r0.status.textContent = "";
  if (r.status >= 200 && r.status < 300 && isObject(r.data) && isItem(r.data.item) && r.data.item.id === id) {
    items = items.map((x) => (x.id === id ? r.data.item : x));
    clearBannerAfter(seq);
    showList();
    announce(M.a6);
    return;
  }
  clearBusyAnnouncement(M.a8);
  r0.cb.checked = r0.item.done;
  if (r.status === 404) {
    const before = [...rows.keys()].indexOf(id);
    if (await load(false)) { clearBannerAfter(seq); setNotice(M.m8); if (!rows.has(id)) focusAfterRemoval(before); }
  } else if (r.status >= 400 && r.status < 500) {
    setBanner(serverError(r) || M.m14(r.status));
  } else {
    writeFailed();
  }
}

function openDeleteStep(id) {
  if (openStep !== null && openStep !== id && rows.has(openStep)) closeDeleteStep(openStep, false);
  const r = rows.get(id);
  openStep = id;
  r.status.textContent = M.m18(r.item.text);
  r.del.hidden = true;
  r.yes.hidden = false;
  r.keep.hidden = false;
  r.keep.focus();
}
function closeDeleteStep(id, focusDelete) {
  const r = rows.get(id);
  if (openStep === id) openStep = null;
  r.status.textContent = "";
  r.yes.hidden = true;
  r.keep.hidden = true;
  r.yes.removeAttribute("aria-disabled");
  r.keep.removeAttribute("aria-disabled");
  r.del.hidden = false;
  if (focusDelete) r.del.focus();
}
async function confirmDelete(id) {
  const r0 = rows.get(id);
  busy.add(id);
  r0.li.setAttribute("aria-busy", "true");
  r0.yes.setAttribute("aria-disabled", "true");
  r0.keep.setAttribute("aria-disabled", "true");
  if (VARIANT === "late_pending") r0.status.textContent = "";
  later(() => { if (busy.has(id)) r0.status.textContent = M.m20; });
  busyAnnounce(M.a9);
  setNotice("");
  const seq = bannerSeq;
  const index = [...rows.keys()].indexOf(id);
  const r = await api("DELETE", `/api/items/${id}`);
  busy.delete(id);
  r0.li.removeAttribute("aria-busy");
  if (r.status >= 200 && r.status < 300 && isObject(r.data) && r.data.deleted === id) {
    if (openStep === id) openStep = null;
    items = items.filter((x) => x.id !== id);
    clearBannerAfter(seq);
    showList();
    announce(M.a2);
    focusAfterRemoval(index);
    return;
  }
  clearBusyAnnouncement(M.a9);
  closeDeleteStep(id, true);
  if (r.status === 404) {
    if (await load(false)) { clearBannerAfter(seq); setNotice(M.m8); if (!rows.has(id)) focusAfterRemoval(index); }
  } else if (r.status >= 400 && r.status < 500) {
    setBanner(serverError(r) || M.m14(r.status));
  } else {
    writeFailed();
  }
}

// ---- traffic-gate plants (controls only; literal constants, G1)
// The page marks what it tried on <html data-plant>: "sent", "unsupported" (the engine lacks the feature: the
// kind is not exercised) or "error:<name>". The mark is DOM only; the checker reads it to tell a MISS (sent, the
// gate did not see it) from a kind this engine never sends.
function plants() {
  if (!VARIANT.startsWith("plant_")) return;
  const mark = (state) => { document.documentElement.dataset.plant = state; };
  try {
    if (VARIANT === "plant_worker") {
      if (typeof Worker !== "function") return mark("unsupported");
      const code = "fetch('https://worker.invalid/w').catch(function () {});";
      new Worker(URL.createObjectURL(new Blob([code], { type: "text/javascript" })));
    } else if (VARIANT === "plant_websocket") {
      if (typeof WebSocket !== "function") return mark("unsupported");
      new WebSocket("wss://websocket.invalid/s");
    } else if (VARIANT === "plant_eventsource") {
      if (typeof EventSource !== "function") return mark("unsupported");
      const es = new EventSource("https://eventsource.invalid/e");
      es.onerror = () => es.close();
    } else if (VARIANT === "plant_beacon") {
      if (typeof navigator.sendBeacon !== "function") return mark("unsupported");
      if (!navigator.sendBeacon("https://beacon.invalid/b")) return mark("unsupported");
    } else if (VARIANT === "plant_redirect") {
      fetch("/plant-redirect", { cache: "no-store" }).catch(() => {});
    } else if (VARIANT === "plant_prefetch") {
      const link = document.createElement("link");
      const known = !!(link.relList && link.relList.supports && link.relList.supports("prefetch"));
      link.rel = "prefetch";
      link.href = "https://prefetch.invalid/p";
      document.head.append(link);
      if (!known) return mark("unsupported");
    }
    mark("sent");
  } catch (e) {
    mark("error:" + (e && e.name ? e.name : "Error"));
  }
}

// ---- start
function start() {
  if (VARIANT === "no_hints") { $("name-hint").remove(); $("item-hint").remove(); }
  else { $("name-hint").textContent = M.m16; $("item-hint").textContent = M.m17; }
  $("name-box").setAttribute("aria-describedby", VARIANT === "no_hints" ? "name-msg" : "name-hint name-msg");
  $("item-box").setAttribute("aria-describedby", VARIANT === "no_hints" ? "item-msg" : "item-hint item-msg");
  let stored = null;
  try { stored = localStorage.getItem(NAME_KEY); } catch (e) { stored = null; }
  if (validName(stored)) { name = stored; showWho(); $("app").hidden = false; }
  else openNameForm(true);

  $("name-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const s = $("name-box").value;
    if (blank(s)) { setFieldMsg("name", M.m4); return; }
    const n = count(s);
    if (n > 50) { setFieldMsg("name", M.m5(n)); return; }
    const first = name === null;
    name = s;
    remember(s);
    setFieldMsg("name", "");
    showWho();
    if (first) {
      $("app").hidden = false;
      $("item-box").focus();
      if (listState === "failed") announce(M.m9);
    } else {
      $("change-name").focus();
      announce(M.a4);
    }
  });
  $("name-box").addEventListener("input", () => {
    const s = $("name-box").value;
    const msg = $("name-msg").textContent;
    if ((msg === M.m4 && !blank(s)) || (msg.startsWith("Too long: ") && count(s) <= 50)) setFieldMsg("name", "");
  });
  const cancel = () => { setFieldMsg("name", ""); showWho(); $("change-name").focus(); };
  $("name-cancel").addEventListener("click", cancel);
  $("name-box").addEventListener("keydown", (ev) => {
    if (ev.key === "Escape" && !ev.isComposing && name !== null) cancel();
  });
  $("change-name").addEventListener("click", () => openNameForm(false));

  $("add-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    if (adding) return;
    const s = $("item-box").value;
    if (blank(s)) { setFieldMsg("item", M.m1); return; }
    const n = count(s);
    if (n > 200) { setFieldMsg("item", M.m2(n)); return; }
    addItem(s);
  });
  $("item-box").addEventListener("input", () => {
    const s = $("item-box").value;
    const msg = $("item-msg").textContent;
    if (!msg) return;
    if (msg === M.m1) { if (!blank(s)) setFieldMsg("item", ""); }
    else if (msg.startsWith("Too long: ")) { if (count(s) <= 200) setFieldMsg("item", ""); }
    else setFieldMsg("item", "");
  });
  $("try-again").addEventListener("click", () => {
    if ($("try-again").getAttribute("aria-disabled") === "true") return;
    setNotice("");
    load(true);
  });
  load(false).then(plants);
}

start();

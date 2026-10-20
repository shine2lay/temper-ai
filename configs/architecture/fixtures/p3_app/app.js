// Architecture #124: the synthetic Project-3-style to-do page for first_app_p3.py's controls (PENDING-SPEC:
// written from Product's FINAL-13ccada4 S3/S4, not QA's frozen kit). The checker replaces the VARIANT line to
// plant one fault per control copy; "clean" must PASS every row.
//   inner_html    item text set through innerHTML (F11 / UNI-UI)
//   utf16_length  limits counted with s.length, not code points (UNI limits)
//   fixed_600     a fixed 600 px wide page (PH-2 at phone size)
//   no_dir_auto   no dir=auto on item text and the who-name (UNI-UI right-to-left)
//   idle_callback start() scheduled with requestIdleCallback, which WebKit lacks (PH-1)
//   no_banner     no M6 banner when a write gets no answer (CR-3)
//   no_put_back   M6 shown, but the typed text is not put back in the box (CR-3)
"use strict";
const VARIANT = "clean";

const M = {
  itemBlank: "Type an item first.",
  itemTooLong: (n) => `Too long: ${n} characters. The limit is 200.`,
  nameBlank: "Type your name first.",
  nameTooLong: (n) => `Too long: ${n} characters. The limit is 50.`,
  unreachable: "Can't reach the server. Your change could not be confirmed. Reload before retrying.",
  deleted: "That item was already deleted.",
  loadFailed: "Can't reach the server. The list couldn't be loaded.",
};
const $ = (id) => document.getElementById(id);
const count = (s) => (VARIANT === "utf16_length" ? s.length : Array.from(s).length);
const NAME_KEY = "p3-todo-name";

let name = null;
let items = [];
let listState = "loading"; // loading | failed | ok
let loadingNow = false;
let adding = false;

function valid(it) {
  return !!it && Number.isInteger(it.id) && typeof it.text === "string" && typeof it.added_by === "string"
    && typeof it.done === "boolean";
}

async function api(method, path, body) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), 10000);
  try {
    const r = await fetch(path, {
      method, cache: "no-store", signal: ctl.signal,
      headers: body === undefined ? {} : { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    return { status: r.status, data };
  } catch (e) {
    return { status: 0, data: null };
  } finally {
    clearTimeout(timer);
  }
}

function announce(text) {
  $("announcer").textContent = "";
  setTimeout(() => { $("announcer").textContent = text; }, 50);
}

function showBanner(text) { $("banner").textContent = text; $("banner").hidden = false; }
function clearBanner() { $("banner").textContent = ""; $("banner").hidden = true; }
function showNotice(text) { $("notice").textContent = text; $("notice").hidden = !text; }

function writeFailed(putBack) {
  if (VARIANT !== "no_banner") showBanner(M.unreachable);
  if (putBack !== undefined) $("item-box").value = VARIANT === "no_put_back" ? "" : putBack;
  $("item-box").focus();
}

function row(item) {
  const li = document.createElement("li");
  li.dataset.id = String(item.id);
  if (item.done) li.classList.add("done");
  const cb = document.createElement("input");
  cb.type = "checkbox";
  cb.id = `cb-${item.id}`;
  cb.checked = item.done;
  const text = document.createElement("span");
  text.className = "item-text";
  text.id = `text-${item.id}`;
  if (VARIANT === "inner_html") text.innerHTML = item.text; else text.textContent = item.text;
  if (VARIANT !== "no_dir_auto") text.dir = "auto";
  const by = document.createElement("span");
  by.className = "item-by";
  by.id = `by-${item.id}`;
  by.append("added by ");
  const bdi = document.createElement("bdi");
  bdi.textContent = item.added_by;
  by.append(bdi);
  cb.setAttribute("aria-labelledby", text.id);
  cb.setAttribute("aria-describedby", by.id);
  const del = document.createElement("button");
  del.type = "button";
  del.textContent = "Delete";
  del.setAttribute("aria-label", `Delete ${item.text}`);
  cb.addEventListener("click", (ev) => { ev.preventDefault(); toggle(item.id, !item.done); });
  del.addEventListener("click", () => remove(item.id));
  li.append(cb, text, by, del);
  return li;
}

function render() {
  $("loading").hidden = listState !== "loading";
  $("load-failed").hidden = listState !== "failed";
  $("load-failed-text").textContent = listState === "failed" ? M.loadFailed : "";
  $("empty").hidden = !(listState === "ok" && items.length === 0);
  const ul = $("list");
  ul.replaceChildren(...(listState === "ok" ? items.map(row) : []));
}

function showApp() {
  $("name-form").hidden = true;
  $("app").hidden = false;
  $("who-name").textContent = name;
  if (VARIANT === "no_dir_auto") $("who-name").removeAttribute("dir");
  render();
}

function showNameForm(current) {
  $("app").hidden = true;
  $("name-form").hidden = false;
  $("name-box").value = current || "";
  $("name-msg").textContent = "";
  $("name-box").focus();
}

async function load(fromTryAgain) {
  if (loadingNow) return;
  loadingNow = true;
  const wasFailed = listState === "failed";
  if (wasFailed) {
    $("try-again").textContent = "Trying again…";
    $("try-again").setAttribute("aria-disabled", "true");
    $("load-failed-text").textContent = "";
  }
  $("list-area").setAttribute("aria-busy", "true");
  const r = await api("GET", "/api/items");
  $("list-area").removeAttribute("aria-busy");
  $("try-again").textContent = "Try again";
  $("try-again").removeAttribute("aria-disabled");
  loadingNow = false;
  if (r.status === 200 && r.data && Array.isArray(r.data.items) && r.data.items.every(valid)) {
    items = r.data.items;
    listState = "ok";
    render();
    if (wasFailed) {
      announce("List loaded.");
      if (fromTryAgain) { clearBanner(); $("item-box").focus(); }
    }
    return true;
  }
  listState = "failed";
  render();
  return false;
}

async function toggle(id, done) {
  const r = await api("PATCH", `/api/items/${id}`, { done });
  if (r.status === 200 && r.data && valid(r.data.item)) {
    items = items.map((x) => (x.id === id ? r.data.item : x));
    clearBanner();
    render();
  } else if (r.status === 404) {
    if (await load(false)) showNotice(M.deleted);
  } else {
    writeFailed();
  }
}

async function remove(id) {
  const r = await api("DELETE", `/api/items/${id}`);
  if (r.status === 200) {
    items = items.filter((x) => x.id !== id);
    clearBanner();
    render();
    announce("Item deleted.");
    $("item-box").focus();
  } else if (r.status === 404) {
    if (await load(false)) showNotice(M.deleted);
  } else {
    writeFailed();
  }
}

function start() {
  if (VARIANT === "fixed_600") document.querySelector("main").style.width = "600px";
  try { name = localStorage.getItem(NAME_KEY); } catch (e) { name = null; }
  if (name) showApp(); else showNameForm("");

  $("name-form").addEventListener("submit", (ev) => {
    ev.preventDefault();
    const s = $("name-box").value;
    $("name-msg").textContent = "";
    if (s.trim() === "") { $("name-msg").textContent = M.nameBlank; return; }
    const n = count(s);
    if (n > 50) { $("name-msg").textContent = M.nameTooLong(n); return; }
    name = s;
    try { localStorage.setItem(NAME_KEY, s); } catch (e) { /* M15 is not part of these controls */ }
    showApp();
    $("item-box").focus();
  });

  $("change-name").addEventListener("click", () => showNameForm(name));

  $("add-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    if (adding) return;
    const s = $("item-box").value;
    $("item-msg").textContent = "";
    if (s.trim() === "") { $("item-msg").textContent = M.itemBlank; return; }
    const n = count(s);
    if (n > 200) { $("item-msg").textContent = M.itemTooLong(n); return; }
    adding = true;
    $("add-button").textContent = "Adding…";
    $("add-form").setAttribute("aria-busy", "true");
    const r = await api("POST", "/api/items", { text: s, added_by: name });
    adding = false;
    $("add-button").textContent = "Add";
    $("add-form").removeAttribute("aria-busy");
    if (r.status === 201 && r.data && valid(r.data.item)) {
      clearBanner();
      $("item-box").value = "";
      if (listState !== "ok") await load(false); else { items.push(r.data.item); render(); }
      announce("Item added.");
      $("item-box").focus();
    } else if (r.status >= 400 && r.status < 500) {
      $("item-msg").textContent = (r.data && r.data.error) || M.unreachable;
    } else {
      writeFailed(s);
    }
  });

  $("try-again").addEventListener("click", () => {
    if ($("try-again").getAttribute("aria-disabled") === "true") return;
    load(true);
  });

  load(false);
}

if (VARIANT === "idle_callback") requestIdleCallback(start, { timeout: 50 }); else start();

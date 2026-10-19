// Synthetic shared to-do page for first_app_check's controls (System architecture, queue #97). Written from QA's
// kit qa-project2-critical-v1 (its wording) and Project 2's page structure (ids, roles, labels, /api/items); not
// the team's code. first_app_shared.materialize sets VARIANT (one seeded defect) and OUTSIDE (the font address of
// variant outside_font); "clean" is the working page. Server-side defects (memory only, delete not saved, author
// not stored) live in the synthetic server, not here.
(function () {
  'use strict';

  const VARIANT = "clean";
  const OUTSIDE = "";
  const NAME_KEY = 'todo.name';
  const LOCAL_KEY = 'todo.items'; // local_only: the list kept in this browser
  const NAME_MAX = 50;
  const TEXT_MAX = 200;
  const TIMEOUT_MS = 10000;
  const TEXT = {
    itemBlank: 'Type an item first.',
    itemTooLong: (n) => `Too long: ${n} characters. The limit is 200.`,
    nameBlank: 'Type your name first.',
    nameTooLong: (n) => `Too long: ${n} characters. The limit is 50.`,
    unreachable: "Can't reach the server. Your change was not saved.",
    loadFailed: "Can't reach the server. The list couldn't be loaded.",
    add: 'Add',
    adding: 'Adding…',
  };
  const state = { name: null, items: [], loaded: false, error: false, adding: false, tmp: 0 };
  let els = null;

  function byId(id) {
    return document.getElementById(id);
  }

  function init() {
    els = {
      banner: byId('banner'), nameForm: byId('name-form'), nameInput: byId('name-input'), nameMsg: byId('name-msg'),
      listView: byId('list-view'), whoamiName: byId('whoami-name'), addForm: byId('add-form'),
      itemInput: byId('item-input'), addButton: byId('add-button'), itemMsg: byId('item-msg'),
      listLoading: byId('list-loading'), loadError: byId('load-error'), loadErrorText: byId('load-error-text'),
      listEmpty: byId('list-empty'), list: byId('items'),
    };
    if (OUTSIDE) { // outside_font: a font from another origin
      const style = document.createElement('style');
      style.textContent = '@font-face { font-family: "Outside"; src: url("' + OUTSIDE + '"); } ' +
        'body { font-family: "Outside", system-ui, sans-serif; }';
      document.head.appendChild(style);
      if (document.fonts && document.fonts.load) document.fonts.load('16px "Outside"').catch(() => {});
    }
    els.nameForm.addEventListener('submit', onNameSubmit);
    els.addForm.addEventListener('submit', onAddSubmit);
    els.list.addEventListener('change', onListChange);
    els.list.addEventListener('click', onListClick);

    const saved = readName();
    if (saved !== null && saved.trim() !== '' && count(saved) <= NAME_MAX) {
      setName(saved);
      showList();
    } else {
      showNameForm();
    }
    loadItems();
  }

  // ---------------------------------------------------------------- text helpers

  function count(text) {
    return Array.from(text).length;
  }

  function setText(el, text) {
    while (el.firstChild) el.removeChild(el.firstChild);
    if (text) el.appendChild(document.createTextNode(text));
  }

  // Names and item texts go in as text; html_rendered puts them in as HTML.
  function put(el, text) {
    if (VARIANT === 'html_rendered') el.innerHTML = text;
    else el.textContent = text;
  }

  function showBanner(text) {
    setText(els.banner, text);
  }

  function clearBanner() {
    setText(els.banner, '');
  }

  // ---------------------------------------------------------------- name

  function readName() {
    try {
      return window.localStorage.getItem(NAME_KEY);
    } catch (error) {
      return null;
    }
  }

  function storeName(name) {
    if (VARIANT === 'name_forgotten') return; // not remembered after a reload
    try {
      window.localStorage.setItem(NAME_KEY, name);
    } catch (error) {
      // blocked: this visit only
    }
  }

  function setName(name) {
    state.name = name;
    put(els.whoamiName, name);
  }

  function showNameForm() {
    els.listView.hidden = true;
    els.nameForm.hidden = false;
    els.nameInput.value = '';
    els.nameInput.focus();
  }

  function showList() {
    els.listView.hidden = false;
    render();
  }

  function onNameSubmit(event) {
    event.preventDefault();
    const name = els.nameInput.value;
    if (name.trim() === '') {
      setText(els.nameMsg, TEXT.nameBlank);
      return;
    }
    if (count(name) > NAME_MAX) {
      setText(els.nameMsg, TEXT.nameTooLong(count(name)));
      return;
    }
    storeName(name);
    setName(name);
    setText(els.nameMsg, '');
    els.nameForm.hidden = true;
    showList();
    els.itemInput.focus();
  }

  // ---------------------------------------------------------------- the server, or this browser (local_only)

  async function api(method, url, body) {
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const options = { method, headers: { Accept: 'application/json' }, cache: 'no-store', signal: controller.signal };
      if (body !== undefined) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(body);
      }
      const response = await fetch(url, options);
      let data = null;
      try {
        data = await response.json();
      } catch (error) {
        data = null;
      }
      if (response.status >= 500) return { ok: false, status: response.status, data: null };
      return { ok: response.ok, status: response.status, data };
    } catch (error) {
      return { ok: false, status: 0, data: null };
    } finally {
      window.clearTimeout(timer);
    }
  }

  function readLocal() {
    try {
      const items = JSON.parse(window.localStorage.getItem(LOCAL_KEY) || '[]');
      return Array.isArray(items) ? items : [];
    } catch (error) {
      return [];
    }
  }

  function writeLocal(items) {
    try {
      window.localStorage.setItem(LOCAL_KEY, JSON.stringify(items));
    } catch (error) {
      // blocked: this visit only
    }
  }

  function toItem(raw) {
    return { id: raw.id, text: String(raw.text), added_by: String(raw.added_by), done: raw.done === true || raw.done === 1 };
  }

  function find(id) {
    return state.items.find((x) => String(x.id) === String(id)) || null;
  }

  async function loadItems() {
    if (VARIANT === 'local_only') {
      state.items = readLocal();
      state.loaded = true;
      render();
      return;
    }
    const result = await api('GET', '/api/items');
    if (result.ok && result.data && Array.isArray(result.data.items)) {
      state.items = result.data.items.map(toItem);
      state.loaded = true;
      state.error = false;
    } else {
      state.error = true;
    }
    render();
  }

  // ---------------------------------------------------------------- add, tick, delete

  function setAdding(on) {
    state.adding = on;
    els.addButton.disabled = on;
    setText(els.addButton, on ? TEXT.adding : TEXT.add);
    els.itemInput.readOnly = on;
  }

  function tooLong(n) {
    if (VARIANT === 'accept_201') return n > 201;
    if (VARIANT === 'refuse_200') return n >= 200;
    return n > TEXT_MAX;
  }

  async function onAddSubmit(event) {
    event.preventDefault();
    if (state.adding || state.name === null) return;
    const text = els.itemInput.value; // sent exactly as typed
    if (text.trim() === '' && VARIANT !== 'blank_added') {
      setText(els.itemMsg, TEXT.itemBlank);
      els.itemInput.focus();
      return;
    }
    const n = count(text);
    if (tooLong(n)) {
      setText(els.itemMsg, TEXT.itemTooLong(n));
      els.itemInput.focus();
      return;
    }
    setText(els.itemMsg, '');
    if (VARIANT === 'local_only') {
      const items = readLocal();
      const id = items.reduce((m, x) => Math.max(m, Number(x.id) || 0), 0) + 1;
      items.push({ id, text, added_by: state.name, done: false });
      writeLocal(items);
      state.items = items;
      els.itemInput.value = '';
      render();
      els.itemInput.focus();
      return;
    }
    let shown = null;
    if (VARIANT === 'optimistic') { // the row shows before the server answers, and stays if it fails
      state.tmp += 1;
      shown = { id: 'tmp-' + state.tmp, text, added_by: state.name, done: false };
      state.items.push(shown);
      render();
    }
    setAdding(true);
    const result = await api('POST', '/api/items', { text, added_by: state.name });
    setAdding(false);
    const item = result.ok && result.data && result.data.item ? toItem(result.data.item) : null;
    if (!item) {
      showBanner(TEXT.unreachable); // nothing added; the text stays in the box
      els.itemInput.focus();
      return;
    }
    if (shown) state.items = state.items.filter((x) => x !== shown);
    clearBanner();
    els.itemInput.value = '';
    state.items.push(item);
    render();
    els.itemInput.focus();
  }

  async function onListChange(event) {
    const box = event.target;
    if (!box.classList || !box.classList.contains('item-check')) return;
    const row = box.closest('li');
    const item = find(row.dataset.id);
    if (!item) return;
    const done = box.checked;
    if (VARIANT === 'local_only') {
      item.done = done;
      writeLocal(state.items);
      render();
      return;
    }
    if (VARIANT === 'tick_local') { // the page changes; nothing is sent
      item.done = done;
      render();
      return;
    }
    row.setAttribute('aria-busy', 'true');
    const result = await api('PATCH', '/api/items/' + row.dataset.id, { done });
    const fresh = result.ok && result.data && result.data.item ? toItem(result.data.item) : null;
    if (fresh) {
      Object.assign(item, fresh);
      clearBanner();
    } else {
      showBanner(TEXT.unreachable); // the checkbox goes back to the server's state
    }
    render();
  }

  async function onListClick(event) {
    const button = event.target.closest ? event.target.closest('button.delete') : null;
    if (!button) return;
    const row = button.closest('li');
    const id = row.dataset.id;
    if (VARIANT === 'local_only') {
      state.items = state.items.filter((x) => String(x.id) !== id);
      writeLocal(state.items);
      render();
      return;
    }
    row.setAttribute('aria-busy', 'true');
    const result = await api('DELETE', '/api/items/' + id);
    if (result.ok && result.data && result.data.deleted !== undefined) {
      state.items = state.items.filter((x) => String(x.id) !== id);
      clearBanner();
    } else {
      showBanner(TEXT.unreachable); // the row stays
    }
    render();
  }

  // ---------------------------------------------------------------- the list

  function render() {
    els.listLoading.hidden = state.loaded || state.error;
    els.loadError.hidden = !state.error || state.loaded;
    setText(els.loadErrorText, state.error && !state.loaded ? TEXT.loadFailed : '');
    els.listEmpty.hidden = !(state.loaded && state.items.length === 0);
    els.list.hidden = !state.loaded;
    while (els.list.firstChild) els.list.removeChild(els.list.firstChild);
    for (const item of state.items) els.list.appendChild(createRow(item));
  }

  function createRow(item) {
    const id = String(item.id);
    const li = document.createElement('li');
    li.className = 'item' + (item.done ? ' is-done' : '');
    li.dataset.id = id;
    const box = document.createElement('input');
    box.type = 'checkbox';
    box.className = 'item-check';
    box.id = 'item-' + id;
    box.checked = item.done;
    box.setAttribute('aria-describedby', 'item-' + id + '-by');
    const body = document.createElement('div');
    body.className = 'item-body';
    const label = document.createElement('label');
    label.className = 'item-text';
    label.htmlFor = box.id;
    label.dir = 'auto';
    put(label, item.text);
    const by = document.createElement('span');
    by.className = 'item-by';
    by.id = 'item-' + id + '-by';
    by.appendChild(document.createTextNode('added by '));
    const name = document.createElement('bdi');
    name.className = 'item-by-name';
    put(name, VARIANT === 'author_viewer' ? state.name : item.added_by); // author_viewer: the viewer's name
    by.appendChild(name);
    body.append(label, by);
    const del = document.createElement('button');
    del.type = 'button';
    del.className = 'delete';
    del.textContent = 'Delete';
    del.setAttribute('aria-label', 'Delete ' + item.text);
    li.append(box, body, del);
    return li;
  }

  init();
})();

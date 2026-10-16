// Synthetic checker control for first_app_check (Architecture #91). Written from the wording of
// QA's kit qa-first-app-critical-v1, not from the Team's app. The checker rewrites the VARIANT line
// below before serving, to make each broken copy; "clean" must pass all 8 kit steps.
//   clean            works as the kit expects
//   forget_reload    never saves: the list is gone after a reload            -> FAIL at C1-5
//   wrong_order      a new item goes to the top                              -> FAIL at C1-3
//   wrong_focus      after adding, focus goes to Add, not New item           -> FAIL at C1-2
//   page_error       ticking a checkbox throws and leaves it unticked        -> FAIL at C1-4
//   outside_request  asks another origin for an image when the page loads    -> traffic gate FAIL at C1-1
// The delete buttons' word comes from the page (data-delete-word on the list, default "Delete"), so
// fixtures/first_app_reworded/index.html can reword the whole page for the profile controls (#92).
"use strict";
const VARIANT = "clean";
const KEY = "first-app-check-control-items";

const form = document.getElementById("add-form");
const input = document.getElementById("new-item");
const addButton = form.querySelector("button");
const list = document.getElementById("list");
const empty = document.getElementById("empty");
const warning = document.getElementById("warning");
const DELETE_WORD = list.dataset.deleteWord || "Delete";

function load() {
  if (VARIANT === "forget_reload") return [];
  try {
    const items = JSON.parse(localStorage.getItem(KEY) || "[]");
    return Array.isArray(items) ? items : [];
  } catch (e) {
    showWarning();
    return [];
  }
}

function save() {
  if (VARIANT === "forget_reload") return;
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch (e) {
    showWarning();
  }
}

function showWarning() {
  warning.textContent = "Your list could not be saved on this device.";
  warning.hidden = false;
}

function render() {
  list.textContent = "";
  items.forEach((item, i) => {
    const li = document.createElement("li");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.id = "item-" + i;
    box.checked = item.done;
    const label = document.createElement("label");
    label.htmlFor = box.id;
    label.textContent = item.text;
    const del = document.createElement("button");
    del.type = "button";
    del.textContent = DELETE_WORD;
    del.setAttribute("aria-label", DELETE_WORD + " " + item.text);
    if (item.done) li.className = "done";
    box.addEventListener("click", (e) => {
      if (VARIANT === "page_error") {
        e.preventDefault();
        throw new Error("synthetic control: toggle failed");
      }
    });
    box.addEventListener("change", () => {
      items[i].done = box.checked;
      li.className = box.checked ? "done" : "";
      save();
    });
    del.addEventListener("click", () => remove(i));
    li.append(box, label, del);
    list.append(li);
  });
  empty.hidden = items.length > 0;
}

function remove(i) {
  items.splice(i, 1);
  save();
  render();
  const boxes = list.querySelectorAll("input[type=checkbox]");
  const next = boxes[i] || boxes[i - 1];
  (next || input).focus();
}

form.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  const item = { text: text, done: false };
  if (VARIANT === "wrong_order") items.unshift(item);
  else items.push(item);
  save();
  render();
  input.value = "";
  (VARIANT === "wrong_focus" ? addButton : input).focus();
});

if (VARIANT === "outside_request") {
  new Image().src = "http://outside.invalid/pixel.gif";
}

let items = load();
render();

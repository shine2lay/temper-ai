#!/usr/bin/env node
// temper-pi-host auth bridge (ADR-M4-15, SW-82).
//
// temper_pi_host.py starts this as a child process.  It talks JSON lines on its stdin and
// stdout (the private pipe) and nowhere else: it writes no file, no log and nothing on
// stderr of its own.  It hands out a Pi login token for one multi-pass alias slot, read and
// (when due) refreshed through the pinned Pi SDK's own auth storage, the way the owner's
// chats use it:
//   - the alias is registered on the SDK's ModelRuntime with the base provider's built-in
//     OAuth flow under the slot's own auth key, as pi-multi-pass registers it;
//   - the login is read with ModelRuntime.getAuth(slot, { minOAuthValidityMs }), whose
//     refresh runs inside the auth storage's credential-modify path: under auth.json's lock
//     it reads the file again and refreshes only if the login still expires soon, so the
//     chats and this bridge refresh once between them.
// Usage is separate: readStoredCredential for the explicitly named slot, checkAccount from the
// pinned vendor with no refresh callback, no profile lookup, only GET of the fixed usage endpoint.
// Re-read the selected credential afterwards; a change means no reading. Nothing is published.
// No file edits, no second copy of a login, no patching of the SDK.
//
// Version checks.  At start, before importing the SDK, it reads the SDK's package.json from
// disk and refuses (hello ok:false, exit 2) when the package or version is not the expected
// one; the hello names what it loaded.  Before every token, status and usage request it reads the
// versions on disk again and refuses that one request when they changed, before any use of
// auth.json.  The refresh callback checks once more, under the lock, before the network
// refresh.
//
// Arguments (no secrets): --sdk-root <dir holding node_modules> --sdk-package <name>
//   --sdk-version <exact> --ai-version <exact|-> --agent-dir <Pi agent dir>
//   --base-provider <id> --slots <a,b|-> --min-validity-ms <ms> --timeout-ms <ms>
//   --usage-timeout-ms <1..10000> (optional, default 10000; only lowered by offline tests)
// Protocol:
//   hello:   {"bridge":1,"ok":true,"package","version","loaded_version","ai_package","ai_version","node"}
//            {"bridge":1,"ok":false,"reason":"sdk_version_mismatch"|"sdk_unreadable"|"sdk_surface"|"bad_args",...}
//   request: {"id":N,"op":"token","slot":"<slot>"} | {"id":N,"op":"status"}
//            {"id":N,"op":"usage","slot":"<slot>"}
//   answer:  {"id":N,"ok":true,"slot","token"} | {"id":N,"ok":false,"slot","reason",...}
//            {"id":N,"ok":true,"state":"ready"|"sdk_changed"|"sdk_unreadable","slots":{...}}
//            {"id":N,"ok":true,"slot","status":"ok","observed_at","windows":[...]}
//            {"id":N,"ok":true,"slot","status":"unavailable","reason"}

import { createHash } from "node:crypto";
import fs from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import readline from "node:readline";
import { fileURLToPath, pathToFileURL } from "node:url";
import { isDeepStrictEqual } from "node:util";

const AI_PACKAGE = "@earendil-works/pi-ai";
const WORD = /^[A-Za-z0-9_.+:-]{1,64}$/;
const NEEDED = ["sdk-root", "sdk-package", "sdk-version", "agent-dir", "base-provider", "slots",
  "min-validity-ms", "timeout-ms"];

function say(message) {
  process.stdout.write(JSON.stringify(message) + "\n");
}

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i];
    const value = argv[i + 1];
    if (typeof key !== "string" || !key.startsWith("--") || value === undefined) return null;
    out[key.slice(2)] = value;
  }
  return NEEDED.every((key) => out[key]) ? out : null;
}

function escapeRe(text) {
  return text.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

// Stop only between requests (Pi writes auth.json in place); set up before anything else.
let busy = false;
let stopping = false;
process.on("SIGTERM", () => {
  stopping = true;
  if (!busy) process.exit(0);
});
process.on("unhandledRejection", () => {}); // e.g. the SDK's own background availability refresh
process.on("uncaughtException", () => process.exit(70));
process.stdout.on("error", () => process.exit(0));

const args = parseArgs(process.argv.slice(2));
if (!args) {
  say({ bridge: 1, ok: false, reason: "bad_args" });
  process.exit(2);
}
const sdkRoot = args["sdk-root"];
const sdkPackage = args["sdk-package"];
const expectedVersion = args["sdk-version"];
const expectedAi = args["ai-version"] && args["ai-version"] !== "-" ? args["ai-version"] : "";
const agentDir = args["agent-dir"];
const authPath = path.join(agentDir, "auth.json");
const base = args["base-provider"];
const slots = args.slots === "-" ? [] : args.slots.split(",");
const minValidityMs = Number(args["min-validity-ms"]);
const timeoutMs = Number(args["timeout-ms"]);
const usageTimeoutMs = Number(args["usage-timeout-ms"] ?? 10_000);
if (!Number.isInteger(usageTimeoutMs) || usageTimeoutMs < 1 || usageTimeoutMs > 10_000) {
  say({ bridge: 1, ok: false, reason: "bad_args" });
  process.exit(2);
}
const aliasRe = new RegExp(`^${escapeRe(base)}-([2-9]|[1-9][0-9]+)$`);

// --- the SDK on disk ---------------------------------------------------------------------

function readPackage(dir) {
  const real = fs.realpathSync(dir);
  const json = JSON.parse(fs.readFileSync(path.join(real, "package.json"), "utf8"));
  if (typeof json?.name !== "string" || typeof json?.version !== "string") throw new Error("no name or version");
  return { dir: real, json, name: json.name, version: json.version };
}

function aiPackageDir(sdkDir) {
  // Where Node itself finds the providers package from the SDK package.
  const lookup = createRequire(path.join(sdkDir, "package.json")).resolve.paths(AI_PACKAGE) ?? [];
  for (const dir of lookup) {
    const candidate = path.join(dir, ...AI_PACKAGE.split("/"));
    if (fs.existsSync(path.join(candidate, "package.json"))) return candidate;
  }
  throw new Error("no providers package");
}

function onDisk() {
  const sdk = readPackage(path.join(sdkRoot, "node_modules", ...sdkPackage.split("/")));
  const ai = readPackage(aiPackageDir(sdk.dir));
  return { sdk, ai };
}

function pick(entry) {
  if (typeof entry === "string") return entry;
  if (Array.isArray(entry)) {
    for (const item of entry) {
      const target = pick(item);
      if (target) return target;
    }
    return undefined;
  }
  if (entry && typeof entry === "object") {
    for (const condition of ["import", "node", "default"]) {
      if (condition in entry) {
        const target = pick(entry[condition]);
        if (target) return target;
      }
    }
  }
  return undefined;
}

function substitute(value, middle) {
  if (typeof value === "string") return value.split("*").join(middle);
  if (Array.isArray(value)) return value.map((item) => substitute(item, middle));
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, substitute(item, middle)]));
  }
  return value;
}

function exportTarget(pkg, subpath) {
  // The file a package's "exports" map gives for an import of `subpath`.
  const field = pkg.json.exports;
  let entry;
  if (typeof field === "string" || Array.isArray(field)) {
    entry = subpath === "." ? field : undefined;
  } else if (field && typeof field === "object") {
    if (Object.prototype.hasOwnProperty.call(field, subpath)) {
      entry = field[subpath];
    } else {
      for (const [key, value] of Object.entries(field)) {
        const star = key.indexOf("*");
        if (star < 0) continue;
        const head = key.slice(0, star);
        const tail = key.slice(star + 1);
        if (subpath.startsWith(head) && subpath.endsWith(tail) && subpath.length >= head.length + tail.length) {
          entry = substitute(value, subpath.slice(head.length, subpath.length - tail.length));
          break;
        }
      }
    }
  } else if (subpath === "." && typeof pkg.json.main === "string") {
    entry = pkg.json.main;
  }
  const target = pick(entry);
  if (typeof target !== "string" || !target.startsWith("./")) throw new Error("no export");
  const file = path.resolve(pkg.dir, target);
  if (!file.startsWith(pkg.dir + path.sep)) throw new Error("export outside the package");
  return file;
}

function versions(found) {
  return { package: found.sdk.name, version: found.sdk.version, ai_package: found.ai.name, ai_version: found.ai.version };
}

// --- start: check the SDK on disk, then load it --------------------------------------------

let loaded;
try {
  loaded = onDisk();
} catch {
  say({ bridge: 1, ok: false, reason: "sdk_unreadable" });
  process.exit(2);
}
if (loaded.sdk.name !== sdkPackage || loaded.sdk.version !== expectedVersion
    || (expectedAi && loaded.ai.version !== expectedAi)) {
  say({ bridge: 1, ok: false, reason: "sdk_version_mismatch", ...versions(loaded) });
  process.exit(2);
}
let sdk;
let providers;
try {
  sdk = await import(pathToFileURL(exportTarget(loaded.sdk, ".")).href);
  providers = await import(pathToFileURL(exportTarget(loaded.ai, "./providers/all")).href);
} catch {
  say({ bridge: 1, ok: false, reason: "sdk_unreadable", ...versions(loaded) });
  process.exit(2);
}
if (typeof sdk.ModelRuntime?.create !== "function" || typeof sdk.readStoredCredential !== "function"
    || typeof providers.builtinProviders !== "function" || typeof providers.getBuiltinModels !== "function") {
  say({ bridge: 1, ok: false, reason: "sdk_surface", ...versions(loaded) });
  process.exit(2);
}
if (sdk.VERSION !== loaded.sdk.version) {
  // The code that loaded says another version than its package.json did a moment ago.
  say({ bridge: 1, ok: false, reason: "sdk_version_mismatch", ...versions(loaded),
    loaded_version: typeof sdk.VERSION === "string" ? sdk.VERSION : "unknown" });
  process.exit(2);
}
say({ bridge: 1, ok: true, ...versions(loaded), loaded_version: sdk.VERSION, node: process.version });

// --- requests ------------------------------------------------------------------------------

function sdkChange() {
  // The versions on disk now, against those loaded at start (which matched the expected ones).
  let now;
  try {
    now = onDisk();
  } catch {
    return { reason: "sdk_unreadable" };
  }
  if (now.sdk.dir !== loaded.sdk.dir || now.sdk.name !== loaded.sdk.name || now.sdk.version !== loaded.sdk.version) {
    return { reason: "sdk_changed", found_version: now.sdk.version };
  }
  if (now.ai.dir !== loaded.ai.dir || now.ai.version !== loaded.ai.version) {
    return { reason: "sdk_changed", found_version: `ai:${now.ai.version}` };
  }
  return null;
}

function slotRefusal(slot) {
  if (!WORD.test(slot)) return "bad_slot";
  if (slot === base) return "account_1";
  if (!aliasRe.test(slot)) return "not_alias";
  if (!slots.includes(slot)) return "not_served";
  return null;
}

function registryRefusal(slot) {
  // pi-multi-pass keeps its subscriptions in <agent dir>/multi-pass.json; read-only here.
  const index = Number(aliasRe.exec(slot)[1]);
  let data;
  try {
    data = JSON.parse(fs.readFileSync(path.join(agentDir, "multi-pass.json"), "utf8"));
  } catch {
    return "registry_unreadable";
  }
  if (!Array.isArray(data?.subscriptions)) return "registry_unreadable";
  return data.subscriptions.some((s) => s && s.provider === base && Number(s.index) === index) ? null : "not_registered";
}

let runtime = null;
const registered = new Set();
let versionRefusal = null;

async function runtimeFor(slot) {
  if (!runtime) {
    runtime = await sdk.ModelRuntime.create({ authPath, modelsPath: null, allowModelNetwork: false,
      refreshOnCreate: false });
  }
  if (!registered.has(slot)) {
    const flow = providers.builtinProviders().find((p) => p.id === base)?.auth?.oauth;
    if (!flow || typeof flow.refresh !== "function" || typeof flow.login !== "function") return null;
    const models = providers.getBuiltinModels(base);
    const index = Number(aliasRe.exec(slot)[1]);
    runtime.registerProvider(slot, {
      baseUrl: models[0]?.baseUrl || "",
      api: models[0]?.api,
      oauth: {
        name: `${base.charAt(0).toUpperCase()}${base.slice(1)} #${index}`,
        isSubscription: flow.isSubscription,
        login: async () => {
          throw new Error("the host helper never logs in");
        },
        refreshToken: async (credential, signal) => {
          const change = sdkChange();
          if (change) {
            versionRefusal = change;
            throw new Error("the Pi SDK changed on disk");
          }
          const oauth = credential.type === "oauth" ? credential : { ...credential, type: "oauth" };
          return flow.refresh(oauth, signal ?? new AbortController().signal);
        },
        getApiKey: (credential) => credential.access,
      },
    });
    registered.add(slot);
  }
  return runtime;
}

function bearer(headers) {
  const value = headers?.Authorization ?? headers?.authorization;
  return /^Bearer\s+(.+)$/iu.exec(typeof value === "string" ? value : "")?.[1];
}

async function mint(slot) {
  const refuse = (reason, extra = {}) => ({ ok: false, slot, reason, ...extra });
  const before = slotRefusal(slot);
  if (before) return refuse(before);
  const change = sdkChange();
  if (change) return refuse(change.reason, change);
  const unregistered = registryRefusal(slot);
  if (unregistered) return refuse(unregistered);
  const rt = await runtimeFor(slot);
  if (!rt) return refuse("no_flow");
  const signal = AbortSignal.timeout(timeoutMs);
  const listed = await rt.listCredentials({ signal });
  const type = listed.find((c) => c?.providerId === slot)?.type;
  if (!type) return refuse("no_login");
  if (type !== "oauth") return refuse("not_oauth");
  versionRefusal = null;
  let auth;
  try {
    auth = await rt.getAuth(slot, { minOAuthValidityMs: minValidityMs, signal });
  } catch (error) {
    if (versionRefusal) return refuse(versionRefusal.reason, versionRefusal);
    // Never pass the SDK's error text on: a refresh error can carry the token endpoint's reply.
    return refuse(/credential store/i.test(String(error?.message)) ? "auth_failed" : "refresh_failed");
  }
  const token = auth?.auth?.apiKey ?? bearer(auth?.auth?.headers);
  if (typeof token !== "string" || !token) return refuse("no_token");
  return { ok: true, slot, token };
}

async function status() {
  const change = sdkChange();
  if (change) return { ok: true, state: change.reason, found_version: change.found_version ?? "unknown", slots: {} };
  const words = {};
  for (const slot of slots) {
    const refusal = slotRefusal(slot) ?? registryRefusal(slot);
    const stored = sdk.readStoredCredential(slot, authPath);
    let login;
    if (!stored) login = "login_missing";
    else if (stored.type !== "oauth") login = "login_not_oauth";
    else if (typeof stored.expires !== "number") login = "login_unknown_expiry";
    else login = stored.expires - Date.now() > minValidityMs ? "login_ready" : "login_refresh_due";
    words[slot] = `${refusal ?? "registered"} ${login}`;
  }
  return { ok: true, state: "ready", slots: words };
}

// --- read-only usage (no ModelRuntime, token mint, profile, cache or room producer) ----------

const VENDOR = {
  "subs-limits.ts": "22a2297e9ad5b493875129a0fb6fa7dea575e7bfb3355d36219f3b9bb73f7489",
  "reset-countdown.ts": "3bb5b9f8171726b8c1ce25b2cd3382e8aa2604490a7bac164299ab104427c8b6",
};
const VENDOR_DIR = fileURLToPath(new URL("./vendor/pi-multi-pass-b8423d2/", import.meta.url));
const USAGE_URL = "https://api.anthropic.com/api/oauth/usage";
const MAX_TIME_S = 253402300799; // last second of year 9999
const USAGE_KEY = /^(?:5h|7d|7d:[a-z0-9-]{1,40})$/;
const NATIVE_REASON = {
  "signed-out": "signed_out", "not-subscription": "not_subscription",
  "sign-in-expired": "sign_in_expired", busy: "busy", timeout: "timeout",
  "no-answer": "no_answer", error: "check_failed",
};

async function loadChecker() {
  for (const [file, digest] of Object.entries(VENDOR)) {
    if (createHash("sha256").update(fs.readFileSync(path.join(VENDOR_DIR, file))).digest("hex") !== digest) {
      throw new Error("vendor changed");
    }
  }
  const checker = await import(pathToFileURL(path.join(VENDOR_DIR, "subs-limits.ts")).href);
  if (typeof checker.checkAccount !== "function" || typeof checker.parseAnthropicUsage !== "function"
      || checker.ANTHROPIC_USAGE_URL !== USAGE_URL) throw new Error("vendor surface");
  return checker;
}

function rfc3339(seconds) {
  return new Date(seconds * 1000).toISOString().replace(/\.\d{3}Z$/, "Z");
}

function record(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function validReset(value) {
  if (value === null) return true;
  let seconds;
  if (typeof value === "number" && Number.isFinite(value)) {
    seconds = value > 1e12 ? Math.floor(value / 1000) : value;
  } else if (typeof value === "string") {
    const parts = /^\d{4}-\d{2}-\d{2}T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
    // Date.parse also repairs hour 24 to the next midnight. Check the raw clock and
    // offset components before parsing, so no malformed reset can become an OK reading.
    if (!parts || Number(parts[1]) > 23 || Number(parts[2]) > 59 || Number(parts[3]) > 59
        || (parts[4] && (Number(parts[5]) > 23 || Number(parts[6]) > 59))) return false;
    seconds = Math.floor(Date.parse(value) / 1000);
    // Date.parse accepts e.g. February 30; reject calendar rollovers before normalising UTC.
    const day = value.slice(0, 10);
    const midnight = new Date(`${day}T00:00:00Z`);
    if (!Number.isFinite(midnight.getTime()) || midnight.toISOString().slice(0, 10) !== day) return false;
  }
  return Number.isInteger(seconds) && seconds > 0 && seconds <= MAX_TIME_S;
}

function validateBody(data, checker) {
  // The vendor intentionally clamps percentages, drops malformed windows and de-duplicates.
  // A reset decision cannot accept those repairs: validate every recognised window first.
  if (!record(data) || (data.limits !== undefined && !Array.isArray(data.limits))
      || (data.limits?.length ?? 0) > 32) return "check_failed";
  const seen = new Map();
  function add(value, field, fragment) {
    if (!record(value) || typeof value[field] !== "number" || !Number.isFinite(value[field])
        || value[field] < 0 || value[field] > 100 || !validReset(value.resets_at)) return false;
    const windows = checker.parseAnthropicUsage(fragment)?.windows;
    if (windows?.length !== 1 || !USAGE_KEY.test(windows[0].key)) return false;
    const window = windows[0];
    const existing = seen.get(window.key);
    if (existing && (existing.usedPercent !== window.usedPercent || existing.resetAt !== window.resetAt)) return false;
    seen.set(window.key, window);
    return true;
  }
  for (const key of ["five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "seven_day_haiku"]) {
    if (data[key] !== undefined && data[key] !== null && !add(data[key], "utilization", { [key]: data[key] })) {
      return "check_failed";
    }
  }
  for (const limit of data.limits ?? []) {
    if (!record(limit)) return "check_failed";
    const known = limit.kind === "session" || limit.kind === "weekly_all";
    const model = limit.scope?.model;
    if (limit.kind === "weekly_scoped" && model !== undefined && model !== null && !record(model)) {
      return "check_failed"; // a surface cannot hide a supplied malformed model scope
    }
    const scoped = limit.kind === "weekly_scoped" && record(model);
    if (known || scoped) {
      if (!add(limit, "percent", { limits: [limit] })) return "check_failed";
    } else if (limit.kind === "weekly_scoped" && !record(limit.scope?.surface)) {
      return "check_failed"; // not a valid model scope or an explicitly non-model surface
    }
  }
  return seen.has("5h") && seen.has("7d") ? null : "incomplete_reading";
}

function readingFrom(row, began, ended) {
  if (row?.failure) return { status: "unavailable", reason: NATIVE_REASON[row.failure.reason] ?? "check_failed" };
  if (row?.source !== "check" || !Number.isFinite(row.checkedAt) || !Array.isArray(row.windows)) {
    return { status: "unavailable", reason: "check_failed" };
  }
  if (row.checkedAt < began || row.checkedAt > ended || ended - began > 26_000) {
    return { status: "unavailable", reason: "stale_reading" };
  }
  const windows = [];
  for (const w of row.windows) {
    if (!USAGE_KEY.test(w?.key) || windows.some((v) => v.key === w.key)
        || typeof w.usedPercent !== "number" || !Number.isFinite(w.usedPercent)
        || w.usedPercent < 0 || w.usedPercent > 100
        || (w.resetAt !== undefined && (!Number.isInteger(w.resetAt) || w.resetAt <= 0 || w.resetAt > MAX_TIME_S))) {
      return { status: "unavailable", reason: "check_failed" };
    }
    windows.push({ key: w.key, used_percent: w.usedPercent,
      resets_at: w.resetAt === undefined ? null : rfc3339(w.resetAt) });
  }
  if (!windows.some((w) => w.key === "5h") || !windows.some((w) => w.key === "7d")) {
    return { status: "unavailable", reason: "incomplete_reading" };
  }
  return { status: "ok", observed_at: rfc3339(Math.floor(row.checkedAt / 1000)), windows };
}

async function usage(slot) {
  const refuse = (reason) => ({ ok: false, slot, reason });
  const unavailable = (reason) => ({ ok: true, slot, status: "unavailable", reason });
  const before = slotRefusal(slot);
  if (before) return refuse(before);
  const unregistered = registryRefusal(slot);
  if (unregistered) return refuse(unregistered);
  const change = sdkChange();
  if (change) return unavailable(change.reason);
  let checker;
  try { checker = await loadChecker(); } catch { return unavailable("checker_unreadable"); }
  if (base !== "anthropic") return unavailable("unsupported");
  let credential;
  try { credential = sdk.readStoredCredential(slot, authPath); } catch { return unavailable("auth_unreadable"); }
  if (!credential) return unavailable("signed_out");
  if (credential.type !== "oauth") return unavailable("not_subscription");
  if (typeof credential.access !== "string" || !credential.access
      || !Number.isFinite(credential.expires) || credential.expires <= Date.now() + 120_000) {
    return unavailable("sign_in_expired");
  }
  const began = Date.now();
  const account = { provider: slot, base, number: Number(aliasRe.exec(slot)[1]), name: "(not read)" };
  const host = { configured: () => [], bases: () => [base],
    stored: (provider) => provider === slot ? structuredClone(credential) : undefined };
  // Stand-in, not cached data: these fields suppress the checker's optional profile GET.
  const previous = { ...account, email: "(not read)", plan: "(not read)", profileAt: began, windows: [] };
  const controller = new AbortController();
  let bodyRefusal = null;
  let stray = false;
  let active = true;
  const options = {
    file: "/dev/null", timeoutMs: usageTimeoutMs, retryDelayMs: 750, retryAfterCapMs: 5000,
    now: Date.now,
    sleep: (ms) => new Promise((resolve) => {
      if (!active) { resolve(); return; }
      const done = () => { clearTimeout(timer); controller.signal.removeEventListener("abort", done); resolve(); };
      const timer = setTimeout(done, ms);
      controller.signal.addEventListener("abort", done, { once: true });
    }),
    fetch: async (input, init = {}) => {
      if (input !== USAGE_URL || (init.method ?? "GET") !== "GET") {
        stray = true;
        throw new Error("outside usage endpoint");
      }
      if (!active) throw new Error("usage finished");
      const response = await fetch(input, { ...init, redirect: "error",
        signal: AbortSignal.any([controller.signal, ...(init.signal ? [init.signal] : [])]) });
      if (!response.ok) return response;
      // Consume only inside the checker's per-attempt deadline. No body escapes this adapter.
      return { status: response.status, statusText: response.statusText, headers: response.headers,
        arrayBuffer: async () => {
          const bytes = await response.arrayBuffer();
          try { bodyRefusal = validateBody(JSON.parse(Buffer.from(bytes).toString("utf8")), checker); }
          catch { bodyRefusal = "check_failed"; }
          return bytes;
        } };
    },
  };
  let timer;
  let row;
  try {
    row = await Promise.race([
      checker.checkAccount(host, account, previous, options),
      new Promise((resolve) => { timer = setTimeout(() => { active = false; controller.abort(); resolve(null); },
        2 * usageTimeoutMs + 5000 + 1000); }),
    ]);
  } catch { return unavailable("check_failed"); }
  finally { clearTimeout(timer); active = false; controller.abort(); }
  const afterChange = sdkChange();
  if (afterChange) return unavailable(afterChange.reason);
  try {
    if (!isDeepStrictEqual(credential, sdk.readStoredCredential(slot, authPath))) return unavailable("login_changed");
  } catch { return unavailable("auth_unreadable"); }
  if (!row) return unavailable("timeout");
  if (stray) return unavailable("check_failed");
  if (bodyRefusal) return unavailable(bodyRefusal);
  return { ok: true, slot, ...readingFrom(row, began, Date.now()) };
}

async function handle(line) {
  let request;
  try {
    request = JSON.parse(line);
  } catch {
    return { id: null, ok: false, reason: "bad_request" };
  }
  const id = request?.id ?? null;
  const slot = typeof request?.slot === "string" ? request.slot : "";
  try {
    if (request?.op === "token") return { id, ...(await mint(slot)) };
    if (request?.op === "status") return { id, ...(await status()) };
    if (request?.op === "usage") return { id, ...(await usage(slot)) };
    return { id, ok: false, reason: "bad_request" };
  } catch {
    return request?.op === "usage"
      ? { id, ok: true, slot, status: "unavailable", reason: "check_failed" }
      : { id, ok: false, slot, reason: "auth_failed" };
  }
}

const queue = [];

async function pump() {
  if (busy) return;
  busy = true;
  while (queue.length) say(await handle(queue.shift()));
  busy = false;
  if (stopping) process.exit(0);
}

const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
lines.on("line", (line) => {
  queue.push(line);
  pump();
});
lines.on("close", () => {
  stopping = true;
  if (!busy) process.exit(0);
});

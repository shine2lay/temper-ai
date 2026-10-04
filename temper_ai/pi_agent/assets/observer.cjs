"use strict";
// Temper Pi worker box metadata observer (from the L1 proof), preloaded with `node --require`.
//
// It subscribes to Node diagnostics channels that undici (Pi's HTTP client) and node:http publish, and
// appends one JSON line per event to /w/observer/events.jsonl. It records only: event kind, a per-request
// sequence id, method, target host (allowlisted names, otherwise "other"), a fixed path CATEGORY
// (model / profile / other — never the path itself), HTTP status, a content-type class, and error code
// classes. It never reads headers other than content-type, request or response bodies, query strings,
// prompts or credentials. It never throws into Pi.
const dc = require("node:diagnostics_channel");
const fs = require("node:fs");

const OUT = process.env.TEMPER_BOX_OBSERVER_OUT || "/w/observer/events.jsonl";
const HOSTS = new Set(["api.anthropic.com", "chatgpt.com", "127.0.0.1"]);
let fd = null;
let seq = 0;
let nextId = 0;
const ids = new WeakMap();

try {
    fd = fs.openSync(OUT, "a", 0o600);
} catch {
    fd = null;
}

function write(record) {
    if (fd === null) return;
    try {
        seq += 1;
        fs.writeSync(fd, JSON.stringify({ seq, t: Date.now(), ...record }) + "\n");
    } catch {
        /* never disturb Pi */
    }
}

function idOf(request) {
    if (!request || typeof request !== "object") return null;
    let id = ids.get(request);
    if (id === undefined) {
        nextId += 1;
        id = nextId;
        ids.set(request, id);
    }
    return id;
}

function hostOf(origin) {
    try {
        const name = new URL(String(origin)).hostname.toLowerCase();
        return HOSTS.has(name) ? name : "other";
    } catch {
        return "unparsed";
    }
}

function category(host, rawPath, method) {
    if (method === "CONNECT") return "tunnel";
    const path = String(rawPath || "").split("?")[0];
    if (host === "api.anthropic.com") {
        if (path === "/v1/messages") return "model";
        if (path === "/api/oauth/profile") return "profile";
        return "other";
    }
    if (host === "chatgpt.com") {
        if (path === "/backend-api/codex/responses") return "model";
        return "other";
    }
    return "other";
}

function tunnelTarget(rawPath) {
    const name = String(rawPath || "").split(":")[0].toLowerCase();
    return HOSTS.has(name) ? name : "other";
}

function contentClass(headers) {
    if (!Array.isArray(headers)) return null;
    for (let i = 0; i + 1 < headers.length; i += 2) {
        if (String(headers[i]).toLowerCase() === "content-type") {
            const value = String(headers[i + 1]).toLowerCase();
            if (value.includes("event-stream")) return "sse";
            if (value.includes("json")) return "json";
            return "other";
        }
    }
    return null;
}

function errorClass(error) {
    const out = {};
    const code = error && error.code;
    if (typeof code === "string" && /^[A-Z0-9_]{1,48}$/.test(code)) out.code = code;
    const name = error && error.name;
    if (typeof name === "string" && /^[A-Za-z]{1,40}$/.test(name)) out.name = name;
    return out;
}

function on(name, fn) {
    try {
        dc.subscribe(name, (message) => {
            try {
                fn(message || {});
            } catch {
                /* never disturb Pi */
            }
        });
    } catch {
        /* channel API unavailable */
    }
}

on("undici:request:create", ({ request }) => {
    const method = request && request.method;
    const host = hostOf(request && request.origin);
    const cat = category(host, request && request.path, method);
    const record = { ev: "request", id: idOf(request), method: typeof method === "string" ? method : null, host, cat };
    if (cat === "tunnel") record.target = tunnelTarget(request && request.path);
    write(record);
});
on("undici:request:headers", ({ request, response }) => {
    write({ ev: "headers", id: idOf(request), status: response && response.statusCode,
            ctype: contentClass(response && response.headers) });
});
on("undici:request:trailers", ({ request }) => write({ ev: "complete", id: idOf(request) }));
on("undici:request:error", ({ request, error }) => write({ ev: "error", id: idOf(request), ...errorClass(error) }));
on("undici:client:connected", ({ connectParams }) => {
    write({ ev: "connected", host: connectParams ? (HOSTS.has(String(connectParams.hostname)) ? connectParams.hostname : "other") : null,
            port: connectParams && Number(connectParams.port) || null });
});
on("undici:client:connectError", ({ connectParams, error }) => {
    write({ ev: "connect_error", host: connectParams ? (HOSTS.has(String(connectParams.hostname)) ? connectParams.hostname : "other") : null,
            ...errorClass(error) });
});
on("undici:websocket:open", () => write({ ev: "websocket_open" }));
on("http.client.request.start", ({ request }) => {
    const host = request && typeof request.host === "string" && HOSTS.has(request.host.toLowerCase()) ? request.host.toLowerCase() : "other";
    write({ ev: "node_http_request", host, method: request && typeof request.method === "string" ? request.method : null });
});

write({ ev: "boot", node: process.version, pid: process.pid });
process.on("exit", (code) => write({ ev: "exit", code }));

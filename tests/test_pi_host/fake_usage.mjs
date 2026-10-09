// Offline-only fetch preload: every request is fake; no socket or real HTTP is opened.
// Records booleans/counts only, never credentials, request headers or response bodies.
import fs from "node:fs";
import path from "node:path";

const root = process.env.TPH_USAGE_FIXTURE;
if (!root) throw new Error("no usage fixture");
const config = () => JSON.parse(fs.readFileSync(path.join(root, "usage-fixture.json"), "utf8"));
let calls = 0;
globalThis.fetch = async (url, init = {}) => {
  calls++;
  const c = config();
  const entry = JSON.parse(fs.readFileSync(c.auth, "utf8"))[c.slot];
  const usage = url === "https://api.anthropic.com/api/oauth/usage" && init.method === "GET";
  fs.appendFileSync(path.join(root, "usage-events.log"), JSON.stringify({ usage,
    authorised: init.headers?.Authorization === `Bearer ${entry?.access}`,
    noRedirect: init.redirect === "error" }) + "\n");
  if (!usage || init.redirect !== "error") throw new Error("FORBIDDEN-SECRET-BODY");
  if (c.change_login) {
    const data = JSON.parse(fs.readFileSync(c.auth, "utf8"));
    data[c.slot].refresh = "changed-by-another-chat";
    fs.writeFileSync(c.auth, JSON.stringify(data));
  }
  if (c.change_sdk) {
    const file = path.join(c.sdk_root, "node_modules/@earendil-works/pi-coding-agent/package.json");
    const pkg = JSON.parse(fs.readFileSync(file, "utf8"));
    pkg.version += "-changed";
    fs.writeFileSync(file, JSON.stringify(pkg));
  }
  if (c.error) throw new Error("PROVIDER-SECRET-BODY");
  if (c.hang) await new Promise(() => {}); // deliberate abort-ignoring fetch tests checker deadline
  if (c.delay_ms) await new Promise((resolve) => setTimeout(resolve, c.delay_ms));
  const statuses = c.statuses ?? [200];
  const status = statuses[Math.min(calls - 1, statuses.length - 1)];
  const text = c.raw ?? JSON.stringify(c.body);
  const response = new Response(status === 204 || status === 304 ? null : text,
    { status, headers: { "Retry-After": "0", "Content-Type": "application/json" } });
  if (c.hang_body) response.arrayBuffer = () => new Promise(() => {});
  return response;
};

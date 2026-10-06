// Test-only: the owner's chat side of the refresh race.  It uses the pinned Pi SDK the way
// pi-web-ui does (one ModelRuntime on <agent dir>/auth.json) and registers the alias the way
// pi-multi-pass does (the base provider's built-in OAuth flow under the alias's own key).
// Usage: node --import fake_fetch.mjs chat_side.mjs <sdk root> <agent dir> <alias> <base> <go at ms>
// Prints {"token": "..."} or {"error": "..."}.
import path from "node:path";
import { pathToFileURL } from "node:url";

const [sdkRoot, agentDir, alias, base, goAt] = process.argv.slice(2);
const scope = path.join(sdkRoot, "node_modules", "@earendil-works");
const sdk = await import(pathToFileURL(path.join(scope, "pi-coding-agent", "dist", "index.js")).href);
const providers = await import(pathToFileURL(path.join(scope, "pi-ai", "dist", "providers", "all.js")).href);

const runtime = await sdk.ModelRuntime.create({
  authPath: path.join(agentDir, "auth.json"),
  modelsPath: path.join(agentDir, "models.json"),
});
const flow = providers.builtinProviders().find((p) => p.id === base).auth.oauth;
const models = providers.getBuiltinModels(base);
const index = Number(alias.split("-").pop());
runtime.registerProvider(alias, {
  baseUrl: models[0]?.baseUrl || "",
  api: models[0]?.api,
  oauth: {
    name: `Anthropic #${index}`,
    isSubscription: flow.isSubscription,
    login: (callbacks) => flow.login(callbacks),
    refreshToken: (credential, signal) =>
      flow.refresh(credential.type === "oauth" ? credential : { ...credential, type: "oauth" },
        signal ?? new AbortController().signal),
    getApiKey: (credential) => credential.access,
  },
});

const wait = Number(goAt) - Date.now();
if (wait > 0) await new Promise((resolve) => setTimeout(resolve, wait));
try {
  const auth = await runtime.getAuth(alias);
  process.stdout.write(JSON.stringify({ token: auth?.auth?.apiKey ?? null }) + "\n");
} catch (error) {
  process.stdout.write(JSON.stringify({ error: String(error?.message) }) + "\n");
}
process.exit(0);

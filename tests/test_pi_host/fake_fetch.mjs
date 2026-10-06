// Test-only preload (node --import): the Pi SDK's OAuth token requests go to a local fake
// endpoint (TPH_FAKE_TOKEN_URL); every other network call is refused.  Never used outside
// tests; the bridge itself patches nothing.
const target = process.env.TPH_FAKE_TOKEN_URL;
const realFetch = globalThis.fetch;

globalThis.fetch = async (input, init) => {
  const url = typeof input === "string" ? input : input instanceof URL ? input.href : input?.url;
  if (target && typeof url === "string" && /^https:\/\/[^/]+\/v1\/oauth\/token$/.test(url)) {
    return realFetch(target, init);
  }
  throw new Error(`blocked in tests: ${url}`);
};

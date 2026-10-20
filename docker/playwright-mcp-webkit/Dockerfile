# playwright-mcp-webkit: temper's playwright-mcp image with WebKit (Safari's engine) added, for
# the docker-compose.yml service of the same name (queue #123, Architecture rm-ebb68a75).
#
# Base: the exact image the Chromium service (playwright-mcp) runs, pinned by its digest, never
# :latest, so this WebKit service and the Chromium one run the same MCP server. When this was
# written that was image af28706f: @playwright/mcp 0.0.82, playwright-core
# 1.64.0-alpha-1789764292000, Debian 12, user node, PLAYWRIGHT_BROWSERS_PATH=/ms-playwright.
#   digest: sha256:77dccc5ce9e94cb8ae7ebea87ddbb6cd54b05760c4d63c54e16accf2726b8734
# Bump this digest together with the Chromium image (and the line above with it; the test
# tests/test_ci/test_playwright_webkit_service.py checks the two agree).
#
# WebKit comes from the image's own playwright-core, not `npx playwright-core` (which could fetch
# another version from npm), so its revision is the one this MCP server looks for (webkit-2365 in
# its browsers.json). --with-deps installs WebKit's system libraries with apt: root for that one
# step, with apt's lists removed after; the server runs as node, as in the base image. The browser
# files stay root's: node can run them, not change them.
FROM mcr.microsoft.com/playwright/mcp@sha256:77dccc5ce9e94cb8ae7ebea87ddbb6cd54b05760c4d63c54e16accf2726b8734

USER root
RUN node /app/node_modules/playwright-core/cli.js install --with-deps webkit \
    && rm -rf /var/lib/apt/lists/*
USER node

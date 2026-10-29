// A tiny suite of plain node tests (no page, no browser, no server) whose real Playwright
// reports are the known answers of tests/test_e2e_shards.py. Run it only through
// tests/fixtures/e2e_shards/generate.py, which says which files to load and where to write.
const fs = require('fs');
const path = require('path');

const listed = fs
  .readFileSync(process.env.E2E_SHARDS_FIXTURE_LIST || path.join(__dirname, 'clean.txt'), 'utf8')
  .split('\n')
  .map((line) => line.split('#')[0].trim())
  .filter(Boolean);

module.exports = {
  testDir: __dirname,
  testMatch: listed,
  retries: 1,
  workers: 1,
  outputDir: process.env.E2E_SHARDS_FIXTURE_OUTPUT || path.join(__dirname, '..', '.test-results'),
};

import { expect, test } from '@playwright/test';

// Plain node tests: no page, no browser, no server.

// Fails on its first attempt and on its retry.
test('fails on every attempt', () => {
  expect(1 + 1).toBe(3);
});

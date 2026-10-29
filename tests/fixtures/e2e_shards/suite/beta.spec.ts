import { expect, test } from '@playwright/test';

// Plain node tests: no page, no browser, no server.

test('same title in two files', () => {
  expect(true).toBe(true);
});

test.skip('is skipped', () => {
  expect(true).toBe(false);
});

// Reported as "a › b", like gamma's test titled "a › b": only the file tells them apart.
test.describe('a', () => {
  test('b', () => {
    expect(true).toBe(true);
  });
});

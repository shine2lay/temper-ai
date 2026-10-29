import { expect, test } from '@playwright/test';

// Plain node tests: no page, no browser, no server.

test('passes', () => {
  expect(1 + 1).toBe(2);
});

// Fails on its first attempt and passes on its retry (or, with --repeat-each, on its second repeat).
test('passes only on its retry', ({}, testInfo) => {
  expect(testInfo.retry > 0 || testInfo.repeatEachIndex > 0).toBe(true);
});

test.describe('outer', () => {
  test.describe('inner', () => {
    test('nested', () => {
      expect(true).toBe(true);
    });
  });
});

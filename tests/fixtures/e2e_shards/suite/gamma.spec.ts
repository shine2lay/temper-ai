import { expect, test } from '@playwright/test';

// Plain node tests: no page, no browser, no server.

test('same title in two files', () => {
  expect(true).toBe(true);
});

// A title with " › " in it, the separator the JUnit report joins title paths with.
test('a › b', () => {
  expect(true).toBe(true);
});

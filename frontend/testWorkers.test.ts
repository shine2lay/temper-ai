import { spawnSync } from 'node:child_process'
import path from 'node:path'
import { expect, it } from 'vitest'

it('resolves local defaults, diagnostics and remote worker settings through Vitest', () => {
  // Only the exit code can enter assertion output; never child streams/argv/env.
  const code = spawnSync(process.execPath, [path.resolve('scripts/check-test-workers.mjs')], {
    stdio: 'ignore',
    timeout: 30_000,
  }).status
  expect(code).toBe(0)
})

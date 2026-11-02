// Fixed configuration answers only: no tests, browser or Temper server started.
import assert from 'node:assert/strict'
import { createVitest, parseCLI } from 'vitest/node'

const root = new URL('../', import.meta.url).pathname
const keys = ['CI', 'GITHUB_ACTIONS', 'VITEST_MAX_WORKERS', 'WT_CHECK_WORKERS']
const cases = [
  ['local', {}, '', undefined, 10],
  ['shared', { WT_CHECK_WORKERS: '6' }, '', undefined, 6],
  ['runner', { WT_CHECK_WORKERS: '6', VITEST_MAX_WORKERS: '2' }, '', undefined, 2],
  ['cli', { WT_CHECK_WORKERS: '6', VITEST_MAX_WORKERS: '8' }, '--maxWorkers=2', undefined, 2],
  ['serial', { VITEST_MAX_WORKERS: '6' }, '--no-file-parallelism', undefined, 1],
  ['one', { VITEST_MAX_WORKERS: '6' }, '--maxWorkers=1', undefined, 1],
  ['empty', { WT_CHECK_WORKERS: '', VITEST_MAX_WORKERS: '' }, '', undefined, 10],
  ['bad-runner', { VITEST_MAX_WORKERS: 'bad', WT_CHECK_WORKERS: '6' }, '', undefined, NaN],
  ['bad-shared', { WT_CHECK_WORKERS: 'bad' }, '', undefined, NaN],
  ['native-parse', { VITEST_MAX_WORKERS: '2suffix' }, '', undefined, 2],
  ['bad-with-cli', { VITEST_MAX_WORKERS: 'bad' }, '--maxWorkers=2', undefined, 2],
  ['bad-with-serial', { VITEST_MAX_WORKERS: 'bad' }, '--no-file-parallelism', undefined, 1],
  ['zero-native-not-serial', { VITEST_MAX_WORKERS: '0' }, '', undefined, 0],
  ['ci', { CI: 'true', WT_CHECK_WORKERS: '6' }, '', undefined, undefined],
  ['ci-empty', { CI: '' }, '', undefined, undefined],
  ['github', { GITHUB_ACTIONS: 'true', WT_CHECK_WORKERS: '6' }, '', undefined, undefined],
  ['github-empty', { GITHUB_ACTIONS: '' }, '', undefined, undefined],
  ['ci-env', { CI: 'true', VITEST_MAX_WORKERS: '6' }, '', undefined, 6],
  ['ci-cli-old-precedence', { CI: 'true', VITEST_MAX_WORKERS: '6' }, '--maxWorkers=2', undefined, 6],
  ['ci-serial-old-precedence', { CI: 'true', VITEST_MAX_WORKERS: '6' }, '--no-file-parallelism', undefined, 6],
  ['ci-bad', { CI: 'true', VITEST_MAX_WORKERS: 'bad' }, '', undefined, NaN],
  ['github-cli', { GITHUB_ACTIONS: 'true' }, '--maxWorkers=2', undefined, 2],
  // Config loading without the repository plugin is the native runner control.
  ['native-local', {}, '', false, undefined],
  ['native-ci-env', { CI: 'true', VITEST_MAX_WORKERS: '6' }, '--maxWorkers=2', false, 6],
]
for (const [name, env, flags, config, expected] of cases) {
  for (const key of keys) delete process.env[key]
  Object.assign(process.env, env)
  const { options } = parseCLI(`vitest run ${flags}`)
  const ctx = await createVitest('test', { ...options, root, config, watch: false })
  try {
    assert.equal(ctx.config.maxWorkers, expected, name)
    assert.equal(ctx.projects[0].config.maxWorkers, expected, `${name}: project`)
    // Input survives resolution/close, including the formerly consumed env:
    // watch reloads and nested launches must not lose an explicit setting.
    assert.equal(process.env.VITEST_MAX_WORKERS, env.VITEST_MAX_WORKERS, `${name}: environment`)
    if (config !== false) {
      assert.equal(ctx.config.testTimeout, 30_000, `${name}: timeout`)
      assert.equal(ctx.config.hookTimeout, 30_000, `${name}: hook timeout`)
      assert.equal(ctx.config.environment, 'jsdom', `${name}: environment kind`)
    }
  } finally {
    await ctx.close()
  }
  assert.equal(process.env.VITEST_MAX_WORKERS, env.VITEST_MAX_WORKERS, `${name}: close`)
}
console.log(`worker configuration: ${cases.length} cases passed`)

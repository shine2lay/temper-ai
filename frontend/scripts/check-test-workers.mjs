// Real configuration answers plus disposable sentinel tests; no browser or Temper server.
import assert from 'node:assert/strict'
import { existsSync, mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { createVitest, parseCLI } from 'vitest/node'

const root = new URL('../', import.meta.url).pathname
const keys = ['CI', 'GITHUB_ACTIONS', 'VITEST_MAX_WORKERS', 'WT_CHECK_WORKERS']
const cases = [
  ['local', {}, '', undefined, 10],
  ['shared2', { WT_CHECK_WORKERS: '2' }, '', undefined, 2],
  ['shared', { WT_CHECK_WORKERS: '6' }, '', undefined, 6],
  ['shared10', { WT_CHECK_WORKERS: '10' }, '', undefined, 10],
  ['runner', { WT_CHECK_WORKERS: '6', VITEST_MAX_WORKERS: '2' }, '', undefined, 2],
  ['cli', { WT_CHECK_WORKERS: '6', VITEST_MAX_WORKERS: '8' }, '--maxWorkers=2', undefined, 2],
  ['serial', { VITEST_MAX_WORKERS: '6' }, '--no-file-parallelism', undefined, 1],
  ['one', { VITEST_MAX_WORKERS: '6' }, '--maxWorkers=1', undefined, 1],
  ['empty-runner', { VITEST_MAX_WORKERS: '' }, '', undefined, 10],
  ['bad-runner', { VITEST_MAX_WORKERS: 'bad', WT_CHECK_WORKERS: '6' }, '', undefined, NaN],
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
const invalidShared = ['', 'bad-private-value', '-1', '1.5', '2suffix', '2\n', ' 2', '+2', '2e1', '0x2', '２', '0', '9007199254740993']
for (const shared of invalidShared) {
  for (const [name, override, flags, expected] of [
    ['cli', {}, '--maxWorkers=2', 2],
    ['serial', {}, '--no-file-parallelism', 1],
    ['runner', { VITEST_MAX_WORKERS: '6' }, '', 6],
    ['bad-runner-native', { VITEST_MAX_WORKERS: 'bad' }, '', NaN],
    ['ci-unused', { CI: 'true' }, '', undefined],
    ['github-unused', { GITHUB_ACTIONS: '' }, '', undefined],
  ]) cases.push([name, { WT_CHECK_WORKERS: shared, ...override }, flags, undefined, expected])
}
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
// Launch only a disposable fixture. Invalid config must refuse before module
// collection or the body runs; the valid control proves the sentinels work.
const dir = mkdtempSync(path.join(root, '.worker-defaults-'))
const fixture = path.join(dir, 'sentinel.test.js')
const collected = path.join(dir, 'collected')
const ran = path.join(dir, 'ran')
writeFileSync(fixture, `import { writeFileSync } from 'node:fs'\nimport { it } from 'vitest'\nwriteFileSync(${JSON.stringify(collected)}, '')\nit('sentinel', () => writeFileSync(${JSON.stringify(ran)}, ''))\n`)
try {
  for (const shared of ['1', ...invalidShared]) {
    for (const key of keys) delete process.env[key]
    process.env.WT_CHECK_WORKERS = shared
    let ctx
    let refused = false
    try {
      ctx = await createVitest('test', { root, watch: false, include: [path.relative(root, fixture)] })
      await ctx.start([fixture])
    } catch (error) {
      assert.equal(error.message, 'WT_CHECK_WORKERS must be a positive whole-number count representable exactly by JavaScript; unset it for the local default.')
      refused = true
    } finally {
      await ctx?.close()
    }
    assert.equal(refused, shared !== '1', 'invalid shared config refused')
    assert.equal(existsSync(collected), shared === '1', 'collection sentinel')
    assert.equal(existsSync(ran), shared === '1', 'test body sentinel')
    rmSync(collected, { force: true })
    rmSync(ran, { force: true })
  }
} finally {
  rmSync(dir, { recursive: true, force: true })
}
console.log(`worker configuration: ${cases.length} resolution cases and ${invalidShared.length + 1} launch cases passed`)

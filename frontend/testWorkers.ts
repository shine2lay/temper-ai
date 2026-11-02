import type { Plugin } from 'vitest/config'

/** Local defaults at Vitest's config/CLI seam, without changing its remote policy. */
export function localTestWorkers(): Plugin {
  let saved: string | undefined
  const restore = () => {
    if (saved !== undefined) process.env.VITEST_MAX_WORKERS = saved
    saved = undefined
  }
  return {
    name: 'temper-local-test-workers',
    config(config) {
      if ('CI' in process.env || 'GITHUB_ACTIONS' in process.env || !process.env.VITEST) return
      saved = process.env.VITEST_MAX_WORKERS
      const workers = saved || process.env.WT_CHECK_WORKERS
      // Vitest 4 reads this again AFTER CLI and fileParallelism=false, overriding
      // even explicit diagnostics. Consume it as a config default instead; let
      // Vitest merge CLI and serial settings normally. Restore it after resolution
      // so workers and watch-mode config reloads still inherit the caller's value.
      delete process.env.VITEST_MAX_WORKERS
      return { test: { maxWorkers: config.test?.maxWorkers ?? (workers ? Number.parseInt(workers) : 10) } }
    },
    configureVitest: restore,
    closeBundle: restore,
  }
}

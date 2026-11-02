import type { Plugin } from 'vitest/config'

/** Local defaults at Vitest's config/CLI seam, without changing its remote policy. */
export function localTestWorkers(): Plugin {
  let saved: string | undefined
  let invalidShared = false
  const restore = () => {
    if (saved !== undefined) process.env.VITEST_MAX_WORKERS = saved
    saved = undefined
  }
  return {
    name: 'temper-local-test-workers',
    config(config) {
      if ('CI' in process.env || 'GITHUB_ACTIONS' in process.env || !process.env.VITEST) return
      saved = process.env.VITEST_MAX_WORKERS
      invalidShared = false
      let maxWorkers = config.test?.maxWorkers
      if (maxWorkers == null) {
        const shared = process.env.WT_CHECK_WORKERS
        if (saved) maxWorkers = Number.parseInt(saved) // Native runner-env handling stays unchanged.
        else if (shared === undefined) maxWorkers = 10
        else {
          const count = Number(shared)
          invalidShared = shared === '' || /[^0-9]/.test(shared) || !Number.isSafeInteger(count) || count < 1
          // CLI/serial options are merged later. A NaN sentinel lets those win;
          // configureVitest refuses only if this invalid input was actually used.
          maxWorkers = invalidShared ? NaN : count
        }
      }
      // Vitest 4 reads this again AFTER CLI and fileParallelism=false, overriding
      // even explicit diagnostics. Consume it as a config default instead; let
      // Vitest merge CLI and serial settings normally. Restore it after resolution
      // so workers and watch-mode config reloads still inherit the caller's value.
      delete process.env.VITEST_MAX_WORKERS
      return { test: { maxWorkers } }
    },
    configureVitest({ project }) {
      restore()
      if (invalidShared && Number.isNaN(project.config.maxWorkers)) {
        throw new Error('WT_CHECK_WORKERS must be a positive whole-number count representable exactly by JavaScript; unset it for the local default.')
      }
    },
    closeBundle: restore,
  }
}

/**
 * Design SPEC's stopped row: a stopped or failed run's Now gives the words given with the stop, as the rounds outcome
 * card quotes them (OwnerWords: a figure named by its caption, "temper's words" or "Your words", the words whole in
 * its blockquote, plain text). Beside them Temper's generic "the run was cancelled" is left out; every other sentence
 * stays, and a run stopped without words looks as before.
 *
 * One journey per theme and width: real serializer replies (real-g7) with neutral made-up words. Nothing is sent;
 * no Temper, model, server or project is started.
 */
import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { expectAxeClean, expectTargets, glanceFontsSettled, nothingSent, serveActions, serveTeam } from './team-helpers';

type Raw = Record<string, unknown>;
const FLOW = path.join(process.cwd(), 'e2e/fixtures/team/flow');
const sample = (name: string, feed = false): Raw =>
  JSON.parse(readFileSync(path.join(FLOW, `${name}${feed ? '-events' : ''}.json`), 'utf8')) as Raw;
test.use({ timezoneId: 'America/Los_Angeles' });

/** A stop with `words` given by `by`: the outcome and the stopping action say the same, as Temper records them. */
function stoppedBy(by: string, words: string | null): Raw {
  const run = sample('real-g7/stopped');
  Object.assign(run.outcome as Raw, { owner_words: words, by });
  for (const action of run.owner_actions as Raw[]) {
    if (action.kind === 'stop') Object.assign(action, { by, source: 'api', detail: words === null ? {} : { reason: words } });
  }
  return run;
}

function failedWith(by: string, words: string): Raw {
  const run = sample('real-g7/failed');
  Object.assign(run.outcome as Raw, { owner_words: words, by });
  return run;
}

const TEMPER_WORDS = 'Stage window ended for today; no retry.';
const LONG_WORDS = `Pausing here so the reviewer can catch up.\nThen: ${'unbreakable'.repeat(12)} <b>stays</b> & whole.`;
/** The failed sample's own sentence: Temper's reason with its first letter capitalised (D119), the rest exact. */
const FAILED_SENTENCE = ((sample('real-g7/failed').phase as Raw).reason as string).replace(/^./u, (first) => first.toUpperCase());

interface Step {
  name: string;
  run: Raw;
  feed: Raw;
  /** The figure's name (OwnerWords' caption), or null for no words. */
  label: string | null;
  /** Now's sentence, or null when it is left out. */
  sentence: string | null;
}

const STEPS = (): Step[] => [
  { name: 'stopped by temper', run: stoppedBy('temper', TEMPER_WORDS), feed: sample('real-g7/stopped', true), label: "temper's words", sentence: null },
  { name: 'stopped by the owner', run: sample('real-g7/stopped'), feed: sample('real-g7/stopped', true), label: 'Your words', sentence: null },
  {
    name: 'failed with words',
    run: failedWith('temper', TEMPER_WORDS),
    feed: sample('real-g7/failed', true),
    label: "temper's words",
    sentence: FAILED_SENTENCE,
  },
  { name: 'stopped without words', run: stoppedBy('temper', null), feed: sample('real-g7/stopped', true), label: null, sentence: 'The run was cancelled' },
  { name: 'a new line and a long word', run: stoppedBy('temper', LONG_WORDS), feed: sample('real-g7/stopped', true), label: "temper's words", sentence: null },
];

const bandEnd = (page: Page) => page.getByTestId('glance-band').evaluate((band) => band.getBoundingClientRect().bottom);

for (const theme of ['dark', 'light']) for (const [width, height] of [[1440, 900], [390, 844]]) {
  test(`journey: the words given with a stop, whole, under Now's sentence, ${theme}, ${width}`, async ({ page }) => {
    test.setTimeout(180_000);
    await page.setViewportSize({ width, height });
    await page.addInitScript((t) => localStorage.setItem('temper_theme', t), theme);
    await page.clock.install();
    const steps = STEPS();
    const state = { step: steps[0] };
    const sent = nothingSent();
    await serveTeam(page, { run: () => ({ route: '', status: 200, body: state.step.run }) });
    await serveActions(page, sent, {});
    await page.route(/\/api\/team\/runs\/[^/]+\/events(\?|$)/, (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state.step.feed) }),
    );
    for (const step of steps) await test.step(step.name, async () => {
      state.step = step;
      const run = step.run;
      await page.clock.setFixedTime(new Date(run.as_of as string));
      await page.goto(`/app/team/runs/${run.execution_id as string}`);
      await expect(page.getByTestId('glance-page')).toHaveAttribute('data-phase', (run.phase as Raw).name as string);
      await expect(page.getByTestId('glance-just-sent')).not.toContainText('Reading the team');
      await glanceFontsSettled(page);
      const now = page.getByTestId('glance-now');
      const words = (run.outcome as Raw).owner_words as string | null;

      if (step.sentence) await expect(page.getByTestId('glance-now-sentence')).toHaveText(step.sentence);
      else await expect(page.getByTestId('glance-now-sentence')).toHaveCount(0);

      if (step.label && words) {
        // The figure is named by its caption; its blockquote holds the words whole, as sent (not whitespace-normalised).
        const figure = now.getByRole('figure', { name: step.label, exact: true });
        await expect(figure).toBeVisible();
        await expect(now.getByRole('figure')).toHaveCount(1);
        const quote = figure.locator('blockquote');
        expect(await quote.textContent()).toBe(words);
        // Plain text: HTML-looking words are shown as typed, never made into elements.
        await expect(quote.locator('*')).toHaveCount(0);
        // Under the Now sentence (or the word, when the generic sentence is left out).
        const above = await (step.sentence ? page.getByTestId('glance-now-sentence') : page.getByTestId('glance-now-word')).boundingBox();
        const box = await figure.boundingBox();
        expect(box!.y).toBeGreaterThanOrEqual(above!.y + above!.height - 1);
        // Wraps inside its box and the page: nothing cut, nothing sideways; no text under the band's 14 px.
        expect(await quote.evaluate((el) => el.scrollWidth <= el.clientWidth + 1)).toBe(true);
        for (const part of [figure.locator('figcaption'), quote]) {
          expect(parseFloat(await part.evaluate((el) => getComputedStyle(el).fontSize))).toBeGreaterThanOrEqual(14);
        }
        await expect(now.getByText(/the run was cancelled/i)).toHaveCount(0);
      } else {
        await expect(now.getByRole('figure')).toHaveCount(0);
        await expect(page.getByTestId('glance-now-words')).toHaveCount(0);
      }
      // D84: the band still ends on a phone's first screen (the long words may take more room).
      if (width < 768 && step.name !== 'a new line and a long word') expect(await bandEnd(page)).toBeLessThanOrEqual(height);
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
      await expectAxeClean(page);
      await expectTargets(page);
    });
    expect(sent).toEqual(nothingSent());
  });
}

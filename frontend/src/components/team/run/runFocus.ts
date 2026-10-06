/**
 * Where the run view puts the focus when the control the owner used goes
 * away under it (Stop run, once the run has ended): the outcome's title,
 * else the run's own title. Both headings take focus from code only.
 */
export const RUN_TITLE_ID = 'team-run-title';
export const OUTCOME_TITLE_ID = 'team-outcome-title';

export function runResultHeading(): HTMLElement | null {
  return document.getElementById(OUTCOME_TITLE_ID) ?? document.getElementById(RUN_TITLE_ID);
}

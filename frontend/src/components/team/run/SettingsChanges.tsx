import { useId, useState } from 'react';
import { CopyButton } from '@/components/shared/CopyButton';
import { HIT_AREA, HIT_AREA_RING } from '@/lib/hitArea';
import { settingLabel } from '@/lib/teamText';
import {
  CHANGES_SHOWN,
  fingerprint,
  firstChanges,
  settingValue,
  settingsGroups,
  type SettingValueView,
} from '@/lib/teamSettings';
import { cn } from '@/lib/utils';
import type { TeamSettingsChange, TeamSettingsPin } from '@/types/team';

const subLabel = 'm-0 text-xs font-semibold uppercase tracking-[0.06em] text-temper-text-muted';
const copyBtn = 'min-h-6 min-w-6 justify-center';

/** A value cell: mono, a digest cut to its fingerprint with the whole of it in the title and the copy. */
function Value({ view, what }: { view: SettingValueView; what: string }) {
  return (
    <span className="inline-flex max-w-full items-center gap-1">
      <span className="min-w-0 font-mono break-all" title={view.full ?? undefined}>
        {view.shown}
      </span>
      {view.full && <CopyButton text={view.full} label={`Copy ${what}`} className={copyBtn} />}
    </span>
  );
}

function SettingName({ change }: { change: TeamSettingsChange }) {
  const label = settingLabel(change.key);
  // A key with no plain name shows as Temper sent it.
  return label ? <>{label}</> : <span className="font-mono">{change.key}</span>;
}

/**
 * "What changed" at a settings wait (SPEC 5.2a, boards R18 and S8): one row
 * per changed setting, the whole team first, then each member; then each
 * member's settings fingerprint before and after.
 */
export function SettingsChanges({
  changes,
  pins,
}: {
  changes: readonly TeamSettingsChange[];
  pins: readonly TeamSettingsPin[];
}) {
  const ids = useId();
  const [all, setAll] = useState(false);
  const groups = settingsGroups(changes);
  const total = groups.reduce((n, g) => n + g.changes.length, 0);
  const cut = !all && total > CHANGES_SHOWN;
  const shown = cut ? firstChanges(groups, CHANGES_SHOWN) : groups;
  const tableId = `${ids}-table`;

  if (total === 0 && pins.length === 0) return null;

  return (
    <div data-settings-changes="" className="flex min-w-0 flex-col gap-2">
      <h3 id={`${ids}-title`} className={subLabel}>
        What changed
      </h3>
      {total > 0 && (
        <table id={tableId} aria-labelledby={`${ids}-title`} className="w-full border-collapse text-sm text-temper-text">
          <thead>
            <tr className="border-b border-[var(--team-wait-card-border)] text-left text-xs text-temper-text-muted">
              <th scope="col" className="w-[34%] px-2 py-1.5 font-semibold">
                Setting
              </th>
              <th scope="col" className="w-[33%] px-2 py-1.5 font-semibold">
                Was
              </th>
              <th scope="col" className="w-[33%] px-2 py-1.5 font-semibold">
                Now
              </th>
            </tr>
          </thead>
          {shown.map((group) => {
            const groupName = group.member ?? 'Whole team';
            return (
              <tbody key={group.member ?? ''} data-settings-group={groupName}>
                <tr>
                  <th
                    scope="rowgroup"
                    colSpan={3}
                    className="bg-temper-panel px-2 py-1 text-left text-xs font-semibold break-words text-temper-text-muted"
                  >
                    {groupName}
                  </th>
                </tr>
                {group.changes.map((change) => {
                  const name = settingLabel(change.key) ?? change.key;
                  const who = group.member ? `${group.member}'s` : "the team's";
                  return (
                    <tr
                      key={`${change.scope}:${change.member ?? ''}:${change.key}`}
                      data-setting={change.key}
                      className="border-b border-[var(--team-wait-card-border)] align-top"
                    >
                      <th scope="row" className="px-2 py-1.5 text-left font-semibold break-words">
                        <SettingName change={change} />
                      </th>
                      <td className="px-2 py-1.5">
                        <Value view={settingValue(change.old, change.value_kind)} what={`${who} old ${name}`} />
                      </td>
                      <td className="px-2 py-1.5">
                        <Value view={settingValue(change.new, change.value_kind)} what={`${who} new ${name}`} />
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            );
          })}
        </table>
      )}
      {total > CHANGES_SHOWN && (
        <p className="m-0 text-xs text-temper-text-muted">
          {cut && <>{total - CHANGES_SHOWN} more changes · </>}
          <button
            type="button"
            aria-expanded={all}
            aria-controls={tableId}
            onClick={() => setAll((v) => !v)}
            className={cn(HIT_AREA, 'inline-flex min-h-6 items-center align-middle text-temper-text')}
          >
            <span className={cn('underline underline-offset-2', HIT_AREA_RING)}>{all ? 'Show fewer' : 'Show all'}</span>
          </button>
        </p>
      )}
      {pins.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-1 p-0 text-xs text-temper-text-muted">
          {pins.map((pin) => (
            <li key={pin.member} data-pin={pin.member} className="flex flex-wrap items-center gap-x-1.5">
              <span className="break-words">Settings fingerprint · {pin.member}</span>
              <Value view={fingerprint(pin.pin_old)} what={`${pin.member}'s old settings fingerprint`} />
              <span aria-hidden="true">→</span>
              <span className="sr-only">to</span>
              <Value view={fingerprint(pin.pin_new)} what={`${pin.member}'s new settings fingerprint`} />
            </li>
          ))}
        </ul>
      )}
      <p className="m-0 text-xs text-temper-text-muted">
        Code and files show their fingerprint: the first 12 characters of the sha256.
      </p>
    </div>
  );
}

/**
 * The settings wait's "What changed" table (contract E24, Design's SPEC
 * 5.2a), from the wait's typed fields only: never parsed from the question.
 */
import type { TeamSettingsChange } from '@/types/team';

/** How many hex digits of a digest show on screen: the fingerprint, as code and files show it. */
export const DIGEST_SHOWN = 12;

/** More changes than this show the first ones, then "<n> more changes · Show all". */
export const CHANGES_SHOWN = 8;

/** Design's line under a settings wait's title (SPEC 5.2a). */
export const SETTINGS_WAIT_LINE =
  'Nothing has run with the new settings yet. Your last answer is on hold: it is applied once after Go on, and dropped if you stop.';

const HEX64 = /^[0-9a-f]{64}$/;
const IMAGE_DIGEST = /^sha256:([0-9a-f]{64})$/;

export interface SettingValueView {
  /** What the cell shows: the text in full, a digest's first 12 hex, or "(none)". */
  shown: string;
  /** The whole value, for the title and the copy button; null when nothing is cut. */
  full: string | null;
}

/**
 * A value as the table shows it. A sha256 shows its first 12 hex; so does a
 * "sha256:" image value, which drops only that prefix on screen (the title
 * and the copy keep it). Text shows in full. An absent value is "(none)".
 */
export function settingValue(value: string | null | undefined, valueKind: string): SettingValueView {
  if (value == null || value === '') return { shown: '(none)', full: null };
  if (valueKind === 'sha256' && value.length > DIGEST_SHOWN) {
    return { shown: value.slice(0, DIGEST_SHOWN), full: value };
  }
  const image = IMAGE_DIGEST.exec(value);
  if (image) return { shown: image[1].slice(0, DIGEST_SHOWN), full: value };
  return { shown: value, full: null };
}

/** A pin digest as a fingerprint: its first 12 hex; a value that isn't one shows as it is. */
export function fingerprint(digest: string | null | undefined): SettingValueView {
  if (digest == null || digest === '') return { shown: '(none)', full: null };
  if (HEX64.test(digest)) return { shown: digest.slice(0, DIGEST_SHOWN), full: digest };
  return settingValue(digest, 'text');
}

export interface SettingsGroup {
  /** null: the whole team. */
  member: string | null;
  changes: TeamSettingsChange[];
}

/**
 * The table's groups, as the engine's question orders them: the whole team
 * first, then each member by name. A group keeps Temper's order of keys.
 */
export function settingsGroups(changes: readonly TeamSettingsChange[]): SettingsGroup[] {
  const team: TeamSettingsChange[] = [];
  const members = new Map<string, TeamSettingsChange[]>();
  for (const change of changes) {
    if (change.scope === 'member' && change.member) {
      const list = members.get(change.member) ?? [];
      list.push(change);
      members.set(change.member, list);
    } else {
      team.push(change);
    }
  }
  // Code-point order, as Python's sorted() puts the members in the question.
  const names = [...members.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const groups: SettingsGroup[] = [];
  if (team.length > 0) groups.push({ member: null, changes: team });
  for (const name of names) groups.push({ member: name, changes: members.get(name) ?? [] });
  return groups;
}

/** The groups cut to the first `limit` changes (a group shows only when one of its changes does). */
export function firstChanges(groups: readonly SettingsGroup[], limit: number): SettingsGroup[] {
  const out: SettingsGroup[] = [];
  let left = limit;
  for (const group of groups) {
    if (left <= 0) break;
    const changes = group.changes.slice(0, left);
    left -= changes.length;
    out.push({ member: group.member, changes });
  }
  return out;
}

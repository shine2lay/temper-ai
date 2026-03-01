/**
 * Reusable profile selector dropdown.
 *
 * Shows tenant profiles from the API plus a "Custom" option for inline config.
 * When a profile is selected, parent stores the profile name reference.
 * When "Custom" is selected, parent manages the inline config.
 */
import { useMemo } from 'react';
import { useProfiles, useProfile } from '@/hooks/useConfigAPI';
import { selectClass } from '../shared';

export interface ProfileSelectorProps {
  profileType: string;
  selectedProfile: string | null;
  onSelect: (profileName: string | null) => void;
  children?: React.ReactNode;
}

const PROFILE_LABELS: Record<string, string> = {
  llm: 'LLM Profile',
  safety: 'Safety Profile',
  error_handling: 'Error Handling Profile',
  observability: 'Observability Profile',
  memory: 'Memory Profile',
  budget: 'Budget Profile',
};

export function ProfileSelector({
  profileType,
  selectedProfile,
  onSelect,
  children,
}: ProfileSelectorProps) {
  const { data } = useProfiles(profileType);

  const profiles = useMemo(() => data?.profiles ?? [], [data]);
  const isCustom = selectedProfile === null;

  return (
    <div className="flex flex-col gap-2">
      <label className="text-[11px] font-medium text-temper-text-muted">
        {PROFILE_LABELS[profileType] ?? profileType}
      </label>
      <select
        className={selectClass}
        value={selectedProfile ?? '__custom__'}
        onChange={(e) => {
          const val = e.target.value;
          onSelect(val === '__custom__' ? null : val);
        }}
      >
        <option value="__custom__">Custom (inline)</option>
        {profiles.map((p) => (
          <option key={p.name} value={p.name}>
            {p.name}
          </option>
        ))}
      </select>

      {/* When a profile is selected, show a read-only summary */}
      {selectedProfile && (
        <ProfileSummaryBadge profileType={profileType} name={selectedProfile} />
      )}

      {/* When "Custom" is selected, render inline form children */}
      {isCustom && children}
    </div>
  );
}

function ProfileSummaryBadge({
  profileType,
  name,
}: {
  profileType: string;
  name: string;
}) {
  const { data } = useProfile(profileType, name);

  if (!data) return null;

  return (
    <div className="px-3 py-2 rounded bg-temper-surface/50 border border-temper-border/50 text-[10px] text-temper-text-dim">
      <p className="font-medium text-temper-text text-xs">{data.name}</p>
      {data.description && <p className="mt-0.5">{data.description}</p>}
      <p className="mt-1 text-temper-text-dim">
        {Object.keys(data.config_data || {}).length} settings configured
      </p>
    </div>
  );
}

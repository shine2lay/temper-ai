/**
 * My Library — tabbed interface to browse, search, create, and delete
 * agents, tools, stages, workflows, and profiles.
 */
import { useState, useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { toast } from 'sonner';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Button } from '@/components/ui/button';
import {
  useConfigs,
  useDeleteConfig,
  useTemplates,
  useForkConfig,
  useProfiles,
  useDeleteProfile,
  type ConfigSummary,
  type TemplateSummary,
} from '@/hooks/useConfigAPI';
import { inputClass } from './shared';

// ── Config types ─────────────────────────────────────────────────────

const CONFIG_TABS = ['workflow', 'agent', 'stage', 'tool'] as const;
type ConfigTab = (typeof CONFIG_TABS)[number];

const TAB_LABELS: Record<ConfigTab, string> = {
  workflow: 'Workflows',
  agent: 'Agents',
  stage: 'Stages',
  tool: 'Tools',
};

// ── Resource list sub-component ──────────────────────────────────────

function ResourceList({
  configType,
  onEdit,
}: {
  configType: string;
  onEdit: (type: string, name: string) => void;
}) {
  const [search, setSearch] = useState('');
  const [showTemplates, setShowTemplates] = useState(false);
  const { data, isLoading, error: _configError } = useConfigs(configType);
  const deleteMutation = useDeleteConfig(configType);

  const filtered = useMemo(() => {
    if (!data?.configs) return [];
    if (!search.trim()) return data.configs;
    const q = search.toLowerCase();
    return data.configs.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        (c.description || '').toLowerCase().includes(q),
    );
  }, [data, search]);

  const handleDelete = useCallback(
    (name: string) => {
      if (!confirm(`Delete "${name}"?`)) return;
      deleteMutation.mutate(name, {
        onSuccess: () => toast.success(`Deleted "${name}"`),
        onError: (err) => toast.error(err.message),
      });
    },
    [deleteMutation],
  );

  return (
    <div className="flex flex-col gap-3">
      {/* Search + actions */}
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={`Search ${configType}s...`}
          className={`${inputClass} flex-1`}
        />
        <Button size="sm" onClick={() => onEdit(configType, '')}>
          New
        </Button>
        <Button
          size="sm"
          variant="outline"
          onClick={() => setShowTemplates((v) => !v)}
        >
          Templates
        </Button>
      </div>

      {/* Template gallery */}
      {showTemplates && (
        <TemplateGallery
          configType={configType}
          onForked={(name) => {
            setShowTemplates(false);
            onEdit(configType, name);
          }}
        />
      )}

      {/* List */}
      {isLoading && (
        <p className="text-xs text-temper-text-muted py-4">Loading...</p>
      )}

      {filtered.map((cfg) => (
        <ConfigItem
          key={cfg.name}
          config={cfg}
          configType={configType}
          onEdit={() => onEdit(configType, cfg.name)}
          onDelete={() => handleDelete(cfg.name)}
        />
      ))}

      {!isLoading && filtered.length === 0 && (
        <p className="text-xs text-temper-text-muted py-4">
          {search ? 'No matching results' : `No ${configType}s yet — click New to create one`}
        </p>
      )}
    </div>
  );
}

// ── Single config item ───────────────────────────────────────────────

function ConfigItem({
  config,
  configType,
  onEdit,
  onDelete,
}: {
  config: ConfigSummary;
  configType: string;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const navigate = useNavigate();

  return (
    <div className="flex items-center gap-3 px-4 py-3 rounded-lg bg-temper-panel border border-temper-border hover:bg-temper-surface hover:border-temper-accent/30 transition-colors">
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-temper-text truncate">
          {config.name}
        </p>
        {config.description && (
          <p className="text-xs text-temper-text-muted truncate mt-0.5">
            {config.description}
          </p>
        )}
      </div>
      <div className="flex items-center gap-1.5 shrink-0">
        {configType === 'workflow' && (
          <Button
            size="xs"
            variant="outline"
            onClick={() => navigate(`/studio/${config.name}`)}
          >
            Open
          </Button>
        )}
        <Button size="xs" variant="outline" onClick={onEdit}>
          Edit
        </Button>
        <Button size="xs" variant="destructive" onClick={onDelete}>
          Delete
        </Button>
      </div>
    </div>
  );
}

// ── Template gallery ─────────────────────────────────────────────────

function TemplateGallery({
  configType,
  onForked,
}: {
  configType: string;
  onForked: (name: string) => void;
}) {
  const { data, isLoading } = useTemplates(configType);
  const forkMutation = useForkConfig(configType);

  const handleFork = useCallback(
    (template: TemplateSummary) => {
      const newName = prompt('Name for your copy:', `my-${template.name}`);
      if (!newName) return;
      forkMutation.mutate(
        { sourceName: template.name, newName },
        {
          onSuccess: (result) => {
            toast.success(`Forked "${template.name}" as "${result.name}"`);
            onForked(result.name);
          },
          onError: (err) => toast.error(err.message),
        },
      );
    },
    [forkMutation, onForked],
  );

  return (
    <div className="border border-temper-border rounded-lg p-3 bg-temper-surface/30">
      <p className="text-xs font-semibold text-temper-text-muted mb-2">
        Templates
      </p>
      {isLoading && (
        <p className="text-xs text-temper-text-muted">Loading templates...</p>
      )}
      {data?.templates.length === 0 && (
        <p className="text-xs text-temper-text-muted">No templates available</p>
      )}
      <div className="flex flex-col gap-1.5">
        {data?.templates.map((t) => (
          <div
            key={t.name}
            className="flex items-center gap-2 px-3 py-2 rounded bg-temper-panel border border-temper-border/50"
          >
            <div className="flex-1 min-w-0">
              <p className="text-xs font-medium text-temper-text">
                {t.name}
              </p>
              {t.description && (
                <p className="text-[10px] text-temper-text-dim truncate">
                  {t.description}
                </p>
              )}
            </div>
            <Button
              size="xs"
              variant="outline"
              onClick={() => handleFork(t)}
              disabled={forkMutation.isPending}
            >
              Fork
            </Button>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Profiles tab ─────────────────────────────────────────────────────

const PROFILE_TYPES = [
  'llm',
  'safety',
  'error_handling',
  'observability',
  'memory',
  'budget',
] as const;

const PROFILE_LABELS: Record<string, string> = {
  llm: 'LLM',
  safety: 'Safety',
  error_handling: 'Error Handling',
  observability: 'Observability',
  memory: 'Memory',
  budget: 'Budget',
};

function ProfilesTab({
  onEditProfile,
}: {
  onEditProfile: (profileType: string, name: string) => void;
}) {
  return (
    <Tabs defaultValue="llm">
      <TabsList variant="line" className="mb-3">
        {PROFILE_TYPES.map((pt) => (
          <TabsTrigger key={pt} value={pt} className="text-xs">
            {PROFILE_LABELS[pt]}
          </TabsTrigger>
        ))}
      </TabsList>
      {PROFILE_TYPES.map((pt) => (
        <TabsContent key={pt} value={pt}>
          <ProfileList
            profileType={pt}
            onEdit={(name) => onEditProfile(pt, name)}
          />
        </TabsContent>
      ))}
    </Tabs>
  );
}

function ProfileList({
  profileType,
  onEdit,
}: {
  profileType: string;
  onEdit: (name: string) => void;
}) {
  const [search, setSearch] = useState('');
  const { data, isLoading, error: _profileError } = useProfiles(profileType);
  const deleteMutation = useDeleteProfile(profileType);

  const filtered = useMemo(() => {
    if (!data?.profiles) return [];
    if (!search.trim()) return data.profiles;
    const q = search.toLowerCase();
    return data.profiles.filter(
      (p) =>
        p.name.toLowerCase().includes(q) ||
        (p.description || '').toLowerCase().includes(q),
    );
  }, [data, search]);

  const handleDelete = useCallback(
    (name: string) => {
      if (!confirm(`Delete profile "${name}"?`)) return;
      deleteMutation.mutate(name, {
        onSuccess: () => toast.success(`Deleted profile "${name}"`),
        onError: (err: Error) => toast.error(err.message),
      });
    },
    [deleteMutation],
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={`Search ${PROFILE_LABELS[profileType]} profiles...`}
          className={`${inputClass} flex-1`}
        />
        <Button size="sm" onClick={() => onEdit('')}>
          New
        </Button>
      </div>

      {isLoading && (
        <p className="text-xs text-temper-text-muted py-4">Loading...</p>
      )}

      {filtered.map((p) => (
        <div
          key={p.name}
          className="flex items-center gap-3 px-4 py-3 rounded-lg bg-temper-panel border border-temper-border hover:bg-temper-surface hover:border-temper-accent/30 transition-colors"
        >
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium text-temper-text truncate">
              {p.name}
            </p>
            {p.description && (
              <p className="text-xs text-temper-text-muted truncate mt-0.5">
                {p.description}
              </p>
            )}
          </div>
          <div className="flex items-center gap-1.5 shrink-0">
            <Button size="xs" variant="outline" onClick={() => onEdit(p.name)}>
              Edit
            </Button>
            <Button
              size="xs"
              variant="destructive"
              onClick={() => handleDelete(p.name)}
            >
              Delete
            </Button>
          </div>
        </div>
      ))}

      {!isLoading && filtered.length === 0 && (
        <p className="text-xs text-temper-text-muted py-4">
          {search ? 'No matching results' : 'No profiles yet — click New to create one'}
        </p>
      )}
    </div>
  );
}

// ── Main export ──────────────────────────────────────────────────────

export function MyLibrary() {
  const navigate = useNavigate();

  const handleEditConfig = useCallback(
    (configType: string, name: string) => {
      if (configType === 'workflow' && name) {
        navigate(`/studio/${name}`);
      } else {
        navigate(`/library/${configType}${name ? `/${name}` : '/new'}`);
      }
    },
    [navigate],
  );

  const handleEditProfile = useCallback(
    (profileType: string, name: string) => {
      navigate(
        `/library/profile/${profileType}${name ? `/${name}` : '/new'}`,
      );
    },
    [navigate],
  );

  return (
    <div className="h-full flex flex-col bg-temper-bg">
      {/* Header */}
      <div className="flex items-center justify-between px-6 py-4 border-b border-temper-border">
        <h1 className="text-lg font-semibold text-temper-text">My Library</h1>
        <Button size="sm" variant="outline" onClick={() => navigate('/')}>
          Back to Dashboard
        </Button>
      </div>

      {/* Tabbed content */}
      <div className="flex-1 overflow-y-auto px-6 py-4">
        <Tabs defaultValue="workflow">
          <TabsList variant="line" className="mb-4">
            {CONFIG_TABS.map((tab) => (
              <TabsTrigger key={tab} value={tab}>
                {TAB_LABELS[tab]}
              </TabsTrigger>
            ))}
            <TabsTrigger value="profiles">Profiles</TabsTrigger>
          </TabsList>

          {CONFIG_TABS.map((tab) => (
            <TabsContent key={tab} value={tab}>
              <ResourceList configType={tab} onEdit={handleEditConfig} />
            </TabsContent>
          ))}

          <TabsContent value="profiles">
            <ProfilesTab onEditProfile={handleEditProfile} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

/**
 * Collapsible YAML panel for all editors.
 *
 * Shows a live YAML representation of the current config.
 * Edits in the YAML textarea update the form state and vice versa.
 * Uses js-yaml for serialization/parsing.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import yaml from 'js-yaml';
import { Collapsible, CollapsibleTrigger, CollapsibleContent } from '@/components/ui/collapsible';

interface YAMLPanelProps {
  configData: Record<string, unknown>;
  onChange: (config: Record<string, unknown>) => void;
}

export function YAMLPanel({ configData, onChange }: YAMLPanelProps) {
  const [open, setOpen] = useState(false);
  const [yamlText, setYamlText] = useState('');
  const [parseError, setParseError] = useState<string | null>(null);
  const isInternalUpdate = useRef(false);

  // Sync form data → YAML text (when form changes externally)
  useEffect(() => {
    if (isInternalUpdate.current) {
      isInternalUpdate.current = false;
      return;
    }
    try {
      const text = yaml.dump(configData, {
        indent: 2,
        lineWidth: 120,
        noRefs: true,
        sortKeys: false,
      });
      setYamlText(text);
      setParseError(null);
    } catch {
      // Form data can't be serialized — keep existing text
    }
  }, [configData]);

  // Handle YAML text edits → parse and update form
  const handleYamlChange = useCallback(
    (text: string) => {
      setYamlText(text);
      try {
        const parsed = yaml.load(text);
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
          setParseError(null);
          isInternalUpdate.current = true;
          onChange(parsed as Record<string, unknown>);
        } else {
          setParseError('YAML must be a mapping (object), not a scalar or array');
        }
      } catch (err) {
        setParseError((err as Error).message);
      }
    },
    [onChange],
  );

  return (
    <Collapsible open={open} onOpenChange={setOpen}>
      <CollapsibleTrigger asChild>
        <button className="flex items-center gap-1.5 w-full px-3 py-2 text-[10px] font-semibold text-temper-text-muted uppercase tracking-wider hover:text-temper-text hover:bg-temper-surface/30 transition-colors border-t border-temper-border/50">
          <span className="text-[8px]">{open ? '\u25BE' : '\u25B8'}</span>
          Show YAML
        </button>
      </CollapsibleTrigger>
      <CollapsibleContent>
        <div className="px-3 pb-3">
          <textarea
            value={yamlText}
            onChange={(e) => handleYamlChange(e.target.value)}
            className="w-full h-64 px-3 py-2 text-xs font-mono bg-temper-surface border border-temper-border rounded text-temper-text resize-y"
            spellCheck={false}
          />
          {parseError && (
            <p className="mt-1 text-[10px] text-red-400">{parseError}</p>
          )}
        </div>
      </CollapsibleContent>
    </Collapsible>
  );
}

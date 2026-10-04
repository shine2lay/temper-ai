/**
 * Inline validation error/success banner for the Studio editor.
 */
import { useDesignStore } from '@/store/designStore';

export function ValidationBanner() {
  const validation = useDesignStore((s) => s.validation);

  if (validation.status === 'idle') return null;

  if (validation.status === 'validating') {
    return (
      <div className="px-4 py-1.5 bg-temper-accent/10 text-temper-accent text-xs border-b border-temper-border">
        Validating...
      </div>
    );
  }

  if (validation.status === 'valid') {
    return (
      <div className="px-4 py-1.5 bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 text-xs border-b border-temper-border">
        Configuration is valid
      </div>
    );
  }

  // invalid
  return (
    <div className="px-4 py-1.5 bg-red-500/10 text-red-700 dark:text-red-400 text-xs border-b border-temper-border">
      <span className="font-medium">Validation errors:</span>
      <ul className="list-disc list-inside mt-0.5">
        {validation.errors.map((err, i) => (
          <li key={i}>{err}</li>
        ))}
      </ul>
    </div>
  );
}

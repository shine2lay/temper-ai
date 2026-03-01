/**
 * Route entry for /library/:configType/:name and /library/profile/:profileType/:name.
 *
 * Routes to the correct editor based on URL params.
 */
import { useParams, Link } from 'react-router-dom';
import { AgentEditor } from '@/components/studio/editors/AgentEditor';
import { StageEditor } from '@/components/studio/editors/StageEditor';
import { ToolEditor } from '@/components/studio/editors/ToolEditor';
import { WorkflowEditor } from '@/components/studio/editors/WorkflowEditor';
import { ProfileEditor } from '@/components/studio/editors/ProfileEditor';

export function EditorView() {
  const { configType, name, profileType } = useParams<{
    configType?: string;
    name?: string;
    profileType?: string;
  }>();

  const editName = name === 'new' ? null : name ?? null;

  // Profile editor
  if (profileType) {
    return <ProfileEditor profileType={profileType} name={editName} />;
  }

  // Config editors
  switch (configType) {
    case 'agent':
      return <AgentEditor name={editName} />;
    case 'stage':
      return <StageEditor name={editName} />;
    case 'tool':
      return <ToolEditor name={editName} />;
    case 'workflow':
      return <WorkflowEditor name={editName} />;
    default:
      return (
        <div className="flex flex-col items-center justify-center h-full bg-temper-bg gap-2">
          <p className="text-sm text-red-400">Unknown config type: {configType}</p>
          <Link to="/library" className="text-xs text-temper-accent hover:underline">
            Back to Library
          </Link>
        </div>
      );
  }
}

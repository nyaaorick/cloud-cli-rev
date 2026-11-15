import { memo } from 'react';

import { useProjectCommandState } from '@/modules/project-workspace/context/ProjectsStateContext';
import { CommandPalette } from '@/modules/command-palette';
import { useWorkbenchLayout } from '@/modules/project-workspace/context/WorkbenchLayoutContext';

/** Rendered by ProjectWorkspaceShell to bind this module's project state to the command-palette module. */
function ProjectCommandPalette() {
  const { commandsOpen, setCommandsOpen, setTerminalOpen } = useWorkbenchLayout();
  const {
    selectedProject,
    handleNewSession,
    openSettings,
    setActiveTab,
  } = useProjectCommandState();

  return (
    <CommandPalette
      selectedProject={selectedProject}
      onStartNewChat={handleNewSession}
      onOpenSettings={openSettings}
      onShowTab={(tab) => tab === 'shell' ? setTerminalOpen(true) : setActiveTab(tab)}
      open={commandsOpen}
      onOpenChange={setCommandsOpen}
    />
  );
}

export default memo(ProjectCommandPalette);

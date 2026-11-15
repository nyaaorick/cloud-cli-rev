import { memo } from 'react';

import ProjectEffects from '@/modules/project-workspace/controllers/ProjectEffects';
import type { ProjectWorkspaceShellProps } from '@/shared/types';
import ProjectCommandPalette from '@/modules/project-workspace/ProjectCommandPalette';
import ProjectMainRegion from '@/modules/project-workspace/ProjectMainRegion';
import ProjectQuickSettingsRegion from '@/modules/project-workspace/ProjectQuickSettingsRegion';
import ProjectSidebarRegion from '@/modules/project-workspace/ProjectSidebarRegion';
import { WorkbenchActivityBar, WorkbenchStatusBar, WorkbenchTitleBar } from '@/modules/project-workspace/WorkbenchChrome';
import { useProjectMainState } from '@/modules/project-workspace/context/ProjectsStateContext';
import { useUiPreferences } from '@/shared/context/UiPreferencesContext';
import '@/modules/project-workspace/workbench.css';

/** Rendered by ProjectWorkspaceRoute to lay out the workspace sidebar, main region and global overlays. */
function ProjectWorkspaceShell({
  isMobile,
  ws,
  sendMessage,
  navigate,
}: ProjectWorkspaceShellProps) {
  const { activeTab } = useProjectMainState();
  const { sidebarVisible } = useUiPreferences();
  const showSessionSidebar = isMobile || (sidebarVisible && activeTab !== 'files');
  return (
    <div
      className="workbench fixed inset-0 flex flex-col bg-background"
      style={{ bottom: 'var(--keyboard-height, 0px)' }}
    >
      <ProjectEffects navigate={navigate} />
      {!isMobile && <WorkbenchTitleBar />}
      <div className="flex min-h-0 flex-1 overflow-hidden">
      {!isMobile && <WorkbenchActivityBar />}
      <div className={showSessionSidebar ? 'contents' : 'hidden'}>
        <ProjectSidebarRegion isMobile={isMobile} />
      </div>

      <div className="flex min-w-0 flex-1 flex-col">
        <ProjectMainRegion
          isMobile={isMobile}
          ws={ws}
          sendMessage={sendMessage}
          navigate={navigate}
        />
      </div>

      <ProjectCommandPalette />
      {/* Last flex child on purpose: when pinned it docks to the right of the main region. */}
      <ProjectQuickSettingsRegion />
      </div>
      {!isMobile && <WorkbenchStatusBar />}
    </div>
  );
}

export default memo(ProjectWorkspaceShell);

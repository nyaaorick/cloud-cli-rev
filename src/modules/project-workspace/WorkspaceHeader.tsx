import type { Dispatch, SetStateAction } from 'react';

import type { AppTab, Project, ProjectSession } from '@/shared/types';
import MobileMenuButton from '@/modules/project-workspace/MobileMenuButton';
import WorkspaceConnectionStatus from '@/modules/project-workspace/WorkspaceConnectionStatus';
import WorkspaceTabs from '@/modules/project-workspace/WorkspaceTabs';
import WorkspaceTitle from '@/modules/project-workspace/WorkspaceTitle';

type WorkspaceHeaderProps = {
  activeTab: AppTab;
  setActiveTab: Dispatch<SetStateAction<AppTab>>;
  selectedProject: Project;
  selectedSession: ProjectSession | null;
  shouldShowTasksTab: boolean;
  shouldShowBrowserTab: boolean;
  isMobile: boolean;
  onMenuClick: () => void;
  /** Persists a new title for a session; resolves false when the backend refuses it. */
  onRenameSession: (sessionId: string, summary: string) => Promise<boolean>;
};

/** Rendered by WorkspaceMain as its compact document strip; mobile retains scrollable view navigation. */
export default function WorkspaceHeader({
  activeTab,
  setActiveTab,
  selectedProject,
  selectedSession,
  shouldShowTasksTab,
  shouldShowBrowserTab,
  isMobile,
  onMenuClick,
  onRenameSession,
}: WorkspaceHeaderProps) {
  return (
    <header className="workbench-editor-header pwa-header-safe">
      <div className="flex min-w-0 items-center">
        {isMobile && <MobileMenuButton onMenuClick={onMenuClick} />}
        <div className="workbench-document-tab">
          <WorkspaceTitle activeTab={activeTab} selectedProject={selectedProject} selectedSession={selectedSession} shouldShowTasksTab={shouldShowTasksTab} onRenameSession={onRenameSession} />
        </div>
        <div className="ml-auto px-3"><WorkspaceConnectionStatus /></div>
      </div>
      {isMobile && (
        <div className="scrollbar-hide overflow-x-auto">
          <WorkspaceTabs activeTab={activeTab} setActiveTab={setActiveTab} shouldShowTasksTab={shouldShowTasksTab} shouldShowBrowserTab={shouldShowBrowserTab} />
        </div>
      )}
    </header>
  );
}

import { ArrowLeft, ArrowRight, ChevronsLeftRight, PanelBottom, PanelLeft, Search, Settings, SquarePen, TerminalSquare } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';

import { useProjectCommandState, useProjectMainState } from '@/modules/project-workspace/context/ProjectsStateContext';
import { useWorkbenchLayout } from '@/modules/project-workspace/context/WorkbenchLayoutContext';
import WorkspaceTabs from '@/modules/project-workspace/WorkspaceTabs';
import { useTasksSettings } from '@/modules/task-master';
import { useBrowserUseEnabled } from '@/modules/browser-use';
import { useSetUiPreference, useUiPreferences } from '@/shared/context/UiPreferencesContext';
import { useWebSocket } from '@/shared/context/WebSocketContext';

/** Used by ProjectWorkspaceShell for its project command center and layout controls. */
export function WorkbenchTitleBar() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { selectedProject, activeTab, setActiveTab } = useProjectMainState();
  const { commandsOpen, setCommandsOpen, terminalOpen, setTerminalOpen } = useWorkbenchLayout();
  const { sidebarVisible } = useUiPreferences();
  const setPreference = useSetUiPreference();
  const commandShortcut = /Mac|iPhone|iPad/.test(navigator.platform) ? '⇧ ⌘ P' : 'Ctrl+Shift+P';
  const sidebarOpen = activeTab === 'files' || sidebarVisible;
  const toggleSidebar = () => {
    if (activeTab === 'files') {
      setActiveTab('chat');
      setPreference('sidebarVisible', false);
    } else {
      setPreference('sidebarVisible', !sidebarVisible);
    }
  };

  return (
    <div className="workbench-titlebar">
      <div className="workbench-brand"><TerminalSquare size={17} /><span>Cloud Cli rev</span></div>
      <div className="workbench-command-group">
        <button type="button" className="workbench-icon-button workbench-history-button" aria-label={t('workbench.back', { defaultValue: 'Go Back' })} onClick={() => navigate(-1)}><ArrowLeft size={16} /></button>
        <button type="button" className="workbench-icon-button workbench-history-button" aria-label={t('workbench.forward', { defaultValue: 'Go Forward' })} onClick={() => navigate(1)}><ArrowRight size={16} /></button>
        <button type="button" className="workbench-command-center" aria-label={t('workbench.commands', { defaultValue: 'Search files and commands' })} aria-expanded={commandsOpen} onClick={() => setCommandsOpen(true)}>
          <Search size={13} /><span>{selectedProject?.displayName || 'Cloud Cli rev'}</span><kbd>{commandShortcut}</kbd>
        </button>
      </div>
      <div className="workbench-layout-actions">
        <button type="button" className="workbench-icon-button" aria-label={t('workbench.sidebar', { defaultValue: 'Toggle Primary Side Bar' })} aria-pressed={sidebarOpen} onClick={toggleSidebar}><PanelLeft size={16} /></button>
        <button type="button" className="workbench-icon-button" aria-label={t('workbench.panel', { defaultValue: 'Toggle Panel' })} aria-pressed={terminalOpen} onClick={() => setTerminalOpen((open) => !open)}><PanelBottom size={16} /></button>
      </div>
    </div>
  );
}

/** Used by ProjectWorkspaceShell to keep workspace navigation and settings in one persistent activity bar. */
export function WorkbenchActivityBar() {
  const { t } = useTranslation();
  const { activeTab, setActiveTab, openSettings } = useProjectMainState();
  const { selectedProject, handleNewSession } = useProjectCommandState();
  const { tasksEnabled, isTaskMasterInstalled } = useTasksSettings();
  const browserUseEnabled = useBrowserUseEnabled();
  const { terminalOpen, setTerminalOpen } = useWorkbenchLayout();
  const { sidebarVisible } = useUiPreferences();
  const setPreference = useSetUiPreference();

  return (
    <aside className="workbench-activitybar" aria-label={t('workbench.activityBar', { defaultValue: 'Activity Bar' })}>
      <WorkspaceTabs
        activeTab={activeTab}
        setActiveTab={setActiveTab}
        shouldShowTasksTab={Boolean(tasksEnabled && isTaskMasterInstalled)}
        shouldShowBrowserTab={browserUseEnabled}
        variant="activity"
        sidebarVisible={sidebarVisible}
        onToggleSidebar={() => setPreference('sidebarVisible', !sidebarVisible)}
      />
      <div className="workbench-activitybar-bottom">
        <button type="button" className="workbench-activity-button" title={t('mainContent.newSession')} aria-label={t('mainContent.newSession')} disabled={!selectedProject} onClick={() => selectedProject && handleNewSession(selectedProject)}><SquarePen size={22} /></button>
        <button type="button" className="workbench-activity-button" title={t('tabs.shell')} aria-label={t('tabs.shell')} aria-pressed={terminalOpen} onClick={() => setTerminalOpen((open) => !open)}><PanelBottom size={22} /></button>
        <button type="button" className="workbench-activity-button" title={t('commandPalette.openSettings')} aria-label={t('commandPalette.openSettings')} onClick={() => openSettings()}><Settings size={23} /></button>
      </div>
    </aside>
  );
}

/** Used by ProjectWorkspaceShell to expose real project/connection state and the bottom-panel toggle. */
export function WorkbenchStatusBar() {
  const { t } = useTranslation();
  const { selectedProject, selectedSession } = useProjectMainState();
  const { connectionStatus } = useWebSocket();
  const { terminalOpen, setTerminalOpen } = useWorkbenchLayout();

  return (
    <footer className="workbench-statusbar">
      <span className="workbench-remote-indicator" title="Cloud Cli rev"><ChevronsLeftRight size={14} /></span>
      <span className="workbench-connection"><span className={`workbench-connection-dot ${connectionStatus === 'connected' ? 'is-connected' : ''}`} />{t(`workbench.${connectionStatus}`, { defaultValue: connectionStatus })}</span>
      <span className="workbench-status-path" title={selectedProject?.path}>{selectedProject?.displayName}</span>
      <span className="ml-auto capitalize">{selectedSession?.__provider || ''}</span>
      <button type="button" aria-pressed={terminalOpen} onClick={() => setTerminalOpen((open) => !open)}><PanelBottom size={13} />{t('tabs.shell')}</button>
      <span className="workbench-status-version">{__APP_VERSION__}</span>
    </footer>
  );
}

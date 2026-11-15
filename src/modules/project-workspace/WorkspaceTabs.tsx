import { MessageSquare, Terminal, Folder, GitBranch, ClipboardCheck, MonitorPlay, type LucideIcon } from 'lucide-react';
import type { Dispatch, KeyboardEvent, SetStateAction } from 'react';
import { useTranslation } from 'react-i18next';

import { Tooltip } from '@/shared/ui';
import type { AppTab } from '@/shared/types';
import { usePlugins,PluginIcon } from '@/modules/plugins';

type WorkspaceTabsProps = {
  activeTab: AppTab;
  setActiveTab: Dispatch<SetStateAction<AppTab>>;
  shouldShowTasksTab: boolean;
  shouldShowBrowserTab: boolean;
  variant?: 'tabs' | 'activity';
  sidebarVisible?: boolean;
  onToggleSidebar?: () => void;
};

type BuiltInTab = {
  kind: 'builtin';
  id: AppTab;
  labelKey: string;
  icon: LucideIcon;
};

type PluginTab = {
  kind: 'plugin';
  id: AppTab;
  label: string;
  pluginName: string;
  iconFile: string;
};

type TabDefinition = BuiltInTab | PluginTab;

const BASE_TABS: BuiltInTab[] = [
  { kind: 'builtin', id: 'chat',  labelKey: 'tabs.chat',  icon: MessageSquare },
  { kind: 'builtin', id: 'shell', labelKey: 'tabs.shell', icon: Terminal },
  { kind: 'builtin', id: 'files', labelKey: 'tabs.files', icon: Folder },
  { kind: 'builtin', id: 'git',   labelKey: 'tabs.git',   icon: GitBranch },
];

const BROWSER_TAB: BuiltInTab = {
  kind: 'builtin',
  id: 'browser',
  labelKey: 'tabs.browser',
  icon: MonitorPlay,
};

const TASKS_TAB: BuiltInTab = {
  kind: 'builtin',
  id: 'tasks',
  labelKey: 'tabs.tasks',
  icon: ClipboardCheck,
};

/** Rendered by WorkspaceHeader to show the built-in workspace tabs plus any enabled plugin tabs. */
export default function WorkspaceTabs({
  activeTab,
  setActiveTab,
  shouldShowTasksTab,
  shouldShowBrowserTab,
  variant = 'tabs',
  sidebarVisible = true,
  onToggleSidebar,
}: WorkspaceTabsProps) {
  const { t } = useTranslation();
  const { plugins } = usePlugins();

  const builtInTabs: BuiltInTab[] = [
    ...BASE_TABS.filter((tab) => variant !== 'activity' || tab.id !== 'shell'),
    ...(shouldShowBrowserTab ? [BROWSER_TAB] : []),
    ...(shouldShowTasksTab ? [TASKS_TAB] : []),
  ];

  const pluginTabs: PluginTab[] = plugins
    .filter((p) => p.enabled)
    .map((p) => ({
      kind: 'plugin',
      id: `plugin:${p.name}` as AppTab,
      label: p.displayName,
      pluginName: p.name,
      iconFile: p.icon,
    }));

  const tabs: TabDefinition[] = [...builtInTabs, ...pluginTabs];

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    const tabList = event.currentTarget.closest('[data-workbench-navigation]');
    if (!tabList) return;

    const tabButtons = Array.from(tabList.querySelectorAll<HTMLButtonElement>('button'));
    const currentIndex = tabButtons.indexOf(event.currentTarget);
    let nextIndex: number;

    if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (currentIndex + 1) % tabButtons.length;
    else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (currentIndex - 1 + tabButtons.length) % tabButtons.length;
    else if (event.key === 'Home') nextIndex = 0;
    else if (event.key === 'End') nextIndex = tabButtons.length - 1;
    else return;

    event.preventDefault();
    tabButtons[nextIndex]?.focus();
    tabButtons[nextIndex]?.click();
  };

  return (
    <nav
      data-workbench-navigation
      aria-label={t('tabs.views', { defaultValue: 'Workspace views' })}
      className={variant === 'activity' ? 'workbench-activity-navigation' : 'workbench-mobile-navigation'}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === activeTab && (tab.id !== 'chat' || sidebarVisible);
        const displayLabel = tab.kind === 'builtin' ? t(tab.labelKey) : tab.label;
        const handleSelect = () => {
          if (variant === 'activity' && tab.id === 'chat' && activeTab === 'chat') {
            onToggleSidebar?.();
          } else if (variant === 'activity' && tab.id === 'files' && activeTab === 'files') {
            setActiveTab('chat');
            if (sidebarVisible) onToggleSidebar?.();
          } else {
            setActiveTab(tab.id);
            if (tab.id === 'chat' && !sidebarVisible) onToggleSidebar?.();
          }
        };
        return (
          <Tooltip key={tab.id} content={displayLabel} position={variant === 'activity' ? 'right' : 'bottom'}>
            <button
              type="button"
              aria-label={displayLabel}
              aria-pressed={isActive}
              onClick={handleSelect}
              onKeyDown={handleTabKeyDown}
              className={variant === 'activity' ? 'workbench-activity-button' : 'workbench-mobile-tab'}
            >
              {tab.kind === 'builtin' ? (
                <tab.icon size={variant === 'activity' ? 24 : 16} strokeWidth={1.5} />
              ) : (
                <PluginIcon pluginName={tab.pluginName} iconFile={tab.iconFile} className="flex h-5 w-5 items-center justify-center [&>svg]:h-full [&>svg]:w-full" />
              )}
              {variant !== 'activity' && <span>{displayLabel}</span>}
            </button>
          </Tooltip>
        );
      })}
    </nav>
  );
}

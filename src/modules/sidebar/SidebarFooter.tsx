import { Settings, ArrowUpCircle, Bug, AlertTriangle } from 'lucide-react';
import type { TFunction } from 'i18next';

import { IS_PLATFORM } from '@/shared/utils';
import type { ReleaseInfo } from '@/shared/types';

type SidebarFooterProps = {
  updateAvailable: boolean;
  restartRequired: boolean;
  releaseInfo: ReleaseInfo | null;
  latestVersion: string | null;
  currentVersion: string;
  onShowVersionModal: () => void;
  onShowSettings: () => void;
  t: TFunction;
};

/** Rendered by SidebarContent for update/restart notices and compact product links; mobile also needs settings here. */
export default function SidebarFooter({ updateAvailable, restartRequired, releaseInfo, latestVersion, currentVersion, onShowVersionModal, onShowSettings, t }: SidebarFooterProps) {
  return (
    <div className="flex-shrink-0" style={{ paddingBottom: 'env(safe-area-inset-bottom, 0)' }}>
      {restartRequired && <div className="workbench-sidebar-warning"><AlertTriangle size={14} /><span>{t('version.restartRequired')}</span></div>}
      {updateAvailable && (
        <button type="button" className="workbench-sidebar-update" onClick={onShowVersionModal}>
          <ArrowUpCircle size={14} /><span className="truncate">{t('version.updateAvailable')} · {releaseInfo?.title || `v${latestVersion}`}</span>
        </button>
      )}
      <div className="workbench-sidebar-footer">
        {!IS_PLATFORM && <a className="min-w-0 flex-1 truncate" href="https://github.com/nyaaorick/cloud-cli-rev" target="_blank" rel="noopener noreferrer">Cloud Cli rev · {currentVersion}</a>}
        <a className="workbench-icon-button" href="https://github.com/nyaaorick/cloud-cli-rev/issues" target="_blank" rel="noopener noreferrer" aria-label={t('actions.reportIssue')} title={t('actions.reportIssue')}><Bug size={14} /></a>
        <button type="button" className="workbench-icon-button md:hidden" onClick={onShowSettings} aria-label={t('actions.settings')}><Settings size={16} /></button>
      </div>
    </div>
  );
}

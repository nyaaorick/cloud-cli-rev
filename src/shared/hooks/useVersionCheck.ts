import { useState, useEffect } from 'react';

import { api } from '@/shared/api';
import { APP_VERSION } from '@/shared/constants';
import type { InstallMode, ReleaseInfo } from '@/shared/types';

/** Used by the sidebar and About tab; all release selection belongs to the Rev backend. */
export const useVersionCheck = () => {
  // The available release controls the update prompt; it is refreshed from the shared backend channel.
  const [updateAvailable, setUpdateAvailable] = useState(false);
  // The displayed target version comes from the same validated release as the update action.
  const [latestVersion, setLatestVersion] = useState<string | null>(null);
  // Release notes and links accompany the selected target version.
  const [releaseInfo, setReleaseInfo] = useState<ReleaseInfo | null>(null);
  // Only explicitly managed installations can request an independent deployment.
  const [installMode, setInstallMode] = useState<InstallMode>('archive');
  // Running and built versions detect a stale client after an ingress switch.
  const [runningVersion, setRunningVersion] = useState<string | null>(null);
  // The sidebar exposes a refresh hint when the loaded frontend belongs to an older version.
  const [restartRequired, setRestartRequired] = useState(false);
  // Failed checks are visible instead of being mistaken for an up-to-date result.
  const [releaseCheckError, setReleaseCheckError] = useState(false);

  useEffect(() => {
    let disposed = false;
    const check = async () => {
      try {
        const healthResponse = await api.system.health();
        if (!healthResponse.ok) throw new Error('Health check failed');
        const health = await healthResponse.json();
        if (!disposed && typeof health.version === 'string') {
          setRunningVersion(health.version);
          setRestartRequired(health.version !== APP_VERSION);
        }
        const response = await api.system.release();
        if (!response.ok) throw new Error('Rev release check failed');
        const data = await response.json();
        if (disposed) return;
        setInstallMode(data.installMode);
        setLatestVersion(data.latestVersion);
        setUpdateAvailable(data.updateAvailable === true);
        setReleaseInfo(data.releaseInfo);
        setReleaseCheckError(false);
      } catch {
        if (!disposed) setReleaseCheckError(true);
      }
    };
    void check();
    const interval = setInterval(check, 5 * 60 * 1000);
    return () => { disposed = true; clearInterval(interval); };
  }, []);
  return { updateAvailable, latestVersion, currentVersion: APP_VERSION, releaseInfo,
    installMode, runningVersion, restartRequired, releaseCheckError };
};

import { revReleases } from '@/shared/index.js';

type SystemUpdateDependencies = {
  version: string;
  installMode: 'managed' | 'git' | 'archive';
  fetchLatestRelease: typeof revReleases.fetchLatest;
  requestManagedUpdate(): Promise<void>;
};

/** Used by authenticated system routes and the CLI through the production composition root. */
export function createSystemUpdateService(dependencies: SystemUpdateDependencies) {
  let pending: Promise<{ success: boolean; status: string; message: string; output: string }> | null = null;
  const getReleaseStatus = async () => {
    const release = await dependencies.fetchLatestRelease();
    return {
      repository: revReleases.repository,
      currentVersion: dependencies.version,
      latestVersion: release?.version ?? null,
      releaseInfo: release,
      installMode: dependencies.installMode,
      updateSupported: dependencies.installMode === 'managed',
      updateAvailable: release !== null && revReleases.compareVersions(release.version, dependencies.version) === 1,
      releasesUrl: revReleases.url,
    };
  };
  const performUpdate = async () => {
    const status = await getReleaseStatus();
    if (!status.latestVersion) throw new Error('No published Rev GitHub release is available');
    if (!status.updateAvailable) return { success: true, status: 'up-to-date',
      message: 'Cloud Cli rev is up to date.', output: `Current Rev version: ${dependencies.version}` };
    if (!status.updateSupported) throw new Error(`Use a managed Rev installation to update. Releases: ${revReleases.url}`);
    await dependencies.requestManagedUpdate();
    return { success: true, status: 'queued', message: 'Rev update queued in the independent deployment service.',
      output: `Requested ${status.latestVersion} from ${revReleases.url}. Existing sessions remain running.` };
  };
  return {
    getReleaseStatus,
    async updateSystem() {
      if (pending) return pending;
      pending = performUpdate();
      try { return await pending; } finally { pending = null; }
    },
  };
}

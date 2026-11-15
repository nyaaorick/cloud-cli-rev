import { execFile } from 'node:child_process';
import { promisify } from 'node:util';

import type { Router } from 'express';

import { getRevInstallation, revReleases } from '@/shared/index.js';

import { createSystemRouter } from './system.routes.js';
import { createSystemUpdateService } from './system.service.js';

type SystemModuleOptions = { appRoot: string; version: string };

/** Used by the CLI and HTTP module; updates run only through the fixed independent deployment unit. */
export function createRevUpdateService(options: SystemModuleOptions) {
  const installation = getRevInstallation(options.appRoot);
  let cached: Awaited<ReturnType<typeof revReleases.fetchLatest>> = null;
  let expires = 0;
  let lookup: ReturnType<typeof revReleases.fetchLatest> | null = null;
  const fetchLatestRelease = async () => {
    if (Date.now() < expires) return cached;
    if (!lookup) lookup = revReleases.fetchLatest();
    try {
      cached = await lookup;
      expires = Date.now() + (cached ? 300000 : 30000);
      return cached;
    } finally { lookup = null; }
  };
  return createSystemUpdateService({
    version: options.version,
    installMode: installation.mode,
    fetchLatestRelease,
    requestManagedUpdate: async () => {
      if (!installation.updateService) throw new Error('Managed Rev update service is not configured');
      try {
        await promisify(execFile)('/usr/bin/sudo', ['-n', '/usr/bin/systemctl', 'start', '--no-block', installation.updateService],
          { timeout: 15000, maxBuffer: 4096 });
      } catch { throw new Error('The independent Rev deployment service could not be started'); }
    },
  });
}

/** Used by server bootstrap to mount authenticated version and update routes. */
export function createSystemModule(options: SystemModuleOptions): Router {
  return createSystemRouter(createRevUpdateService(options));
}

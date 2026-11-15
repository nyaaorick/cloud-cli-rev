import assert from 'node:assert/strict';
import test from 'node:test';

import express from 'express';

import { createSystemRouter } from '../system.routes.js';
import { createSystemUpdateService } from '../system.service.js';

test('release status and update responses expose the same fork/version without accepting a caller command', async () => {
  let deployments = 0;
  const service = createSystemUpdateService({ version: '1.37.8-rev.2', installMode: 'managed',
    fetchLatestRelease: async () => ({ version: '1.37.8-rev.3', title: 'Rev', body: '',
      htmlUrl: 'https://github.com/nyaaorick/cloud-cli-rev/releases/tag/v1.37.8-rev.3', publishedAt: '' }),
    requestManagedUpdate: async () => { deployments += 1; },
  });
  const app = express();
  app.use(express.json());
  app.use('/api/system', createSystemRouter(service));
  const server = app.listen(0, '127.0.0.1');
  await new Promise<void>(resolve => server.once('listening', resolve));
  try {
    const address = server.address();
    assert.ok(address && typeof address === 'object');
    const base = `http://127.0.0.1:${address.port}/api/system`;
    const status = await (await fetch(base + '/release')).json() as { repository: string; latestVersion: string };
    assert.equal(status.repository, 'nyaaorick/cloud-cli-rev');
    assert.equal(status.latestVersion, '1.37.8-rev.3');
    const response = await fetch(base + '/update', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ command: 'untrusted command', repository: 'another/repo' }) });
    assert.equal(response.status, 200);
    assert.equal(((await response.json()) as { status: string }).status, 'queued');
    assert.equal(deployments, 1);
  } finally {
    server.closeAllConnections();
    await new Promise<void>(resolve => server.close(() => resolve()));
  }
});

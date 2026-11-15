import assert from 'node:assert/strict';
import test from 'node:test';

import { revReleases } from '@/shared/index.js';
import { createSystemUpdateService } from '../system.service.js';

type Dependencies = Parameters<typeof createSystemUpdateService>[0];
const release = { version: '1.37.8-rev.3', title: 'Rev', body: '',
  htmlUrl: 'https://github.com/nyaaorick/cloud-cli-rev/releases/tag/v1.37.8-rev.3', publishedAt: '' };
function service(overrides: Partial<Dependencies> = {}) {
  return createSystemUpdateService({ version: '1.37.8-rev.2', installMode: 'managed',
    fetchLatestRelease: async () => release, requestManagedUpdate: async () => undefined, ...overrides });
}

test('Rev status uses the fork release and recognizes revision updates', async () => {
  const status = await service().getReleaseStatus();
  assert.equal(status.repository, 'nyaaorick/cloud-cli-rev');
  assert.equal(status.updateAvailable, true);
  assert.equal(status.latestVersion, '1.37.8-rev.3');
});
test('current and older releases never request a deployment', async () => {
  for (const version of ['1.37.8-rev.3', '1.37.8-rev.4']) {
    const result = await service({ version, requestManagedUpdate: async () => { throw new Error('must not run'); } }).updateSystem();
    assert.equal(result.status, 'up-to-date');
  }
});
test('updates are queued once when concurrent requests arrive', async () => {
  let requests = 0;
  let finish: () => void = () => undefined;
  const gate = new Promise<void>(resolve => { finish = resolve; });
  const updater = service({ requestManagedUpdate: async () => { requests += 1; await gate; } });
  const first = updater.updateSystem();
  const second = updater.updateSystem();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(requests, 1); finish();
  assert.equal((await first).status, 'queued');
  assert.equal((await second).status, 'queued');
});
test('archive and git modes cannot fall back to an upstream npm install', async () => {
  for (const installMode of ['archive', 'git'] as const) {
    await assert.rejects(service({ installMode }).updateSystem(), /managed Rev installation/);
  }
});
test('missing releases and lookup failures are not reported as up to date', async () => {
  await assert.rejects(service({ fetchLatestRelease: async () => null }).updateSystem(), /No published/);
  await assert.rejects(service({ fetchLatestRelease: async () => { throw new Error('offline'); } }).updateSystem(), /offline/);
});
test('SemVer handles cross-patch Rev releases, identifiers, build metadata and invalid versions', () => {
  for (const [newer, older] of [['1.37.9-rev.1', '1.37.8-rev.2'], ['1.37.8-rev.10', '1.37.8-rev.2'],
    ['1.0.0', '1.0.0-rc.1'], ['1.0.0-beta', '1.0.0-alpha.10'], ['1.0.0-alpha.1', '1.0.0-alpha']]) {
    assert.equal(revReleases.compareVersions(newer, older), 1);
    assert.equal(revReleases.compareVersions(older, newer), -1);
  }
  assert.equal(revReleases.compareVersions('1.2.3+one', '1.2.3+two'), 0);
  for (const invalid of ['01.2.3', '1.2.3-rev.01', 'nope', '1.2']) assert.equal(revReleases.compareVersions(invalid, '1.2.3'), null);
});
test('GitHub metadata is requested only from the Rev channel and malformed releases fail closed', async () => {
  let requested = '';
  const fetcher: typeof fetch = async url => { requested = String(url); return new Response(JSON.stringify({
    tag_name: 'v1.37.8-rev.3', html_url: release.htmlUrl, prerelease: false, draft: false })); };
  assert.equal((await revReleases.fetchLatest(fetcher))?.version, release.version);
  assert.equal(requested, 'https://api.github.com/repos/nyaaorick/cloud-cli-rev/releases/latest');
  assert.equal(await revReleases.fetchLatest(async () => new Response('', { status: 404 })), null);
  await assert.rejects(revReleases.fetchLatest(async () => new Response(JSON.stringify({ tag_name: 'v1.37.8-rev.3',
    html_url: 'https://github.com/siteboon/claudecodeui/releases/tag/v1.37.8-rev.3' }))), /Invalid Rev/);
});

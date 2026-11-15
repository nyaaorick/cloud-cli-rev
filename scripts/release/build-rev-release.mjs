import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { RELEASE_REPOSITORY, compareReleaseVersions } from '../../shared/releases.js';

const root = fileURLToPath(new URL('../..', import.meta.url));
const pkg = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'));
if (!/^\d+\.\d+\.\d+-rev\.\d+$/.test(pkg.version) || pkg.name !== 'cloud-cli-rev' || pkg.repository.url !== `git+https://github.com/${RELEASE_REPOSITORY}.git`
    || compareReleaseVersions(pkg.version, pkg.version) !== 0) throw new Error('Invalid Rev package identity');
const commit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: root, encoding: 'utf8' }).trim();
if (execFileSync('git', ['status', '--porcelain', '--untracked-files=no'], { cwd: root, encoding: 'utf8' }).trim()) {
  throw new Error('Commit the tested source before building a release');
}
const out = path.join(root, 'release', 'rev');
const stage = path.join(out, '.stage');
await fs.mkdir(out, { recursive: true });
await fs.rm(stage, { recursive: true, force: true });
await fs.mkdir(stage);
for (const name of ['dist', 'dist-server', 'shared', 'scripts', 'deploy', 'public', 'package.json',
  'package-lock.json', 'LICENSE', 'NOTICE', 'README.md', 'README.upstream.md']) {
  await fs.cp(path.join(root, name), path.join(stage, name), { recursive: true });
}
const archive = `cloud-cli-rev-v${pkg.version}-app.tar.gz`;
execFileSync('tar', ['-czf', path.join(out, archive), '-C', stage, '.']);
const bytes = await fs.readFile(path.join(out, archive));
const lock = await fs.readFile(path.join(root, 'package-lock.json'));
const manifest = { schemaVersion: 1, repository: RELEASE_REPOSITORY, version: pkg.version,
  tag: `v${pkg.version}`, commit, nodeMajor: 22, archive, bytes: bytes.length,
  sha256: createHash('sha256').update(bytes).digest('hex'),
  licenseSha256: createHash('sha256').update(await fs.readFile(path.join(root, 'LICENSE'))).digest('hex'),
  noticeSha256: createHash('sha256').update(await fs.readFile(path.join(root, 'NOTICE'))).digest('hex'),
  lockSha256: createHash('sha256').update(lock).digest('hex'),
  dependencyInstallation: 'npm ci --omit=dev; native modules use the target Node ABI',
  sourceUrl: `https://github.com/${RELEASE_REPOSITORY}/tree/${commit}` };
await fs.writeFile(path.join(out, 'release-manifest.json'), JSON.stringify(manifest, null, 2) + '\n');
const manifestBytes = await fs.readFile(path.join(out, 'release-manifest.json'));
await fs.writeFile(path.join(out, 'SHA256SUMS'), `${manifest.sha256}  ${archive}\n${createHash('sha256').update(manifestBytes).digest('hex')}  release-manifest.json\n`);
await fs.rm(stage, { recursive: true, force: true });
console.log(JSON.stringify({ version: pkg.version, commit, archive, bytes: bytes.length, sha256: manifest.sha256 }));

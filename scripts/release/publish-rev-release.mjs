import fs from 'node:fs/promises';
import path from 'node:path';
import { createHash } from 'node:crypto';
import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { RELEASE_REPOSITORY } from '../../shared/releases.js';

const root = fileURLToPath(new URL('../..', import.meta.url));
const out = path.join(root, 'release', 'rev');
const manifest = JSON.parse(await fs.readFile(path.join(out, 'release-manifest.json'), 'utf8'));
const pkg = JSON.parse(await fs.readFile(path.join(root, 'package.json'), 'utf8'));
const git = (...args) => execFileSync('git', args, { cwd: root, encoding: 'utf8' }).trim();
if (manifest.repository !== RELEASE_REPOSITORY || manifest.version !== pkg.version
    || manifest.commit !== git('rev-parse', 'HEAD') || manifest.commit !== git('rev-list', '-1', manifest.tag)
    || git('status', '--porcelain', '--untracked-files=no')) throw new Error('Release identity or clean-tree check failed');
const archive = path.join(out, manifest.archive);
if (path.basename(manifest.archive) !== manifest.archive || createHash('sha256').update(await fs.readFile(archive)).digest('hex') !== manifest.sha256) {
  throw new Error('Release archive checksum failed');
}
const notes = path.join(out, 'release-notes.md');
const environmentPath = path.join(out, 'cloudflare-manifest.json');
const environmentBytes = await fs.readFile(environmentPath);
const environment = JSON.parse(environmentBytes);
const environmentArchive = path.join(out, environment.archive);
if (environment.schemaVersion !== 1 || environment.repository !== RELEASE_REPOSITORY
    || environment.version !== pkg.version || environment.commit !== manifest.commit || environment.tag !== manifest.tag
    || environment.archive !== `cloud-cli-rev-v${pkg.version}-cloudflare-linux-amd64.tar.gz`
    || createHash('sha256').update(await fs.readFile(environmentArchive)).digest('hex') !== environment.sha256) {
  throw new Error('Environment release identity or checksum failed');
}
const environmentSums = await fs.readFile(path.join(out, 'CLOUDFLARE-SHA256SUMS'), 'utf8');
if (environmentSums !== `${environment.sha256}  ${environment.archive}\n${createHash('sha256').update(environmentBytes).digest('hex')}  cloudflare-manifest.json\n`) {
  throw new Error('Environment checksum manifest failed');
}
await fs.writeFile(notes, `Cloud Cli rev ${pkg.version}\n\nIndependent AGPL-3.0-or-later maintenance release.\n\nSource: ${manifest.sourceUrl}\n\nThis maintenance release adds a separate pinned Cloudflare offline environment, configurable physical-only routing and read-only diagnostics, and removes the blocking Google Fonts startup dependency.\n\nInstall/update instructions: https://github.com/${RELEASE_REPOSITORY}/blob/${manifest.tag}/deploy/cn25/REV-UPDATES.md\n\nCloudflare environment: https://github.com/${RELEASE_REPOSITORY}/blob/${manifest.tag}/deploy/cn25/cloudflare/README.md\n\nThe app archive includes compiled browser/server files and the dependency lockfile. Install production dependencies with Node 22; do not replace a running installation in place. Verify SHA256SUMS for the app and CLOUDFLARE-SHA256SUMS for the optional environment archive. The environment tools never provision DNS or replace credentials, databases or native history.\n`);
// Authentication is provided by gh internally; no .env file or token is read here.
execFileSync('gh', ['release', 'create', manifest.tag, '--repo', RELEASE_REPOSITORY, '--verify-tag',
  '--latest', '--title', `Cloud Cli rev ${pkg.version}`, '--notes-file', notes,
  archive, path.join(out, 'release-manifest.json'), path.join(out, 'SHA256SUMS'),
  environmentArchive, environmentPath, path.join(out, 'CLOUDFLARE-SHA256SUMS')], { cwd: root, stdio: 'inherit' });

/** Canonical release identity used by the app, CLI and GitHub publisher. */
export const RELEASE_REPOSITORY = 'nyaaorick/cloud-cli-rev';
export const RELEASES_URL = `https://github.com/${RELEASE_REPOSITORY}/releases`;
export const RELEASE_API_URL = `https://api.github.com/repos/${RELEASE_REPOSITORY}/releases/latest`;

function parseVersion(value) {
  if (typeof value !== 'string') return null;
  const match = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-([\da-zA-Z-]+(?:\.[\da-zA-Z-]+)*))?(?:\+[\da-zA-Z-]+(?:\.[\da-zA-Z-]+)*)?$/.exec(value);
  if (!match) return null;
  const pre = match[4]?.split('.') ?? [];
  if (pre.some(part => /^\d+$/.test(part) && part.length > 1 && part[0] === '0')) return null;
  return { core: match.slice(1, 4), pre };
}

/** Full SemVer precedence, including numeric prerelease identifiers; null rejects invalid input. */
export function compareReleaseVersions(left, right) {
  const a = parseVersion(left);
  const b = parseVersion(right);
  if (!a || !b) return null;
  for (let index = 0; index < 3; index += 1) {
    const x = BigInt(a.core[index]);
    const y = BigInt(b.core[index]);
    if (x !== y) return x > y ? 1 : -1;
  }
  if (!a.pre.length || !b.pre.length) return a.pre.length === b.pre.length ? 0 : a.pre.length ? -1 : 1;
  for (let index = 0; index < Math.max(a.pre.length, b.pre.length); index += 1) {
    const x = a.pre[index];
    const y = b.pre[index];
    if (x === undefined || y === undefined) return x === undefined ? -1 : 1;
    if (x === y) continue;
    const xn = /^\d+$/.test(x);
    const yn = /^\d+$/.test(y);
    if (xn && yn) return BigInt(x) > BigInt(y) ? 1 : -1;
    if (xn !== yn) return xn ? -1 : 1;
    return x > y ? 1 : -1;
  }
  return 0;
}

/** Fetch only this fork's published channel; Git tags alone are not releases. */
export async function fetchLatestRevRelease(fetcher = fetch) {
  const response = await fetcher(RELEASE_API_URL, {
    headers: { Accept: 'application/vnd.github+json' }, signal: AbortSignal.timeout(15000),
  });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error('Rev GitHub release lookup failed');
  const data = await response.json();
  const version = typeof data.tag_name === 'string' ? data.tag_name.replace(/^v/, '') : '';
  if (compareReleaseVersions(version, version) !== 0 || data.draft || data.prerelease
      || data.html_url !== `${RELEASES_URL}/tag/v${version}`) throw new Error('Invalid Rev GitHub release metadata');
  return { version, title: typeof data.name === 'string' ? data.name : data.tag_name,
    body: typeof data.body === 'string' ? data.body : '', htmlUrl: data.html_url,
    publishedAt: typeof data.published_at === 'string' ? data.published_at : '' };
}

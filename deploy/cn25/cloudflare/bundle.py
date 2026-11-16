#!/usr/bin/python3
"""Build the separate offline environment asset from an explicit public allowlist."""
import argparse
import gzip
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tarfile
import urllib.request

from cf_common import ROOT, sha
from install import RUNTIME_FILES

BUNDLE_FILES = (*RUNTIME_FILES, 'install.py', 'bundle.py', 'README.md', 'tests/test_environment.py', 'tests/check_isolated.py')


def verified_binary(path=None):
    artifact = json.loads((ROOT / 'artifact.json').read_text())
    if path:
        data = Path(path).read_bytes()
    else:
        request = urllib.request.Request(artifact['url'], headers={'User-Agent': 'cloud-cli-rev-offline-bundle'})
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(100 * 1024 ** 2 + 1)
    if len(data) > 100 * 1024 ** 2 or sha(data) != artifact['sha256']:
        raise ValueError('Pinned official binary integrity mismatch')
    if sha((ROOT / 'cloudflared-LICENSE').read_bytes()) != artifact['licenseSha256']:
        raise ValueError('Official license integrity mismatch')
    return data, artifact


def build(output, version, commit, binary_data, artifact, source=ROOT):
    if not re.fullmatch(r'\d+\.\d+\.\d+-rev\.\d+', version) or not re.fullmatch('[0-9a-f]{40}', commit):
        raise ValueError('Invalid immutable release identity')
    if sha(binary_data) != artifact['sha256']:
        raise ValueError('Binary integrity mismatch')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    archive_name = 'cloud-cli-rev-v' + version + '-cloudflare-linux-amd64.tar.gz'
    archive = output / archive_name
    manifest_path = output / 'cloudflare-manifest.json'
    checksum_path = output / 'CLOUDFLARE-SHA256SUMS'
    if any(path.exists() for path in [archive, manifest_path, checksum_path]):
        raise RuntimeError('Existing environment artifacts preserved')
    payload = {}
    for name in BUNDLE_FILES:
        path = Path(source) / name
        if not path.is_file() or path.is_symlink():
            raise ValueError('Nonregular bundle input')
        payload[name] = path.read_bytes()
    payload['binary/cloudflared'] = binary_data
    internal = {'schemaVersion': 1, 'repository': 'nyaaorick/cloud-cli-rev', 'version': version,
                'tag': 'v' + version, 'commit': commit, 'cloudflared': artifact,
                'files': {name: {'sha256': sha(data), 'bytes': len(data)} for name, data in sorted(payload.items())}}
    payload['ENVIRONMENT-MANIFEST.json'] = (json.dumps(internal, indent=2) + '\n').encode()
    with archive.open('xb') as stream:
        with gzip.GzipFile(filename='', mode='wb', fileobj=stream, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode='w') as bundle:
                for name, data in sorted(payload.items()):
                    info = tarfile.TarInfo('cloudflare/' + name)
                    info.size = len(data)
                    info.mode = 0o755 if name == 'binary/cloudflared' else 0o644
                    info.mtime = 0
                    bundle.addfile(info, io.BytesIO(data))
    manifest = {key: value for key, value in internal.items() if key != 'files'}
    manifest.update(archive=archive_name, bytes=archive.stat().st_size, sha256=sha(archive.read_bytes()))
    manifest_path.write_text(json.dumps(manifest, indent=2) + '\n')
    checksum_path.write_text(manifest['sha256'] + '  ' + archive_name + '\n' +
                             sha(manifest_path.read_bytes()) + '  cloudflare-manifest.json\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--binary', help='Use a previously verified local official binary')
    args = parser.parse_args()
    try:
        repository = ROOT.parents[2]
        package = json.loads((repository / 'package.json').read_text())
        commit = subprocess.check_output(['git', '-C', str(repository), 'rev-parse', 'HEAD'], text=True).strip()
        data, artifact = verified_binary(args.binary)
        result = build(args.output, package['version'], commit, data, artifact)
        print(json.dumps({key: result[key] for key in ('version', 'commit', 'archive', 'bytes', 'sha256')}))
    except Exception as error:
        print(json.dumps({'status': 'environment-bundle-failed', 'error_type': type(error).__name__}))
        sys.exit(1)

import importlib.util
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location('rev_update', Path(__file__).resolve().parents[1] / 'rev-update.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArchiveBoundaryTests(unittest.TestCase):
    def test_rejects_traversal_links_and_devices(self):
        for name, kind in [('../outside', tarfile.REGTYPE), ('/absolute', tarfile.REGTYPE),
                           ('link', tarfile.SYMTYPE), ('hard', tarfile.LNKTYPE), ('device', tarfile.CHRTYPE)]:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary)
                archive = base / 'app.tar.gz'
                with tarfile.open(archive, 'w:gz') as bundle:
                    item = tarfile.TarInfo(name)
                    item.type = kind
                    item.linkname = '/etc/passwd'
                    bundle.addfile(item)
                target = base / 'release'
                target.mkdir()
                with self.assertRaises(ValueError):
                    MODULE.safe_extract(archive, target)
                self.assertEqual(list(target.iterdir()), [])

    def test_accepts_regular_release_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive = base / 'app.tar.gz'
            with tarfile.open(archive, 'w:gz') as bundle:
                data = b'{"name":"cloud-cli-rev"}'
                item = tarfile.TarInfo('./package.json')
                item.size = len(data)
                bundle.addfile(item, io.BytesIO(data))
            target = base / 'release'
            target.mkdir()
            MODULE.safe_extract(archive, target)
            self.assertEqual(json.loads((target / 'package.json').read_text())['name'], 'cloud-cli-rev')

    def test_dependency_reuse_ignores_only_root_identity(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            first = base / 'first.json'
            second = base / 'second.json'
            original = {'packages': {'': {'name': 'old', 'version': '1', 'dependencies': {'dep': '1'}},
                                     'node_modules/dep': {'version': '1', 'integrity': 'hash1'}}}
            first.write_text(json.dumps(original))
            original['packages']['']['name'] = 'rev'
            original['packages']['']['version'] = '2'
            second.write_text(json.dumps(original))
            self.assertEqual(MODULE.dependency_fingerprint(first), MODULE.dependency_fingerprint(second))
            original['packages']['node_modules/dep']['integrity'] = 'hash2'
            second.write_text(json.dumps(original))
            self.assertNotEqual(MODULE.dependency_fingerprint(first), MODULE.dependency_fingerprint(second))

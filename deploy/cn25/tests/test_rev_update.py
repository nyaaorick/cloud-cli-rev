import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('rev_update', Path(__file__).resolve().parents[1] / 'rev-update.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ArchiveBoundaryTests(unittest.TestCase):
    def test_root_private_umask_becomes_readable_without_touching_live_dependencies(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            previous = base / 'live-dependencies'
            previous.mkdir()
            dependency = previous / 'private-mode-unchanged'
            dependency.write_text('fixture')
            dependency.chmod(0o600)
            old_umask = os.umask(0o077)
            try:
                release = base / 'release'
                release.mkdir(mode=0o755)
                (release / 'dist-server').mkdir()
                (release / 'dist-server/index.js').write_text('fixture')
            finally:
                os.umask(old_umask)
            self.assertEqual(release.stat().st_mode & 0o777, 0o700)
            (release / 'node_modules').symlink_to(previous)
            MODULE.runtime_permissions(release)
            self.assertEqual(release.stat().st_mode & 0o777, 0o755)
            self.assertEqual((release / 'dist-server').stat().st_mode & 0o777, 0o755)
            self.assertEqual((release / 'dist-server/index.js').stat().st_mode & 0o777, 0o644)
            self.assertEqual(dependency.stat().st_mode & 0o777, 0o600)

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


class IdleGateTests(unittest.TestCase):
    def test_protects_live_pid_birth_identity_and_all_console_children(self):
        config = {'service': 'cn25-console-rev.service', 'protectedProcesses': [{'pid': 42, 'start': '100'}]}
        with patch.object(MODULE, 'run', return_value=b'20\n'), \
                patch.object(MODULE, 'process_identity', return_value={'pid': 42, 'start': '100'}), \
                patch.object(MODULE, 'descendants', return_value={42, 43}):
            status = MODULE.idle_snapshot(config, lambda _: {'data': {'sessions': [{}]}})
        self.assertEqual(status, dict(main_pid=20, running_sessions=1, child_processes=2, protected_processes=1))

    def test_active_turn_never_restarts_or_changes_release(self):
        config = {'idleWaitSeconds': 1}
        with patch.object(MODULE, 'idle_snapshot', return_value={
                'main_pid': 20, 'running_sessions': 1, 'child_processes': 0, 'protected_processes': 0}), \
                patch.object(MODULE.time, 'monotonic', side_effect=[0, 0, 2]), \
                patch.object(MODULE.time, 'sleep'), patch.object(MODULE, 'run') as run:
            with self.assertRaises(TimeoutError):
                MODULE.wait_idle(config, lambda _: None, None)
            run.assert_not_called()

    def test_requires_a_continuous_quiet_window(self):
        empty = dict(main_pid=20, running_sessions=0, child_processes=0, protected_processes=0)
        with patch.object(MODULE, 'idle_snapshot', return_value=empty), \
                patch.object(MODULE.time, 'monotonic', side_effect=[0, 1, 1, 1, 10, 10, 40, 40]), \
                patch.object(MODULE.time, 'sleep'):
            self.assertEqual(MODULE.wait_idle({'quietSeconds': 30}, lambda _: None, None), empty)


class FixedServiceRollbackTests(unittest.TestCase):
    def test_failed_new_health_restores_previous_fixed_service(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            releases = base / 'releases'
            old, new = releases / 'old', releases / 'new'
            old.mkdir(parents=True)
            new.mkdir()
            previous = {'version': '1.37.8-rev.2', 'release': str(old)}
            state = {'version': '1.37.8-rev.4', 'commit': 'a' * 40}
            quiet = dict(main_pid=20, running_sessions=0, child_processes=0, protected_processes=0)
            commands = []
            def run(args, **_kwargs):
                commands.append(args)
                return str(old / 'dist-server/server/index.js').encode() if 'ExecStart' in args else b''
            def health(_port):
                if sum('restart' in args for args in commands) < 2:
                    raise OSError('new application unavailable')
                return {'version': previous['version']}
            config = dict(service='cn25-console-rev.service', port=3302, releases=str(releases), node='/node')
            with patch.object(MODULE, 'BASE', base), patch.object(MODULE, 'SYSTEMD', base / 'systemd'), \
                    patch.object(MODULE, 'wait_idle', return_value=quiet), \
                    patch.object(MODULE, 'idle_snapshot', return_value=quiet), \
                    patch.object(MODULE, 'run', side_effect=run), patch.object(MODULE, 'health', side_effect=health), \
                    patch.object(MODULE.time, 'sleep'):
                with self.assertRaisesRegex(RuntimeError, 'local health'):
                    MODULE.switch_release(config, new, previous, state, lambda: None, None)
            self.assertEqual(state['status'], 'rolled-back')
            self.assertEqual(json.loads((base / 'active.json').read_text()), previous)
            self.assertFalse((base / 'systemd/cn25-console-rev.service.d/80-rev-release.conf').exists())
            self.assertEqual([args for args in commands if 'restart' in args], [
                ['systemctl', 'restart', 'cn25-console-rev.service'],
                ['systemctl', 'restart', 'cn25-console-rev.service']])

"""Failure boundaries for privileged maintenance; no real services or API writes."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import bundle
import cf_common as common
import connector
import guard
import install

spec = importlib.util.spec_from_file_location('cf_test_route', ROOT / 'direct-route.py')
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def config():
    return common.load_config(ROOT / 'config.cn25.json')


class ConfigurationTests(unittest.TestCase):
    def invalid(self, field, value):
        candidate = config()
        candidate[field] = value
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'profile.json'
            path.write_text(json.dumps(candidate))
            with self.assertRaises((ValueError, TypeError)):
                common.load_config(path)

    def test_rejects_nft_and_systemd_injection(self):
        for field, value in [('interface', 'eth0" accept'), ('ruleCommentPrefix', 'x"\nflush ruleset'),
                             ('runtimeDirectory', '/tmp/a\nExecStart=/bin/false'), ('user', 'root root')]:
            with self.subTest(field=field):
                self.invalid(field, value)

    def test_rejects_uid_bool_and_bad_route_order(self):
        self.invalid('uid', True)
        self.invalid('routePriorities', [8989, 8988])
        self.invalid('routePriorities', [8988, 8988])

    def test_rejects_loopback_dns_and_port_aliases(self):
        self.invalid('dnsServers', ['127.0.0.1'])
        self.invalid('metricsPorts', [3302])

    def test_units_have_credential_files_and_no_automatic_route_removal(self):
        value = config()
        files = common.unit_files(value)
        tunnel = files[value['tunnelUnit']]
        self.assertIn('LoadCredential=tunnel-token:' + value['tokenFile'], tunnel)
        self.assertIn('RestrictNetworkInterfaces=' + value['interface'] + ' lo', tunnel)
        self.assertIn('DynamicUser=no', tunnel)
        self.assertNotIn('ExecStop=', files[value['routeUnit']])
        self.assertNotIn('use-vc', common.resolver_text(value))


class ConnectorTests(unittest.TestCase):
    def test_raw_errors_headers_urls_and_arbitrary_fields_are_discarded(self):
        synthetic = 'SYNTHETIC_PRIVATE_AUTH_MATERIAL'
        data = {'message': 'Unable to reach the origin ' + synthetic, 'level': 'error',
                'url': 'https://example/ws?auth=' + synthetic, 'headers': {'Authorization': synthetic},
                'token': synthetic, 'location': 'lax11', 'connIndex': 2, 'protocol': 'http2', 'ip': '198.41.192.7'}
        value = connector.summarize(json.dumps(data))
        self.assertNotIn(synthetic, json.dumps(value))
        self.assertEqual(value, {'event': 'origin-unavailable', 'level': 'error', 'connection': 2,
                                 'protocol': 'http2', 'location': 'lax11', 'edge_ip': '198.41.192.7'})

    def test_nonobjects_and_bad_operational_values_are_ignored(self):
        for value in ['not-json', '[]', 'null', '"text"']:
            self.assertIsNone(connector.summarize(value))
        self.assertEqual(connector.summarize(json.dumps({'level': 'secret', 'location': 'secret', 'connIndex': True})),
                         {'event': 'connector-event'})

    def test_registration_and_unregistration_are_distinct(self):
        self.assertEqual(connector.summarize('{"message":"Unregistered tunnel connection"}')['event'], 'connection-unregistered')

    def test_credential_path_and_bind_address_are_passed_without_reading_credentials(self):
        value = config()
        args = connector.command(value, '/run/credentials/acceptance/tunnel-token')
        self.assertEqual(args[-2:], ['--token-file', '/run/credentials/acceptance/tunnel-token'])
        self.assertEqual(args[args.index('--edge-bind-address') + 1], value['bindAddress'])
        self.assertEqual(args[args.index('--protocol') + 1], 'http2')
        self.assertIn('--no-autoupdate', args)


class RouteTests(unittest.TestCase):
    def simulator(self, initial=None, fail_priority=None):
        value = config()
        current = list(initial or [])
        operations = []
        def run(args, **_kwargs):
            if '-j' in args:
                return json.dumps(current).encode()
            action = args[3]
            priority = int(args[args.index('priority') + 1])
            operations.append((action, priority))
            if action == 'add' and priority == fail_priority:
                raise RuntimeError('Synthetic insertion failure')
            if action == 'add':
                current.append(route.expected(value, priority))
            else:
                current[:] = [item for item in current if item['priority'] != priority]
            return b''
        return value, current, operations, run

    def test_refusal_precedes_bypass_and_repeat_does_nothing(self):
        value, current, operations, run = self.simulator()
        with patch.object(route, 'run', run):
            route.main('apply', value)
            route.main('apply', value)
        self.assertEqual(operations, [('add', 8989), ('add', 8988)])
        self.assertEqual(len(current), 2)

    def test_conflicts_are_preserved_without_mutation(self):
        changed = route.expected(config(), 8988)
        changed['uid_start'] += 1
        value, current, operations, run = self.simulator([changed])
        with patch.object(route, 'run', run), self.assertRaises(RuntimeError):
            route.main('apply', value)
        self.assertEqual(operations, [])
        self.assertEqual(current, [changed])

    def test_failed_bypass_insertion_removes_only_the_rule_it_added(self):
        value, current, operations, run = self.simulator(fail_priority=8988)
        with patch.object(route, 'run', run), self.assertRaises(RuntimeError):
            route.main('apply', value)
        self.assertEqual(operations, [('add', 8989), ('add', 8988), ('del', 8989)])
        self.assertEqual(current, [])

    def test_existing_refusal_is_not_removed_on_failure(self):
        existing = route.expected(config(), 8989)
        value, current, operations, run = self.simulator([existing], fail_priority=8988)
        with patch.object(route, 'run', run), self.assertRaises(RuntimeError):
            route.main('apply', value)
        self.assertEqual(current, [existing])
        self.assertEqual(operations, [('add', 8988)])

    def test_route_removal_refuses_a_live_identity(self):
        value, current, operations, run = self.simulator([route.expected(config(), 8989)])
        with patch.object(route, 'run', run), patch.object(route.subprocess, 'run', return_value=SimpleNamespace(returncode=0)):
            with self.assertRaises(RuntimeError):
                route.main('remove', value)
        self.assertEqual(operations, [])


class GuardTests(unittest.TestCase):
    def test_only_known_redundant_rules_are_removed(self):
        desired = [{'comment': 'keep', 'expr': [{'accept': None}]}]
        legacy = [{'comment': 'legacy', 'expr': [{'accept': None}]}]
        mode, removed = guard.classify([dict(legacy[0], handle=1), dict(desired[0], handle=2)], desired, legacy)
        self.assertEqual(mode, 'legacy')
        self.assertEqual([item['handle'] for item in removed], [1])
        self.assertEqual(guard.classify([dict(desired[0], handle=3)], desired, legacy), ('current', []))

    def test_unknown_change_and_repeated_legacy_are_preserved(self):
        desired = [{'comment': 'keep', 'expr': [{'accept': None}]}]
        legacy = [{'comment': 'legacy', 'expr': [{'accept': None}]}]
        for current in [[{'comment': 'unknown', 'expr': []}], [legacy[0], legacy[0], desired[0]]]:
            with self.subTest(current=current), self.assertRaises(RuntimeError):
                guard.classify(current, desired, legacy)

    def test_persistent_edit_keeps_unrelated_rules_and_requires_unique_anchor(self):
        value = config()
        before = ('table x {\n keep unrelated\n meta skuid 17034 counter drop comment "CN25 Cloudflare physical only old"\n'
                  '        oifname "lo" counter accept comment "IPv4 loopback services only"\n}\n').encode()
        after, previous = guard.candidate_text(before, value, ['replacement'])
        self.assertIn(b' keep unrelated\n', after)
        self.assertIn(b'        replacement\n', after)
        self.assertEqual(len(previous), 1)
        with self.assertRaises(RuntimeError):
            guard.candidate_text(before.replace(b'IPv4 loopback services only', b'changed anchor'), value, [])

    def test_rollback_refuses_concurrent_change_before_any_nft_mutation(self):
        with patch.object(guard, 'chain', return_value=b'someone elses change'), patch.object(guard, 'run') as run:
            with self.assertRaises(RuntimeError):
                guard.restore(config(), {'expected': b'our expected change'})
        run.assert_not_called()

    def test_idempotent_apply_performs_no_nft_write(self):
        with tempfile.TemporaryDirectory() as temporary:
            value = config()
            value['guardLock'] = str(Path(temporary) / 'guard.lock')
            planned = {'mode': 'current', 'duplicates': 0, 'before': b'unchanged', 'expected': b'unchanged', 'transaction': b''}
            with patch.object(guard, 'preflights'), patch.object(guard, 'plan', return_value=planned), patch.object(guard, 'run') as run:
                self.assertEqual(guard.apply(value)['status'], 'unchanged')
            run.assert_not_called()


class IdentityTests(unittest.TestCase):
    def test_public_runtime_parents_remain_readable_with_root_private_umask(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'runtime' / 'nested'
            previous = os.umask(0o077)
            try:
                install.public_directory(path)
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o755)
            self.assertEqual(stat.S_IMODE(Path(temporary).stat().st_mode), 0o700)

    def lookups(self, user=None, group=None):
        def user_lookup(_argument):
            if user is None:
                raise KeyError('synthetic absent identity')
            return user
        def group_lookup(_argument):
            if group is None:
                raise KeyError('synthetic absent identity')
            return group
        return [patch.object(install.pwd, 'getpwnam', user_lookup), patch.object(install.pwd, 'getpwuid', user_lookup),
                patch.object(install.grp, 'getgrnam', group_lookup), patch.object(install.grp, 'getgrgid', group_lookup)]

    def test_missing_account_is_reported_and_credential_contents_are_never_read(self):
        value = config()
        patches = self.lookups()
        with patches[0], patches[1], patches[2], patches[3], \
             patch.object(install, 'run', return_value=json.dumps([{'addr_info': [{'local': value['bindAddress']}]}]).encode()), \
             patch.object(Path, 'lstat', return_value=SimpleNamespace(st_mode=stat.S_IFREG | 0o600, st_uid=0)), \
             patch.object(Path, 'read_bytes', side_effect=AssertionError('Credential read forbidden')):
            self.assertEqual(install.identity(value), 'needs-sysusers')
        self.assertIn('17034:cn25-cloudflared', common.sysusers_text(value))

    def test_mismatched_uid_is_not_claimed(self):
        value = config()
        user = SimpleNamespace(pw_name='another-owner', pw_uid=value['uid'], pw_gid=value['uid'])
        patches = self.lookups(user=user)
        with patches[0], patches[1], patches[2], patches[3], self.assertRaises(RuntimeError):
            install.identity(value)


class BundleTests(unittest.TestCase):
    def test_archive_allowlist_excludes_environment_and_runtime_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / 'source'
            output = Path(temporary) / 'output'
            source.mkdir()
            for name in bundle.BUNDLE_FILES:
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('public source ' + name)
            (source / '.env').write_text('SYNTHETIC_PRIVATE_DATA')
            (source / 'state.json').write_text('SYNTHETIC_PRIVATE_DATA')
            data = b'synthetic-public-binary'
            artifact = {'sha256': common.sha(data), 'version': 'test'}
            manifest = bundle.build(output, '1.37.8-rev.7', 'a' * 40, data, artifact, source)
            with tarfile.open(output / manifest['archive']) as archive:
                self.assertTrue(all(item.isfile() and not item.issym() for item in archive.getmembers()))
                self.assertFalse(any(name.endswith(('.env', 'state.json')) for name in archive.getnames()))
                self.assertEqual(archive.extractfile('cloudflare/binary/cloudflared').read(), data)
                self.assertNotIn(b'SYNTHETIC_PRIVATE_DATA', b''.join(archive.extractfile(item).read() for item in archive.getmembers()))
            self.assertEqual(common.sha((output / manifest['archive']).read_bytes()), manifest['sha256'])
            with self.assertRaises(RuntimeError):
                bundle.build(output, '1.37.8-rev.7', 'a' * 40, data, artifact, source)

    def test_corrupted_binary_is_rejected_before_any_artifact_is_written(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / 'must-not-exist'
            with self.assertRaises(ValueError):
                bundle.build(output, '1.37.8-rev.7', 'a' * 40, b'bad binary', {'sha256': '0' * 64})
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()

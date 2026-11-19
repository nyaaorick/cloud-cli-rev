import http.client
import http.server
import importlib.util
import json
import os
from pathlib import Path
import pwd
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

BASE = Path(__file__).resolve().parents[1] / 'claude-code'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, BASE / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


relay = load('cn25_claude_relay', 'relay.py')
launch = load('cn25_claude_launch', 'launch.py')
MANAGER = {'user': pwd.getpwuid(os.getuid()).pw_name, 'model': 'openai/gpt-6.2-sol', 'effort': 'xhigh'}


class PolicyTests(unittest.TestCase):
    def test_only_pinned_messages_requests_are_forwarded(self):
        body = {'model': 'openai/gpt-6.2-sol', 'output_config': {'effort': 'xhigh'}}
        self.assertIsNone(relay.policy(MANAGER, '/v1/messages', body))
        self.assertIsNone(relay.policy(MANAGER, '/v1/messages?beta=true', body))
        self.assertIsNone(relay.policy(MANAGER, '/v1/messages', {'model': 'openai/gpt-6.2-sol'}))
        refused = [
            ('/v1/messages', {'model': 'claude-opus-5-5', 'output_config': {'effort': 'xhigh'}}),
            ('/v1/messages', {'model': 'openai/gpt-6.2-sol', 'output_config': {'effort': 'low'}}),
            ('/v1/messages/count_tokens', body),
            ('/v1/models', body),
            ('http://elsewhere.invalid/v1/messages', body),
            ('/v1/messages?other=1', body),
            ('/v1/messages', ['not', 'an', 'object']),
        ]
        for target, data in refused:
            self.assertIsNotNone(relay.policy(MANAGER, target, data), target)

    def test_relay_launcher_and_cloudcli_pin_the_same_manager_pair(self):
        config = json.loads((BASE / 'relay.json').read_text())
        manager = config['roles']['manager']
        self.assertEqual((manager['model'], manager['effort']), ('openai/gpt-6.2-sol', 'xhigh'))
        self.assertEqual(launch.ROLES['manager']['model'], manager['model'])
        self.assertEqual(config['upstream'], {'host': 'hubs.foliodude.it.com', 'port': 8443,
                                              'path': '/anthropic/v1/messages'})

    def test_credential_file_owned_by_a_user_is_refused(self):
        with tempfile.NamedTemporaryFile('w', delete=False) as handle:
            handle.write('CODEX_GATEWAY_API_KEY=sk-bf-fixture\n')
        os.chmod(handle.name, 0o600)
        try:
            if os.getuid() != 0:
                with self.assertRaises(SystemExit):
                    relay.read_key(handle.name)
        finally:
            os.unlink(handle.name)

    def test_manager_role_names_the_manager(self):
        role = (BASE / 'manager-role.md').read_text()
        self.assertIn('CN25 manager', role)
        self.assertTrue(role.isascii(), 'the role is English')


class LauncherTests(unittest.TestCase):
    def test_role_comes_from_the_installed_name(self):
        self.assertEqual(launch.role_of('/usr/local/libexec/cn25-claude-code/manager-launch'), 'manager')
        self.assertEqual(launch.role_of('worker-launch'), 'worker')
        for name in ('claude', 'admin-launch', 'manager'):
            with self.assertRaises(SystemExit):
                launch.role_of(name)

    def test_account_and_installer_commands_are_refused(self):
        for args in (['auth', 'login'], ['login'], ['--debug', 'setup-token'], ['logout'], ['update'],
                     ['mcp', 'add'], ['plugin', 'install', 'x'], ['doctor']):
            self.assertIsNone(launch.build_argv(args), args)

    def test_sessions_always_run_bare(self):
        args = ['--output-format', 'stream-json', '--input-format', 'stream-json']
        self.assertEqual(launch.build_argv(args), [launch.BINARY, '--bare'] + args)
        self.assertEqual(launch.build_argv(['--bare', '-p']), [launch.BINARY, '--bare', '-p'])
        self.assertEqual(launch.build_argv(['--version']), [launch.BINARY, '--version'])

    def test_environment_is_fixed_and_carries_no_caller_credentials(self):
        caller = {'CLAUDE_CODE_ENTRYPOINT': 'claudecodeui', 'CLAUDE_CODE_OAUTH_TOKEN': 'secret-1',
                  'ANTHROPIC_AUTH_TOKEN': 'secret-2', 'ANTHROPIC_API_KEY': 'secret-3',
                  'CODEX_GATEWAY_API_KEY': 'secret-4', 'ANTHROPIC_BASE_URL': 'http://untrusted.invalid',
                  'CLAUDE_CONFIG_DIR': '/tmp/elsewhere', 'PATH': '/tmp/untrusted', 'NODE_OPTIONS': '--require x'}
        account = pwd.struct_passwd(('cn25-manager', 'x', 1, 1, '', '/srv/review/manager-home', '/bin/bash'))
        env = launch.build_env('manager', 41234, caller, account)
        self.assertFalse({value for value in env.values()} & {'secret-1', 'secret-2', 'secret-3', 'secret-4'})
        for name in ('CLAUDE_CODE_OAUTH_TOKEN', 'ANTHROPIC_AUTH_TOKEN', 'CODEX_GATEWAY_API_KEY',
                     'CLAUDE_CONFIG_DIR', 'NODE_OPTIONS'):
            self.assertNotIn(name, env)
        self.assertEqual(env['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:41234')
        self.assertEqual(env['ANTHROPIC_API_KEY'], launch.PLACEHOLDER_KEY)
        self.assertEqual(env['HOME'], '/srv/review/manager-home')
        self.assertEqual(env['PATH'], launch.ROLES['manager']['path'])
        self.assertEqual(env['CLAUDE_CODE_ENTRYPOINT'], 'claudecodeui')
        for name in ('ANTHROPIC_MODEL', 'ANTHROPIC_SMALL_FAST_MODEL', 'CLAUDE_CODE_SUBAGENT_MODEL',
                     'ANTHROPIC_DEFAULT_OPUS_MODEL', 'ANTHROPIC_DEFAULT_SONNET_MODEL', 'ANTHROPIC_DEFAULT_HAIKU_MODEL'):
            self.assertEqual(env[name], 'openai/gpt-6.2-sol')
        for name in ('CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC', 'DISABLE_AUTOUPDATER', 'DISABLE_TELEMETRY',
                     'DISABLE_ERROR_REPORTING'):
            self.assertEqual(env[name], '1')

    def test_only_a_review_checkout_is_marked_safe_for_git(self):
        account = pwd.struct_passwd(('cn25-codex', 'x', 985, 985, '', '/srv/review/codex-home', '/bin/bash'))
        accepted = {'GIT_CONFIG_COUNT': '1', 'GIT_CONFIG_KEY_0': 'safe.directory',
                    'GIT_CONFIG_VALUE_0': '/srv/review/wt/review-0123/repo', 'TMPDIR': '/tmp'}
        env = launch.build_env('worker', 1, accepted, account)
        for name, value in accepted.items():
            self.assertEqual(env[name], value)
        refused = [
            dict(accepted, GIT_CONFIG_COUNT='2'),
            dict(accepted, GIT_CONFIG_KEY_0='core.hooksPath'),
            dict(accepted, GIT_CONFIG_VALUE_0='*'),
            dict(accepted, GIT_CONFIG_VALUE_0='/srv/review/wt/../secrets'),
            dict(accepted, GIT_CONFIG_VALUE_0='/home/shijunyao/repo'),
        ]
        for caller in refused:
            env = launch.build_env('worker', 1, caller, account)
            for name in ('GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_0', 'GIT_CONFIG_VALUE_0'):
                self.assertNotIn(name, env, caller)
        self.assertNotIn('TMPDIR', launch.build_env('worker', 1, {'TMPDIR': 'relative'}, account))

    def test_worker_pair_matches_the_relay(self):
        worker = json.loads((BASE / 'relay.json').read_text())['roles']['worker']
        self.assertEqual((worker['user'], worker['model'], worker['effort']),
                         ('cn25-codex', 'deepseek/deepseek-flash', 'max'))
        self.assertEqual(launch.ROLES['worker']['model'], worker['model'])

    def test_no_session_starts_without_the_relay(self):
        with tempfile.TemporaryDirectory() as empty, patch.object(launch, 'RUN_DIR', empty), \
                patch.object(launch.subprocess, 'Popen') as popen:
            self.assertEqual(launch.main(['manager-launch', '--output-format', 'stream-json']),
                             launch.EX_UNAVAILABLE)
        popen.assert_not_called()

    def test_bridge_admits_only_the_owning_account(self):
        table = ('  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid\n'
                 '   0: 0100007F:A0B1 0100007F:C0D1 01 00000000:00000000 00:00000000 00000000   985 0 1 1\n'
                 '   1: 0100007F:A0B2 0100007F:C0D1 01 00000000:00000000 00:00000000 00000000  1003 0 2 1\n')
        with tempfile.NamedTemporaryFile('w', delete=False) as handle:
            handle.write(table)
        try:
            self.assertEqual(launch.peer_uid(0xA0B1, 0xC0D1, handle.name), 985)
            self.assertEqual(launch.peer_uid(0xA0B2, 0xC0D1, handle.name), 1003)
            self.assertIsNone(launch.peer_uid(0xA0B3, 0xC0D1, handle.name))
        finally:
            os.unlink(handle.name)


class Upstream(http.server.BaseHTTPRequestHandler):
    seen = []

    def log_message(self, *args):
        pass

    def do_POST(self):
        body = self.rfile.read(int(self.headers['Content-Length']))
        Upstream.seen.append((self.path, self.headers.get('x-api-key'), json.loads(body)['model']))
        reply = b'event: message_stop\ndata: {}\n\n'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('request-id', 'req_fixture')
        self.send_header('Content-Length', str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)


class UnixConnection(http.client.HTTPConnection):
    def __init__(self, path):
        super().__init__('localhost')
        self.path = path

    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX)
        self.sock.connect(self.path)


@unittest.skipUnless(hasattr(socket, 'SO_PEERCRED'), 'peer credentials are Linux-only')
class RelayRoundTripTests(unittest.TestCase):
    def setUp(self):
        Upstream.seen = []
        self.upstream = http.server.HTTPServer(('127.0.0.1', 0), Upstream)
        threading.Thread(target=self.upstream.serve_forever, daemon=True).start()
        port = self.upstream.server_address[1]
        self.directory = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.directory.name, 'manager.sock')
        upstream = {'host': '127.0.0.1', 'port': port, 'path': '/anthropic/v1/messages'}
        self.server = relay.RoleServer(self.path, 'manager', MANAGER, upstream, 'sk-bf-fixture',
                                       connect=lambda target: http.client.HTTPConnection(target['host'], target['port']))
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.upstream.shutdown()
        self.upstream.server_close()
        self.directory.cleanup()

    def post(self, target, body):
        connection = UnixConnection(self.path)
        connection.request('POST', target, body=json.dumps(body),
                           headers={'Content-Type': 'application/json', 'x-api-key': 'cn25-relay-placeholder'})
        response = connection.getresponse()
        return response.status, response.read()

    def test_pinned_request_reaches_the_gateway_with_the_relay_key_only(self):
        status, body = self.post('/v1/messages?beta=true', {'model': 'openai/gpt-6.2-sol',
                                                            'output_config': {'effort': 'xhigh'}, 'stream': True})
        self.assertEqual(status, 200)
        self.assertIn(b'message_stop', body)
        self.assertEqual(Upstream.seen, [('/anthropic/v1/messages', 'sk-bf-fixture', 'openai/gpt-6.2-sol')])
        self.assertEqual(os.stat(self.path).st_mode & 0o777, 0o600)

    def test_other_models_never_reach_the_gateway(self):
        status, body = self.post('/v1/messages', {'model': 'claude-opus-5-5'})
        self.assertEqual(status, 422)
        self.assertIn(b'cn25_relay_refused', body)
        self.assertNotIn(b'sk-bf-fixture', body)
        self.assertEqual(Upstream.seen, [])


if __name__ == '__main__':
    unittest.main()

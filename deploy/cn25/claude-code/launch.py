#!/usr/bin/python3 -I
"""Fixed Claude Code launcher for one CN25 role, installed as `<role>-launch`.

Claude Code always runs `--bare`: no account login, OAuth, keychain, hooks or
plugins. Its only API endpoint is a loopback port that this launcher bridges
to the role's relay socket; the relay holds the Bifrost key and pins model
and effort. The CLI gets a placeholder key and a fixed environment, never the
caller's. Account and installer subcommands are refused.
"""
import os
import pwd
import signal
import socket
import subprocess
import sys
import threading

BINARY = '/usr/local/libexec/cn25-claude-code/2.1.311/claude'
RUN_DIR = '/run/cn25-claude'
ROLES = {
    'manager': {'model': 'openai/gpt-6.2-sol',
                'path': '/srv/review/tools/node-v22.23.4-linux-x64/bin:/usr/local/bin:/usr/bin:/bin'},
    'worker': {'model': 'deepseek/deepseek-flash',
               'path': '/srv/review/tools/node-v22.23.4-linux-x64/bin:/usr/local/bin:/usr/bin:/bin'},
}
REFUSED = frozenset(('auth', 'login', 'logout', 'setup-token', 'update', 'upgrade', 'install',
                     'migrate-installer', 'doctor', 'mcp', 'plugin', 'plugins', 'remote-control'))
PASSED = ('CLAUDE_CODE_ENTRYPOINT', 'CLAUDE_AGENT_SDK_VERSION', 'TERM', 'LANG', 'TZ')
# Review checkouts belong to another account; git needs them marked safe.
SAFE_DIRECTORY_ROOTS = ('/srv/review/wt/', '/srv/review/codex-home/workspace/')
PLACEHOLDER_KEY = 'cn25-relay-placeholder'
EX_USAGE, EX_UNAVAILABLE = 64, 69


def role_of(argv0):
    name = os.path.basename(argv0)
    role = name[:-len('-launch')] if name.endswith('-launch') else None
    if role not in ROLES:
        raise SystemExit('unknown CN25 Claude role')
    return role


def is_version_probe(args):
    return args in (['--version'], ['-v'])


def build_argv(args):
    if any(arg in REFUSED for arg in args):
        return None
    if is_version_probe(args):
        return [BINARY] + args
    return [BINARY] + ([] if '--bare' in args else ['--bare']) + args


def build_env(role, port, environ, account):
    model = ROLES[role]['model']
    env = {name: environ[name] for name in PASSED if name in environ}
    env.setdefault('LANG', 'C.UTF-8')
    if os.path.isabs(environ.get('TMPDIR', '')):
        env['TMPDIR'] = environ['TMPDIR']
    safe = environ.get('GIT_CONFIG_VALUE_0', '')
    if (environ.get('GIT_CONFIG_COUNT') == '1' and environ.get('GIT_CONFIG_KEY_0') == 'safe.directory'
            and os.path.normpath(safe) == safe and safe.startswith(SAFE_DIRECTORY_ROOTS)):
        env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='safe.directory', GIT_CONFIG_VALUE_0=safe)
    env.update(
        HOME=account.pw_dir, USER=account.pw_name, LOGNAME=account.pw_name, SHELL='/bin/bash',
        PATH=ROLES[role]['path'],
        ANTHROPIC_BASE_URL='http://127.0.0.1:%d' % port, ANTHROPIC_API_KEY=PLACEHOLDER_KEY,
        ANTHROPIC_MODEL=model, ANTHROPIC_SMALL_FAST_MODEL=model, CLAUDE_CODE_SUBAGENT_MODEL=model,
        ANTHROPIC_DEFAULT_OPUS_MODEL=model, ANTHROPIC_DEFAULT_SONNET_MODEL=model,
        ANTHROPIC_DEFAULT_HAIKU_MODEL=model,
        CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC='1', CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS='1',
        DISABLE_AUTOUPDATER='1', DISABLE_TELEMETRY='1', DISABLE_ERROR_REPORTING='1',
        DISABLE_FEEDBACK_COMMAND='1',
    )
    return env


def peer_uid(client_port, server_port, table='/proc/net/tcp'):
    """UID owning the loopback client end of a connection to server_port."""
    local, remote = '0100007F:%04X' % client_port, '0100007F:%04X' % server_port
    with open(table) as handle:
        next(handle)
        for line in handle:
            fields = line.split()
            if fields[1] == local and fields[2] == remote:
                return int(fields[7])
    return None


def pump(source, target):
    try:
        while True:
            chunk = source.recv(65536)
            if not chunk:
                break
            target.sendall(chunk)
    except OSError:
        pass
    finally:
        try:
            target.shutdown(socket.SHUT_WR)
        except OSError:
            pass


def bridge(client, server_port, relay_path):
    with client:
        # Only this account's processes may use the bridge.
        if peer_uid(client.getpeername()[1], server_port) != os.getuid():
            return
        with socket.socket(socket.AF_UNIX) as relay:
            try:
                relay.connect(relay_path)
            except OSError:
                return
            upstream = threading.Thread(target=pump, args=(client, relay), daemon=True)
            upstream.start()
            pump(relay, client)
            upstream.join()


def serve(listener, relay_path):
    port = listener.getsockname()[1]
    while True:
        client, _ = listener.accept()
        threading.Thread(target=bridge, args=(client, port, relay_path), daemon=True).start()


def main(argv):
    role = role_of(argv[0])
    command = build_argv(argv[1:])
    if command is None:
        print('CN25 Claude Code is API-only; account and installer commands are disabled.', file=sys.stderr)
        return EX_USAGE
    account = pwd.getpwuid(os.getuid())
    if is_version_probe(argv[1:]):
        # Version probes make no API call; port 9 (discard) is never reached.
        os.execve(BINARY, command, build_env(role, 9, os.environ, account))
    relay_path = os.path.join(RUN_DIR, role + '.sock')
    try:
        with socket.socket(socket.AF_UNIX) as probe:
            probe.connect(relay_path)
    except OSError:
        print('CN25 Claude relay is unavailable; no fallback is allowed.', file=sys.stderr)
        return EX_UNAVAILABLE
    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(64)
    threading.Thread(target=serve, args=(listener, relay_path), daemon=True).start()
    env = build_env(role, listener.getsockname()[1], os.environ, account)
    child = subprocess.Popen(command, env=env)
    for number in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP, signal.SIGQUIT):
        signal.signal(number, lambda received, _frame: child.send_signal(received))
    code = child.wait()
    return 128 - code if code < 0 else code


if __name__ == '__main__':
    sys.exit(main(sys.argv))

#!/usr/bin/python3 -I
"""CN25 Claude Code Messages relay: the only holder of the Bifrost key.

Each configured role gets a Unix socket that only that role's account can
open. A request is forwarded only when it is POST /v1/messages naming the
role's pinned model; the relay sets the role's pinned effort on every request,
adds the key, streams the gateway reply back and logs policy facts only,
never content, headers or credentials. Claude Code itself runs `--bare` with a placeholder.
"""
import http.client
import http.server
import json
import os
import pwd
import re
import socket
import socketserver
import ssl
import struct
import sys
import threading
from urllib.parse import urlsplit

CONFIG = '/etc/cn25-claude-relay.json'
KEY_FILE = '/srv/review/secrets/bifrost.env'
RUN_DIR = '/run/cn25-claude'
MAX_BODY = 64 * 1024 * 1024
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
KEY_LINE = re.compile(r'^CODEX_GATEWAY_API_KEY=([\x22\x27]?)(sk-bf-[A-Za-z0-9_-]+)\1$', re.M)
REQUEST_ID = re.compile(r'[A-Za-z0-9._-]{1,100}')
# Gateway-specific body fields that could route around the pinned model.
GATEWAY_FIELDS = ('fallbacks',)
# Reply headers Claude Code needs for retries and integrity.
REPLY_HEADERS = ('Content-Length', 'retry-after', 'x-should-retry')


def read_key(path=KEY_FILE):
    attrs = os.lstat(path)
    if not os.path.isfile(path) or os.path.islink(path) or attrs.st_uid != 0 or attrs.st_mode & 0o077:
        raise SystemExit('unsafe Bifrost credential file')
    with open(path) as handle:
        match = KEY_LINE.search(handle.read())
    if not match:
        raise SystemExit('Bifrost key missing')
    return match.group(2)


def load_config(path=CONFIG):
    with open(path) as handle:
        config = json.load(handle)
    upstream = config['upstream']
    if not (isinstance(upstream.get('host'), str) and type(upstream.get('port')) is int
            and isinstance(upstream.get('path'), str) and upstream['path'].startswith('/')):
        raise SystemExit('invalid relay upstream')
    for name, role in config['roles'].items():
        if not re.fullmatch(r'[a-z]+', name) or role.get('effort') not in EFFORTS or not role.get('model'):
            raise SystemExit('invalid relay role ' + name)
        pwd.getpwnam(role['user'])
    return config


def unique_keys(pairs):
    # The gateway may match keys case-insensitively; an object that is
    # ambiguous under either reading is refused rather than forwarded.
    seen = set()
    for key, _value in pairs:
        if key.casefold() in seen:
            raise ValueError('ambiguous JSON key')
        seen.add(key.casefold())
    return dict(pairs)


def parse(body):
    return json.loads(body, object_pairs_hook=unique_keys,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('non-finite number')))


def policy(role, target, data):
    """Return the refusal reason for a request, or None to forward it."""
    url = urlsplit(target)
    if url.scheme or url.netloc or url.fragment or url.path != '/v1/messages' or url.query not in ('', 'beta=true'):
        return 'only Messages POST is relayed'
    if not isinstance(data, dict):
        return 'request body is not a JSON object'
    if any(key.casefold() in GATEWAY_FIELDS for key in data):
        return 'gateway routing fields are not relayed'
    if data.get('model') != role['model']:
        return 'model is pinned for this role'
    if not isinstance(data.get('output_config', {}), dict):
        return 'output_config is not an object'
    return None


def pin_effort(role, data):
    """Set the role's effort whatever the CLI chose; return what it asked for."""
    output = dict(data.get('output_config') or {})
    requested = output.get('effort')
    output['effort'] = role['effort']
    data['output_config'] = output
    return requested if requested in EFFORTS else None


def peer_uid(sock):
    _pid, uid, _gid = struct.unpack('3i', sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize('3i')))
    return uid


def log(role, **facts):
    print('role=' + role, ' '.join('%s=%s' % item for item in facts.items()), flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = 'cn25-claude-relay'
    timeout = 120

    def log_message(self, *args):
        pass

    def refuse(self, status, reason):
        log(self.server.role_name, refused=status, reason=reason.replace(' ', '_'))
        body = json.dumps({'type': 'error', 'error': {'type': 'cn25_relay_refused', 'message': reason}}).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self.refuse(403, 'only Messages POST is relayed')

    do_PUT = do_PATCH = do_DELETE = do_GET

    def do_POST(self):
        try:
            length = int(self.headers.get('Content-Length', ''))
        except ValueError:
            return self.refuse(411, 'Content-Length is required')
        if not 0 < length <= MAX_BODY:
            return self.refuse(413, 'request body size is out of range')
        body = self.rfile.read(length)
        try:
            data = parse(body)
        except (ValueError, RecursionError):
            return self.refuse(400, 'request body is not unambiguous JSON')
        role = self.server.role
        reason = policy(role, self.path, data)
        if reason:
            return self.refuse(403 if 'Messages' in reason else 422, reason)
        requested = pin_effort(role, data)
        # Forward exactly what was checked, never the original bytes.
        canonical = json.dumps(data, ensure_ascii=False, separators=(',', ':')).encode()
        self.forward(canonical, requested, data.get('stream') is True)

    def forward(self, body, requested, stream):
        upstream = self.server.upstream
        headers = {'Content-Type': 'application/json', 'x-api-key': self.server.key,
                   'anthropic-version': self.headers.get('anthropic-version') or '2023-06-01',
                   'User-Agent': 'cn25-claude-relay/' + self.server.role_name}
        if self.headers.get('anthropic-beta'):
            headers['anthropic-beta'] = self.headers['anthropic-beta']
        connection = self.server.connect(upstream)
        sent = 0
        try:
            try:
                connection.request('POST', upstream['path'], body=body, headers=headers)
                response = connection.getresponse()
            except (OSError, http.client.HTTPException) as error:
                log(self.server.role_name, transport_error=type(error).__name__)
                return self.refuse(502, 'gateway unreachable')
            reference = response.getheader('x-bifrost-request-id') or response.getheader('request-id') or ''
            if 300 <= response.status < 400:
                return self.refuse(502, 'gateway redirect rejected')
            self.send_response(response.status)
            self.send_header('Content-Type', response.getheader('Content-Type', 'application/octet-stream'))
            if REQUEST_ID.fullmatch(reference):
                self.send_header('request-id', reference)
            for name, value in response.getheaders():
                if name.lower() in [header.lower() for header in REPLY_HEADERS] or name.lower().startswith('anthropic-ratelimit-'):
                    self.send_header(name, value)
            self.end_headers()
            for chunk in iter(lambda: response.read1(65536), b''):
                self.wfile.write(chunk)
                self.wfile.flush()
                sent += len(chunk)
            log(self.server.role_name, status=response.status, requested_effort=requested,
                effort=self.server.role['effort'], stream=stream,
                bytes_out=sent, request_id=reference if REQUEST_ID.fullmatch(reference) else None)
        except (OSError, http.client.HTTPException) as error:
            log(self.server.role_name, transport_error=type(error).__name__, bytes_out=sent)
        finally:
            connection.close()


def https_connection(upstream):
    return http.client.HTTPSConnection(upstream['host'], upstream['port'], timeout=900,
                                       context=ssl.create_default_context())


class RoleServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True

    def __init__(self, path, role_name, role, upstream, key, connect=https_connection):
        self.role_name, self.role, self.upstream, self.key, self.connect = role_name, role, upstream, key, connect
        self.uid = pwd.getpwnam(role['user']).pw_uid
        if os.path.lexists(path):
            os.unlink(path)
        super().__init__(path, Handler)
        os.chown(path, self.uid, -1)
        os.chmod(path, 0o600)

    def verify_request(self, request, client_address):
        # Socket permissions already restrict access; the kernel's peer
        # credentials confirm the caller is the role's account (or root).
        return peer_uid(request) in (self.uid, 0)

    def handle_error(self, request, client_address):
        log(self.role_name, relay_error=type(sys.exc_info()[1]).__name__)


def main():
    config = load_config()
    key = read_key()
    servers = []
    for name, role in sorted(config['roles'].items()):
        server = RoleServer(os.path.join(RUN_DIR, name + '.sock'), name, role, config['upstream'], key)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        log(name, listening=True, model=role['model'], effort=role['effort'])
    threading.Event().wait()


if __name__ == '__main__':
    main()

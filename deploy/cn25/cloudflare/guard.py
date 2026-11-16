"""Plan and apply owned nft rules without replacing the shared table or chain."""
import datetime
import fcntl
import json
from pathlib import Path
import re
import tempfile

from cf_common import NFT_CHAIN, atomic, normalize_rule, rules, run, sha


def isolated(content):
    """Compile a complete candidate only inside a new network namespace."""
    with tempfile.TemporaryDirectory(prefix='cn25-cf-nft-') as temporary:
        path = Path(temporary) / 'guard.nft'
        path.write_bytes(content)
        code = ('import json,subprocess,sys;'
                'subprocess.run(["nft","-f",sys.argv[1]],check=True,capture_output=True);'
                'print(json.dumps({"text":subprocess.check_output(["nft","-s","list","chain","inet","cn25_us_egress","output"]).decode(),'
                '"json":json.loads(subprocess.check_output(["nft","-j","list","chain","inet","cn25_us_egress","output"]))}))')
        return json.loads(run(['unshare', '-n', '/usr/bin/python3', '-B', '-c', code, str(path)]))


def chain():
    return run(['nft', '-s', 'list', 'chain', *NFT_CHAIN])


def json_rules(value):
    return [item['rule'] for item in value['nftables'] if 'rule' in item]


def owned(value, config):
    prefix = config['ruleCommentPrefix'] + ' '
    return [item for item in json_rules(value) if item.get('comment', '').startswith(prefix)]


def compiled_rules(expressions):
    content = ('table inet cn25_us_egress {\n chain output {\n' +
               ''.join(expression + '\n' for expression in expressions) + '}\n}\n').encode()
    return [normalize_rule(item) for item in json_rules(isolated(content)['json'])]


def legacy_expressions(config):
    # These two exact old rules are already covered by the full official list.
    if not {443, 8443}.issubset(config['httpsPorts']):
        return []
    prefix = ('meta skuid %d oifname "%s" ip daddr { 104.16.0.0/13, 172.64.0.0/13 } tcp dport '
              % (config['uid'], config['interface']))
    return [prefix + str(port) + ' counter accept comment "' + config['ruleCommentPrefix'] + ' ' + suffix + '"'
            for port, suffix in [(443, 'Cloudflare HTTPS'), (8443, 'Cloudflare HTTPS8443')]]


def classify(current, desired, legacy):
    """Reject unknown or repeated owned rules instead of overwriting them."""
    normalized = [normalize_rule(item) for item in current]
    if not normalized:
        return 'fresh', []
    duplicates = []
    retained = []
    for original, value in zip(current, normalized):
        if value in legacy:
            if value in [normalize_rule(item) for item in duplicates]:
                raise RuntimeError('Repeated legacy rule needs inspection')
            duplicates.append(original)
        else:
            retained.append(value)
    if retained != desired:
        raise RuntimeError('Unknown owned firewall change preserved')
    return ('legacy' if duplicates else 'current'), duplicates


def candidate_text(original, config, expressions):
    prefix = config['ruleCommentPrefix'] + ' '
    anchor = 'comment "' + config['anchorComment'] + '"'
    lines = original.decode().splitlines(keepends=True)
    anchors = [index for index, line in enumerate(lines) if line.rstrip().endswith(anchor)]
    if len(anchors) != 1:
        raise RuntimeError('Persistent anchor conflict')
    output, previous = [], []
    for line in lines:
        if prefix in line:
            if not re.search(r'comment "' + re.escape(prefix) + r'[A-Za-z0-9 _-]+"\s*$', line):
                raise RuntimeError('Unrecognized persistent owned rule')
            previous.append(line.strip())
            continue
        if line.rstrip().endswith(anchor):
            indent = line[:len(line) - len(line.lstrip())]
            output.extend(indent + expression + '\n' for expression in expressions)
        output.append(line)
    return ''.join(output).encode(), previous


def preflights(config):
    for path in config['guardChecks']:
        run(['/usr/bin/python3', '-B', path])


def plan(config):
    original = Path(config['guardFile']).read_bytes()
    before = chain()
    persisted = isolated(original)
    if persisted['text'].encode() != before:
        raise RuntimeError('Persistent guard differs from running rules')
    pins = {path: Path(path).read_bytes() for path in config['guardPins']}
    if any(value.decode().strip() != sha(before) for value in pins.values()):
        raise RuntimeError('Guard pin conflict preserved')
    live = json.loads(run(['nft', '-j', 'list', 'chain', *NFT_CHAIN]))
    actual = owned(live, config)
    expressions = rules(config)
    desired = compiled_rules(expressions)
    mode, duplicates = classify(actual, desired, compiled_rules(legacy_expressions(config)))
    candidate, old_expressions = candidate_text(original, config, expressions)
    if len(old_expressions) != len(actual):
        raise RuntimeError('Persistent owned rule count differs')
    after = isolated(candidate)
    if [normalize_rule(item) for item in owned(after['json'], config)] != desired:
        raise RuntimeError('Candidate does not express the intended rules')
    without_owned = lambda value: [normalize_rule(item) for item in json_rules(value)
                                   if not item.get('comment', '').startswith(config['ruleCommentPrefix'] + ' ')]
    if without_owned(live) != without_owned(after['json']):
        raise RuntimeError('Candidate changes unrelated firewall rules')
    anchors = [item['handle'] for item in json_rules(live) if item.get('comment') == config['anchorComment']]
    if len(anchors) != 1:
        raise RuntimeError('Live anchor conflict')
    transaction = ''.join('delete rule inet cn25_us_egress output handle %d\n' % item['handle'] for item in duplicates)
    if mode == 'fresh':
        transaction += ''.join('insert rule inet cn25_us_egress output position %d %s\n' % (anchors[0], value)
                               for value in expressions)
    return {'mode': mode, 'duplicates': len(duplicates), 'before': before, 'original': original,
            'pins': pins, 'candidate': candidate, 'expected': after['text'].encode(),
            'transaction': transaction.encode(), 'old_expressions': old_expressions,
            'forward': run(['nft', '-s', 'list', 'chain', 'inet', 'cn25_us_egress', 'forward'])}


def summary(value):
    return {'mode': value['mode'], 'redundant_rules_to_remove': value['duplicates'],
            'guard_before_sha256': sha(value['before']), 'guard_after_sha256': sha(value['expected']),
            'changes_required': bool(value['transaction']), 'preserves_unrelated_rules': True}


def restore(config, value):
    """Rollback only our rules, and only while the exact expected state remains."""
    if chain() != value['expected']:
        raise RuntimeError('Concurrent rules prevent scoped rollback')
    file = Path(config['guardFile'])
    if file.read_bytes() not in (value['original'], value['candidate']):
        raise RuntimeError('Concurrent persistence change preserved')
    for path, old in value['pins'].items():
        if Path(path).read_bytes() not in (old, (sha(value['expected']) + '\n').encode()):
            raise RuntimeError('Concurrent pin change preserved')
    live = json.loads(run(['nft', '-j', 'list', 'chain', *NFT_CHAIN]))
    anchors = [item['handle'] for item in json_rules(live) if item.get('comment') == config['anchorComment']]
    if len(anchors) != 1:
        raise RuntimeError('Rollback anchor conflict')
    transaction = ''.join('delete rule inet cn25_us_egress output handle %d\n' % item['handle'] for item in owned(live, config))
    transaction += ''.join('insert rule inet cn25_us_egress output position %d %s\n' % (anchors[0], value)
                           for value in value['old_expressions'])
    run(['nft', '-c', '-f', '-'], transaction.encode())
    run(['nft', '-f', '-'], transaction.encode())
    if chain() != value['before']:
        raise RuntimeError('Scoped rollback differs from prior output')
    atomic(file, value['original'])
    for path, old in value['pins'].items():
        atomic(path, old)
    preflights(config)


def apply(config):
    with open(config['guardLock'], 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        preflights(config)
        value = plan(config)
        if not value['transaction']:
            return dict(summary(value), status='unchanged')
        state = Path(config['stateDirectory'])
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        attempt = Path(tempfile.mkdtemp(prefix='guard-', dir=str(state)))
        atomic(attempt / 'guard.before.nft', value['original'], 0o600)
        atomic(attempt / 'guard.candidate.nft', value['candidate'], 0o600)
        atomic(attempt / 'pins.before.json', (json.dumps({p: v.decode() for p, v in value['pins'].items()}) + '\n').encode(), 0o600)
        receipt = dict(summary(value), status='prepared', at=datetime.datetime.now(datetime.timezone.utc).isoformat())
        def save():
            atomic(attempt / 'receipt.json', (json.dumps(receipt, indent=2) + '\n').encode(), 0o600)
        save()
        try:
            if chain() != value['before'] or Path(config['guardFile']).read_bytes() != value['original']:
                raise RuntimeError('Concurrent firewall change preserved')
            run(['nft', '-c', '-f', '-'], value['transaction'])
            run(['nft', '-f', '-'], value['transaction'])
            if chain() != value['expected']:
                raise RuntimeError('Unexpected output after scoped transaction')
            if run(['nft', '-s', 'list', 'chain', 'inet', 'cn25_us_egress', 'forward']) != value['forward']:
                raise RuntimeError('Forward chain changed concurrently')
            atomic(config['guardFile'], value['candidate'])
            for path in config['guardPins']:
                atomic(path, (sha(value['expected']) + '\n').encode())
            preflights(config)
            receipt['status'] = 'applied'
        except BaseException as error:
            receipt.update(status='needs-inspection', error_type=type(error).__name__)
            try:
                if chain() == value['expected']:
                    restore(config, value)
                    receipt['status'] = 'rolled-back'
                elif chain() == value['before'] and Path(config['guardFile']).read_bytes() == value['original']:
                    receipt['status'] = 'failed-before-change'
            except BaseException as rollback_error:
                receipt['rollback_error_type'] = type(rollback_error).__name__
            save()
            raise
        save()
        return dict(receipt, receipt=str(attempt / 'receipt.json'))

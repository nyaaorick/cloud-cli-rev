#!/usr/bin/python3
"""VPS guard for the two CN25 console forwards; no credential access."""
import fcntl,json,os,pathlib,re,select,signal,subprocess,sys,time
BASE=pathlib.Path('/etc/cn25-console/forward-lease')
PORTS={13301,13302}
LEASE_SECONDS=40

def identity(pid):
    try:
        raw=pathlib.Path('/proc',str(pid),'stat').read_text()
        fields=raw[raw.rfind(')')+2:].split()
        name=pathlib.Path('/proc',str(pid),'comm').read_text().strip()
        return {'pid':pid,'start':fields[19],'name':name}
    except (FileNotFoundError,ProcessLookupError):return None

def listeners():
    output=subprocess.check_output(['ss','-lntpH'],text=True,timeout=5)
    result={}
    for line in output.splitlines():
        fields=line.split()
        if len(fields)<4:continue
        port=int(fields[3].rsplit(':',1)[1])
        for pid in re.findall(r'pid=(\d+)',line):result.setdefault(int(pid),set()).add(port)
    return result

def terminate_owned(owner):
    actual=identity(owner['pid'])
    if actual is None:return
    assert actual==owner and actual['name'].startswith('sshd'), 'PID identity changed'
    ports=listeners().get(owner['pid'],set())
    assert ports and ports.issubset(PORTS), 'Connection no longer owns only console forward ports'
    os.kill(owner['pid'],signal.SIGTERM)

def write_record(value):
    tmp=BASE/'lease.next';tmp.write_text(json.dumps(value)+'\n');tmp.chmod(0o600);tmp.replace(BASE/'lease.json')

def event(value):
    path=BASE/'events.jsonl'
    if path.exists() and path.stat().st_size>1024*1024:path.replace(BASE/'events.previous.jsonl')
    with path.open('a') as out:out.write(json.dumps(dict(value,at=time.time()))+'\n')

def read_record():
    p=BASE/'lease.json';return json.loads(p.read_text()) if p.exists() else None

def lock():
    BASE.mkdir(mode=0o700,parents=True,exist_ok=True)
    handle=(BASE/'owner.lock').open('a');os.chmod(str(BASE/'owner.lock'),0o600)
    try:fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except Exception:handle.close();raise
    return handle

def prepare():
    with lock():
        prior=read_record()
        active={pid:ports.intersection(PORTS) for pid,ports in listeners().items() if ports.intersection(PORTS)}
        if active:
            assert prior and prior.get('owner'), 'Unknown forward owner; inspect before takeover'
            assert time.time()-prior['heartbeat_at']>LEASE_SECONDS, 'Prior lease not expired'
            assert set(active)=={prior['owner']['pid']}, 'Forward owner differs from recorded lease'
            terminate_owned(prior['owner'])
            for _ in range(50):
                if not any(p.intersection(PORTS) for p in listeners().values()):break
                time.sleep(.1)
            else:raise RuntimeError('Old forward has not released ports')
        print(json.dumps({'ready':True}),flush=True)

def serve(fd,out,on_ping,on_expire,timeout=LEASE_SECONDS):
    buffered=b'';last=time.monotonic()
    while True:
        remaining=timeout-(time.monotonic()-last)
        if remaining<=0:on_expire('heartbeat-timeout');return
        ready,_,_=select.select([fd],[],[],remaining)
        if not ready:continue
        data=os.read(fd,4096)
        if not data:on_expire('stdin-eof');return
        buffered+=data
        if len(buffered)>8192:raise RuntimeError('Invalid heartbeat input')
        while b'\n' in buffered:
            line,buffered=buffered.split(b'\n',1)
            value=json.loads(line)
            assert set(value)=={'ping'} and type(value['ping']) is int, 'Invalid heartbeat'
            last=time.monotonic();on_ping()
            out.write(json.dumps({'pong':value['ping']})+'\n');out.flush()

def session():
    held=lock();owned=listeners()
    owners=[pid for pid,ports in owned.items() if ports.intersection(PORTS)]
    assert len(owners)==1 and owned[owners[0]]==PORTS, 'Expected one SSH owner for both forwards'
    pid=owners[0];ancestor=os.getppid();ancestors=set()
    while ancestor>1:
        ancestors.add(ancestor)
        status=pathlib.Path('/proc',str(ancestor),'status').read_text()
        ancestor=int(re.search(r'^PPid:\s*(\d+)',status,re.M).group(1))
    assert pid in ancestors, 'Forward is not owned by this SSH connection'
    owner=identity(pid);assert owner and owner['name'].startswith('sshd')
    record={'owner':owner,'guard_pid':os.getpid(),'ports':sorted(PORTS),'heartbeat_at':time.time(),'state':'active'}
    write_record(record)
    event(record)
    def ping():record['heartbeat_at']=time.time();write_record(record)
    def expired(reason):record['state']=reason;record['close_reason']=reason;write_record(record)
    def stopped(_signal,_frame):raise InterruptedError('Guard stopped')
    signal.signal(signal.SIGTERM,stopped);signal.signal(signal.SIGINT,stopped)
    print(json.dumps({'ready':True,'owner_pid':pid,'lease_seconds':LEASE_SECONDS}),flush=True)
    try:serve(sys.stdin.fileno(),sys.stdout,ping,expired)
    except BaseException as error:
        record['close_reason']=type(error).__name__;raise
    finally:
        record['state']='closing';write_record(record);event(record)
        # Exact start time and the dedicated pair of listening ports are
        # checked again; never kill the sshd listener or another connection.
        terminate_owned(owner)
        held.close()

def main():
    os.umask(0o077)
    try:
        if sys.argv[1]=='prepare':prepare()
        elif sys.argv[1]=='session':session()
        elif sys.argv[1]=='status':print(json.dumps(read_record()))
        else:raise ValueError('Unknown command')
    except Exception as error:
        print(json.dumps({'ready':False,'error_type':type(error).__name__}),flush=True);return 1
    return 0
if __name__=='__main__':sys.exit(main())

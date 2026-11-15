#!/usr/bin/python3
"""Single local SSH owner; backoff belongs to systemd, not parallel clients."""
import fcntl,json,os,pathlib,select,signal,subprocess,sys,time
BASE=pathlib.Path('/srv/review/controller/cloudcli-forward-20261115')
SSH=['/usr/bin/ssh','-T','-F','/srv/review/secrets/manager-access/ssh_config','-o','BatchMode=yes','-o','ControlMaster=no','-o','ControlPath=none','-o','ConnectTimeout=15','-o','ServerAliveInterval=10','-o','ServerAliveCountMax=3','-o','ExitOnForwardFailure=yes']
REMOTE='/etc/cn25-console/forward-lease.py'

def event(record):
    path=BASE/'events.jsonl'
    if path.exists() and path.stat().st_size>1024*1024:path.replace(BASE/'events.previous.jsonl')
    with path.open('a') as out:out.write(json.dumps(dict(record,at=time.time()))+'\n')

def classify(data):
    # Retain categories only: raw SSH stderr can contain authentication details.
    data=data.lower()
    return [name for name,needle in [('timeout',b'timed out'),('reset',b'reset by peer'),
            ('closed',b'connection closed'),('broken-pipe',b'broken pipe'),
            ('port-in-use',b'address already in use'),('forward-refused',b'remote port forwarding failed'),
            ('network-unreachable',b'network is unreachable'),('permission-denied',b'permission denied')]
            if needle in data]

def save(record):
    record['at']=time.time();temp=BASE/'status.next';temp.write_text(json.dumps(record)+'\n');temp.chmod(0o600);temp.replace(BASE/'status.json')

def run():
    os.umask(0o077);BASE.mkdir(parents=True,mode=0o700,exist_ok=True)
    held=(BASE/'owner.lock').open('a');fcntl.flock(held,fcntl.LOCK_EX|fcntl.LOCK_NB)
    def stop(_signum,_frame):raise InterruptedError('Supervisor stopped')
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    # The remote command can reclaim only an expired lease bearing the same
    # PID birth identity. Unknown owners are preserved, never blindly killed.
    prepared=subprocess.run(SSH+['console-vps','python3 '+REMOTE+' prepare'],capture_output=True,text=True,timeout=30)
    if prepared.returncode!=0:
        record={'state':'preflight-unavailable','returncode':prepared.returncode,'stderr_categories':classify(prepared.stderr.encode())}
        save(record);event(record);return 1
    response=json.loads(prepared.stdout);assert response.get('ready') is True
    command=SSH+['-R','127.0.0.1:13301:127.0.0.1:3301','-R','127.0.0.1:13302:127.0.0.1:3302','console-vps','python3 '+REMOTE+' session']
    child=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    record={'state':'connecting','ssh_pid':child.pid,'ports':[13301,13302]};save(record);event(record)
    last=time.monotonic();started=last;next_ping=0;sequence=0;buffered=b'';ready=False;categories=set()
    try:
        while child.poll() is None:
            now=time.monotonic()
            if now-last>45:raise TimeoutError('Remote heartbeat deadline')
            if now>=next_ping:
                sequence+=1;child.stdin.write((json.dumps({'ping':sequence})+'\n').encode());child.stdin.flush();next_ping=now+10
            readable,_,_=select.select([child.stdout,child.stderr],[],[],min(1,max(0,next_ping-time.monotonic())))
            if not readable:continue
            if child.stderr in readable:
                categories.update(classify(os.read(child.stderr.fileno(),4096)))
            if child.stdout not in readable:continue
            data=os.read(child.stdout.fileno(),4096)
            if not data:break
            buffered+=data
            if len(buffered)>8192:raise RuntimeError('Invalid remote response')
            while b'\n' in buffered:
                line,buffered=buffered.split(b'\n',1);message=json.loads(line)
                if message.get('ready') is True:
                    ready=True;record['remote_owner_pid']=message['owner_pid'];event(dict(record,state='ready'))
                elif type(message.get('pong')) is int and 0<message['pong']<=sequence:last=time.monotonic();record['last_pong']=message['pong']
                else:raise RuntimeError('Remote lease refused')
                record['state']='active' if ready else 'connecting';save(record)
        raise ConnectionError('SSH connection ended')
    except BaseException as error:
        record['error_type']=type(error).__name__
        raise
    finally:
        if child.stdin:
            try:child.stdin.close()
            except (BrokenPipeError,OSError):pass
        if child.poll() is None:
            child.terminate()
            try:child.wait(timeout=5)
            except subprocess.TimeoutExpired:child.kill();child.wait(timeout=5)
        categories.update(classify(child.stderr.read(16384)))
        record.update(state='closed',ssh_returncode=child.returncode,stderr_categories=sorted(categories),
                      uptime_seconds=round(time.monotonic()-started,3),pong_age_seconds=round(time.monotonic()-last,3))
        save(record);event(record)
        held.close()

if __name__=='__main__':
    try:sys.exit(run())
    except Exception as error:
        try:event({'state':'failed','error_type':type(error).__name__})
        except Exception:pass
        sys.exit(1)

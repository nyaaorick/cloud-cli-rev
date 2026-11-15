import importlib.util,pathlib,unittest,os,io,threading,time,tempfile,json
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('lease',pathlib.Path(__file__).resolve().parents[1]/'forward-lease.py');lease=importlib.util.module_from_spec(spec);spec.loader.exec_module(lease)
class LeaseTests(unittest.TestCase):
 def test_heartbeat_timeout_reclaims(self):
  r,w=os.pipe();out=io.StringIO();events=[]
  try:
   os.write(w,b'{"ping":1}\n');lease.serve(r,out,lambda:events.append('ping'),events.append,timeout=.04)
   self.assertEqual(events,['ping','heartbeat-timeout']);self.assertEqual(json.loads(out.getvalue()),{'pong':1})
  finally:os.close(r);os.close(w)
 def test_closed_input_expires_immediately(self):
  r,w=os.pipe();os.close(w);events=[]
  try:lease.serve(r,io.StringIO(),lambda:None,events.append,timeout=10);self.assertEqual(events,['stdin-eof'])
  finally:os.close(r)
 def test_heartbeats_reset_deadline(self):
  r,w=os.pipe();events=[]
  def writer():
   for i in range(3):os.write(w,(json.dumps({'ping':i})+'\n').encode());time.sleep(.02)
   os.close(w)
  t=threading.Thread(target=writer);t.start()
  try:lease.serve(r,io.StringIO(),lambda:events.append('ping'),events.append,timeout=.05);self.assertEqual(events,['ping']*3+['stdin-eof'])
  finally:t.join();os.close(r)
 def test_pid_reuse_never_kills(self):
  owner={'pid':123,'start':'1','name':'sshd'}
  with patch.object(lease,'identity',return_value={**owner,'start':'2'}),patch.object(lease.os,'kill') as kill:
   with self.assertRaises(AssertionError):lease.terminate_owned(owner)
   kill.assert_not_called()
 def test_other_port_never_kills(self):
  owner={'pid':123,'start':'1','name':'sshd'}
  with patch.object(lease,'identity',return_value=owner),patch.object(lease,'listeners',return_value={123:{60335}}),patch.object(lease.os,'kill') as kill:
   with self.assertRaises(AssertionError):lease.terminate_owned(owner)
   kill.assert_not_called()
 def test_exact_owned_pair_is_only_signal_target(self):
  owner={'pid':123,'start':'1','name':'sshd'}
  with patch.object(lease,'identity',return_value=owner),patch.object(lease,'listeners',return_value={123:{13301,13302},999:{60335}}),patch.object(lease.os,'kill') as kill:
   lease.terminate_owned(owner);kill.assert_called_once_with(123,lease.signal.SIGTERM)
 def test_second_owner_lock_refused(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(lease,'BASE',pathlib.Path(temp)):
   first=lease.lock()
   try:
    with self.assertRaises(BlockingIOError):lease.lock()
   finally:first.close()
 def test_unknown_existing_forward_is_preserved(self):
  with tempfile.TemporaryDirectory() as temp,patch.object(lease,'BASE',pathlib.Path(temp)),patch.object(lease,'listeners',return_value={123:{13301,13302}}),patch.object(lease,'read_record',return_value=None),patch.object(lease,'terminate_owned') as terminate:
   with self.assertRaisesRegex(AssertionError,'Unknown forward owner'):lease.prepare()
   terminate.assert_not_called()
 def test_unexpired_lease_is_preserved(self):
  owner={'pid':123,'start':'1','name':'sshd'}
  with tempfile.TemporaryDirectory() as temp,patch.object(lease,'BASE',pathlib.Path(temp)),patch.object(lease,'listeners',return_value={123:{13301,13302}}),patch.object(lease,'read_record',return_value={'owner':owner,'heartbeat_at':time.time()}),patch.object(lease,'terminate_owned') as terminate:
   with self.assertRaisesRegex(AssertionError,'not expired'):lease.prepare()
   terminate.assert_not_called()
 def test_expired_known_owner_is_reclaimed_before_ready(self):
  owner={'pid':123,'start':'1','name':'sshd'}
  with tempfile.TemporaryDirectory() as temp,patch.object(lease,'BASE',pathlib.Path(temp)),patch.object(lease,'listeners',side_effect=[{123:{13301,13302}},{}]),patch.object(lease,'read_record',return_value={'owner':owner,'heartbeat_at':time.time()-100}),patch.object(lease,'terminate_owned') as terminate,patch('builtins.print'):
   lease.prepare();terminate.assert_called_once_with(owner)
if __name__=='__main__':unittest.main()

"""Local orchestration of existing isolated worker; never publishes."""
from pathlib import Path
import sys,os,subprocess,json,time,hashlib,re,socket
R=Path(__file__).resolve().parent

def accept_events(events,expected):
 assert len(events)==len(expected)==139
 assert [x['id'] for x in events]==expected and len({x['id'] for x in events})==139
 assert all(x['status']=='success' for x in events)
 return True

def main():
 from verify_sources import verify
 verify()
 expected=json.loads((R/'expected-tests.json').read_text())['ids']
 E=R/('evidence-offline' if sys.argv[1:]==['offline-preflight'] else 'evidence');E.mkdir(exist_ok=False)
 env={k:v for k,v in os.environ.items() if k.lower() in {'systemroot','windir'}}
 env.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
 def run(label,mode,*args):
  path=E/(label+'.log')
  with path.open('x',encoding='utf8') as f:
   p=subprocess.run([sys.executable,'-s','-B',str(R/'ci_entry.py'),mode,*args],cwd=R,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=300)
  print('STAGE',label,p.returncode,hashlib.sha256(path.read_bytes()).hexdigest(),flush=True)
  text=path.read_text(encoding='utf8');print(text,flush=True)
  assert p.returncode==0,(label,p.returncode)
  return text
 if sys.argv[1:]==['offline-preflight']:
  run('offline-preflight','offline-preflight');verify();return
 assert not sys.argv[1:]
 servers=[];handles=[];C=R/'candidate'
 def closed(port):
  with socket.socket() as s:return s.connect_ex(('127.0.0.1',port))!=0
 try:
  run('migrate','migrate')
  initial=json.loads(run('fixtures-initial','fixtures').splitlines()[-1]);assert initial['superusers']==0
  for port in (55451,55452,55453):
   assert closed(port)
   h=(E/('server-'+str(port)+'.log')).open('xb');handles.append(h)
   servers.append(subprocess.Popen([sys.executable,'-s','-B',str(R/'ci_entry.py'),'server',str(port)],cwd=R,env=env,stdout=h,stderr=h))
  for _ in range(200):
   if all(not closed(p) for p in (55451,55452,55453)):break
   assert all(p.poll() is None for p in servers);time.sleep(.1)
  assert all(not closed(p) for p in (55451,55452,55453))
  records=[];groups=json.loads((R/'expected-tests.json').read_text())['batches']
  assert [x for group in groups for x in group]==expected
  for i,group in enumerate(groups):
   if i:time.sleep(61)
   run('batch-'+str(i),'batch',*group)
   data=json.loads((C/'events.json').read_text());assert data['successful'] and data['run']==len(group)
   assert [x['id'] for x in data['events']]==group
   records+=data['events'];(E/('batch-'+str(i)+'.json')).write_text(json.dumps(data,indent=2))
  accept_events(records,expected)
  run('readback','readback');run('readback-service','readback-service')
  final=json.loads(run('fixtures-final','fixtures').splitlines()[-1]);assert final['superusers']<=256
  verify()
  report={'ids':records,'distinct':139,'invocations':139,'passed':139,'failed':0,'skipped':0,'superusers':[0,final['superusers']],'guard_256_unchanged':True,'separate_process_readbacks':True}
  (E/'result.json').write_text(json.dumps(report,indent=2));print('QUALIFICATION_RESULT',json.dumps(report))
 finally:
  (C/'stop.txt').write_text('stop')
  for p in servers:
   try:p.wait(timeout=15)
   except subprocess.TimeoutExpired:p.terminate();p.wait(timeout=10)
  for h in handles:h.close()
  assert all(closed(p) for p in (55451,55452,55453));verify()
if __name__=='__main__':main()

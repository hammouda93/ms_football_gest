"""Actual isolated child entrypoint, including network-free import preflight."""
import os,sys,json,runpy,unittest
from pathlib import Path
R=Path(__file__).resolve().parent;C=R/'candidate'
windows={k:v for k,v in os.environ.items() if k.lower() in {'systemroot','windir'}}
os.environ.clear()
os.environ.update(windows,PYTHONDONTWRITEBYTECODE='1',DJANGO_SETTINGS_MODULE='lab_settings')
sys.path[:0]=[str(C),str(C/'source')]
from target_wrapper import install,adapt
install()
mode=sys.argv[1]
assert mode in {'offline-preflight','migrate','batch','readback','readback-service','server','fixtures'}
if mode=='offline-preflight':
 from isolation import install as guard,deny,EVENTS
 guard()
 def offline_audit(event,args):
  if event in {'socket.connect','socket.bind','socket.sendto','socket.getaddrinfo'}:deny('offline network')
 sys.addaudithook(offline_audit)
 import psycopg2
 psycopg2.connect=lambda *a,**k:deny('offline database')
 import django
 django.setup()
 expected=json.loads((R/'expected-tests.json').read_text())['ids']
 suite=unittest.defaultTestLoader.loadTestsFromNames(expected)
 def ids(node):
  if isinstance(node,unittest.TestSuite):return [i for t in node for i in ids(t)]
  return [node.id()]
 observed=ids(suite)
 assert observed==expected and len(set(observed))==139,(observed,set(expected)-set(observed))
 # Import preflight does not execute tests, SQL, or synthesize Linux identity.
 from ci_target import validate
 from lab_control import identity
 from django.db import connections
 for alias in connections:assert connections[alias].connection is None
 # Exercise actual refusals, not merely installed callbacks.
 blocked=[]
 import socket,subprocess
 for label,probe in [('database',lambda:psycopg2.connect(host='127.0.0.1',port=55440,user='msf_action01_fixture_owner',dbname='msf_action03_fiction')),('network',lambda:socket.getaddrinfo('example.invalid',443)),('process',lambda:subprocess.run([sys.executable,'-V'])),('secret-file',lambda:open(C/'.env'))]:
  try:probe()
  except PermissionError:blocked.append(label)
  else:raise AssertionError('offline guard accepted '+label)
 assert len(blocked)==4
 print('OFFLINE_GUARDS',json.dumps(blocked))
 print('OFFLINE_PREFLIGHT',json.dumps({'ids':observed,'count':len(observed),'django':django.get_version(),'python':sys.version,'platform':sys.platform,'businessSQL':False,'businessNetwork':False,'events':EVENTS}))
else:
 if mode=='server':
  from isolation import install as guard
  guard()
  from lab_control import identity
  identity()
 path=C/({'migrate':'worker.py','batch':'worker.py','readback':'worker.py','readback-service':'worker.py','server':'server.py','fixtures':'fixture_snapshot.py'}[mode])
 args=[mode] if mode in {'migrate','readback','readback-service'} else sys.argv[2:]
 sys.argv=[str(path),*args]
 exec(compile(adapt(path.read_text(encoding='utf8')),str(path),'exec'),{'__name__':'__main__','__file__':str(path)})

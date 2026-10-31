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
assert mode in {'offline-preflight','migrate','batch','readback','fixtures'}
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
 assert observed==expected and len(set(observed))==90,(observed,set(expected)-set(observed))
 # Import preflight does not execute tests, SQL, or synthesize Linux identity.
 from ci_target import validate
 from lab_control import identity
 from django.db import connections
 for alias in connections:assert connections[alias].connection is None
 print('OFFLINE_PREFLIGHT',json.dumps({'ids':observed,'count':len(observed),'django':django.get_version(),'python':sys.version,'platform':sys.platform,'businessSQL':False,'businessNetwork':False,'events':EVENTS}))
else:
 path=C/({'migrate':'worker.py','batch':'worker.py','readback':'readback_unified01.py','fixtures':'fixture_snapshot.py'}[mode])
 args=['migrate'] if mode=='migrate' else sys.argv[2:]
 sys.argv=[str(path),*args]
 exec(compile(adapt(path.read_text(encoding='utf8')),str(path),'exec'),{'__name__':'__main__','__file__':str(path)})

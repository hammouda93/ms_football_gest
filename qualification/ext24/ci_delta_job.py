"""Executable exact-13 delta, offline collection, migration and separate readback.
Extract extension24-ci.zip, use Python3.10; no inherited 139-test replay.
"""
from pathlib import Path
import sys,os,json,unittest,hashlib,contextlib,io
R=Path(__file__).resolve().parent;C=R/'candidate'
mode=sys.argv[1];assert mode in {'offline','migrate','tests','readback'}
windows={k:v for k,v in os.environ.items() if k.lower() in {'systemroot','windir'}};os.environ.clear();os.environ.update(windows,PYTHONDONTWRITEBYTECODE='1',DJANGO_SETTINGS_MODULE='ci_settings')
sys.path[:0]=[str(C),str(C/'source')]
from ci_delta_target import install,identity
install(R,mode=='offline')
from verify_ci_inventory import verify
verify()
with contextlib.redirect_stdout(io.StringIO()),contextlib.redirect_stderr(io.StringIO()):
 import django;django.setup()
 from data_access.metadata import catalog
 from actions.registry import catalogue
 cat=catalog();contracts=catalogue()
 assert len(cat['models'])==37 and sum(len(m['fields']) for m in cat['models'].values())==385 and len(contracts)==24
 assert cat['schemaFingerprint']=='ec515db783193a91e4136e2afc1abdfacbc3240bb19da50dd536187d3496f916'
 suite=unittest.defaultTestLoader.loadTestsFromNames(['test_fix','test_delivery_salary'])
 def ids(s):return [i for x in s for i in ids(x)] if isinstance(s,unittest.TestSuite) else [s.id()]
 labels=ids(suite);assert labels==json.loads((R/'expected-delta.json').read_text()) and len(labels)==len(set(labels))==13
imports={}
for module in list(sys.modules.values()):
 p=getattr(module,'__file__',None)
 if p:
  path=Path(p).resolve()
  if C.resolve() in path.parents and path.is_file():imports[path.relative_to(R).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
report={'importedCandidateHashes':imports,'mode':mode,'schemaFingerprint':cat['schemaFingerprint'],'ids':labels,'python':sys.version,'django':django.get_version(),'linux':sys.platform=='linux'}
if mode=='offline':
 from django.db import connections
 for alias in connections:assert connections[alias].connection is None
 import socket,subprocess,psycopg2
 blocked=[]
 for n,fn in [('network',lambda:socket.getaddrinfo('example.invalid',443)),('database',lambda:psycopg2.connect('')),('process',lambda:subprocess.run([sys.executable,'-V']))]:
  try:fn()
  except PermissionError:blocked.append(n)
  else:raise AssertionError(n)
 report.update(testsExecuted=False,blocked=blocked)
else:
 report['databaseIdentity']=identity()
 from django.core.management import call_command
 if mode=='migrate':call_command('migrate',interactive=False,verbosity=1)
 if mode=='tests':
  class Result(unittest.TextTestResult):
   def startTest(self,t):super().startTest(t);self.events.append({'id':t.id(),'status':'started'})
   def addSuccess(self,t):super().addSuccess(t);self.events[-1]['status']='success'
  Result.events=[]
  result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
  report.update(events=result.events,successful=result.wasSuccessful(),run=result.testsRun)
  (R/'delta-result.json').write_text(json.dumps(report,indent=2))
  if not result.wasSuccessful():sys.exit(1)
 if mode=='readback':
  from actions.models import Plan
  from actions.models import Verification
  from django.db import connection
  with connection.cursor() as q:q.execute('SET default_transaction_read_only=on')
  report['plans']=Plan.objects.count();report['receipts']=Verification.objects.count()
verify();print(json.dumps(report))

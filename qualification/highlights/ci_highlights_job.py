"""Small delta of ext24 runner: exact Highlights fixtures, separate readback."""
from pathlib import Path
import sys,os,json,unittest,hashlib,contextlib,io
R=Path(__file__).resolve().parent
mode=sys.argv[1]
assert mode in {'offline','migrate','tests','readback'}
windows={k:v for k,v in os.environ.items() if k.lower() in {'systemroot','windir'}}
os.environ.clear();os.environ.update(windows,PYTHONDONTWRITEBYTECODE='1',DJANGO_SETTINGS_MODULE='ci_settings')
sys.path.insert(0,str(R/'repo'))
from ci_delta_target import install,identity
install(R,mode=='offline')
from verify_ci_inventory import verify
verify()
import django
django.setup()
from data_access.metadata import catalog
from actions.registry import catalogue
cat=catalog();contracts=catalogue()
assert len(contracts)==26
assert cat['schemaFingerprint']=='ec515db783193a91e4136e2afc1abdfacbc3240bb19da50dd536187d3496f916'
old=json.loads((R/'BASE-CONTRACTS.json').read_bytes())
assert len(old)==24 and {k:contracts[k] for k in old}==old
expected=json.loads((R/'expected-tests.json').read_bytes())
def ids(s):
 return [i for x in s for i in ids(x)] if isinstance(s,unittest.TestSuite) else [s.id()]
suites=[]
for group in expected:
 s=unittest.defaultTestLoader.loadTestsFromName(group['module'])
 assert ids(s)==group['ids']
 suites.append(s)
labels=[label for g in expected for label in g['ids']]
assert len(labels)==len(set(labels))==16
report={'mode':mode,'schemaFingerprint':cat['schemaFingerprint'],'contracts':len(contracts),'legacyContractsIdentical':True,'ids':labels,'python':sys.version,'django':django.get_version(),'linux':sys.platform=='linux'}
if mode=='offline':
 from django.db import connections
 for alias in connections:assert connections[alias].connection is None
 import socket,subprocess,psycopg2
 blocked=[]
 for name,fn in [('network',lambda:socket.getaddrinfo('example.invalid',443)),('database',lambda:psycopg2.connect('')),('process',lambda:subprocess.run([sys.executable,'-V']))]:
  try:fn()
  except PermissionError:blocked.append(name)
  else:raise AssertionError(name)
 report.update(testsExecuted=False,blocked=blocked)
else:
 report['databaseIdentity']=identity()
 assert sys.platform=='linux' and sys.version_info[:2]==(3,10) and django.get_version()=='4.2.20'
 if mode=='migrate':
  from django.core.management import call_command
  call_command('migrate',interactive=False,verbosity=1)
 if mode in {'tests','readback'}:
  if mode=='readback':
   from ci_readback_guard import guard_readbacks
   suite=unittest.defaultTestLoader.loadTestsFromName('fix_readback')
   expected_readback=['readback_fixture.IndependentReadback.test_committed_http_targets','fix_readback.PaymentSuccessors.test_latest_payment_and_persisted_ledger_for_superseded_creates']
   assert ids(suite)==expected_readback
  else:suite=unittest.TestSuite(suites)
  execution_ids=ids(suite)
  class Result(unittest.TextTestResult):
   def __init__(self,*a,**kw):super().__init__(*a,**kw);self.events=[]
   def record(self,t,status):self.events.append({'id':t.id(),'status':status})
   def addSuccess(self,t):super().addSuccess(t);self.record(t,'success')
   def addFailure(self,t,e):super().addFailure(t,e);self.record(t,'failure')
   def addError(self,t,e):super().addError(t,e);self.record(t,'error')
   def addSkip(self,t,r):super().addSkip(t,r);self.record(t,'skip')
   def addExpectedFailure(self,t,e):super().addExpectedFailure(t,e);self.record(t,'expectedFailure')
   def addUnexpectedSuccess(self,t):super().addUnexpectedSuccess(t);self.record(t,'unexpectedSuccess')
   def addSubTest(self,t,s,e):
    super().addSubTest(t,s,e)
    if e:self.record(t,'subtestError')
  with (guard_readbacks(R,report) if mode=='readback' else contextlib.nullcontext()):
   result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
  final={i:'missing' for i in execution_ids}
  for event in result.events:
   i=event['id'];status=event['status']
   if final.get(i) in {'missing','success'}:final[i]=status
  report.update(events=result.events,final=final,successful=result.wasSuccessful() and all(s=='success' for s in final.values()),run=result.testsRun,ids=execution_ids)
  print('HIGHLIGHTS_MACHINE '+json.dumps(report,sort_keys=True),flush=True)
  (R/(mode+'-result.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
  if not report['successful']:sys.exit(1)
verify()
report['importedCandidateHashes']={}
for module in list(sys.modules.values()):
 p=getattr(module,'__file__',None)
 if p:
  path=Path(p).resolve()
  if (R/'repo').resolve() in path.parents and path.is_file():report['importedCandidateHashes'][path.relative_to(R).as_posix()]=hashlib.sha256(path.read_bytes()).hexdigest()
print('HIGHLIGHTS_MACHINE '+json.dumps(report,sort_keys=True),flush=True)

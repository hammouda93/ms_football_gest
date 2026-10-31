"""Independent-process real READ ONLY technical and persisted-result readback."""
import json,hashlib
from pathlib import Path
from django.db import connections,transaction
from actions.models import Plan,Verification,Audit
from django.apps import apps
R=Path(__file__).resolve().parent
c=connections['verification']
try:
 with transaction.atomic(using='verification'):
  with c.cursor() as q:
   q.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
   q.execute("SELECT current_database(),current_user,host(inet_server_addr()),inet_server_port(),current_setting('data_directory'),current_setting('transaction_read_only'),pg_backend_pid()")
   identity=q.fetchone()
   from ci_target import validate
   import platform,sys
   q.execute("SELECT current_setting('server_version')");version=q.fetchone()[0]
   validate(tuple(identity[:5])+(version,),json.loads((R.parent/'ci-target.json').read_text()),platform.system(),sys.version_info[:3]);assert identity[5]=='on'
  results=[]
  from actions.registry import catalogue
  rules=catalogue()
  for p in Plan.objects.using('verification').order_by('created_at'):
   bound=list(Audit.objects.using('verification').filter(plan=p,event='verification_bound').values_list('code',flat=True))
   exists={}
   for s in p.steps:
    pk=p.results.get(s['as'])
    if pk is not None:exists[s['as']]=apps.get_model(rules[s['op']]['model']).objects.using('verification').filter(pk=pk).exists()
   results.append({'plan':str(p.pk),'state':p.state,'error':p.error,'results':p.results,'result_rows_exist':exists,'pre_count':Verification.objects.using('verification').filter(plan=p).count(),'bound':bound})
  assert all(x['pre_count'] and len(x['bound'])==1 and all(x['result_rows_exist'].values()) for x in results if x['state']=='succeeded')
  out={'identity':identity,'plans':results,'contracts':sorted(rules),'transaction_read_only':True}
  (R/'readback.json').write_text(json.dumps(out,indent=2));transaction.set_rollback(True,using='verification')
finally:c.close()
print('READBACK',len(results),'plans',len(rules),'contracts; role owns isolated cluster, not restricted production role')

"""Read committed records in another process after the HTTP workers exited."""
import json,os,sys
from pathlib import Path
from django.db import connections
from actions.models import Plan,Audit,Verification
from actions.readback import readonly
R=Path(__file__).parent
proof=json.loads((R/'composed-proof.json').read_text())
with readonly():
 p=Plan.objects.using('verification').get(pk=proof['plan'])
 events=list(Audit.objects.using('verification').filter(plan=p).order_by('pk').values('event','code'))
 assert p.state=='succeeded'
 assert any(x=={'event':'verification_bound','code':proof['PRE']['receipt']} for x in events)
 assert any(x=={'event':'verification_post','code':'verified'} for x in events)
 assert Verification.objects.using('verification').filter(pk=proof['PRE']['receipt']).exists()
 assert os.getpid() not in proof['pids']+[proof['controller']]
 with connections['verification'].cursor() as q:
  q.execute("SELECT version(),current_setting('transaction_read_only')");version,ro=q.fetchone();assert ro=='on'
result={'pid':os.getpid(),'plan':str(p.pk),'events':events,'readonly':ro,'postgres':version,'python':sys.version,'django':__import__('django').get_version()}
(R/'durable-readback.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

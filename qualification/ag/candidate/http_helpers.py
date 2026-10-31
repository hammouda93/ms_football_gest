import json,time
from pathlib import Path
from datetime import timedelta
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from django.utils import timezone
R=Path(__file__).parent

def call(port,route,data):
 time.sleep(.14)
 req=Request('http://127.0.0.1:'+str(port)+'/actions/v1/'+route,data=json.dumps(data).encode(),headers={'Authorization':'Bearer FICTION_READBACK_TOKEN','Content-Type':'application/json','Cookie':'sessionid=expired-fiction'})
 try:
  with urlopen(req,timeout=20) as r:return r.status,json.load(r)
 except HTTPError as r:return r.code,json.load(r)
def configure(actor,pk):
 from actions.models import Plan
 from actions.registry import catalogue
 p=Plan.objects.get(pk=pk)
 cfg={'credential':{'actor':actor,'scopes':['catalogue','prepare','status','execute','verify',*['op:'+n for n in catalogue()]],'expires':(timezone.now()+timedelta(minutes=10)).isoformat(),'revoked':False},'binding':{'plan_id':str(p.pk),'actor':actor,'digest':p.digest,'operations':[s['op'] for s in p.steps]}}
 (R/'http-fixture.json').write_text(json.dumps(cfg))
 return p

def execute(actor,pk):
 from actions.http import issue_approval
 from django.conf import settings
 p=configure(actor,pk)
 settings.ACTIONS_APPROVAL_KEY='FICTION_UNIFIED_APPROVAL_KEY_001_NOT_LIVE'
 token=issue_approval(pk,actor,p.digest,timezone.now()+timedelta(minutes=2))
 code,result=call(55852,'execute',{'id':str(pk),'approval':token})
 assert code==200,(code,result)
 return result

"""Fixture orchestration only: real durable PRE, no engine monkeypatch."""
def prepared(result):
 from actions.models import Plan,Verification
 from actions.readback import before
 value=result
 if isinstance(result,tuple):
  if result[0]!=200:return result
  value=result[1]
 if hasattr(result,'status_code'):
  if result.status_code!=200:return result
  import json
  value=json.loads(result.content)
 if not isinstance(value,dict) or 'id' not in value:return result
 plan=Plan.objects.get(pk=value['id'])
 if plan.state=='prepared' and not Verification.objects.filter(plan=plan).exists():
  before(plan.actor_id,plan.pk)
 return result

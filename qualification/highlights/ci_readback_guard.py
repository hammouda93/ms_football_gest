"""Readback harness only: full fixture snapshots and exact technical-audit delta."""
import json,re
from collections import Counter
from contextlib import contextmanager
from pathlib import Path


def expected_posts(root):
 from actions.models import Plan
 root=Path(root)
 attacked={x['id'] for x in map(json.loads,(root/'ATTACKED-TARGETS.jsonl').read_text().splitlines())}
 receipts=[json.loads(p.read_text()) for p in sorted(root.glob('hl-*.json'))]
 latest={};superseded=[]
 plans=list(Plan.objects.order_by('created_at','pk'))
 by_id={str(p.pk):p for p in plans}
 for r in receipts:
  p=by_id[r['plan']]
  if not p.steps[0]['op'].startswith('video.'):continue
  pk=r['result']['results']['x']
  payments=[q for q in plans if q.created_at>p.created_at and q.state=='succeeded' and any(s['op']=='finance.highlight.payment.record' and s['values'].get('video')==pk for s in q.steps)]
  if payments:superseded.append((pk,payments[-1]))
  elif pk not in attacked and (pk not in latest or p.created_at>latest[pk][0].created_at):latest[pk]=(p,r)
 expected=[]
 for pk,(p,r) in latest.items():
  if any(q.created_at>p.created_at and q.state=='succeeded' and any(s['values'].get('id')==pk for s in q.steps) for q in plans):continue
  assert p.results==r['result']['results'] and p.actor_id==r['actor']
  expected.append((str(p.pk),p.actor_id,'verification_post','verified'))
 for pk,p in superseded:
  if not any(q.state=='succeeded' and any(s['op']=='video.conditions.amend' and s['values'].get('id')==pk for s in q.steps) for q in plans):
   expected.append((str(p.pk),p.actor_id,'verification_post','verified'))
 assert expected,'no expected readback audit'
 return expected


def snapshot():
 from actions.readback import readonly
 from django.db import connections
 with readonly():
  c=connections['verification']
  with c.cursor() as q:
   q.execute("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename")
   tables=[r[0] for r in q.fetchall()]
   out={}
   for table in tables:
    q.execute('SELECT to_jsonb(t)::text FROM '+c.ops.quote_name(table)+' AS t ORDER BY to_jsonb(t)::text')
    out[table]=[json.loads(r[0]) for r in q.fetchall()]
 assert 'actions_audit' in out
 return out


def check_delta(before,after,expected):
 assert set(before)==set(after),'fixture tables changed'
 for table in before:
  if table!='actions_audit':assert before[table]==after[table],'fixture mutation: '+table
 old={r['id']:r for r in before['actions_audit']}
 new={r['id']:r for r in after['actions_audit']}
 assert len(old)==len(before['actions_audit']) and len(new)==len(after['actions_audit'])
 assert all(new.get(pk)==r for pk,r in old.items()),'prior audit changed'
 added=[r for pk,r in new.items() if pk not in old]
 keys={'id','plan_id','actor_id','event','code','created_at'}
 assert all(set(r)==keys and type(r['id']) is int and r['id']>0 and type(r['created_at']) is str and r['created_at'] for r in added),'audit shape'
 actual=[(r['plan_id'],r['actor_id'],r['event'],r['code']) for r in added]
 assert Counter(actual)==Counter(expected),'unexpected audit delta'
 return added


@contextmanager
def guard_readbacks(root,report):
 from django.db import connections
 expected=expected_posts(root)
 before=snapshot()
 remaining=Counter(expected)
 def audit_only(execute,sql,params,many,context):
  # Closed exact templates observed through the real readback entrypoint.
  # SQL text is never normalized, split, or stripped: comments, terminators,
  # functions, COPY, WITH and arbitrary SELECT/SHOW/SET cannot broaden it.
  # Parameter values remain separate, so punctuation in data is not SQL.
  allowed_reads={
   'SELECT "actions_plan"."id", "actions_plan"."actor_id", "actions_plan"."key", "actions_plan"."digest", "actions_plan"."steps", "actions_plan"."snapshots", "actions_plan"."state", "actions_plan"."results", "actions_plan"."effects", "actions_plan"."error", "actions_plan"."created_at" FROM "actions_plan" ORDER BY "actions_plan"."created_at" ASC, "actions_plan"."id" ASC',
   'SELECT "actions_plan"."id", "actions_plan"."actor_id", "actions_plan"."key", "actions_plan"."digest", "actions_plan"."steps", "actions_plan"."snapshots", "actions_plan"."state", "actions_plan"."results", "actions_plan"."effects", "actions_plan"."error", "actions_plan"."created_at" FROM "actions_plan" WHERE "actions_plan"."id" = %s LIMIT 21',
   'SELECT "actions_plan"."id", "actions_plan"."actor_id", "actions_plan"."key", "actions_plan"."digest", "actions_plan"."steps", "actions_plan"."snapshots", "actions_plan"."state", "actions_plan"."results", "actions_plan"."effects", "actions_plan"."error", "actions_plan"."created_at" FROM "actions_plan" WHERE "actions_plan"."state" = %s',
   'SELECT "actions_plan"."id", "actions_plan"."actor_id", "actions_plan"."key", "actions_plan"."digest", "actions_plan"."steps", "actions_plan"."snapshots", "actions_plan"."state", "actions_plan"."results", "actions_plan"."effects", "actions_plan"."error", "actions_plan"."created_at" FROM "actions_plan" WHERE ("actions_plan"."created_at" > %s AND "actions_plan"."state" = %s)',
  }
  if not many and type(sql) is str and sql in allowed_reads:
   return execute(sql,params,many,context)
  # Django's real Audit INSERT; no other DML/DDL or extra SQL is admitted.
  pattern=r'INSERT INTO "actions_audit" \("plan_id", "actor_id", "event", "code", "created_at"\) VALUES \(%s, %s, %s, %s, %s\) RETURNING "actions_audit"\."id"'
  if many or not re.fullmatch(pattern,sql):raise PermissionError('readback business write blocked')
  key=(str(params[0]),params[1],params[2],params[3])
  if remaining[key]<=0:raise PermissionError('unplanned readback audit')
  result=execute(sql,params,many,context)
  remaining[key]-=1
  return result
 with connections['default'].execute_wrapper(audit_only):
  try:yield
  finally:
   after=snapshot()
   added=check_delta(before,after,expected)
   assert not +remaining,'missing readback audit'
   report.update(readbackGuard={'allFixtureTablesUnchangedExceptAudit':True,'tables':sorted(before),'before':before,'after':after,'expectedAudit':[list(x) for x in expected],'addedAudit':added})

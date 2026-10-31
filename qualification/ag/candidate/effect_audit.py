"""Test-only oracle on every successful transition of the 52-ID replay."""
import unittest
from actions.engine import Engine
from actions.models import Plan
from test_wf01 import business_rows, assert_effects
CHECKED=[]
def install():
    original=Engine.execute
    def execute(engine,plan_id):
        plan=Plan.objects.get(pk=plan_id)
        transitions=plan.snapshots.get('__preview__',{}).get('transitions',[])
        before={p['id']:business_rows(p['id']) for p in transitions} if plan.state=='prepared' else {}
        result=original(engine,plan_id)
        if transitions and before and result['state']=='succeeded':
            assert_effects(unittest.TestCase(),plan,result,before)
            CHECKED.append({'plan':str(plan_id),'videos':list(before),'counts':{k:len(result['effects'][k]) for k in ('history','activities','notifications')}})
        return result
    Engine.execute=execute

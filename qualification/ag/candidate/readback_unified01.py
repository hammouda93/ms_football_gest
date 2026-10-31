"""Independent process verifies committed effect payloads, all inserts and IDs."""
import os,sys,json,unittest
from pathlib import Path
R=Path(__file__).resolve().parent
sys.path[:0]=[str(R),str(R/'source')];os.environ['DJANGO_SETTINGS_MODULE']='lab_settings'
from isolation import install
install()
from lab_control import identity
who=identity()
import django
django.setup()
from django.db import transaction,connection
from actions.models import Plan
from gestion_joueurs.models import Player
from test_wf01 import assert_effects,business_rows
rows=[json.loads(x) for x in (R/'unified01-records.jsonl').read_text().splitlines()]
# RED rows remain evidence of the original defect, not expected GREEN state.
rows=rows[-7:]
assert len({c['kind'] for c in rows})==7
with transaction.atomic():
 with connection.cursor() as q:q.execute('SET TRANSACTION READ ONLY');q.execute('SET LOCAL statement_timeout=5000')
 for c in rows:
  assert os.getpid()!=c['pid']
  p=Plan.objects.get(pk=c['plan']);assert p.state=='succeeded' and p.effects==c['result']['effects']
  normalize=lambda v:json.loads(json.dumps(v,default=str))
  assert normalize(business_rows(c['video']))==c['readback']
  assert normalize(Player.objects.values().get(pk=c['player_id']))==c['player']
  from test_wf01 import MODELS,FIELDS
  canonical=lambda v:sorted(normalize(v),key=lambda r:json.dumps(r,sort_keys=True))
  for name,model in MODELS.items():
   old=c['before'][name];ids=[r['id'] for r in old]
   assert normalize(list(model.objects.filter(pk__in=ids).order_by('pk').values()))==old
   new=model.objects.filter(video_id=c['video']).exclude(pk__in=ids).order_by('pk')
   expected=[r for t in c['preview']['transitions'] for r in t[name]]
   actual=list(new.values(*FIELDS[name]))
   assert len(actual)==len(expected) and canonical(actual)==canonical(expected),name
   assert sorted(new.values_list('pk',flat=True))==sorted(c['result']['effects'][name]),name
 refused=json.loads((R/'refusal-records.jsonl').read_text().splitlines()[-1]);assert os.getpid()!=refused['pid']
 p=Plan.objects.get(pk=refused['plan']);assert normalize((p.digest,p.snapshots,p.state,p.effects))==refused['frozen']
 assert normalize(business_rows(refused['video']))==refused['readback']
 assert normalize(Player.objects.values().get(pk=refused['player_id']))==refused['player']
print(json.dumps({'refusal_readback_exact':True,'read_only':True,'pid':os.getpid(),'identity':who,'cases':[c['kind'] for c in rows],'all_effect_payloads_counts_ids_exact':True}))

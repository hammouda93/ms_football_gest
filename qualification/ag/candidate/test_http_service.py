import unittest,json,uuid,os,time
from pathlib import Path
from datetime import date,timedelta
from django.contrib.auth.models import User
from django.utils import timezone
from django.conf import settings
from actions.engine import Engine
from actions.models import Audit,Plan
from http_helpers import call,configure,execute
R=Path(__file__).parent
class ServiceHttpTests(unittest.TestCase):
 def test_composed_creation_pre_execute_post_three_processes(self):
  from gestion_joueurs.models import VideoEditor,Invoice
  from client_portal.models import Organization
  actor=User.objects.create(username='FICTION_COMPOSE_'+uuid.uuid4().hex,is_superuser=True)
  ve=VideoEditor.objects.create(user=actor);org=Organization.objects.create(name='FICTION_COMPOSE',kind='agent')
  e=Engine(actor.pk)
  steps=[{'as':'p','op':'player.create','values':{'name':'FICTION_COMPOSE_'+uuid.uuid4().hex,'club':'FICTION','league':'OC','position':'MF','date_of_birth':'2002-01-02'}},{'as':'link','op':'organization.link','values':{'player':{'ref':'p'},'organization':org.pk,'expected_matches':5}},{'as':'order','op':'video.order','values':{'player':{'ref':'p'},'editor':ve.pk,'client_organization':org.pk,'whatsapp_conversation_date':date.today().isoformat(),'deadline_from_whatsapp':True,'match_package':5,'season':'2025/2026','advance_payment':'0.00','info':'FICTION_PRIVATE'}}]
  p=e.prepare(uuid.uuid4().hex,steps);configure(actor.pk,p['id'])
  self.assertEqual(call(55852,'execute',{'id':p['id'],'approval':'bad'})[0],403)
  code,t=call(55851,'verify',{'id':p['id'],'phase':'before'});self.assertEqual(code,200,t)
  done=execute(actor.pk,p['id']);self.assertEqual(done['state'],'succeeded',done)
  code,post=call(55853,'verify',{'id':t['receipt'],'phase':'after'});self.assertEqual((code,post.get('verdict')),(200,'verified'),post)
  self.assertEqual(execute(actor.pk,p['id']),done)
  pids=[json.loads((R/('ready-'+str(port)+'.json')).read_text())['pid'] for port in (55851,55852,55853)]
  self.assertEqual(len(set(pids+[os.getpid()])),4)
  self.assertEqual(Invoice.objects.filter(video_id=done['results']['order']).count(),1)
  (R/'composed-proof.json').write_text(json.dumps({'plan':p['id'],'PRE':t,'POST':post,'pids':pids,'controller':os.getpid(),'approval':'fixture_not_human'},indent=2))
 def test_verify_quota_and_actor_ttl_and_redaction(self):
  from gestion_joueurs.models import Player
  actor=User.objects.create(username='FICTION_QUOTA_'+uuid.uuid4().hex,is_superuser=True)
  player=Player.objects.create(name='FICTION_PRIVATE',club='CLUB',league='OC',position='MF',date_of_birth=date(2002,1,2))
  p=Engine(actor.pk).prepare(uuid.uuid4().hex,[{'as':'p','op':'player.amend','values':{'id':player.pk,'club':'NEW'}}]);configure(actor.pk,p['id'])
  code,t=call(55851,'verify',{'id':p['id'],'phase':'before'});self.assertEqual(code,200,t)
  self.assertNotIn('FICTION_PRIVATE',json.dumps(t))
  self.assertEqual(call(55851,'verify',{'id':p['id'],'phase':'before','fields':['password']})[0],400)
  cfg=json.loads((R/'http-fixture.json').read_text());cfg['credential']['expires']=(timezone.now()+timedelta(days=2)).isoformat();(R/'http-fixture.json').write_text(json.dumps(cfg))
  self.assertEqual(call(55851,'verify',{'id':p['id'],'phase':'before'})[0],403)
  configure(actor.pk,p['id'])
  cfg=json.loads((R/'http-fixture.json').read_text());cfg.update(quota_window=60,quota_identity=1);(R/'http-fixture.json').write_text(json.dumps(cfg))
  self.assertEqual(call(55851,'verify',{'id':p['id'],'phase':'before'})[0],429)

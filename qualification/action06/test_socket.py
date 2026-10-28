"""Real loopback HTTP, independent DB connections, persistent exact readback."""
import unittest,threading,json,secrets,hashlib,uuid,urllib.request
from datetime import timedelta
from socketserver import ThreadingMixIn
from wsgiref.simple_server import WSGIServer,WSGIRequestHandler,make_server
from django.core.handlers.wsgi import WSGIHandler
from django.test import override_settings
from django.utils import timezone
from django.db import connections
from django.contrib.auth.models import User
from gestion_joueurs.models import Player,Video,Invoice,VideoStatusHistory,VideoEditor,Notification
from client_portal.models import Organization,OrganizationPlayer
from actions.models import Plan,Audit
from test_actions import ActionsTests

class ThreadServer(ThreadingMixIn,WSGIServer):
    daemon_threads=True
class QuietHandler(WSGIRequestHandler):
    def log_message(self,*args):pass
class SocketTests(unittest.TestCase):
    def test_two_concurrent_execute_http_clients_and_exact_readback(self):
        uid=uuid.uuid4().hex
        self.actor=User.objects.create(username='FICTION_HTTP_'+uid,is_superuser=True,is_active=True)
        self.editor=VideoEditor.objects.create(user=self.actor)
        self.org=Organization.objects.create(name='FICTION_HTTP_'+uid,kind='agent')
        self.name='FICTION_HTTP_PLAYER_'+uid
        token=secrets.token_urlsafe(32)
        config={hashlib.sha256(token.encode()).hexdigest():{'actor':self.actor.pk,'scopes':['catalogue','prepare','execute','status','op:player.create','op:organization.link','op:video.order'],'expires':(timezone.now()+timedelta(minutes=5)).isoformat(),'revoked':False}}
        def call(op,data=None):
            req=urllib.request.Request('http://127.0.0.1:55441/actions/v1/'+op,data=None if data is None else json.dumps(data).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
            with urllib.request.urlopen(req,timeout=15) as response:return response.status,json.load(response)
        with override_settings(ACTIONS_ENABLED=True,ACTIONS_CREDENTIALS=config,ACTIONS_APPROVAL_KEY='FICTION-'+secrets.token_hex(32),ALLOWED_HOSTS=['127.0.0.1']):
            server=make_server('127.0.0.1',55441,WSGIHandler(),server_class=ThreadServer,handler_class=QuietHandler)
            service=threading.Thread(target=server.serve_forever);service.start()
            try:
                self.assertEqual(call('catalogue')[0],200)
                code,p=call('prepare',{'key':uid,'steps':ActionsTests.plan(self)})
                self.assertEqual(code,200)
                from actions.http import issue_approval
                approval=issue_approval(p['id'],self.actor.pk,p['digest'],timezone.now()+timedelta(minutes=2))
                barrier=threading.Barrier(3);results=[];errors=[]
                def execute():
                    try:
                        barrier.wait(timeout=5)
                        results.append(call('execute',{'id':p['id'],'approval':approval}))
                    except BaseException as exc:errors.append(repr(exc))
                    finally:connections.close_all()
                workers=[threading.Thread(target=execute) for _ in range(2)]
                for thread in workers:thread.start()
                barrier.wait(timeout=5)
                for thread in workers:thread.join(timeout=20)
                self.assertFalse(errors,errors);self.assertEqual(len(results),2)
                self.assertEqual(results[0],results[1]);self.assertEqual(results[0][0],200)
                result=results[0][1];self.assertEqual(result['state'],'succeeded')
                self.assertEqual(call('status',{'id':p['id']})[1],result)
                video=Video.objects.get(pk=result['results']['order']);player=Player.objects.get(pk=result['results']['p'])
                self.assertEqual(Player.objects.filter(name=self.name).count(),1)
                self.assertEqual(Video.objects.filter(player=player).count(),1)
                self.assertEqual(video.player_id,player.pk);self.assertEqual(video.editor_id,self.editor.pk)
                self.assertEqual(str(video.total_payment),'350.00');self.assertEqual(video.advance_payment,0)
                self.assertEqual(OrganizationPlayer.objects.get(pk=result['results']['link']).player_id,player.pk)
                self.assertEqual(VideoStatusHistory.objects.get(video=video).created_by_id,self.actor.pk)
                self.assertEqual(Audit.objects.filter(plan_id=p['id'],event='succeeded').count(),1)
                from django.conf import settings
                receipt={'plan':p['id'],'result':result,'player':{'id':player.pk,'name':player.name},'video':{'id':video.pk,'player':video.player_id,'editor':video.editor_id,'deadline':str(video.deadline),'price':str(video.total_payment)},'concurrent_responses':results,'single_success_audit':True}
                from pathlib import Path
                path=Path(settings.ROOT)/'evidence'/('socket-readback-'+uid+'.json');path.write_text(json.dumps(receipt,indent=2))
                print('EXACT_HTTP_READBACK',json.dumps(receipt))
            finally:
                server.shutdown();server.server_close();service.join(timeout=5)
        # Committed FICTION fixtures intentionally retained, never reset or delete.

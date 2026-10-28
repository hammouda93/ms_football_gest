"""Real loopback pilot: prepare/status durable, execute absent, business rows unchanged."""
import hashlib
import importlib.util
import json
from pathlib import Path
import secrets
import sys
import threading
import unittest
import urllib.error
import urllib.request
import uuid
from datetime import timedelta
from wsgiref.simple_server import make_server, WSGIRequestHandler
from django.core.handlers.wsgi import WSGIHandler
from django.test import override_settings
from django.utils import timezone
from django.db import connections
from django.contrib.auth.models import User
from gestion_joueurs.models import Player, Video, Invoice, VideoEditor, VideoStatusHistory
from client_portal.models import Organization, OrganizationPlayer
from actions.models import Plan, Audit
from django.conf import settings

class PilotHTTPTests(unittest.TestCase):
    def test_real_socket_plugin_prepare_status_execute_refused_and_durable_readback(self):
        uid = uuid.uuid4().hex
        actor = User.objects.create(username='FICTION_PILOT_'+uid, is_superuser=True, is_staff=True, is_active=True)
        token = secrets.token_urlsafe(32)
        credential = {'actor': actor.pk, 'scopes': ['catalogue','prepare','status','op:player.create'],
                      'expires': (timezone.now()+timedelta(minutes=5)).isoformat(), 'revoked': False}
        steps = [{'as': 'p', 'op': 'player.create', 'values': {'name':'FICTION_PILOT_PLAYER_'+uid,
                  'club':'FICTION_CLUB','league':'OC','position':'MF','date_of_birth':'2002-01-02'}}]
        models = (User, Player, Video, Invoice, VideoEditor, VideoStatusHistory, Organization, OrganizationPlayer)
        def digest():
            return hashlib.sha256(json.dumps({m._meta.label:list(m.objects.order_by('pk').values()) for m in models},default=str,sort_keys=True).encode()).hexdigest()
        before = digest()
        class Quiet(WSGIRequestHandler):
            def log_message(self,*args): pass
        root = Path(__file__).resolve().parent
        plugin_path = root/'hermes-plugin'
        spec = importlib.util.spec_from_file_location('pilot_transport_'+uid,plugin_path/'__init__.py',submodule_search_locations=[str(plugin_path)])
        plugin = importlib.util.module_from_spec(spec); sys.modules[spec.name] = plugin; spec.loader.exec_module(plugin)
        class TransportContext:
            # Transport-only CI context. Real native PluginContext separately qualified locally.
            def __init__(self): self.tools = {}
            def get_config(self,name,default=None): return {'enabled':True,'target':'lab'}.get(name,default)
            def register_hook(self,*a,**kw): pass
            def on_unload(self,*a): pass
            def register_tool(self,**kw): self.tools[kw['name']] = kw
        ctx = TransportContext()
        plugin.register(ctx, token_provider=lambda:token, approval_key_provider=lambda:self.fail('signer used'))
        def call(op,args): return json.loads(ctx.tools['ms_football_action_'+op]['handler'](args))
        middleware = [m.replace('actions.http.WriterBoundary','actions.pilot.PrepareOnlyBoundary') for m in settings.MIDDLEWARE]
        with override_settings(MIDDLEWARE=middleware,ACTIONS_ENABLED=True,ACTIONS_EXECUTE_ENABLED=True,
                               ACTIONS_CREDENTIALS={hashlib.sha256(token.encode()).hexdigest():credential},
                               ACTIONS_APPROVAL_KEY='',ALLOWED_HOSTS=['127.0.0.1'],ACTIONS_QUOTA_GLOBAL=10000,ACTIONS_QUOTA_IDENTITY=30):
            server = make_server('127.0.0.1',55441,WSGIHandler(),handler_class=Quiet)
            thread = threading.Thread(target=server.serve_forever); thread.start()
            try:
                self.assertEqual(call('catalogue',{})['status'],200)
                prepared = call('prepare',{'key':uid,'steps':steps})
                self.assertEqual(prepared['status'],200,prepared)
                plan_id = prepared['data']['id']
                self.assertEqual(call('execute',{'id':plan_id}),{'error':'execute_disabled_pilot'})
                status = call('status',{'id':plan_id})
                self.assertEqual(status['data']['state'],'prepared')
                self.assertEqual(status['data']['results'],{})
                request=urllib.request.Request('http://127.0.0.1:55441/actions/v1/execute',data=b'{}')
                with self.assertRaises(urllib.error.HTTPError) as refused: urllib.request.urlopen(request)
                self.assertEqual(refused.exception.code,403)
                self.assertEqual(json.load(refused.exception),{'error':'execute_disabled_pilot'})
            finally:
                server.shutdown(); server.server_close(); thread.join(5)
        connections.close_all()
        plan = Plan.objects.get(pk=plan_id,actor_id=actor.pk)
        self.assertEqual(plan.state,'prepared')
        self.assertEqual(plan.results,{})
        self.assertEqual(Audit.objects.filter(plan=plan,event='prepared').count(),1)
        self.assertFalse(Audit.objects.filter(plan=plan,event='succeeded').exists())
        self.assertEqual(before,digest())
        print('PILOT_HTTP_READBACK',json.dumps({'plan':str(plan.pk),'state':plan.state,'businessUnchanged':True,'executeHTTP':403,'nativeContext':False}))

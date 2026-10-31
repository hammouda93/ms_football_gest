"""Three isolated WSGI workers: PRE, execute, POST. Fixture-only controls."""
import sys,os,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parent
port=int(sys.argv[1]);assert port in (55851,55852,55853)
sys.path[:0]=[str(R),str(R/'source')]
os.environ['DJANGO_SETTINGS_MODULE']='lab_settings'
from isolation import install
install()
import django
django.setup()
from django.conf import settings
from copy import deepcopy
settings.DATABASES['verification']=deepcopy(settings.DATABASES['default'])
settings.DATABASES['verification'].update(ATOMIC_REQUESTS=False,CONN_MAX_AGE=0)
settings.ACTIONS_VERIFICATION_KEY='FICTION_UNIFIED_VERIFY_KEY_001_NOT_LIVE'
settings.ACTIONS_APPROVAL_KEY='FICTION_UNIFIED_APPROVAL_KEY_001_NOT_LIVE'
settings.ACTIONS_ENABLED=True
settings.ACTIONS_QUOTA_WINDOW_SECONDS=1
settings.ALLOWED_HOSTS=['127.0.0.1']
settings.MIDDLEWARE=[m.replace('actions.http.WriterBoundary','actions.pilot.PrepareOnlyBoundary') for m in settings.MIDDLEWARE]
from django.core.wsgi import get_wsgi_application
from wsgiref.simple_server import make_server,WSGIRequestHandler
application=get_wsgi_application()
class Quiet(WSGIRequestHandler):
 def log_message(self,*a):pass
def handler(env,start):
 cfg=json.loads((R/'http-fixture.json').read_text())
 c=cfg.get('credential',dict(actor=cfg.get('actor'),scopes=list(dict.fromkeys(['catalogue','prepare','status',*cfg.get('scopes',[])])),expires=cfg.get('expires'),revoked=False))
 settings.ACTIONS_CREDENTIALS={hashlib.sha256(b'FICTION_READBACK_TOKEN').hexdigest():c}
 settings.ACTIONS_EXECUTE_ENABLED=True
 settings.ACTIONS_EXECUTE_BINDING=cfg.get('binding',{})
 settings.ACTIONS_QUOTA_WINDOW_SECONDS=cfg.get('quota_window',1)
 settings.ACTIONS_QUOTA_IDENTITY=cfg.get('quota_identity',8)
 return application(env,start)
with make_server('127.0.0.1',port,handler,handler_class=Quiet) as server:
 server.timeout=.2
 (R/('ready-'+str(port)+'.json')).write_text(json.dumps({'pid':os.getpid(),'port':port}))
 while not (R/'stop.txt').exists():server.handle_request()

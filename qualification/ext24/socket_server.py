"""Real WSGI fixture socket. Only isolated pre-attested PostgreSQL permitted."""
from pathlib import Path
import os,sys,json
R=Path(__file__).resolve().parent;C=R/'candidate'
os.environ['DJANGO_SETTINGS_MODULE']='ci_settings';os.environ['PYTHONDONTWRITEBYTECODE']='1';sys.path[:0]=[str(C),str(C/'source')]
from ci_delta_target import install,identity
install(R,False,socket_port=55621);identity()
import django;django.setup()
from django.contrib.auth.models import User
from test_next import mounted
from actions.registry import catalogue
from django.test import override_settings
from django.core.wsgi import get_wsgi_application
from wsgiref.simple_server import make_server,WSGIRequestHandler
actor=User.objects.create(username='FICTION_SOCKET_'+__import__('uuid').uuid4().hex,is_superuser=True,is_active=True)
class Quiet(WSGIRequestHandler):
 def log_message(self,*a):pass
with override_settings(**mounted(actor.pk,set(catalogue())),ALLOWED_HOSTS=['127.0.0.1']):
 server=make_server('127.0.0.1',55621,get_wsgi_application(),handler_class=Quiet)
 print('READY',flush=True);server.serve_forever()

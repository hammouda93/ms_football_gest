"""Dedicated writer boundary. No reader credential or session fallback."""
import base64,hashlib,hmac,json
from datetime import datetime
from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction
from django.core.exceptions import ObjectDoesNotExist,ValidationError
from .engine import Engine
from .models import Plan

def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':')).encode()

def issue_approval(plan_id,actor,digest,expires):
    # Trusted approval authority only; never registered as an agent/HTTP action.
    value={'plan':str(plan_id),'actor':actor,'digest':digest,'expires':expires.isoformat()}
    raw=canonical(value)
    key=getattr(settings,'ACTIONS_APPROVAL_KEY','')
    if not isinstance(key,str) or len(key)<32:raise PermissionError('approval_unconfigured')
    return base64.urlsafe_b64encode(raw).decode()+'.'+hmac.new(key.encode(),raw,hashlib.sha256).hexdigest()

def verify_approval(token,p,actor):
    try:
        encoded,signature=token.split('.')
        raw=base64.b64decode(encoded,altchars=b'-_',validate=True)
        key=getattr(settings,'ACTIONS_APPROVAL_KEY','')
        if not isinstance(key,str) or len(key)<32:raise ValueError()
        if not hmac.compare_digest(signature,hmac.new(key.encode(),raw,hashlib.sha256).hexdigest()):raise ValueError()
        value=json.loads(raw)
        expires=datetime.fromisoformat(value['expires'])
        if timezone.is_naive(expires) or expires<=timezone.now():raise ValueError()
        if set(value)!={'plan','actor','digest','expires'} or type(value['actor']) is not int:raise ValueError()
        if Engine.proposal_digest(p.steps,p.snapshots)!=p.digest:raise ValueError()
        if (value['plan'],value['actor'],value['digest'])!=(str(p.pk),actor,p.digest):raise ValueError()
    except (ValueError,TypeError,KeyError,AttributeError):raise PermissionError('approval_invalid')

def respond(data,status=200):
    r=JsonResponse(data,status=status);r['Cache-Control']='no-store';return r

class WriterBoundary:
    def __init__(self,get_response):self.get_response=get_response
    def __call__(self,request):
        if not (request.path=='/actions' or request.path.startswith('/actions/')):return self.get_response(request)
        try:return self.dispatch(request)
        except PermissionError as e:return respond({'error':str(e)},403)
        except (ValueError,TypeError,KeyError,ValidationError):return respond({'error':'invalid_request'},400)
        except ObjectDoesNotExist:return respond({'error':'not_found'},404)
    def dispatch(self,request):
        if getattr(settings,'ACTIONS_ENABLED',False) is not True:raise PermissionError('writer_disabled')
        auth=request.META.get('HTTP_AUTHORIZATION','')
        if not auth.startswith('Bearer ') or len(auth)>256:raise PermissionError('credential_invalid')
        c=getattr(settings,'ACTIONS_CREDENTIALS',{}).get(hashlib.sha256(auth[7:].encode()).hexdigest())
        try:
            if not isinstance(c,dict) or set(c)!={'actor','scopes','expires','revoked'}:raise ValueError()
            if type(c['actor']) is not int or c['actor']<=0 or c['revoked'] is not False:raise ValueError()
            if not isinstance(c['scopes'],list) or any(type(s) is not str for s in c['scopes']):raise ValueError()
            expiry=datetime.fromisoformat(c['expires'])
            if timezone.is_naive(expiry) or expiry<=timezone.now():raise ValueError()
        except (ValueError,TypeError,KeyError):raise PermissionError('credential_invalid')
        routes={'/actions/v1/catalogue':('GET','catalogue'),'/actions/v1/prepare':('POST','prepare'),'/actions/v1/execute':('POST','execute'),'/actions/v1/status':('POST','status')}
        if request.path not in routes:return respond({'error':'not_found'},404)
        method,op=routes[request.path]
        if request.method!=method:return respond({'error':'method_not_allowed'},405)
        if op not in c['scopes']:raise PermissionError('scope_denied')
        return self.authorized_dispatch(request,c,op)
    def authorized_dispatch(self,request,c,op):
        e=Engine(c['actor']);e.authorize()
        if op=='catalogue':return respond({'catalogue':e.catalogue()})
        length=request.META.get('CONTENT_LENGTH','0')
        if not length.isdigit() or int(length)>32000:raise ValueError()
        if request.content_type!='application/json':raise ValueError()
        raw=request.body
        if len(raw)>32000:raise ValueError()
        data=json.loads(raw)
        if not isinstance(data,dict):raise ValueError()
        if op=='prepare':
            if set(data)!={'key','steps'}:raise ValueError()
            e.validate(data['steps'])
            if any('op:'+s['op'] not in c['scopes'] for s in data['steps']):raise PermissionError('scope_denied')
            result=e.prepare(data['key'],data['steps'])
            p=Plan.objects.get(pk=result['id'],actor_id=c['actor'])
            return respond(dict(result,digest=p.digest,preview=p.snapshots['__preview__'],preconditions=p.snapshots))
        import uuid
        if type(data.get('id')) is not str:raise ValueError()
        if str(uuid.UUID(data['id']))!=data['id']:raise ValueError()
        if op=='status':
            if set(data)!={'id'}:raise ValueError()
            return respond(e.status(data['id']))
        if set(data)!={'id','approval'}:raise PermissionError('approval_invalid')
        with transaction.atomic():
            p=Plan.objects.select_for_update().get(pk=data['id'],actor_id=c['actor'])
            verify_approval(data['approval'],p,c['actor'])
            e.validate(p.steps)
            if any('op:'+s['op'] not in c['scopes'] for s in p.steps):raise PermissionError('scope_denied')
            return respond(e.execute(p.pk))

class OperationalWriterBoundary(WriterBoundary):
    """Deployment boundary owns commits; library stays composable in tests."""
    def __call__(self,request):
        if not (request.path=='/actions' or request.path.startswith('/actions/')):
            return self.get_response(request)
        if getattr(settings,'ACTIONS_ENABLED',False) is not True:
            return respond({'error':'writer_disabled'},403)
        from django.db import connection
        if connection.in_atomic_block or not connection.get_autocommit():
            return respond({'error':'transaction_owned_externally'},409)
        return super().__call__(request)
    def authorized_dispatch(self,request,c,op):
        from .limits import reserve,QuotaExceeded,setting
        from django.db import DatabaseError,connection
        try:
            statement=setting('ACTIONS_STATEMENT_TIMEOUT_MS',2000,10000)
            lock=setting('ACTIONS_LOCK_TIMEOUT_MS',200,2000)
            reserve(c['actor'])
            with transaction.atomic(durable=True):
                with connection.cursor() as cursor:
                    cursor.execute("SELECT set_config('statement_timeout', %s, true),set_config('lock_timeout', %s, true)",[str(statement)+'ms',str(lock)+'ms'])
                return super().authorized_dispatch(request,c,op)
        except QuotaExceeded:
            return respond({'error':'quota_exceeded'},429)
        except DatabaseError:
            return respond({'error':'writer_unavailable'},503)


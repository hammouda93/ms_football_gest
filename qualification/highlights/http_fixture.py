"""Delta only; synthetic records, real mounted Django/PostgreSQL."""
import json,unittest,uuid,hashlib,os
from pathlib import Path
from datetime import datetime,timedelta,timezone
from copy import deepcopy
from unittest.mock import patch
from django.test import Client,override_settings
from django.conf import settings
from actions.registry import catalogue
from actions.mount import configure
R=Path(__file__).resolve().parent
NEW={'finance.highlight.payment.record','finance.performance.payment.record','finance.expense.record','finance.income.record','prospect.convert'}
TOKEN='FICTION_NEXT_BEARER';KEY='FICTION_NEXT_HMAC_NOT_HUMAN_000000000000000'

def mounted(actor,ops):
    expiry=(datetime.now(timezone.utc)+timedelta(minutes=20)).isoformat()
    credential={'actor':actor,'scopes':['catalogue','prepare','execute','status','verify']+['op:'+o for o in sorted(ops)],'expires':expiry,'revoked':False}
    env={k:os.environ[k] for k in ('SYSTEMROOT','WINDIR') if k in os.environ}
    env.update(MSF_ACTIONS_PILOT_CONFIG=json.dumps({'enabled':True,'credentials':{hashlib.sha256(TOKEN.encode()).hexdigest():credential}}),MSF_ACTIONS_EXECUTE_ENABLED='true',MSF_ACTIONS_APPROVAL_KEY=KEY,MSF_ACTIONS_EXECUTE_BINDING=json.dumps({'mode':'service','actor':actor,'operations':sorted(ops),'expires':expiry}),MSF_ACTIONS_VERIFICATION_KEY=KEY)
    ns={'INSTALLED_APPS':[a for a in settings.INSTALLED_APPS if a!='actions'],'MIDDLEWARE':['django.middleware.security.SecurityMiddleware'],'DATABASES':deepcopy(settings.DATABASES)}
    with patch.dict(os.environ,env,clear=True):configure(ns)
    return {k:v for k,v in ns.items() if k.startswith('ACTIONS_') or k=='MIDDLEWARE'}|{'ACTIONS_QUOTA_GLOBAL':10000,'ACTIONS_QUOTA_IDENTITY':10000}


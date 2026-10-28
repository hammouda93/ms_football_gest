"""Offline process guard installed before all business imports."""
import importlib.abc,os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
EVENTS=[]
def deny(kind):
    EVENTS.append(kind)
    raise PermissionError('LAB blocked '+kind)
class Excluded(importlib.abc.MetaPathFinder):
    def find_spec(self,fullname,path=None,target=None):
        if 'jarvis' in fullname.lower() or fullname.split('.')[0]=='agent_api': deny('historical integration')
def audit(event,args):
    if event in ('subprocess.Popen','os.system','os.startfile','os.posix_spawn'): deny('process')
    if event in ('socket.bind','socket.sendto') and (not isinstance(args[-1],tuple) or args[-1][:2]!=('127.0.0.1',55441)): deny('network endpoint')
    if event=='socket.connect' and args[1][:2] not in [('127.0.0.1',55440),('127.0.0.1',55441)]: deny('network')
    if event=='socket.getaddrinfo' and (args[0]!='127.0.0.1' or str(args[1]) not in ('55440','55441')): deny('dns')
    if event=='smtplib.connect': deny('smtp')
    if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
        p=Path(os.fsdecode(args[0]))
        if p.name.lower().startswith('.env') or p.name.lower()=='db.sqlite3': deny('secret file')
        mode,flags=args[1:3]
        if (isinstance(mode,str) and any(c in mode for c in 'wax+')) or (isinstance(flags,int) and flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC)):
            if ROOT not in p.resolve().parents: deny('write outside action05: '+str(p))
def install():
    import psycopg2,dotenv
    original=psycopg2.connect
    def connect(dsn=None,*args,**kw):
        from psycopg2.extensions import parse_dsn
        cfg=parse_dsn(dsn) if dsn else {}
        cfg.update(kw)
        if cfg.get('host')!='127.0.0.1' or str(cfg.get('port'))!='55440' or cfg.get('user')!='msf_action01_fixture_owner' or cfg.get('dbname',cfg.get('database'))!='msf_action03_fiction': deny('database target')
        return original(dsn,*args,**kw)
    psycopg2.connect=connect
    dotenv.load_dotenv=lambda *a,**kw:False
    dotenv.find_dotenv=lambda *a,**kw:''
    sys.meta_path.insert(0,Excluded())
    sys.addaudithook(audit)
    from celery.app.task import Task
    Task.apply_async=lambda *a,**kw:deny('celery task')

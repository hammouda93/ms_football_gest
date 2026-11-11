"""Closed fixture target; guards installed before any application import."""
from pathlib import Path
import os,sys,importlib.abc
HOST='127.0.0.1';PORT=55961;ROLE='msf_highlights_fixture';DB='msf_highlights_fiction'
def install(root,offline,socket_port=None):
 import psycopg2,dotenv
 real=psycopg2.connect
 def connect(dsn=None,*args,**kw):
  from psycopg2.extensions import parse_dsn,cursor
  # Qualify each input before merging: kwargs must not conceal DSN redirection.
  if offline or args or any(k.upper().startswith('PG') for k in os.environ):raise PermissionError('fixture DB only')
  try:parsed=parse_dsn(dsn) if dsn else {}
  except (TypeError,psycopg2.Error):raise PermissionError('fixture conninfo only') from None
  allowed={'host','port','user','dbname','database','client_encoding','cursor_factory'}
  for cfg in (parsed,kw):
   if set(cfg)-allowed:raise PermissionError('unqualified fixture DB parameter')
   if 'client_encoding' in cfg and cfg['client_encoding']!='UTF8':raise PermissionError('fixture encoding only')
   if 'cursor_factory' in cfg and cfg['cursor_factory'] is not cursor:raise PermissionError('fixture cursor only')
   if 'database' in cfg and cfg['database']!=DB:raise PermissionError('fixture DB only')
  cfg={**parsed,**kw}
  if 'database' in cfg:
   cfg['dbname']=cfg.pop('database')
  if (cfg.get('host'),str(cfg.get('port')),cfg.get('user'),cfg.get('dbname'))!=(HOST,str(PORT),ROLE,DB):raise PermissionError('fixture DB only')
  # Pass only the validated effective parameters, never the raw conninfo again.
  return real(**cfg)
 psycopg2.connect=connect;dotenv.load_dotenv=lambda *a,**k:False;dotenv.find_dotenv=lambda *a,**k:''
 class Excluded(importlib.abc.MetaPathFinder):
  def find_spec(self,fullname,path=None,target=None):
   if 'jarvis' in fullname.lower() or fullname.split('.')[0]=='agent_api':raise PermissionError('excluded integration')
 sys.meta_path.insert(0,Excluded())
 def audit(event,args):
  if event in {'subprocess.Popen','os.system','os.posix_spawn','smtplib.connect'}:raise PermissionError('external effect blocked')
  if event=='socket.connect' and (offline or args[1][:2]!=(HOST,PORT)):raise PermissionError('network blocked')
  if event=='socket.getaddrinfo' and (offline or (args[0],str(args[1])) not in {(HOST,str(PORT)),*(([(HOST,str(socket_port))]) if socket_port==55621 else [])}):raise PermissionError('DNS blocked')
  if event=='socket.sendto':raise PermissionError('network blocked')
  if event=='socket.bind' and (socket_port!=55621 or args[1][:2]!=(HOST,55621)):raise PermissionError('network blocked')
  if event=='open' and isinstance(args[0],(str,bytes,os.PathLike)):
   p=Path(os.fsdecode(args[0]))
   if p.name.lower().startswith('.env') or p.name.lower()=='db.sqlite3':raise PermissionError('secret file blocked')
 sys.addaudithook(audit)
 from celery.app.task import Task
 def deny(*a,**k):raise PermissionError('task blocked')
 Task.apply_async=deny

def identity():
 import psycopg2,json
 c=psycopg2.connect(host=HOST,port=PORT,user=ROLE,dbname=DB)
 try:
  with c.cursor() as q:
   q.execute("select current_database(),current_user,host(inet_server_addr()),inet_server_port(),current_setting('data_directory'),version()")
   row=q.fetchone()
  target=json.loads((Path(__file__).parent/'ci-target.json').read_text())
  assert row[:2]==(DB,ROLE) and row[2]==target['serverAddress'] and row[3]==target['serverPort'] and row[4].replace('\\','/')==target['dataDirectory'].replace('\\','/')
  if sys.platform=='linux':assert 'PostgreSQL 16.14' in row[5]
  return row
 finally:c.close()

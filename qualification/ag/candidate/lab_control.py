"""Only the attested disposable Linux service; no cluster lifecycle commands."""
import json,platform,sys
from pathlib import Path
from ci_target import validate
ROOT=Path(__file__).resolve().parent

def identity():
 import psycopg2
 expected=json.loads((ROOT.parent/'ci-target.json').read_text())
 assert platform.system()=='Linux' and sys.version_info[:3]==(3,10,22),'runtime identity before DB'
 c=psycopg2.connect(host='127.0.0.1',port=55440,user='msf_action01_fixture_owner',dbname='msf_action03_fiction')
 try:
  with c.cursor() as q:
   q.execute("select current_database(),current_user(),host(inet_server_addr()),inet_server_port(),current_setting('data_directory'),current_setting('server_version')".replace('current_user()','current_user'))
   row=q.fetchone()
  return validate(row,expected,platform.system(),sys.version_info[:3])
 finally:c.close()

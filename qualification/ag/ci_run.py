"""Local orchestration of existing isolated worker; never publishes."""
from pathlib import Path
import sys,os,subprocess,json,time,hashlib,re
R=Path(__file__).resolve().parent

def main():
 from verify_sources import verify
 verify()
 expected=json.loads((R/'expected-tests.json').read_text())['ids']
 E=R/('evidence-offline' if sys.argv[1:]==['offline-preflight'] else 'evidence');E.mkdir(exist_ok=False)
 env={k:v for k,v in os.environ.items() if k.lower() in {'systemroot','windir'}}
 env.update(PYTHONNOUSERSITE='1',PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
 def run(label,mode,*args):
  path=E/(label+'.log')
  with path.open('x',encoding='utf8') as f:
   p=subprocess.run([sys.executable,'-s','-B',str(R/'ci_entry.py'),mode,*args],cwd=R,env=env,stdout=f,stderr=subprocess.STDOUT,timeout=300)
  print('STAGE',label,p.returncode,hashlib.sha256(path.read_bytes()).hexdigest(),flush=True)
  text=path.read_text(encoding='utf8');print(text,flush=True)
  assert p.returncode==0,(label,p.returncode)
  return text
 if sys.argv[1:]==['offline-preflight']:
  run('offline-preflight','offline-preflight');verify();return
 assert not sys.argv[1:]
 run('migrate','migrate')
 initial=json.loads(run('fixtures-initial','fixtures').splitlines()[-1]);assert initial['superusers']==0
 records=[]
 # Preserve exact accepted ID order; retain quota window and never reset fixtures.
 groups=json.loads((R/'expected-tests.json').read_text())['batches']
 assert [x for group in groups for x in group]==expected
 for i,group in enumerate(groups):
  if i:time.sleep(61)
  text=run('batch-'+str(i),'batch',*group)
  starts=list(re.finditer(r'^(test_\S+) \(([^)]+)\) \.\.\. ',text,re.M));seen=[]
  for j,m in enumerate(starts):
   end=starts[j+1].start() if j+1<len(starts) else text.index('\n----------------------------------------------------------------------',m.end())
   events=re.findall(r'(?:^|\n)(ok|FAIL|ERROR|skipped[^\n]*)\s*$',text[m.end():end],re.M)
   record={'id':m.group(2)+'.'+m.group(1),'events':events};records.append(record);seen.append(record['id'])
   assert events==['ok'],record
  assert seen==group and '\nOK\n' in text,(seen,group)
 assert [x['id'] for x in records]==expected and len({x['id'] for x in records})==90
 readback=run('readback','readback')
 final=json.loads(run('fixtures-final','fixtures').splitlines()[-1]);assert final['superusers']==72
 verify()
 report={'ids':records,'distinct':90,'invocations':90,'passed':90,'failed':0,'skipped':0,'superusers':[0,72],'separate_process_readback':True,'readback_sha256':hashlib.sha256(readback.encode()).hexdigest()}
 (E/'result.json').write_text(json.dumps(report,indent=2));print('QUALIFICATION_RESULT',json.dumps(report))
if __name__=='__main__':main()

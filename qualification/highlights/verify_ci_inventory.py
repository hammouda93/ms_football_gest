"""Exact immutable sources plus a closed fixture-output namespace."""
from pathlib import Path,PurePosixPath
import json,hashlib,re
R=Path(__file__).resolve().parent
OUTPUTS={'ci-target.json','networks.json','offline.log','migrate.log','tests.log','readback.log','tests-result.json','readback-result.json','ATTACKED-TARGETS.jsonl','FINAL-RECEIPTS.json','SUPERSEDED-CREATE-RECEIPTS.json','FIX-FINANCIAL.json','FIX-HTTP.json','FIX-INDEPENDENT-LEDGERS.json','INDEPENDENT-READBACK.json','review-financial-observation.json'}
def verify(root=R):
 root=root.resolve()
 files=json.loads((root/'ci-inventory.json').read_text())
 for name,digest in files.items():
  rel=PurePosixPath(name)
  if rel.is_absolute() or '..' in rel.parts or '\\' in name:raise ValueError('invalid source path')
  p=root/name
  if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('CI source drift: '+name)
 receipt_count=0
 for p in root.rglob('*'):
  rel=p.relative_to(root)
  if rel.parts[0]=='.venv':continue
  if p.is_symlink():raise ValueError('unexpected symlink')
  if not p.is_file():continue
  name=rel.as_posix()
  if name in files or name=='ci-inventory.json':continue
  if len(rel.parts)==1 and name in OUTPUTS:continue
  if len(rel.parts)==1 and re.fullmatch(r'hl-[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\.json',name):
   receipt_count+=1
   if receipt_count>200:raise ValueError('fixture receipt bound')
   continue
  raise ValueError('unexpected fixture file: '+name)
 return len(files)
if __name__=='__main__':print(verify())

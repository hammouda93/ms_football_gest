from pathlib import Path
import json,hashlib
R=Path(__file__).resolve().parent
def verify():
 files=json.loads((R/'ci-inventory.json').read_text())
 for name,digest in files.items():
  p=R/name
  if p.is_symlink() or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('CI source drift: '+name)
 return len(files)
if __name__=='__main__':print(verify())

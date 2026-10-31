"""Verify immutable publication list and bytes, including this entrypoint."""
from pathlib import Path
import hashlib,json
R=Path(__file__).resolve().parent

def verify():
 root=R.parent.parent
 manifest=json.loads((R/'publication-manifest.json').read_text())
 for name,h in manifest['files'].items():
  assert not Path(name).is_absolute() and '..' not in Path(name).parts,name
  p=root/name
  assert p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest()==h,name
 allowed=set(manifest['files'])|{'qualification/ag/publication-manifest.json'}
 actual={p.relative_to(root).as_posix() for p in R.rglob('*') if p.is_file() and not set(p.relative_to(R).parts)&{'.venv','evidence','evidence-offline','__pycache__'} and p.name not in {'ci-target.json','ci-networks.json'}}
 assert actual=={n for n in allowed if n.startswith('qualification/ag/')},(actual-allowed,allowed-actual)
 print('SOURCES_VERIFIED',len(manifest['files']))
 return manifest
if __name__=='__main__':verify()

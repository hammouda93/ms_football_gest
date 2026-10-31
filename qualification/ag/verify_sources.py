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
 # Frozen tests create these exact evidence files beside their modules.
 # Never ignore an extension or arbitrary path; source hashes remain mandatory.
 generated={
  'combination-missions.json','composed-mission.json','concurrent-mission.json',
  'df01-legitimate.json','df01-refused-amend.json','df01-refused-create.json',
  'df01-revalidation.json','http-compatibility-result.json','legacy-result.json',
  'lookup-result.json','mixed-missions.json','negative-cases.json',
  'player-create-mission.json','refusal-records.jsonl','security-probe-result.json',
  'socket-result.json','unified01-records.jsonl',
 }
 evidence={'qualification/ag/candidate/'+name for name in generated}
 assert not evidence&allowed,'generated evidence overlaps immutable sources'
 for name in evidence:
  p=root/name
  assert not p.is_symlink() and (not p.exists() or p.is_file()),name
 actual={p.relative_to(root).as_posix() for p in R.rglob('*') if p.is_file() and not set(p.relative_to(R).parts)&{'.venv','evidence','evidence-offline','__pycache__'} and p.name not in {'ci-target.json','ci-networks.json'}}
 actual-=evidence
 assert actual=={n for n in allowed if n.startswith('qualification/ag/')},(actual-allowed,allowed-actual)
 print('SOURCES_VERIFIED',len(manifest['files']))
 return manifest
if __name__=='__main__':verify()

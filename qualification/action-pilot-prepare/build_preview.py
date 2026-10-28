"""Build-only exact release327 delta, private full slug and public-safe overlay."""
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import zipfile
from slug_overlay import overlay, verify
ROOT = Path(__file__).resolve().parent
PARENT = ROOT.parent
SCRATCH = Path(os.environ['HERMES_HOME']) / 'cache/scratch'
BASE = SCRATCH / 'msf-pilot-candidate-d-slug.tgz'
TARGET = SCRATCH / 'msf-action-pilot-prepare-slug.tgz'
EXPECTED = '2efa22eda672a541e7f8e10646ccb1942a3367995ca85b1498fd54500038c4ab'
def sha(value): return hashlib.sha256(value).hexdigest()
assert sha(BASE.read_bytes()) == EXPECTED
meta = json.loads((ROOT/'evidence/release327-checksum.json').read_text())
assert meta['source']['checksum'] == 'SHA256:' + EXPECTED
assert meta['releases'][0]['version'] == 327 and meta['githubLink']['auto_deploy'] is False
names = ['ms_football_gest/settings.py', 'gestion_joueurs/utils.py',
         'gestion_joueurs/middleware.py', 'gestion_joueurs/signals.py']
base_bytes = {}
with tarfile.open(BASE) as archive:
    for name in names:
        base_bytes[name] = archive.extractfile('./app/'+name).read()
settings = base_bytes[names[0]]
assert b'actions' not in settings
replacements = {'app/'+names[0]: settings + b'\n# Dedicated prepare-only pilot, closed unless strict hash-only config is present.\nfrom actions.mount import configure as _actions_configure\n_actions_configure(globals())\ndel _actions_configure\n'}
for name in names[1:]:
    replacements['app/'+name] = (PARENT/'action-06/source'/name).read_bytes()
for path in sorted((ROOT/'actions').rglob('*.py')):
    replacements['app/'+path.relative_to(ROOT).as_posix()] = path.read_bytes()
for name, body in replacements.items():
    if name.endswith('.py'): compile(body, name, 'exec')
output = ROOT/'deployment-overlay'
assert not output.exists()
for name, body in replacements.items():
    path = output/name.removeprefix('app/'); path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(body)
work = ROOT/'deployment-git'
work.mkdir()
def git(*args): return subprocess.run(['git','-C',str(work),*args],check=True,capture_output=True).stdout
git('init'); git('config','core.autocrlf','false'); git('config','user.name','Fictional candidate packager'); git('config','user.email','fixture@example.invalid')
for name, body in base_bytes.items():
    path = work/name; path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(body)
git('add','--',*names); git('commit','-m','Exact allowlisted release327 source bytes')
base_commit = git('rev-parse','HEAD').decode().strip()
for name, body in replacements.items():
    path = work/name.removeprefix('app/'); path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(body)
git('add','--',*names,'actions'); git('commit','-m','Prepare-only pilot and separately declared signal fixes')
commit = git('rev-parse','HEAD').decode().strip()
patch = git('diff','--binary',base_commit,commit)
(ROOT/'release327-to-pilot.patch').write_bytes(patch)
check = ROOT/'deployment-apply-check'
git('worktree','add','--detach',str(check),base_commit)
subprocess.run(['git','-C',str(check),'apply','--check',str(ROOT/'release327-to-pilot.patch')],check=True)
subprocess.run(['git','-C',str(check),'apply',str(ROOT/'release327-to-pilot.patch')],check=True)
for name, body in replacements.items(): assert (check/name.removeprefix('app/')).read_bytes() == body
change = overlay(BASE,TARGET,replacements)
proof = verify(BASE,TARGET,replacements)
with tarfile.open(BASE) as original, tarfile.open(TARGET) as candidate:
    a = {m.name:m for m in original}; b = {m.name:m for m in candidate}
    assert len(a) == len(set(a)) and len(b) == len(set(b))
    assert all(n == '.' or n == './app' or n.startswith('./app/') for n in b)
    reader = {n:sha(original.extractfile(m).read()) for n,m in a.items() if n.startswith('./app/data_access/') and m.isfile()}
    for name,digest in reader.items(): assert sha(candidate.extractfile(b[name]).read()) == digest
    file_count = sum(m.isfile() for m in a.values())
proof.update(baseRelease=327, baseSlug='d9f99fab-b675-457c-9b49-73b91875869e',
             baseCommit=meta['source']['commit'], baseFileCount=file_count,
             exactGitPatchApplied=True, patchSha256=sha(patch), packagingCommit=commit,
             changed=change, readerHashes=reader, readerUnchanged=True,
             changesOutsideActions=names, technicalMigrations=['actions.0001_initial','actions.0002_quotabucket'],
             note='Preview only. No upload/release/config/backup/dyno executed. Full slug private, never publish.')
(ROOT/'evidence/slug-proof.json').write_text(json.dumps(proof,indent=2),encoding='utf8')
with zipfile.ZipFile(ROOT/'pilot-preview-overlay.zip','x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name,body in replacements.items(): archive.writestr('overlay/'+name.removeprefix('app/'),body)
    archive.writestr('release327-to-pilot.patch',patch)
    archive.writestr('slug-proof.json',json.dumps(proof,indent=2))
with zipfile.ZipFile(ROOT/'pilot-preview-overlay.zip') as archive:
    assert archive.testzip() is None
    for name,body in replacements.items(): assert archive.read('overlay/'+name.removeprefix('app/')) == body
print(json.dumps({'verified': True,'baseFiles':file_count,'unchangedFiles':proof['unchangedFiles'],
                  'changedExisting':change['replaced'],'newFiles':len(change['added']),
                  'candidateSha256':proof['candidateSha256'],'overlaySha256':sha((ROOT/'pilot-preview-overlay.zip').read_bytes())}))

"""Preserve interrupted candidate evidence, then rebuild same release327 bytes locally."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parent
prior = ROOT/'evidence/prior-interrupted-candidate'
prior.mkdir(exist_ok=False)
paths = ['deployment-overlay', 'deployment-git', 'deployment-apply-check',
         'release327-to-pilot.patch', 'pilot-preview-overlay.zip', 'evidence/slug-proof.json', 'README.md']
records = {}
for name in paths:
    path = ROOT/name
    files = [path] if path.is_file() else [p for p in path.rglob('*') if p.is_file()]
    for file in files:
        records[file.relative_to(ROOT).as_posix()] = hashlib.sha256(file.read_bytes()).hexdigest()
    target = prior/name
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(target))
slug = Path(os.environ['HERMES_HOME'])/'cache/scratch/msf-action-pilot-prepare-slug.tgz'
oldslug = slug.with_name('msf-action-pilot-prepare-slug-interrupted-v1.tgz')
assert not oldslug.exists()
records[str(oldslug)] = hashlib.sha256(slug.read_bytes()).hexdigest()
slug.rename(oldslug)
(prior/'ARCHIVE-MANIFEST.json').write_text(json.dumps(records, indent=2), encoding='utf8')
result = subprocess.run([sys.executable, '-s', '-B', str(ROOT/'build_preview.py')], capture_output=True)
(ROOT/'evidence/28-rebuild-final.log').write_bytes(result.stdout+result.stderr)
print((result.stdout+result.stderr).decode('utf8', errors='replace'))
print('REAL_EXIT', result.returncode)
sys.exit(result.returncode)

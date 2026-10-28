"""Offline package preview: exact reviewed bytes, no deployment/installation."""
import hashlib
import json
from pathlib import Path
import zipfile
ROOT = Path(__file__).resolve().parent
manifest = json.loads((ROOT/'SOURCE-MANIFEST.json').read_text())
for name, record in manifest['files'].items():
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == record['sha256'], name
output = ROOT/'evidence/pilot-preview-only.zip'
with zipfile.ZipFile(output,'x',compression=zipfile.ZIP_DEFLATED) as archive:
    for name in manifest['files']:
        if name.startswith(('actions/','hermes-plugin/','deployment-overlay/')) or name == 'release327-to-pilot.patch':
            archive.write(ROOT/name,name)
with zipfile.ZipFile(output) as archive:
    assert archive.testzip() is None
    for name in archive.namelist():
        assert hashlib.sha256(archive.read(name)).hexdigest() == manifest['files'][name]['sha256']
print('PILOT_PREVIEW_PACKAGE',json.dumps({'previewOnly':True,'files':len(archive.namelist()),'sha256':hashlib.sha256(output.read_bytes()).hexdigest(),'installed':False,'deployed':False}))

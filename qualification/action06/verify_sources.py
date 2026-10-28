"""Verify every published input, including the unchanged action06 test IDs."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
manifest=json.loads((ROOT/'SOURCE-MANIFEST.json').read_text())
for name,record in manifest['files'].items():
    assert not any(x in name.lower() for x in ('jarvis','agent_api','.env','sqlite'))
    assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==record['sha256'],name
expected=json.loads((ROOT/'expected-tests.json').read_text())
assert len(expected['ids'])==len(set(expected['ids']))==61
assert len(expected['labels'])==14
print(json.dumps({'verifiedInputs':len(manifest['files']),'unchangedCandidateIDs':len(expected['ids']),'upstreamPin':manifest['upstreamPin'],'candidateCommit':manifest['candidateCommit']}))

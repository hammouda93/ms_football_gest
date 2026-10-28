"""Linux CI delta only: reuse already qualified action06 imports/fixtures."""
import json
import os
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent
OLD = ROOT.parent/'action06'
os.environ.clear()
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
(ROOT/'evidence').mkdir(exist_ok=True)
sys.path[:0] = [str(ROOT), str(OLD), str(OLD/'source')]
os.environ['DJANGO_SETTINGS_MODULE'] = 'lab_settings'
from isolation import install, EVENTS
install()
import django
django.setup()
from django.db import connection
import platform
expected = json.loads((OLD/'ci-target.json').read_text())
with connection.cursor() as cursor:
    cursor.execute("select current_database(), current_user, host(inet_server_addr()), inet_server_port(), current_setting('data_directory'), current_setting('server_version')")
    target = cursor.fetchone()
assert platform.system() == 'Linux' and sys.version_info[:3] == (3,10,22)
assert target[:2] == ('msf_action03_fiction','msf_action01_fixture_owner')
assert target[2] == expected['serverAddress'] and target[3] == 5432
assert target[4] == '/var/lib/postgresql/data' and target[5].split()[0] == '16.14'
print('PILOT_RUNTIME_TARGET',json.dumps({'python':platform.python_version(),'django':django.get_version(),'target':target}))
if sys.argv[1:] == ['migrate']:
    from django.core.management import call_command
    call_command('migrate',interactive=False,verbosity=1,run_syncdb=True)
else:
    labels = ['test_config.ConfigTests','test_boundary.BoundaryTests','test_overlay.PilotOverlayTests',
              'test_pilot_http.PilotHTTPTests','test_ci_isolation.IsolationTests']
    suite = unittest.defaultTestLoader.loadTestsFromNames(labels)
    def ids(node):
        return [i for test in node for i in ids(test)] if isinstance(node,unittest.TestSuite) else [node.id()]
    collected = ids(suite)
    assert len(collected) == len(set(collected))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    failed = {test.id() for test,trace in result.failures+result.errors}
    skipped = {test.id() for test,reason in result.skipped}
    report = {'collected':collected,'passed':sorted(set(collected)-failed-skipped),'failed':sorted(failed),
              'skipped':sorted(skipped),'run':result.testsRun,'success':result.wasSuccessful(),
              'isolationEvents':EVENTS,'sourcePolicy':'unchanged 66-test baseline retained, only affected entries replayed'}
    (ROOT/'evidence/result.json').write_text(json.dumps(report,indent=2))
    print('PILOT_QUALIFICATION_RESULT',json.dumps(report))
    sys.exit(not (result.wasSuccessful() and not skipped and result.testsRun == len(collected)))

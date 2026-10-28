import os,sys,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parent
os.environ.clear()
os.environ['PYTHONDONTWRITEBYTECODE']='1'
(ROOT/'evidence').mkdir(exist_ok=True)
sys.path[:0]=[str(ROOT),str(ROOT/'source')]
os.environ['DJANGO_SETTINGS_MODULE']='lab_settings'
from isolation import install,EVENTS
install()
import django
django.setup()
from django.db import connection
with connection.cursor() as c:
    c.execute("select current_database(),current_user,inet_server_addr()::text,inet_server_port(),current_setting('data_directory')")
    target=c.fetchone()
assert target[:2]==('msf_action03_fiction','msf_action01_fixture_owner'),target
import json,platform
expected=json.loads((ROOT/'ci-target.json').read_text())
assert platform.system()=='Linux' and sys.version_info[:3]==(3,10,22)
assert target[2].split('/')[0]==expected['serverAddress'] and target[3]==5432,target
assert target[4]=='/var/lib/postgresql/data',target
with connection.cursor() as c:
    c.execute('SHOW server_version');version=c.fetchone()[0]
assert version.split()[0]=='16.14',version
print('RUNTIME_TARGET',json.dumps({'python':platform.python_version(),'django':django.get_version(),'postgresql':version,'target':target,'isolated':True}))
if sys.argv[1:]==['migration-probe']:
    from migration_probe import run
    run()
elif sys.argv[1:]==['verify-final']:
    from verify_final import verify
    verify()
elif sys.argv[1:]==['native-server']:
    from native_server import run
    run()
elif sys.argv[1:]==['schema-effects']:
    from actions.models import Plan
    with connection.schema_editor() as editor:
        editor.add_field(Plan,Plan._meta.get_field('effects'))
elif len(sys.argv)==2 and sys.argv[1].startswith('durable-'):
    from durable_probe import run
    run(sys.argv[1][8:])
elif sys.argv[1:]==['verify-targets']:
    from verify_targets import verify
    verify()
elif sys.argv[1:]==['migrate']:
    from django.core.management import call_command
    call_command('migrate',interactive=False,verbosity=1,run_syncdb=True)
else:
    expected=json.loads((ROOT/'expected-tests.json').read_text())
    suite=unittest.defaultTestLoader.loadTestsFromNames(expected['labels']+['test_ci_isolation.IsolationTests'])
    def ids(node):
        if isinstance(node,unittest.TestSuite):
            return [i for test in node for i in ids(test)]
        return [node.id()]
    collected=ids(suite)
    assert len(collected)==len(set(collected))==66,collected
    assert set(expected['ids']).issubset(collected),collected
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    failed={test.id() for test,trace in result.failures+result.errors}
    passed=sorted(set(collected)-failed-{t.id() for t,reason in result.skipped})
    report={'collected':collected,'passed':passed,'failed':sorted(failed),'run':result.testsRun,'success':result.wasSuccessful(),'isolationEvents':EVENTS}
    (ROOT/'evidence/result.json').write_text(json.dumps(report,indent=2))
    print('QUALIFICATION_RESULT',json.dumps(report))
    sys.exit(not (result.wasSuccessful() and len(passed)==66))

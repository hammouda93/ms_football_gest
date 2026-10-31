import os,sys,unittest,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sys.path[:0]=[str(ROOT),str(ROOT/'source')]
os.environ['DJANGO_SETTINGS_MODULE']='lab_settings'
from isolation import install,EVENTS
install()
from lab_control import identity
print('IDENTITY',json.dumps(identity()))
import django
django.setup()
from django.db import connection
if sys.argv[1:]==['migrate']:
    from django.core.management import call_command
    call_command('migrate',interactive=False,verbosity=1)
else:
    from effect_audit import install as install_effect_audit, CHECKED
    if not any(name.startswith('test_unified01') for name in sys.argv[1:]):install_effect_audit()
    suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:] or ['test_integration'])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    print('EFFECT_AUDIT',json.dumps(CHECKED))
    print('ISOLATION',EVENTS)
    sys.exit(not result.wasSuccessful())

import os,sys,json,unittest
from pathlib import Path
R=Path(__file__).resolve().parent
sys.path[:0]=[str(R),str(R/'source')]
os.environ['DJANGO_SETTINGS_MODULE']='lab_settings'
from isolation import install,EVENTS
install()
from lab_control import identity
print('IDENTITY',identity(),flush=True)
import django
django.setup()
if sys.argv[1:]==['migrate']:
 from django.core.management import call_command
 call_command('migrate',interactive=False,verbosity=0)
elif sys.argv[1:]==['readback-service']:
 import readback_durable
elif sys.argv[1:]==['readback']:
 import readback
else:
 class Result(unittest.TextTestResult):
  def startTest(self,t):
   super().startTest(t);self.current=t.id()
  def addSuccess(self,t):super().addSuccess(t);events.append({'id':t.id(),'status':'success'})
  def addFailure(self,t,e):super().addFailure(t,e);events.append({'id':t.id(),'status':'failure','trace':self._exc_info_to_string(e,t)})
  def addError(self,t,e):super().addError(t,e);events.append({'id':t.id(),'status':'error','trace':self._exc_info_to_string(e,t)})
  def addSkip(self,t,reason):super().addSkip(t,reason);events.append({'id':t.id(),'status':'skip','reason':reason})
  def addSubTest(self,t,sub,e):
   super().addSubTest(t,sub,e)
   if e:events.append({'id':t.id(),'status':'subtest','trace':self._exc_info_to_string(e,t)})
 events=[]
 suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:])
 result=unittest.TextTestRunner(verbosity=2,resultclass=Result).run(suite)
 (R/os.environ.get('RESULT_FILE','events.json')).write_text(json.dumps({'events':events,'run':result.testsRun,'successful':result.wasSuccessful(),'isolation':EVENTS},indent=2))
 sys.exit(not result.wasSuccessful())

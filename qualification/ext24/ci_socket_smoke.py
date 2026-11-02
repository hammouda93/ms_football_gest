"""Exercise unchanged plugin HTTP transport against real fixture WSGI socket.
CI context is explicit fixture; native PluginContext is qualified separately locally.
"""
from pathlib import Path
import subprocess,sys,time,socket,json,importlib.util
R=Path(__file__).resolve().parent
class Context:
 def __init__(self):self.handlers={}
 def get_config(self,k,d=None):return {'enabled':True,'target':'lab','execute_enabled':False,'native_approval_enabled':False}.get(k,d)
 def on_unload(self,callback):self.unload=callback
 def register_hook(self,*a,**kw):pass # execute deliberately closed; no fabricated approval
 def register_tool(self,*a,**kw):
  name=kw.get('name',a[0] if a else None);self.handlers[name]=kw['handler']
def main():
 with (R/'socket.log').open('xb') as log:
  p=subprocess.Popen([sys.executable,'-s','-B',str(R/'socket_server.py')],stdout=log,stderr=log)
  try:
   for _ in range(200):
    with socket.socket() as s:ready=s.connect_ex(('127.0.0.1',55621))==0
    if ready:break
    assert p.poll() is None;time.sleep(.1)
   assert ready
   spec=importlib.util.spec_from_file_location('ci_fixture_plugin',R/'plugin/__init__.py',submodule_search_locations=[str(R/'plugin')]);mod=importlib.util.module_from_spec(spec);sys.modules[spec.name]=mod;spec.loader.exec_module(mod)
   ctx=Context();mod.register(ctx,token_provider=lambda:'FICTION_NEXT_BEARER')
   result=json.loads(ctx.handlers['ms_football_action_catalogue']({}));assert result['status']==200 and len(result['data']['catalogue'])==24
   assert json.loads(ctx.handlers['ms_football_action_execute']({}))=={'error':'native_approval_disabled'}
   print(json.dumps({'socket':True,'unchangedPluginTransport':True,'contracts':24,'nativeContext':False}))
  finally:p.terminate();p.wait(timeout=30)
if __name__=='__main__':main()

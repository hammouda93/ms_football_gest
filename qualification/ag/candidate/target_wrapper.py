"""Review-only compiler: exact copied files, explicit test-target literals only.
No candidate source rewrite. Assertions and guards retain identical AST shape.
"""
import ast, io, tokenize, sys, subprocess, importlib.machinery
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ORIGINAL=ROOT
MAPPING={'55572':'55440','55573':'55441','msf_unified_fixed_fixture':'msf_action01_fixture_owner','msf_unified_fixed_fiction':'msf_action03_fiction'}
MODES={'lab_control','worker','replay','run_union','readback_unified01','fixture_snapshot','extra_http','fixture_snapshot'}
def eligible(path):
 p=Path(path).resolve()
 return p.parent==ROOT and ((ORIGINAL/p.name).is_file() and p.suffix=='.py')
def adapt(source):
 edits=[]
 lines=source.splitlines(keepends=True);offsets=[0]
 for line in lines:offsets.append(offsets[-1]+len(line))
 for t in tokenize.generate_tokens(io.StringIO(source).readline):
  if t.type not in (tokenize.STRING,tokenize.NUMBER):continue
  value=t.string
  for old,new in MAPPING.items():value=value.replace(old,new)
  if value!=t.string:edits.append((offsets[t.start[0]-1]+t.start[1],offsets[t.end[0]-1]+t.end[1],value))
 result=source
 for start,end,value in reversed(edits):result=result[:start]+value+result[end:]
 class LiteralTarget(ast.NodeTransformer):
  def visit_Constant(self,node):
   if isinstance(node.value,str):
    for old,new in MAPPING.items():node.value=node.value.replace(old,new)
   elif type(node.value) is int and str(node.value) in MAPPING:node.value=int(MAPPING[str(node.value)])
   return node
 assert ast.dump(LiteralTarget().visit(ast.parse(source)),include_attributes=False)==ast.dump(ast.parse(result),include_attributes=False),'nonliteral change'
 return result
def install():
 original=importlib.machinery.SourceFileLoader.source_to_code
 def compile_source(loader,data,path,*,_optimize=-1):
  if eligible(path):data=adapt(data.decode('utf8') if isinstance(data,bytes) else data)
  return original(loader,data,path,_optimize=_optimize)
 importlib.machinery.SourceFileLoader.source_to_code=compile_source
 real_run=subprocess.run
 def run(cmd,*a,**kw):
  if isinstance(cmd,list):
   cmd=list(cmd)
   for i,value in enumerate(cmd):
    p=Path(str(value))
    if p.parent==ROOT and p.stem in MODES and p.suffix=='.py':
     cmd[i:i+1]=[str(ROOT/'target_wrapper.py'),p.stem];break
  return real_run(cmd,*a,**kw)
 subprocess.run=run
if __name__=='__main__':
 mode=sys.argv[1];assert mode in MODES
 install();path=ROOT/(mode+'.py');sys.argv=[str(path),*sys.argv[2:]]
 raw=path.read_text(encoding='utf8')
 code=adapt(raw) if eligible(path) else raw
 exec(compile(code,str(path),'exec'),{'__name__':'__main__','__file__':str(path)})

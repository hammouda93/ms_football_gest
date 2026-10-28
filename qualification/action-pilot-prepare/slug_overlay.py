"""Stream-copy a private Heroku slug with explicit reviewed additions only.
No extraction, credential parsing, runtime rebuild or secrets in manifests.
"""
import copy,hashlib,io,tarfile
from pathlib import Path,PurePosixPath

def checked(replacements):
    for n,b in replacements.items():
        if n.startswith('app/data_access/'):
            raise ValueError('Reader replacement forbidden')
        if not n.startswith('app/') or '..' in PurePosixPath(n).parts or not isinstance(b,bytes):
            raise ValueError('Invalid explicit slug overlay path')

def overlay(original,target,replacements):
    checked(replacements)
    if Path(target).exists():raise FileExistsError('Refuse slug overwrite')
    seen=set();replaced=[]
    with tarfile.open(original,'r:gz') as source,tarfile.open(target,'w:gz',compresslevel=3,format=tarfile.GNU_FORMAT) as output:
        for m in source:
            n=m.name.removeprefix('./')
            if n in seen:raise ValueError('Duplicate original archive name')
            seen.add(n)
            item=copy.copy(m)
            if n in replacements:
                if not m.isfile():raise ValueError('Replacement is not regular file')
                body=replacements[n];item.size=len(body);output.addfile(item,io.BytesIO(body));replaced.append(n)
            else:output.addfile(item,source.extractfile(m) if m.isfile() else None)
        added_dirs=set()
        for n in sorted(set(replacements)-seen):
            for parent in reversed(PurePosixPath(n).parents):
                p=str(parent)
                if p in {'.','app'} or p in seen or p in added_dirs:continue
                m=tarfile.TarInfo('./'+p);m.type=tarfile.DIRTYPE;m.mode=0o755;m.uid=0;m.gid=0;m.mtime=0
                output.addfile(m);added_dirs.add(p)
        for n,body in sorted(replacements.items()):
            if n in seen:continue
            m=tarfile.TarInfo('./'+n);m.size=len(body);m.mode=0o644;m.uid=0;m.gid=0;m.mtime=0
            output.addfile(m,io.BytesIO(body))
    return {'replaced':sorted(replaced),'added':sorted(set(replacements)-seen)}

def inventory(path):
    result={}
    with tarfile.open(path,'r:gz') as t:
        for m in t:
            n=m.name.removeprefix('./')
            if n in result:raise ValueError('Duplicate archive path')
            digest=None
            if m.isfile():
                h=hashlib.sha256();f=t.extractfile(m)
                while True:
                    block=f.read(1024*1024)
                    if not block:break
                    h.update(block)
                digest=h.hexdigest()
            result[n]={'type':m.type.decode('ascii'),'size':m.size,'mode':m.mode,'uid':m.uid,'gid':m.gid,'uname':m.uname,'gname':m.gname,'mtime':m.mtime,'linkname':m.linkname,'pax':m.pax_headers,'sha256':digest}
    return result

def verify(original,target,replacements):
    checked(replacements);a,b=inventory(original),inventory(target)
    expected_dirs=set()
    for n in set(replacements)-set(a):
        expected_dirs.update(str(p) for p in PurePosixPath(n).parents if str(p) not in {'.','app'} and str(p) not in a)
    if set(b)!=set(a)|set(replacements)|expected_dirs:raise ValueError('Unexpected archive paths')
    for n in expected_dirs:
        if b[n]['type']!='5' or b[n]['mode']!=0o755:raise ValueError('Invalid added directory')
    unchanged=0
    for n,item in a.items():
        if n not in replacements:
            if b[n]!=item:raise ValueError('Unreviewed slug entry changed: '+n)
            if item['type']=='0':unchanged+=1
        else:
            expected=dict(item,size=len(replacements[n]),sha256=hashlib.sha256(replacements[n]).hexdigest())
            if b[n]!=expected:raise ValueError('Reviewed replacement mismatch: '+n)
    for n,body in replacements.items():
        if b[n]['sha256']!=hashlib.sha256(body).hexdigest():raise ValueError('Overlay hash mismatch')
    def file_hash(path):
        result=hashlib.sha256()
        with open(path,'rb') as stream:
            for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
        return result.hexdigest()
    original_hash=file_hash(original)
    target_hash=file_hash(target)
    return {'verified':True,'originalEntries':len(a),'candidateEntries':len(b),'unchangedFiles':unchanged,'reviewedChanges':{n:hashlib.sha256(v).hexdigest() for n,v in replacements.items()},'originalSha256':original_hash,'candidateSha256':target_hash}

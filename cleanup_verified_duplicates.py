"""Remove only byte-verified inactive migration copies; never follow reparse points."""
import hashlib, os, stat, sys
from pathlib import Path
from collections import Counter
ROOT=Path(__file__).resolve().parent
state=ROOT/'state'
active=Path(r'D:\SeedanceHubData-migrated')
old=Path(r'D:\SeedanceHubData')
names=('media','assets','edits','edit_footage','voice','libtv')
skip={'248c764f09667e19b192280a.mp4','2731192f97d75558ebef4234.mp4','ba441fd9109676b0a6cb9f6c.mp4','ff2746ce007ed849e7699a58.mp4'}
delete='--delete' in sys.argv

def reparse(p):return bool(p.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
def digest(p):
 h=hashlib.sha256()
 with p.open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.digest()
def walk(root):
 stack=[root]
 while stack:
  p=stack.pop()
  try:
   if reparse(p):yield ('link',p);continue
   if p.is_dir():
    with os.scandir(p) as it: stack.extend(Path(e.path) for e in it)
   elif p.is_file():yield ('file',p)
   else:yield ('other',p)
  except OSError:yield ('error',p)

for n in names:
 if (state/n).resolve(strict=True)!=(active/n).resolve(strict=True):raise SystemExit('Unexpected active target '+n)
pairs=[(state/(n+'.before-d-migration'),active/n,n) for n in names]+[(old/n,active/n,'old-D/'+n) for n in names]
for source,dest,label in pairs:
 c=Counter();bytes_removed=0
 if not source.exists():print(label,'missing',flush=True);continue
 if reparse(source) or source.resolve()==dest.resolve():raise SystemExit('Unsafe source '+str(source))
 for kind,p in walk(source):
  if kind!='file':c[kind]+=1;continue
  if label=='edits' and p.name in skip:c['protected']+=1;continue
  q=dest/p.relative_to(source)
  try:
   # Reject links in destination path, including intermediate directories.
   cur=dest
   for part in p.relative_to(source).parts:
    cur=cur/part
    if reparse(cur):raise ValueError('reparse target')
   before=p.stat(); other=q.stat()
   if not q.is_file() or before.st_size!=other.st_size:c['different_or_missing']+=1;continue
   if digest(p)!=digest(q):c['different_or_missing']+=1;continue
   after=p.stat();other_after=q.stat()
   if (before.st_size,before.st_mtime_ns)!=(after.st_size,after.st_mtime_ns) or (other.st_size,other.st_mtime_ns)!=(other_after.st_size,other_after.st_mtime_ns):c['changed']+=1;continue
   if delete:p.unlink()
   c['verified_deleted' if delete else 'verified']+=1;bytes_removed+=before.st_size
  except (OSError,ValueError) as e:c['unreadable_or_missing']+=1
 print(label,dict(c),'bytes',bytes_removed,flush=True)
print('mode', 'delete' if delete else 'dry-run',flush=True)

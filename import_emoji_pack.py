from pathlib import Path
from PIL import Image
import zipfile, json
root=Path(__file__).resolve().parent
out=root/'static/stickers/imported';out.mkdir(exist_ok=True)
records=[]
with zipfile.ZipFile(r'C:\Users\111\Downloads\tk_emoji_gif_12.zip') as z:
 for entry in z.infolist():
  if not entry.filename.endswith('.gif') or '/' in entry.filename or '\\' in entry.filename:raise ValueError('Unexpected archive entry')
  data=z.read(entry);name='emoji_'+Path(entry.filename).stem
  dest=out/(name+'.gif')
  if dest.exists():raise FileExistsError(dest)
  dest.write_bytes(data)
  im=Image.open(dest);durations=[];frames=[]
  for i in range(im.n_frames):
   im.seek(i);durations.append(im.info.get('duration',100));frames.append(im.convert('RGBA').resize((192,192),Image.Resampling.LANCZOS))
  total=sum(durations);count=round(total/1000*30)
  sheet=Image.new('RGBA',(192*10,192*((count+9)//10)))
  for i in range(count):
   at=i*1000/30;acc=0;idx=len(frames)-1
   for j,d in enumerate(durations):
    acc+=d
    if at<acc:idx=j;break
   sheet.paste(frames[idx],((i%10)*192,(i//10)*192))
  sheet.save(out/(name+'.png'))
  records.append(dict(file=name,frames=count,ms=total,size=im.size))
print(json.dumps(records))

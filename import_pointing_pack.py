from pathlib import Path
from PIL import Image
import zipfile,json
root=Path(__file__).resolve().parent;out=root/'static/stickers/imported'
records=[]
with zipfile.ZipFile(r'C:\Users\111\Downloads\pointing_16_gif_webm.zip') as z:
 for entry in z.infolist():
  p=Path(entry.filename)
  if p.parent.as_posix()!='gif' or p.suffix!='.gif':continue
  name='pointing_'+p.stem;dest=out/(name+'.gif')
  if dest.exists():raise FileExistsError(dest)
  dest.write_bytes(z.read(entry));frames=[];durations=[]
  with Image.open(dest) as im:
   for i in range(im.n_frames):
    im.seek(i);durations.append(im.info.get('duration',100));frames.append(im.convert('RGBA').resize((192,192),Image.Resampling.LANCZOS))
  total=sum(durations);count=round(total*.03);sheet=Image.new('RGBA',(1920,192*((count+9)//10)))
  for i in range(count):
   at=i*1000/30;acc=0;idx=len(frames)-1
   for j,d in enumerate(durations):
    acc+=d
    if at<acc:idx=j;break
   sheet.paste(frames[idx],((i%10)*192,(i//10)*192))
  sheet.save(out/(name+'.png'));records.append(dict(file=name,frames=count,ms=total))
print(json.dumps(records))

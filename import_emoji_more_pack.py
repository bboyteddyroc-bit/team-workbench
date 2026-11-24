"""Import explicitly selected GIFs only; retain original archive unchanged."""
from pathlib import Path
from PIL import Image
import zipfile,json
ROOT=Path(__file__).resolve().parent
NAMES=('01_kiss','02_smirk','03_eyeroll','04_nervous','05_shy','06_dizzy','07_sick','08_freezing','09_moneyeyes','10_starstruck','11_party','12_devil','13_angel','14_pleading','15_yawn','16_speechless')
def main():
 out=ROOT/'static/stickers/imported'
 with zipfile.ZipFile(r'C:\Users\111\Downloads\emoji_16_more_gif_webm.zip') as z:
  for name in NAMES:
   for ext in ('.gif','.png'):
    if (out/('emoji_more_'+name+ext)).exists():raise FileExistsError(name+ext)
  records=[]
  for name in NAMES:
   dest=out/('emoji_more_'+name+'.gif');dest.write_bytes(z.read('gif/'+name+'.gif'))
   frames=[];durations=[]
   with Image.open(dest) as im:
    for i in range(im.n_frames):
     im.seek(i);durations.append(im.info.get('duration',100));frames.append(im.convert('RGBA').resize((192,192),Image.Resampling.LANCZOS))
   total=sum(durations);count=round(total*30/1000)
   sheet=Image.new('RGBA',(1920,192*((count+9)//10)))
   for i in range(count):
    at=i*1000/30;acc=0;idx=len(frames)-1
    for j,d in enumerate(durations):
     acc+=d
     if at<acc:idx=j;break
    sheet.paste(frames[idx],(i%10*192,i//10*192))
   sheet.save(dest.with_suffix('.png'))
   records.append(dict(name=name,frames=count,duration_ms=total))
 print(json.dumps(records))
if __name__=='__main__':main()

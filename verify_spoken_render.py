import tempfile, subprocess, shutil
from pathlib import Path
from PIL import Image
from editor import write_ass
caption={'text':'HELLO WORLD','start':0,'end':2,'font':'default','size':200,'anim':{'loop':{'id':'spoken','color':'#ff0000'}},'words':[{'text':'HELLO','from':0,'to':5,'start':.3,'end':.8},{'text':'WORLD','from':6,'to':11,'start':1.1,'end':1.6}]}
with tempfile.TemporaryDirectory() as temp:
    path=Path(temp);write_ass(path/'test.ass',[caption],720,480)
    def red(t):
        image=path/(str(t)+'.png')
        subprocess.run([shutil.which('ffmpeg'),'-v','error','-y','-f','lavfi','-i',f'color=black:s=720x480:r=25:d=2', '-vf',f"ass=filename='test.ass'",'-ss',str(t),'-frames:v','1',str(image)],cwd=path,check=True)
        im=Image.open(image).convert('RGB')
        return sum(1 for r,g,b in im.getdata() if r>150 and g<100 and b<100)
    values=[red(t) for t in (.1,.5,.95,1.3,1.8)]
    print('red pixels before / first / pause / second / after:',values)
    assert values[0]<5 and values[1]>30 and values[2]<5 and values[3]>30 and values[4]<5

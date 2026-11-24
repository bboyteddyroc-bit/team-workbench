"""Validated per-clip colour grading and a shared selective HSL 3D LUT."""
import colorsys
import math

CHANNELS=('red','orange','yellow','green','cyan','blue','purple','magenta')
CENTRES=(0,30,60,120,180,240,270,315)
BASIC=('brightness','contrast','saturation')

def validate(raw):
    if raw is None:return {}
    if not isinstance(raw,dict):raise ValueError('调色参数无效')
    if not raw:return {}
    def val(v):
        if isinstance(v,bool):raise ValueError('调色参数无效')
        try:n=float(v)
        except (ValueError,TypeError):raise ValueError('调色参数无效') from None
        if not math.isfinite(n) or not -100<=n<=100:raise ValueError('调色参数范围为 -100 至 100')
        return round(n,2)
    result={k:val(raw.get(k,0)) for k in BASIC}
    hsl=raw.get('hsl',{})
    if not isinstance(hsl,dict):raise ValueError('HSL 参数无效')
    result['hsl']={}
    for key in CHANNELS:
        c=hsl.get(key,{})
        if not isinstance(c,dict):raise ValueError('HSL 参数无效')
        result['hsl'][key]={k:val(c.get(k,0)) for k in ('h','s','l')}
    return result

def transform(r,g,b,adjust):
    h,l,s=colorsys.rgb_to_hls(r,g,b); hue=h*360
    dh=ds=dl=0
    for key,centre in zip(CHANNELS,CENTRES):
        c=adjust.get('hsl',{}).get(key,{})
        distance=abs((hue-centre+180)%360-180)
        weight=max(0,1-distance/45)*min(1,s*8)
        dh+=weight*c.get('h',0)*.6;ds+=weight*c.get('s',0)/100;dl+=weight*c.get('l',0)/200
    h=(h+dh/360)%1;s=max(0,min(1,s*(1+ds)));l=max(0,min(1,l+dl))
    r,g,b=colorsys.hls_to_rgb(h,l,s)
    sat=1+adjust.get('saturation',0)/100;contrast=1+adjust.get('contrast',0)/100;bright=adjust.get('brightness',0)/200
    grey=.2126*r+.7152*g+.0722*b
    return tuple(max(0,min(1,((grey+(v-grey)*sat)-.5)*contrast+.5+bright)) for v in (r,g,b))

def write_lut(path,adjust,size=33):
    with open(path,'w',encoding='ascii',newline='\n') as f:
        f.write(f'LUT_3D_SIZE {size}\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n')
        for b in range(size):
            for g in range(size):
                for r in range(size):
                    f.write('%.6f %.6f %.6f\n'%transform(r/(size-1),g/(size-1),b/(size-1),adjust))

def enabled(adjust):
    return any(adjust.get(k,0) for k in BASIC) or any(any(v.values()) for v in adjust.get('hsl',{}).values())

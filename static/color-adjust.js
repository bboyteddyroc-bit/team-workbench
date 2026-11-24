'use strict';
window.HubColor=(()=>{
  const channels=['red','orange','yellow','green','cyan','blue','purple','magenta'],centres=[0,30,60,120,180,240,270,315],size=33;
  const clamp=x=>Math.min(1,Math.max(0,x));
  function transform(r,g,b,a){
    let max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min,l=(max+min)/2,s=d?(l>.5?d/(2-max-min):d/(max+min)):0,h=0;
    if(d){if(max===r)h=((g-b)/d+(g<b?6:0))/6;else if(max===g)h=((b-r)/d+2)/6;else h=((r-g)/d+4)/6;}
    let dh=0,ds=0,dl=0;channels.forEach((key,i)=>{let c=a.hsl?.[key]||{},dist=Math.abs(((h*360-centres[i]+540)%360)-180),w=Math.max(0,1-dist/45)*Math.min(1,s*8);dh+=w*(c.h||0)*.6;ds+=w*(c.s||0)/100;dl+=w*(c.l||0)/200;});
    h=((h+dh/360)%1+1)%1;s=clamp(s*(1+ds));l=clamp(l+dl);
    function hue(p,q,t){t=(t+1)%1;if(t<1/6)return p+(q-p)*6*t;if(t<.5)return q;if(t<2/3)return p+(q-p)*(2/3-t)*6;return p;}
    if(s){let q=l<.5?l*(1+s):l+s-l*s,p=2*l-q;r=hue(p,q,h+1/3);g=hue(p,q,h);b=hue(p,q,h-1/3);}else r=g=b=l;
    const gray=.2126*r+.7152*g+.0722*b,sat=1+(a.saturation||0)/100,con=1+(a.contrast||0)/100,br=(a.brightness||0)/200;
    return [r,g,b].map(v=>Math.round(clamp((gray+(v-gray)*sat-.5)*con+.5+br)*255));
  }
  let signature='',lut=null;
  function apply(ctx,w,h,a){
    if(!a||!Object.values(a).some(v=>typeof v==='number'?v!==0:Object.values(v||{}).some(x=>Object.values(x).some(Boolean))))return;
    if(window.HubColorGPU?.apply(ctx,w,h,a))return;
    let key=JSON.stringify(a);if(key!==signature){signature=key;lut=new Uint8ClampedArray(size*size*size*3);for(let b=0;b<size;b++)for(let g=0;g<size;g++)for(let r=0;r<size;r++){let i=((b*size+g)*size+r)*3;lut.set(transform(r/(size-1),g/(size-1),b/(size-1),a),i);}}
    let image=ctx.getImageData(0,0,w,h),p=image.data;
    for(let i=0;i<p.length;i+=4){let r=p[i]*32/255,g=p[i+1]*32/255,b=p[i+2]*32/255,ri=Math.min(31,r|0),gi=Math.min(31,g|0),bi=Math.min(31,b|0),fr=r-ri,fg=g-gi,fb=b-bi,base=((bi*size+gi)*size+ri)*3;
      for(let c=0;c<3;c++){let z=0;for(let db=0;db<2;db++)for(let dg=0;dg<2;dg++)for(let dr=0;dr<2;dr++)z+=lut[base+(db*size*size+dg*size+dr)*3+c]*(db?fb:1-fb)*(dg?fg:1-fg)*(dr?fr:1-fr);p[i+c]=z;}}
    ctx.putImageData(image,0,0);
  }
  return {apply,transform,channels};
})();

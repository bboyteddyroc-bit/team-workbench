/* Original GSAP gallery; no React Bits Pro source or dependency. */
'use strict';
document.addEventListener('DOMContentLoaded',()=>{
 const host=document.getElementById('home-stage'),page=document.getElementById('home');if(!host)return;
 const reduced=matchMedia('(prefers-reduced-motion: reduce)');
 const specs=[['materials','素材管理','COLLECTION',0,62,471,301,330,260],['studio','制作台','ZERO TO ONE',0,388,370,534,403,440],['editor','剪辑台','SHAPING TIME',0,943,273,285,528,270],['intelligence','竞对与脚本','INSIGHT TO STORY',0,1254,402,344,399,300],['accounts','公司账号池','CONNECTED ENERGY',1,37,521,335,451,270],['members','团队成员','IN HARMONY',1,414,521,333,451,300],['audit','操作记录','EVERY TRACE',1,789,521,334,451,250],['storage','存储管理','KEEP THE MOMENT',1,1165,521,336,451,300]];
 host.replaceChildren();const rail=document.createElement('div');rail.className='gallery-rail';host.append(rail);
 let cards=[],items=[],active=0,drag=null,suppress=false,signature='';
 const clamp=(x,a,b)=>Math.max(a,Math.min(b,x));
 const motion={x:0};let period=0;
 function paint(){if(!period)return;const wrapped=((motion.x%period)+period)%period;rail.style.transform=`translate3d(${-period+wrapped}px,0,0)`;}
 function measure(){if(cards.length>=items.length*2){period=cards[items.length].offsetLeft-cards[0].offsetLeft;paint();}}
 function select(index){if(!cards.length)return;const target=cards[(index+cards.length)%cards.length];target.focus({preventScroll:true});motion.x=-(target.offsetLeft-cards[0].offsetLeft);paint();}
 function build(){const visible=specs.filter(m=>{const nav=document.querySelector('.sidebar [data-view="'+m[0]+'"]');return nav&&!nav.hidden;});const key=visible.map(m=>m[0]).join();if(key===signature)return;signature=key;items=visible;rail.replaceChildren();cards=[...items,...items,...items].map((m,i)=>{const b=document.createElement('button');b.type='button';b.className='gallery-poster';b.style.setProperty('--poster-width',m[8]+'px');b.style.setProperty('--poster-offset',[90,28,0,60,30,80,10,55][i%items.length]+'px');const art=document.createElement('span');art.className='gallery-art';art.style.aspectRatio=['3/4','3/5','4/5','3/4','3/4','3/4','3/4','3/4'][specs.indexOf(m)];const idx=specs.indexOf(m);art.style.setProperty('--scene-position',`${idx%4*100/3}% ${idx<4?0:100}%`);const base=document.createElement('span');base.className='gallery-scene gallery-scene-base';const color=document.createElement('span');color.className='gallery-scene gallery-scene-color';color.setAttribute('aria-hidden','true');art.append(base,color);const title=document.createElement('strong');title.textContent=m[1];const label=document.createElement('small');label.textContent=String(i%items.length+1).padStart(2,'0')+' / '+m[2];b.append(art,title,label);b.onclick=()=>{if(!suppress)navigate(m[0]);};b.onkeydown=e=>{if(['ArrowRight','ArrowLeft','Home','End'].includes(e.key)){e.preventDefault();select(e.key==='Home'?items.length:e.key==='End'?items.length*2-1:i+(e.key==='ArrowRight'?1:-1));}};b.onpointermove=e=>{if(drag||reduced.matches||e.pointerType==='touch'||!window.gsap)return;const r=b.getBoundingClientRect();gsap.to(art,{rotationY:((e.clientX-r.left)/r.width-.5)*9,rotationX:-((e.clientY-r.top)/r.height-.5)*7,y:-7,duration:.3,overwrite:true,transformPerspective:900});};b.onpointerleave=()=>window.gsap?.to(art,{rotationX:0,rotationY:0,y:0,duration:.45,overwrite:true});rail.append(b);return b;});motion.x=0;requestAnimationFrame(measure);}
 function enter(){build();if(!page.hidden&&window.gsap&&!reduced.matches){gsap.killTweensOf(cards);gsap.fromTo(cards,{opacity:0,y:28},{opacity:1,y:0,duration:.7,stagger:.07,ease:'power3.out',clearProps:'opacity,transform'});}}
 host.onpointerdown=e=>{if(e.button!==0)return;window.gsap?.killTweensOf(motion);suppress=false;drag={id:e.pointerId,x:e.clientX,start:motion.x,last:e.clientX,time:performance.now(),v:0,moved:false};};
 host.onpointermove=e=>{if(!drag||drag.id!==e.pointerId)return;const dx=e.clientX-drag.x;if(!drag.moved&&Math.abs(dx)<7)return;drag.moved=true;suppress=true;host.setPointerCapture(e.pointerId);motion.x=drag.start+dx*1.6;paint();const now=performance.now();drag.v=(e.clientX-drag.last)/Math.max(1,now-drag.time);drag.last=e.clientX;drag.time=now;};
 function release(e){if(!drag||drag.id!==e.pointerId)return;const d=drag;drag=null;if(host.hasPointerCapture(e.pointerId))host.releasePointerCapture(e.pointerId);if(d.moved&&e.type!=='pointercancel'&&window.gsap&&!reduced.matches){const velocity=performance.now()-d.time<100?clamp(d.v,-8,8):0;gsap.to(motion,{x:motion.x+velocity*420,duration:1.1,ease:'power3.out',onUpdate:paint,overwrite:true});}setTimeout(()=>suppress=false,0);}
 host.onpointerup=release;host.onpointercancel=release;host.onlostpointercapture=release;
 host.addEventListener('wheel',e=>{if(Math.abs(e.deltaX)>Math.abs(e.deltaY)||e.shiftKey){e.preventDefault();window.gsap?.killTweensOf(motion);motion.x-=e.deltaX||e.deltaY;paint();}},{passive:false});
 new ResizeObserver(measure).observe(host);
 // Drift only while visible and idle; never compete with dragging or inertia.
 let hovered=false,keyboardFocus=false,lastFrame=0,frame=0;
 host.addEventListener('pointerover',e=>{if(e.pointerType!=='touch')hovered=!!e.target.closest('.gallery-art');});
 host.addEventListener('pointerout',e=>{if(e.pointerType!=='touch')hovered=!!(e.relatedTarget instanceof Element&&host.contains(e.relatedTarget)&&e.relatedTarget.closest('.gallery-art'));});
 host.addEventListener('pointerleave',()=>{hovered=false;});
 host.addEventListener('focusin',e=>{keyboardFocus=e.target.matches(':focus-visible');});
 host.addEventListener('focusout',e=>{if(!host.contains(e.relatedTarget))keyboardFocus=false;});
 function drift(now){
   frame=0;
   if(page.hidden||document.hidden||reduced.matches){lastFrame=0;return;}
   const dt=lastFrame?Math.min(now-lastFrame,50):0;lastFrame=now;
   if(period&&!hovered&&!keyboardFocus&&!drag&&!window.gsap?.isTweening(motion)){
     motion.x-=dt*.035;paint();
   }
   frame=requestAnimationFrame(drift);
 }
 function syncDrift(){if(frame)cancelAnimationFrame(frame);frame=0;lastFrame=0;if(!page.hidden&&!document.hidden&&!reduced.matches)frame=requestAnimationFrame(drift);}
 new MutationObserver(syncDrift).observe(page,{attributes:true,attributeFilter:['hidden']});
 document.addEventListener('visibilitychange',syncDrift);
 reduced.addEventListener('change',syncDrift);
 syncDrift();
 new MutationObserver(()=>{if(page.hidden){window.gsap?.killTweensOf([motion,...cards]);drag=null;}else {enter();requestAnimationFrame(measure);}}).observe(page,{attributes:true,attributeFilter:['hidden']});
 new MutationObserver(build).observe(document.querySelector('.sidebar'),{subtree:true,attributes:true,attributeFilter:['hidden']});
 reduced.addEventListener('change',()=>{window.gsap?.killTweensOf([motion,...cards]);cards.forEach(c=>{c.style.opacity='';c.style.transform='';window.gsap?.set(c.firstChild,{rotationX:0,rotationY:0,y:0});});});
 enter();
});

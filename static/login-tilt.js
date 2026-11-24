/* Native adaptation of beui.dev/components/motion/tilt-card.
 * Keep the existing form DOM and authentication bindings intact. */
(()=>{
  const auth=document.getElementById('auth'),card=auth?.querySelector('.auth-card');
  if(!card)return;
  const motion=matchMedia('(prefers-reduced-motion: reduce)'),hover=matchMedia('(hover: hover) and (pointer: fine)');
  const glare=document.createElement('div');glare.className='login-tilt-glare';glare.setAttribute('aria-hidden','true');card.append(glare);
  let x=0,y=0,tx=0,ty=0,raf=0,last=0;
  const enabled=()=>!motion.matches&&hover.matches&&!auth.hidden&&!document.hidden&&!card.contains(document.activeElement);
  function paint(now){
    raf=0;const dt=Math.min(50,now-last||16);last=now;
    const mix=1-Math.exp(-dt/85);x+=(tx-x)*mix;y+=(ty-y)*mix;
    card.style.setProperty('--tilt-x',x+'deg');card.style.setProperty('--tilt-y',y+'deg');
    if(Math.abs(tx-x)+Math.abs(ty-y)>.005)raf=requestAnimationFrame(paint);
  }
  function update(){if(!raf){last=performance.now();raf=requestAnimationFrame(paint);}}
  function reset(immediate=false){tx=ty=0;glare.style.opacity='0';if(immediate){cancelAnimationFrame(raf);raf=0;x=y=0;card.style.setProperty('--tilt-x','0deg');card.style.setProperty('--tilt-y','0deg');}else update();}
  card.addEventListener('pointermove',e=>{
    if(!enabled()||e.pointerType==='touch')return;
    const r=card.parentElement.getBoundingClientRect(),px=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width)),py=Math.max(0,Math.min(1,(e.clientY-r.top)/r.height));
    tx=(.5-py)*8;ty=(px-.5)*8;
    glare.style.background=`radial-gradient(circle at ${px*100}% ${py*100}%, #bdeff5, transparent 55%)`;glare.style.opacity='.12';update();
  });
  card.addEventListener('pointerleave',()=>reset());
  card.addEventListener('focusin',()=>reset(true));
  motion.addEventListener('change',()=>reset(true));hover.addEventListener('change',()=>reset(true));
  document.addEventListener('visibilitychange',()=>reset(true));
  new MutationObserver(()=>reset(true)).observe(auth,{attributes:true,attributeFilter:['hidden']});
})();

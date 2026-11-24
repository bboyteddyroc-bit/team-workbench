'use strict';
// Only opt-in card previews. Timeline/source playback pools must not use this helper.
window.hubMediaLazy=(()=>{
 const pending=new Set();
 const visible=m=>m.isConnected&&m.getClientRects().length>0&&!m.closest('[hidden]');
 function activate(m){if(!pending.has(m)||!visible(m))return false;pending.delete(m);observer?.unobserve(m);m.preload=m.dataset.cardPreload||'metadata';m.src=m.dataset.cardSrc;delete m.dataset.cardSrc;delete m.dataset.cardPreload;if(m.tagName!=='IMG')m.load();return true;}
 const observer=typeof IntersectionObserver==='function'?new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting)activate(e.target);},{rootMargin:'160px 0px'}):null;
 function watch(m,url,preload='metadata'){
  m.preload='none';m.setAttribute('loading','lazy');m.dataset.cardSrc=url;m.dataset.cardPreload=preload;
  // Keep a stable intrinsic box before metadata arrives; CSS continues controlling card size.
  if(m.tagName==='VIDEO'){m.width=640;m.height=360;}
  pending.add(m);observer?.observe(m);
  for(const event of ['pointerdown','focus'])m.addEventListener(event,()=>activate(m),{once:true});
  if(!observer){m.src=url;m.preload='none';pending.delete(m);delete m.dataset.cardSrc;delete m.dataset.cardPreload;}
  return m;
 }
 function sweep(){for(const m of pending)if(!m.isConnected){pending.delete(m);observer?.unobserve(m);}}
 function visibility(){sweep();document.querySelectorAll('.view[hidden] video,.view[hidden] audio').forEach(m=>{if(!m.paused)m.pause();});}
 function watchImage(img,url){img.decoding='async';img.loading='lazy';return watch(img,url,'none');}
 return {watch,watchImage,visibility,sweep};
})();

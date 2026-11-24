/* Creator pass entrance; existing server authentication remains authoritative. */
(()=>{
 const init=()=>{const auth=document.getElementById('auth');if(!auth)return;const form=auth.querySelector('.auth-form');auth.classList.add('pass-login');
 const scene=document.createElement('div');scene.className='pass-scene';scene.innerHTML=`<div class="pass-card-window"><button type="button" class="creator-pass" aria-label="刷创作通行证，打开登录"><span class="pass-name">CREATOR PASS</span><svg viewBox="0 0 600 350" aria-hidden="true"><defs><linearGradient id="pass-paper" x2="0.7" y2="1"><stop stop-color="#ffffff"/><stop offset="1" stop-color="#dce1e0"/></linearGradient><linearGradient id="pass-ink"><stop stop-color="#292f31"/><stop offset="1" stop-color="#586164"/></linearGradient><linearGradient id="pass-cyan"><stop stop-color="#157b8d"/><stop offset="1" stop-color="#23b7ca"/></linearGradient></defs><path d="M0 305C190 120 320 115 600 228L600 292C310 172 160 248 0 350Z" fill="url(#pass-ink)"/><path d="M80 350C240 290 310 100 600 90L600 152C350 128 300 310 200 350Z" fill="url(#pass-paper)"/><path d="M180 350C320 250 350 45 600 20L600 90C390 123 320 294 240 350Z" fill="url(#pass-cyan)"/></svg><span class="pass-bottom"><span class="pass-barcode" aria-hidden="true"></span><small>001</small></span></button></div><div class="pass-reader" aria-hidden="true"><span class="pass-slot"></span><span class="pass-display">READY</span><i></i></div><p class="pass-hint" aria-live="polite">拖动卡片，开始创作</p><button type="button" class="pass-feishu">飞书登录</button><button type="button" class="pass-skip">直接登录</button>`;auth.prepend(scene);
 const card=scene.querySelector('.creator-pass'),display=scene.querySelector('.pass-display'),hint=scene.querySelector('.pass-hint'),reader=scene.querySelector('.pass-reader'),slot=scene.querySelector('.pass-slot');
 let drag=null,opened=false,timer=0,animation=null,version=0,suppressClickUntil=0;
 const reduce=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
 function showForm(){auth.classList.add('pass-open');form.inert=false;card.disabled=true;card.style.opacity='0';display.textContent='VERIFY';hint.textContent='';form.querySelector('input')?.focus();}
 async function open(skip=false){
  if(opened)return;opened=true;const run=++version;reader.classList.remove('pass-near');
  if(skip||reduce()){showForm();return;}
  const current=getComputedStyle(card).transform;
  const sr=card.parentElement.getBoundingClientRect(),r=slot.getBoundingClientRect();
  const w=card.offsetWidth,h=card.offsetHeight;
  const scale=Math.min(1,(r.width-16)/w);
  const x=r.left+r.width/2-(sr.left+card.offsetLeft+w/2);
  const top=sr.top+card.offsetTop+h*(1-scale)/2;
  const draggedY=parseFloat(card.style.getPropertyValue('--drag-y'))||0;
  const startY=Math.max(r.top-top-h*scale-5,draggedY),endY=r.top-top+2;
  const transform=y=>'translate('+x+'px,'+y+'px) rotate(0deg) scale('+scale+')';
  card.parentElement.classList.add('pass-docked');card.classList.add('pass-inserting');display.textContent='ALIGN';hint.textContent='';
  try{
   animation=card.animate([{transform:current,clipPath:'inset(0 0 0 0)'},{transform:transform(startY),clipPath:'inset(0 0 0 0)'}],{duration:300,easing:'cubic-bezier(.2,.8,.2,1)',fill:'forwards'});await animation.finished;
   if(run!==version)return;
   card.style.transform=transform(startY);animation.cancel();
   display.textContent='READING';reader.classList.add('pass-reading');
   // The stationary window ends at the slot; the moving card is clipped by it.
   animation=card.animate([{transform:transform(startY)},{transform:transform(endY)}],{duration:1000,easing:'cubic-bezier(.35,0,.3,1)',fill:'forwards'});await animation.finished;
   if(run===version){reader.classList.remove('pass-reading');showForm();}
  }catch(error){if(run===version){reader.classList.remove('pass-reading');showForm();}}
 }
 card.onclick=()=>{if(performance.now()>suppressClickUntil)open();};scene.querySelector('.pass-skip').onclick=()=>open(true);
 scene.querySelector('.pass-feishu').onclick=()=>{const login=document.getElementById('feishu-login');if(login)login.click();else open(true);};
 function nearSlot(){const c=card.getBoundingClientRect(),r=slot.getBoundingClientRect();return c.bottom>=r.top-12&&c.top<r.bottom&&c.left>=r.left+3&&c.right<=r.right-3;}
 card.addEventListener('pointerdown',e=>{if(e.button!==0||opened)return;const c=card.getBoundingClientRect(),r=slot.getBoundingClientRect();drag={id:e.pointerId,x:e.clientX,y:e.clientY,base:c,slot:r};card.setPointerCapture(e.pointerId);card.classList.add('pass-dragging');});
 card.addEventListener('pointermove',e=>{
  if(!drag||drag.id!==e.pointerId)return;
  const c=drag.base,r=drag.slot;
  let dx=Math.max(-180,Math.min(180,e.clientX-drag.x)),dy=Math.max(-100,Math.min(c.height,e.clientY-drag.y));
  const center=r.left+r.width/2-(c.left+c.width/2);
  const distanceY=Math.abs(r.top-(c.bottom+dy)),distanceX=Math.abs(dx-center);
  // The magnet strength rises continuously as the badge approaches the reader.
  const t=Math.max(0,Math.min(1,(100-distanceY)/100))*Math.max(0,Math.min(1,(130-distanceX)/130));
  const strength=t*t*(3-2*t)*.7;
  dx+=(center-dx)*strength;
  const near=distanceY<55&&distanceX<100;drag.near=near;
  card.style.setProperty('--drag-x',dx+'px');card.style.setProperty('--drag-y',dy+'px');
  reader.classList.toggle('pass-near',near);display.textContent=near?'INSERT':'READY';
 });
 function release(e){if(!drag||drag.id!==e.pointerId)return;const distance=Math.hypot(e.clientX-drag.x,e.clientY-drag.y),accept=e.type!=='pointercancel'&&distance>8&&!!drag.near;drag=null;card.classList.remove('pass-dragging');if(card.hasPointerCapture(e.pointerId))card.releasePointerCapture(e.pointerId);if(distance>8||e.type==='pointercancel')suppressClickUntil=performance.now()+500;if(accept){open();}else{card.parentElement.classList.remove('pass-docked');card.style.removeProperty('--drag-x');card.style.removeProperty('--drag-y');reader.classList.remove('pass-near');display.textContent='READY';}}
 card.addEventListener('pointerup',release);card.addEventListener('pointercancel',release);
 window.hubLoginPass={complete:async()=>{if(auth.hidden)return;display.textContent='SUCCESS';hint.textContent='';auth.classList.add('pass-success');if(!matchMedia('(prefers-reduced-motion: reduce)').matches)await new Promise(resolve=>setTimeout(resolve,650));}};
 function reset(){if(auth.hidden)return;clearTimeout(timer);version++;animation?.cancel();animation=null;drag=null;opened=false;card.style.removeProperty('transform');card.style.removeProperty('opacity');card.style.removeProperty('--drag-x');card.style.removeProperty('--drag-y');card.parentElement.classList.remove('pass-docked');card.classList.remove('pass-inserting','pass-dragging');reader.classList.remove('pass-near','pass-reading');auth.classList.remove('pass-open','pass-success');card.classList.remove('pass-swiping');card.disabled=false;form.inert=true;display.textContent='READY';hint.textContent='拖动卡片，开始创作';}
 new MutationObserver(()=>{if(auth.hidden){clearTimeout(timer);version++;animation?.cancel();form.inert=false;}else reset();}).observe(auth,{attributes:true,attributeFilter:['hidden']});
 new MutationObserver(()=>{if(document.getElementById('auth-error').textContent)display.textContent='RETRY';}).observe(document.getElementById('auth-error'),{childList:true,subtree:true});
 document.getElementById('login-form').addEventListener('submit',()=>{display.textContent='VERIFY';});reset();
 };if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();

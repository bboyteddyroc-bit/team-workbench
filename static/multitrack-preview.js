'use strict';
window.hubMultitrackPreview=(()=>{
  const stage=document.getElementById('edit-stage'),canvas=document.createElement('canvas');canvas.id='multitrack-canvas';stage.prepend(canvas);
  const context=canvas.getContext('2d'),pool=new Map();let current=null,time=0,running=false;
  const active=(body,t)=>body.clips.map((c,i)=>({c,i})).filter(({c})=>t>=c.at-1e-7&&t<c.at+HubTimeline.length(c)-1e-7);
  const top=(body,t)=>active(body,t).sort((a,b)=>body.tracks.findIndex(x=>x.id===a.c.track)-body.tracks.findIndex(x=>x.id===b.c.track)||b.i-a.i)[0];
  function draw(force=false){
    if(!current)return;const item=top(current,time),v=item&&pool.get(item.i);
    if(item&&(!v||v.readyState<2||v.seeking))return; // Keep the last decoded frame while buffering a contiguous cut.
    // Render playback at half resolution to reduce per-frame canvas and color work;
    // scrubbing and paused frames retain the original resolution. Export is separate.
    const sizes=running?{'9:16':[360,640],'16:9':[640,360],'1:1':[360,360]}:{'9:16':[720,1280],'16:9':[1280,720],'1:1':[720,720]};
    const [w,h]=sizes[current.ratio];
    // Playback counters can stall or update out of step with decoded frames. Always paint while playing.
    if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}
    context.fillStyle='#000';context.fillRect(0,0,w,h);
    if(v){const scale=Math.min(w/v.videoWidth,h/v.videoHeight),dw=v.videoWidth*scale,dh=v.videoHeight*scale;context.drawImage(v,(w-dw)/2,(h-dh)/2,dw,dh);window.HubColor?.apply(context,w,h,item.c.color);}
    window.hubStickers?.draw(context,current,time,w,h);
    const visible=!!item||(current.stickers||[]).some(s=>time>=s.start&&time<s.end);
    const empty=document.getElementById('edit-empty'),emptyHidden=visible,canvasHidden=!visible;
    if(empty.hidden!==emptyHidden)empty.hidden=emptyHidden;
    if(canvas.hidden!==canvasHidden)canvas.hidden=canvasHidden;
  }
  const proxies=new Map();let checking=false, legacy=false;
  const base=c=>'/api/editor/preview-proxy/'+encodeURIComponent(c.task_id);
  function check(c){
    const id=c.task_id, entry=proxies.get(id);
    if(legacy||checking||entry?.url||entry?.until>Date.now()||typeof fetch!=='function')return;
    if(proxies.size>=100)proxies.delete(proxies.keys().next().value);
    const next={until:Date.now()+15000};proxies.set(id,next);checking=true;
    fetch(base(c),{method:'POST',cache:'no-store',headers:{'X-Hub-Request':'1'}}).then(async response=>{
      if(response.status===405){legacy=true;return;}
      if(!response.ok)return;
      const data=await response.json();
      if(data.state==='ready'&&/^[0-9a-f]{64}$/.test(data.version))next.url=base(c)+'/'+data.version;
      else next.until=Date.now()+(data.state==='pending'?4000:60000);
    }).catch(()=>{}).finally(()=>{checking=false;});
  }
  function media(i,c){
    let v=pool.get(i);const original='/api/tasks/'+c.task_id+'/video';
    check(c);
    // Keep attached media pinned throughout playback, including preloaded cuts.
    const url=(running&&v?v.dataset.variant:proxies.get(c.task_id)?.url)||original;
    if(v&&v.dataset.variant!==url){v.onerror=null;v.pause();v.removeAttribute('src');v.load();pool.delete(i);v=null;}
    if(!v){v=document.createElement('video');v.playsInline=true;v.preload='auto';v.dataset.source=original;v.dataset.variant=url;v.src=url;v.addEventListener('loadedmetadata',()=>apply(v));v.addEventListener('seeked',()=>{draw(true);apply(v);});v.addEventListener('loadeddata',()=>draw(true));v.onerror=()=>{if(pool.get(i)!==v)return;if(v.dataset.variant!==original){proxies.set(c.task_id,{until:Date.now()+60000});v.dataset.variant=original;v.src=original;return;}window.hubEditor?.pause();document.getElementById('edit-error').textContent='视频预览读取失败，请检查素材是否可播放';};pool.set(i,v);}return v;
  }
  function apply(v){
    if(v.readyState<1)return;
    // During playback allow decoder jitter (especially at high playbackRate) rather
    // than issuing a new seek every few frames. Paused scrubbing remains precise.
    const tolerance=v._play?Math.max(.35,(v.playbackRate||1)*.25):.025;
    if(!v.seeking&&Math.abs(v.currentTime-v._target)>tolerance){if(!v._play&&!v.paused)v.pause();v.currentTime=v._target;return;}
    if(v._play){if(v.paused&&!v.seeking)v.play().catch(()=>{});}else if(!v.paused)v.pause();
  }
  function sync(body,t,play){current=body;time=t;running=play;
    const live=active(body,t),needed=new Set(live.map(r=>r.i));body.clips.forEach((c,i)=>{if(c.at>t&&c.at<t+2)needed.add(i);});
    // Keep a small warm cache when scrubbing backwards across cuts.
    for(const [i,v]of pool){
      const c=body.clips[i];
      if(!c||v.dataset.source!=='/api/tasks/'+c.task_id+'/video'){v.pause();v.removeAttribute('src');v.load();pool.delete(i);continue;}
      if(!needed.has(i)){v._play=false;v.pause();}
    }
    for(const [i,v]of pool){
      if(pool.size<=Math.max(6,needed.size))break;
      if(!needed.has(i)){v.pause();v.removeAttribute('src');v.load();pool.delete(i);}
    }
    for(const i of needed){const c=body.clips[i],v=media(i,c),isActive=live.some(r=>r.i===i);v._target=Math.max(c.start,Math.min(c.end-.001,c.start+(Math.max(0,t-c.at))*(c.speed||1)));v._play=isActive&&play;const rate=c.speed||1,volume=body.tracks.find(x=>x.id===c.track)?.muted?0:Math.min(1,Math.max(0,c.volume??1));if(v.playbackRate!==rate)v.playbackRate=rate;if(v.volume!==volume)v.volume=volume;apply(v);pool.delete(i);pool.set(i,v);}
    for(const [i,v]of pool){if(pool.size<=Math.max(6,needed.size))break;if(!needed.has(i)){v.pause();v.removeAttribute('src');v.load();pool.delete(i);}}
    draw();
  }
  return {sync,pause(){const wasRunning=running;running=false;for(const v of pool.values()){v._play=false;v.pause();}if(wasRunning)draw();},ready(body,t){const item=top(body,t),v=item&&pool.get(item.i);return !item||!!v&&v.readyState>=2&&!v.seeking;},reset(){current=null;for(const v of pool.values()){v.pause();v.removeAttribute('src');v.load();}pool.clear();context.clearRect(0,0,canvas.width,canvas.height);}};
})();

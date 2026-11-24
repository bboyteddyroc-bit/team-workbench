'use strict';
// Pure timeline layout rules: collision resolution, main-track magnet, de-overlap and linked following.
(function(root){
  const FPS=24,EPS=1e-6,MAIN='video-main';
  const q=t=>Math.round(t*FPS)/FPS;
  const len=c=>Math.max(1,Math.round((c.end-c.start)/(c.speed||1)*FPS))/FPS;
  const isVoice=item=>item.source==='voice'||!!item.voice_job_id;
  // A new project's first video track can have an automatically generated ID.
  // Explicit video-main remains authoritative when present.
  function mainTrack(body){
    if(body.main_track)return body.main_track;
    if(body.tracks?.some(t=>t.id===MAIN)||body.clips.some(c=>(c.track||MAIN)===MAIN))return MAIN;
    const videoTracks=new Set(body.clips.map(c=>c.track||MAIN));
    return body.tracks?.find(t=>videoTracks.has(t.id))?.id||body.clips[0]?.track||MAIN;
  }

  // movers/obstacles: [{start,end,lane}]. Returns the delta closest to `delta` where no mover overlaps
  // an obstacle on the same lane and nothing moves before time 0.
  function resolveMove(movers,obstacles,delta){
    if(!movers.length)return delta;
    const floor=-Math.min(...movers.map(m=>m.start));
    const candidates=new Set([delta,floor]);
    for(const m of movers)for(const o of obstacles)if(m.lane===o.lane){candidates.add(o.end-m.start);candidates.add(o.start-m.end);}
    const ok=d=>d>=floor-EPS&&movers.every(m=>obstacles.every(o=>m.lane!==o.lane||m.start+d>=o.end-EPS||m.end+d<=o.start+EPS));
    let best=null;
    for(const d of candidates){if(!ok(d))continue;if(best===null||Math.abs(d-delta)<Math.abs(best-delta)-EPS)best=d;}
    return best;
  }

  // Magnet: main-track clips sit back to back from 0. Order follows the clip centres, so a clip dropped
  // between two neighbours is inserted there and later clips ripple.
  function pack(body,main=MAIN,originalCenters=null){
    const rows=body.clips.map((c,i)=>({c,i})).filter(r=>(r.c.track||MAIN)===main);
    const center=c=>originalCenters?.get(c)??((c.at||0)+len(c)/2);
    rows.sort((a,b)=>center(a.c)-center(b.c)||a.i-b.i);
    let t=0,changed=false;
    for(const r of rows){if(Math.abs((r.c.at||0)-t)>EPS){r.c.at=q(t);changed=true;}t+=len(r.c);}
    return changed;
  }

  // Safety net: video and audio clips on one track never overlap; later clips are pushed forward.
  function deoverlap(body){
    const lanes=new Map(),add=(track,item,duration)=>{if(!lanes.has(track))lanes.set(track,[]);lanes.get(track).push({item,duration});};
    body.clips.forEach(c=>add(c.track||MAIN,c,len(c)));
    (body.audio_clips||[]).forEach((c,i)=>add(c.track||'audio-'+i,c,c.end-c.start));
    let changed=false;
    for(const rows of lanes.values()){
      rows.sort((a,b)=>(a.item.at||0)-(b.item.at||0));let cursor=0;
      const fixed=rows.filter(r=>r.item.locked).map(r=>({start:r.item.at||0,end:(r.item.at||0)+r.duration}));
      for(const r of rows){
        if(r.item.locked)continue;
        let at=Math.max(r.item.at||0,cursor);
        for(const f of fixed)if(at<f.end-EPS&&at+r.duration>f.start+EPS)at=Math.ceil(f.end*FPS-1e-6)/FPS;
        if(at>(r.item.at||0)+EPS){r.item.at=Math.ceil(at*FPS-1e-6)/FPS;changed=true;}
        cursor=(r.item.at||0)+r.duration;
      }
    }
    return changed;
  }

  // Linkage: remember which main-track clip each captions / audio / overlay item sits on.
  function snapshot(body,exclude=new Set(),main=mainTrack(body)){
    const mains=body.clips.filter(c=>(c.track||MAIN)===main).map(c=>({clip:c,at:c.at||0,end:(c.at||0)+len(c)}));
    const bound=[],find=t=>mains.find(m=>t>=m.at-EPS&&t<m.end-EPS);
    const consider=(item,start,kind)=>{if(item.locked||exclude.has(item)||isVoice(item))return;const m=find(start);if(m)bound.push({item,m,kind,ref:m.at});};
    (body.captions||[]).forEach(c=>consider(c,c.start,'caption'));
    (body.audio_clips||[]).forEach(c=>consider(c,c.at||0,'at'));
    body.clips.forEach(c=>{if((c.track||MAIN)!==main)consider(c,c.at||0,'at');});
    return {mains,bound};
  }
  // Items follow the clip they were attached to; deleted anchors leave them in place; `stay` anchors keep theirs.
  function apply(body,snap,stay=new Set()){
    const alive=new Set(body.clips);let changed=false;
    for(const b of snap.bound){const {item,m,kind}=b;
      if(!alive.has(m.clip)||stay.has(m.clip))continue;
      let d=(m.clip.at||0)-b.ref;if(Math.abs(d)<EPS)continue;b.ref=m.clip.at||0;
      if(kind==='caption'){d=Math.max(d,-item.start);item.start+=d;item.end+=d;}
      else{d=Math.max(d,-(item.at||0));item.at=q((item.at||0)+d);}
      changed=true;
    }
    return changed;
  }
  // Voice subtitles follow their own audio, independently of the main-track link toggle.
  // Remember identities/times to avoid moving explicitly selected or already-adjusted subtitles twice.
  function voiceSnapshot(body,exclude=new Set()){
    return (body.audio_clips||[]).filter(c=>c.voice_job_id&&c.link_captions!==false).map(clip=>({
      clip,at:clip.at||0,start:clip.start,end:clip.end,
      captions:(body.captions||[]).filter(c=>c.voice_job_id===clip.voice_job_id&&(!clip.edit_compound||c.edit_compound===clip.edit_compound)&&!c.locked&&!exclude.has(c)).map(item=>({item,start:item.start,end:item.end}))
    }));
  }
  function applyVoice(body,anchors){
    const sounds=new Set(body.audio_clips||[]),captions=new Set(body.captions||[]),removed=new Set();
    for(const anchor of anchors){
      const {clip}=anchor;if(!sounds.has(clip)||clip.link_captions===false)continue;
      const at=clip.at||0,delta=(at-anchor.at)-(clip.start-anchor.start),end=at+clip.end-clip.start;
      if(Math.abs(delta)<EPS&&clip.end===anchor.end&&clip.start===anchor.start)continue;
      for(const previous of anchor.captions){
        const {item}=previous;
        if(!captions.has(item)||item.start!==previous.start||item.end!==previous.end)continue;
        const start=Math.max(at,item.start+delta),stop=Math.min(end,item.end+delta);
        if(stop>start){item.start=start;item.end=stop;}else removed.add(item);
      }
    }
    if(removed.size)body.captions=body.captions.filter(c=>!removed.has(c));
  }
  // One entry point for every timeline mutation: snapshot links, run the change, then magnet / link / de-overlap.
  function edit(body,mutator,o={}){
    const exclude=o.exclude||new Set(),voices=voiceSnapshot(body,exclude);
    const main=o.main||mainTrack(body),snap=o.link?snapshot(body,exclude,main):null,stay=o.stay||new Set();
    const centers=o.preserveOrder?new Map(body.clips.map(c=>[c,(c.at||0)+len(c)/2])):null;
    body.main_track=main;
    const result=mutator();
    if(o.magnet)pack(body,main,centers);
    if(snap)apply(body,snap,stay);
    if(deoverlap(body)&&snap)apply(body,snap,stay);
    deoverlap(body);
    applyVoice(body,voices);
    return result;
  }
  const api={FPS,MAIN,q,len,mainTrack,resolveMove,pack,deoverlap,snapshot,apply,edit};
  if(typeof module==='object'&&module.exports)module.exports=api;else root.HubLayout=api;
})(typeof window!=='undefined'?window:globalThis);

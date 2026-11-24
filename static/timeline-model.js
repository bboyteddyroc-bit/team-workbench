'use strict';
window.HubTimeline={
  fps:24,
  length:c=>Math.max(1,Math.round((c.end-c.start)/(c.speed||1)*24))/24,
  migrate(body){
    body.tracks||=[];const ids=new Set(body.tracks.map(t=>t.id));
    const ensure=id=>{if(!ids.has(id)){body.tracks.push({id,muted:false});ids.add(id);}return id;};
    let at=0;for(const c of body.clips){c.at=Number.isFinite(c.at)?Math.round(c.at*24)/24:at;c.track=ensure(c.track||'video-main');at=c.at+this.length(c);}
    // Preserve timing and existing lanes where possible; overlapping subtitles need separate lanes.
    const occupied=new Map(),media=new Set([...body.clips.map(c=>c.track),...(body.audio_clips||[]).map(c=>c.track),body.audio?.track].filter(Boolean));
    const free=(id,c)=>!media.has(id)&&!(occupied.get(id)||[]).some(other=>c.start<other.end-1e-6&&c.end>other.start+1e-6);
    const captionLanes=()=>body.tracks.map(t=>t.id).filter(id=>id.startsWith('caption-')&&!media.has(id));
    for(const c of body.captions){let id=c.track||'caption-main';if(!free(id,c)){id=captionLanes().find(candidate=>free(candidate,c));if(!id){let n=1;while(ids.has('caption-auto-'+n))n++;id='caption-auto-'+n;}}c.track=ensure(id);if(!occupied.has(id))occupied.set(id,[]);occupied.get(id).push(c);}
    (body.audio_clips||[]).forEach((c,i)=>c.track=ensure(c.track||'audio-'+i));
    for(const c of body.stickers||[])c.track=ensure(c.track||'sticker-main');
    if(body.audio&&body.audio.duration>0&&(body.audio_clips||[]).length<50){const a=body.audio;body.audio_clips||=[];body.audio_clips.push({source:'asset',asset_id:a.asset_id,source_duration:a.duration,start:0,end:a.duration,at:0,volume:a.volume,locked:false,muted:false,fade_in:0,fade_out:0,track:ensure(a.track||'background-audio')});body.audio=null;}
    if(body.audio)body.audio.track=ensure(body.audio.track||'background-audio');body.schema_version=4;
  },
  lastFrame:total=>Math.max(0,(Math.ceil(total*24-1e-7)-1)/24),
  clamp(time,total){return Math.max(0,Math.min(this.lastFrame(total),Math.round((Number(time)||0)*24)/24));}
};

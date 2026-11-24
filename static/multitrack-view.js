'use strict';
window.hubMultitrackView=(()=>{
  const scroll=document.querySelector('.track-scroll'),ruler=document.getElementById('timeline-ruler');
  scroll.querySelectorAll(':scope > .track-row:not(.compound-row)').forEach(n=>{n.hidden=true;n.classList.add('legacy-track');});
  const root=document.createElement('div');root.id='multi-tracks';scroll.append(root);
  const AUDIO_DRAG='application/x-seedance-audio',VIDEO_DRAG='application/x-seedance-task',STICKER_DRAG='application/x-seedance-sticker';
  const audioFile=file=>/^audio\//i.test(file.type||'')||/\.(mp3|wav|m4a|aac|ogg|oga|opus|flac)$/i.test(file.name||'');
  const videoFile=file=>/^video\//i.test(file.type||'')||/\.(mp4|mov|m4v|mkv|avi|webm|flv|wmv)$/i.test(file.name||'');
  function acceptsDrag(data){
    const types=Array.from(data?.types||[]);
    return types.includes(VIDEO_DRAG)||types.includes(AUDIO_DRAG)||types.includes(STICKER_DRAG)||types.includes('Files');
  }
  function dropMedia(event,lane,trackId,actions,scale){
    const data=event.dataTransfer,left=lane.getBoundingClientRect().left,time=Math.max(0,(event.clientX-left)/scale);
    const stickerStyle=data.getData(STICKER_DRAG),audioId=data.getData(AUDIO_DRAG),taskId=data.getData(VIDEO_DRAG);
    if(stickerStyle){actions.insertSticker(stickerStyle,trackId,time);return;}
    if(audioId){actions.insertAudio(audioId,trackId,time);return;}
    if(taskId){let range=null;try{range=JSON.parse(data.getData('application/x-seedance-range')||'null');}catch{}actions.insert(taskId,trackId,time,range);return;}
    const files=[...(data.files||[])].filter(f=>audioFile(f)||videoFile(f));
    if(files.length&&actions.insertAudioFiles)actions.insertAudioFiles(files,trackId,time);
  }
  // Keep user track order identical to video compositing order.
  function trackInfo(body,trackId){
    const hasVideo=body.clips.some(c=>c.track===trackId),hasCaption=body.captions.some(c=>c.track===trackId),hasAudio=(body.audio_clips||[]).some(c=>c.track===trackId)||body.audio?.track===trackId,hasSticker=(body.stickers||[]).some(c=>c.track===trackId);
    const kind=hasVideo&&(hasCaption||hasSticker)?'mixed':hasVideo?'video':hasCaption?'caption':hasSticker?'sticker':hasAudio?'audio':'empty';
    const rank=kind==='caption'?0:kind==='sticker'?0.5:kind==='video'||kind==='mixed'?1:2;
    return {hasVideo,hasCaption,hasAudio,hasSticker,kind,rank};
  }
  const pendingTracks=new Set();
  function orderedRows(body){
    return body.tracks.map((track,index)=>({track,index,info:trackInfo(body,track.id)}))
      .filter(row=>{if(row.info.kind!=='empty'){pendingTracks.delete(row.track.id);return true;}return pendingTracks.has(row.track.id);});
  }
  function volumeChip(node,key,item,actions){
    if(!actions.volume)return;
    const chip=document.createElement('button');chip.type='button';chip.className='clip-vol';
    const level=item.muted?0:Math.max(0,Math.min(2,Number(item.volume??1)));
    chip.textContent=level<=0?'🔇':'🔊';
    chip.title=`音量 ${Math.round(level*100)}%（点击调节）`;
    chip.setAttribute('aria-label',chip.title);
    chip.onpointerdown=e=>{e.stopPropagation();};
    chip.onclick=e=>{e.stopPropagation();e.preventDefault();actions.volume(key,chip);};
    node.append(chip);
  }
  function render(body,videos,audios,actions){
    const scale=window.hubTimelineScale||32,total=window.hubEditor.total(),width=Math.max(scroll.clientWidth-104,total*scale+48);
    ruler.replaceChildren();ruler.style.width=(width+104)+'px';for(let t=0;t<=total;t+=scale<25?5:1){const tick=document.createElement('span');tick.textContent=t+'s';tick.style.left=(104+t*scale)+'px';ruler.append(tick);}
    root.replaceChildren();const lanes=new Map();
    const captionDrop=document.createElement('div');captionDrop.className='caption-drop-zone';captionDrop.dataset.trackId='new-caption';
    const captionHint=document.createElement('span');captionHint.textContent='向上拖动字幕，在此创建字幕轨道';captionDrop.append(captionHint);root.append(captionDrop);
    const visibleRows=orderedRows(body);
    for(const {track,info} of visibleRows){
      const row=document.createElement('div');row.className='track-row multi-track';row.dataset.trackId=track.id;row.dataset.trackKind=info.kind;
      const head=document.createElement('div');head.className='track-label';
      if(actions.reorderTrack){
        const controls=document.createElement('span');controls.className='track-order-controls';
        for(const [delta,text,title] of [[-1,'↑','上移轨道'],[1,'↓','下移轨道']]){
          const button=document.createElement('button');button.type='button';button.textContent=text;button.title=title;button.setAttribute('aria-label',title);
          const index=visibleRows.findIndex(r=>r.track.id===track.id),target=visibleRows[index+delta];button.disabled=!target;
          button.onpointerdown=e=>e.stopPropagation();button.onclick=e=>{e.stopPropagation();if(target)actions.reorderTrack(track.id,body.tracks.indexOf(target.track)-body.tracks.indexOf(track));};controls.append(button);
        }head.append(controls);
      }

      const types=[info.hasVideo&&'视频',info.hasCaption&&'字幕',info.hasSticker&&'贴纸',info.hasAudio&&'音频'].filter(Boolean),name=types.length?types.join(' / '):'空轨道';
      const label=document.createElement('span');label.className='track-name';label.textContent=name;label.title=name;head.append(label);
      if(info.hasCaption&&actions.selectCaptionTrack){const all=document.createElement('button');all.type='button';all.className='track-mute';all.textContent='↔';all.classList.add('track-select-all');all.title='选中本轨全部字幕，再拖动任一字幕块';all.setAttribute('aria-label','选择本轨全部字幕以整体移动');all.onpointerdown=e=>e.stopPropagation();all.onclick=e=>{e.stopPropagation();actions.selectCaptionTrack(track.id);};head.append(all);}
      const sound=info.hasVideo||info.hasAudio;
      if(sound){const mute=document.createElement('button');mute.type='button';mute.className='track-mute';mute.textContent=track.muted?'🔇':'🔊';mute.title=track.muted?'取消轨道静音':'轨道静音';mute.setAttribute('aria-label',mute.title);mute.setAttribute('aria-pressed',String(track.muted));mute.onclick=()=>actions.mute(track.id);head.append(mute);}
      const lane=document.createElement('div');lane.className='track-lane multi-lane';lane.style.width=width+'px';row.append(head,lane);root.append(row);lanes.set(track.id,lane);
      lane.ondragover=e=>{if(!acceptsDrag(e.dataTransfer))return;e.preventDefault();e.dataTransfer.dropEffect='copy';lane.classList.add('drop-target');};lane.ondragleave=()=>lane.classList.remove('drop-target');lane.ondrop=e=>{e.preventDefault();e.stopPropagation();lane.classList.remove('drop-target');dropMedia(e,lane,track.id,actions,scale);};
    }
    const attach=(node,key,item,at,duration,kind)=>{const lane=lanes.get(item.track);if(!lane)return;node.dataset.timelineKey=key;node.style.position='absolute';node.style.left=at*scale+'px';node.style.width=duration*scale+'px';node.style.top='4px';node.style.bottom='4px';node.style.height='auto';node.draggable=false;lane.append(node);
      if(kind!=='caption'&&(kind==='video'||kind==='audio')&&duration*scale>=64)volumeChip(node,key,item,actions);
      node.onpointerdown=e=>{e.stopPropagation();actions.move(e,key,node);};
      node.onclick=e=>{if(actions.suppressed())return;if(e.detail===0){actions.select(key,node);}scroll.focus({preventScroll:true});};
    };
    videos.forEach((node,i)=>{const c=body.clips[i];if(!c)return;attach(node,'video:'+i,c,c.at,HubTimeline.length(c),'video');if(!c.audio_detached&&(c.volume??1)>0){const tag=document.createElement('small');tag.className='embedded-audio';tag.textContent='♫';tag.title='包含原声';node.querySelector('.embedded-audio')?.remove();node.append(tag);}});
    body.captions.forEach((c,i)=>{const n=document.createElement('button');n.type='button';n.className='timeline-block caption-segment';const text=document.createElement('span');text.className='caption-block-text';text.textContent=c.text;n.append(text);n.title=c.text;attach(n,'caption:'+i,c,c.start,c.end-c.start,'caption');for(const edge of ['start','end']){const h=document.createElement('span');h.className='trim-handle trim-'+edge;h.title='拖动调整字幕'+(edge==='start'?'入点':'出点');h.onpointerdown=e=>actions.resizeCaption(e,i,edge,n);h.onclick=e=>e.stopPropagation();n.append(h);}});
    audios.forEach((node,i)=>{const c=body.audio_clips[i];if(c)attach(node,'detached:'+i,c,c.at,c.end-c.start,'audio');});
    if(body.audio){const n=document.createElement('button');n.type='button';n.className='timeline-block audio-segment-simple';n.textContent='配音 / 音乐';attach(n,'audio:0',body.audio,0,body.audio.duration,'audio');}
    window.hubStickers?.renderBlocks(body,lanes,scale,actions);
    const add=document.createElement('div');add.className='track-row multi-track new-track';add.dataset.trackId='new';
    const button=document.createElement('button');button.type='button';button.className='track-label';button.textContent='+';button.title='添加轨道';button.onclick=actions.addTrack;
    const lane=document.createElement('div');lane.className='track-lane new-track-drop';lane.style.width=width+'px';lane.textContent='拖入视频、音频或贴纸，在此新建轨道';
    lane.ondragover=e=>{if(!acceptsDrag(e.dataTransfer))return;e.preventDefault();e.dataTransfer.dropEffect='copy';lane.classList.add('drop-target');};
    lane.ondragleave=()=>lane.classList.remove('drop-target');
    lane.ondrop=e=>{e.preventDefault();e.stopPropagation();lane.classList.remove('drop-target');dropMedia(e,lane,null,actions,scale);};
    add.append(button,lane);root.append(add);
  }
  return {render,revealEmpty:id=>pendingTracks.add(id)};
})();

'use strict';
window.hubEditor=(()=>{
  const $=id=>document.getElementById(id), player=$('edit-player'),voice=$('edit-audio');
  let library=[],projects=[],project=null,selected=0,dirty=false,loaded=false,opening=null,playing=false,position=0,epoch=0,busy=false,dragIndex=null,requestKey=crypto.randomUUID();
  let undo=[],redo=[],lastEdit=null,detachedPlayers=[];
  const pendingSaves=new WeakMap(),separatingClips=new WeakSet();
  let exportIds=null,exportPending=false;const exportOpen=new Set(),exportRows=new Map();
  const videoSelection=new Set();
  const timelineSelection=new Set();
  let bundlesSupported=false,marqueeSelectionActive=false,libraryComplete=false;
  let selectionAnchor=0;
  let timelineVideoNodes=[];
  const fresh=()=>({id:null,version:0,title:'未命名剪辑',body:{clips:[],captions:[],ratio:'9:16',audio:null,target_duration:30}});
  // Browser-local recovery is account-scoped and never submits or exports a project.
  const draftKey=()=>me?.id?'hub-editor-recovery-v1:'+me.id:null;
  function saveRecovery(){
    const key=draftKey();if(!key||!project)return false;
    try{localStorage.setItem(key,JSON.stringify({project,dirty,position,updated:Date.now()}));return true;}
    catch(e){console.warn('剪辑自动保存失败',e);return false;}
  }
  function readRecovery(){
    try{const value=JSON.parse(localStorage.getItem(draftKey())||'null');return value?.project?.body&&Array.isArray(value.project.body.clips)&&Array.isArray(value.project.body.captions)?value:null;}catch{return null;}
  }
  const clips=()=>project?.body.clips||[];
  const length=c=>HubTimeline.length(c);
  const videoTotal=()=>Math.max(0,...clips().map((c,i)=>offset(i)+length(c)));
  const total=()=>Math.max(videoTotal(),(project?.body.audio?(Number(project.body.audio.duration||voice.duration)||0):0),...(project?.body.captions||[]).map(c=>c.end),...(project?.body.audio_clips||[]).map(c=>c.at+c.end-c.start),...(project?.body.stickers||[]).map(c=>c.end));
  let trackSelection=null,playTimer=null,playClock=0;
  let pendingCommit=0,primaryCaption=null,syncPending=0,panelSig='';
  window.hubTimelineExtent=60;
  const offset=i=>clips()[i]?.at??clips().slice(0,i).reduce((n,c)=>n+length(c),0);
  const seconds=n=>Math.round(n*100)/100;
  const clock=n=>`${Math.floor(n/60).toString().padStart(2,'0')}:${Math.floor(n%60).toString().padStart(2,'0')}`;
  const FPS=24,frame=1/FPS;
  const tc=n=>{const count=Math.max(0,Math.floor((Number(n)||0)*FPS+1e-6)),m=Math.floor(count/(FPS*60)),s=Math.floor(count/FPS)%60,f=count%FPS;return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}.${String(f).padStart(2,'0')}`;};
  const source=id=>library.find(s=>s.id===id);
  const soundId=c=>c.voice_job_id||c.asset_id||c.task_id;
  const soundMax=c=>c.source==='voice'||c.source==='asset'?(c.source_duration||c.end):(source(c.task_id)?.duration||c.end);
  const soundUrl=c=>c.source==='voice'?'/api/voice/jobs/'+c.voice_job_id+'/audio':c.source==='asset'?'/api/assets/'+c.asset_id:'/api/tasks/'+c.task_id+'/video';
  function linkedCaptions(clip,next){
    if(!clip.voice_job_id||clip.link_captions===false)return;
    const delta=(next.at-clip.at)-(next.start-clip.start),end=next.at+next.end-next.start;
    project.body.captions=project.body.captions.flatMap(c=>{
      if(c.voice_job_id!==clip.voice_job_id||c.locked||(clip.edit_compound&&c.edit_compound!==clip.edit_compound))return [c];
      const start=Math.max(next.at,c.start+delta),stop=Math.min(end,c.end+delta);
      return stop>start?[{...c,start,end:stop}]:[];
    });
  }
  function insertVoice(job){
    if(!project)throw Error('请先打开剪辑台');
    if(!job.project_id||job.project_id!==project.id)throw Error('请打开生成配音时的剪辑项目，再加入时间轴');
    if(job.state!=='ready'||!Number.isFinite(job.duration)||job.duration<.1)throw Error('配音尚未完成');
    const at=Number(job.insert_at||0),end=at+job.duration;
    if(!Number.isFinite(at)||at<0)throw Error('配音插入位置无效');
    const sounds=project.body.audio_clips||[];
    if(sounds.some(c=>c.voice_job_id===job.id))throw Error('这条配音已经加入当前时间轴');
    if(sounds.length>=50)throw Error('最多 50 段音轨');
    const caps=(job.captions||[]).map(c=>({text:c.text,start:Math.max(at,Number(c.start)+at),end:Math.min(end,Number(c.end)+at),voice_job_id:job.id})).filter(c=>c.end>c.start);
    if(project.body.captions.length+caps.length>600)throw Error('加入后超过 600 条字幕，请先整理字幕');
    pause();project.body.audio_clips=sounds;
    sounds.push({source:'voice',voice_job_id:job.id,source_duration:job.duration,start:0,end:job.duration,at,volume:1,locked:false,muted:false,fade_in:0,fade_out:0});
    project.body.captions.push(...caps);mark();render();
  }
  function fail(e){const message=e.message||String(e);$('edit-error').textContent=message;toast(message,true);}
  const audioMime=file=>{const declared=(file.type||'').toLowerCase();if(declared&&declared!=='application/octet-stream')return declared;const ext=(file.name.split('.').pop()||'').toLowerCase();return {mp3:'audio/mpeg',wav:'audio/wav',m4a:'audio/mp4',aac:'audio/aac',ogg:'audio/ogg',oga:'audio/ogg',opus:'audio/ogg',flac:'audio/flac'}[ext]||declared;};
  // .mp4/.mov 是视频容器（也能装音频）：按视频走实拍导入，绝不当音频上传。
  const VIDEO_EXT=/\.(mp4|mov|m4v|mkv|avi|webm|flv|wmv)$/i;
  const isVideoFile=file=>/^video\//i.test((file.type||'').toLowerCase())||VIDEO_EXT.test(file.name||'');
  const isAudioFile=file=>!isVideoFile(file)&&(/^audio\//i.test(audioMime(file))||/\.(mp3|wav|m4a|aac|ogg|oga|opus|flac)$/i.test(file.name||''));
  function audioTrack(){
    const tracks=(project?.body.tracks||[]).filter(t=>!String(t.id).startsWith('video-')&&!String(t.id).startsWith('caption-'));
    const used=new Set((project?.body.audio_clips||[]).map(c=>c.track).filter(Boolean));
    return (tracks.find(t=>used.has(t.id))||tracks[0])?.id;
  }
  // Append without committing history so compound operations can make one atomic edit.
  function appendAudioAsset(asset,duration,at,track){
    if(!project)throw Error('请先打开剪辑台');
    if(!Number.isFinite(duration)||duration<=0)throw Error('无法读取音频时长');
    if((project.body.audio_clips||[]).length>=50)throw Error('最多 50 段音轨');
    const start=Number.isFinite(at)&&at>=0?at:position;
    const clip={source:'asset',asset_id:asset.id,source_duration:duration,start:0,end:duration,at:seconds(start),volume:1,locked:false,muted:false,fade_in:0,fade_out:0};
    clip.track=track||audioTrack();
    project.body.audio_clips||=[];project.body.audio_clips.push(clip);
    return clip;
  }
  function insertAudioAsset(asset,duration,at,track){
    pause();commitEdits();const clip=appendAudioAsset(asset,duration,at,track);
    mark();render();return clip;
  }
  function probeAudioDuration(assetId){
    return new Promise((resolve,reject)=>{
      const node=new Audio();let timer=0;
      const done=()=>{const value=node.duration;cleanup();Number.isFinite(value)&&value>0?resolve(value):reject(Error('无法读取音频时长，请换一个文件'));};
      const bad=()=>{cleanup();reject(Error('音频读取失败，请确认格式为 MP3、WAV、M4A、AAC、OGG 或 FLAC'));};
      const cleanup=()=>{clearTimeout(timer);node.removeEventListener('loadedmetadata',done);node.removeEventListener('error',bad);node.removeAttribute('src');};
      timer=setTimeout(bad,20000);
      node.addEventListener('loadedmetadata',done);node.addEventListener('error',bad);
      node.preload='metadata';node.src='/api/assets/'+encodeURIComponent(assetId);
    });
  }
  async function adoptSfx(id){
    const r=await fetch('/api/editor/sfx/'+encodeURIComponent(id)+'/adopt',{method:'POST',credentials:'same-origin',headers:{'X-Hub-Request':'1'}});
    const data=await r.json().catch(()=>({}));
    if(!r.ok)throw Error(data.detail||'无法取得该音效');
    return data;
  }
  async function insertAudioAssetAt(assetId,track,at){
    if(!project)throw Error('请先打开剪辑台');
    const time=Number.isFinite(at)&&at>=0?at:position;
    // 内置音效用 sfx:<id> 标记，落轨前先复制成用户自己的素材。
    if(String(assetId).startsWith('sfx:')){
      const data=await adoptSfx(String(assetId).slice(4));
      const duration=Number(data.duration)>0?Number(data.duration):await probeAudioDuration(data.id);
      insertAudioAsset({id:data.id,name:data.name},duration,time,track);
      return time;
    }
    const duration=await probeAudioDuration(assetId);
    insertAudioAsset({id:assetId},duration,time,track);
    return time;
  }
  async function uploadAudioFiles(files){
    const token=epoch;const created=[];
    for(const file of files){
      if(file.size>64*1024*1024)throw Error('音频不能超过 64 MB');
      const r=await fetch('/api/assets',{method:'POST',credentials:'same-origin',headers:{'Content-Type':audioMime(file),'X-Hub-Request':'1','X-File-Name':encodeURIComponent(file.name)},body:file});
      const asset=await r.json();
      if(!r.ok)throw Error(asset.detail||'音频上传失败');
      if(token!==epoch)throw Error('登录状态已变化');
      created.push(asset);
    }
    return created;
  }
  async function insertAudioFiles(files,track,time){
    const audio=[...files].filter(isAudioFile);
    if(!audio.length)throw Error('请拖入 MP3、WAV、M4A、AAC、OGG 或 FLAC 音频文件');
    if(!project)throw Error('请先打开剪辑台');
    if((project.body.audio_clips||[]).length+audio.length>50)throw Error('最多 50 段音轨');
    const created=await uploadAudioFiles(audio);
    let at=Number.isFinite(time)&&time>=0?time:position;
    for(const asset of created){const duration=await probeAudioDuration(asset.id);insertAudioAsset(asset,duration,at,track);at=seconds(at+duration);}
    window.hubAudioLibrary?.refresh?.();window.toast?.(audio.length>1?`已加入 ${audio.length} 个音频`:`已加入 ${audio[0].name}`);
  }
  async function importFootage(files){
    if(!project)throw Error('请先打开剪辑台');
    const token=epoch,created=[];
    for(const file of [...files]){
      if(file.size>1024*1024*1024)throw Error(`${file.name} 超过 1 GB`);
      const response=await fetch('/api/editor/footage',{method:'POST',credentials:'same-origin',headers:{'X-Hub-Request':'1','Content-Type':'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});
      if(!response.ok){let data;try{data=await response.json();}catch{}throw Error(data?.detail||`${file.name} 导入失败 (${response.status})`);}
      created.push(await response.json());
      if(token!==epoch)throw Error('登录状态已变化');
    }
    if(created.length){$('library-scope').value='today';await refresh();}
    return created;
  }
  async function insertVideoFiles(files){
    if(!project)throw Error('请先打开剪辑台');
    if(clips().length+[...files].length>50)throw Error('每个项目最多 50 个片段');
    const created=await importFootage(files);
    for(const item of created)add(item.id,0,item.duration);
    window.toast?.(created.length>1?`已加入 ${created.length} 个视频`:`已加入 ${created[0]?.name||'视频'}`);
    return created;
  }
  async function insertDroppedFiles(files,track,time){
    const list=[...files],audio=list.filter(isAudioFile),video=list.filter(isVideoFile);
    if(!audio.length&&!video.length)throw Error('请拖入视频（MP4 / MOV / M4V）或音频（MP3 / WAV / M4A / AAC / OGG / FLAC）文件');
    if(audio.length)await insertAudioFiles(audio,track,time);
    if(video.length)await insertVideoFiles(video);
  }
  // Browsers reject a pending play() promise with AbortError whenever pause() wins the race
  // (scrubbing, switching clips, pausing right after play). That is normal playback control,
  // not a media failure, so it must never reach the error line.
  function tryPlay(node){const result=node.play();if(result&&typeof result.catch==='function')result.catch(err=>{if(err&&err.name==='AbortError')return;fail(err);});}
  const snapshot=()=>{HubTimeline.migrate(project.body);return JSON.stringify({title:project.title,body:project.body});};
  function historyReset(){if(pendingCommit){clearTimeout(pendingCommit);pendingCommit=0;}primaryCaption=null;panelSig='';marqueeSelectionActive=false;timelineSelection.clear();videoSelection.clear();trackSelection=null;undo=[];redo=[];lastEdit=project?snapshot():null;}
  function mark(){markCore(false);}
  function markCore(keepSelection){if(pendingCommit){clearTimeout(pendingCommit);pendingCommit=0;}if(!keepSelection)timelineSelection.clear();if(project){const now=snapshot();if(lastEdit&&now!==lastEdit){undo.push(lastEdit);if(undo.length>60)undo.shift();redo=[];}lastEdit=now;}dirty=true;if($('edit-undo')){$('edit-undo').disabled=!undo.length;$('edit-redo').disabled=!redo.length;}requestKey=crypto.randomUUID();$('edit-save-state').textContent=saveRecovery()?'已自动保存到本机（未保存到项目）':'有未保存的更改';$('edit-error').textContent='';announce();}
  function pause(){cancelAnimationFrame(playTimer);playTimer=null;playing=false;window.hubMultitrackPreview?.pause();player.pause();voice.pause();detachedPlayers.forEach(a=>a.pause());$('edit-play').textContent='播放';}
  function reset(){projectPage=0;libraryPage=0;libraryScope='';$('edit-project-pagination')?.replaceChildren();$('edit-library-pagination')?.replaceChildren();endSourcePreview();clearHoverPreview(false);$('multi-tracks')?.replaceChildren();asrState.info=null;timelineVideoNodes=[];window.hubMultitrackPreview?.reset();epoch++;waveCache.clear();closeClipMenu();pause();library=[];libraryComplete=false;projects=[];project=null;loaded=false;opening=null;dirty=false;historyReset();detachedPlayers.forEach(a=>a.remove());detachedPlayers=[];player.removeAttribute('src');voice.removeAttribute('src');$('edit-library-list').replaceChildren();delete $('edit-library-list').dataset.signature;$('edit-clips').replaceChildren();$('edit-exports-list').replaceChildren();exportIds=null;exportRows.clear();exportOpen.clear();exportPending=false;}
  function clampCaptions(){} // Other tracks retain their independent positions.
  function lock(value){busy=value;['edit-save','edit-export','edit-new','edit-projects'].forEach(id=>$(id).disabled=value);$('edit-export').disabled=value||!total();}
  async function refresh(){
    const token=epoch,scope=$('library-scope').value,now=new Date(),start=new Date(now.getFullYear(),now.getMonth(),now.getDate()).getTime()/1000,end=new Date(now.getFullYear(),now.getMonth(),now.getDate()+1).getTime()/1000;
    const [data,saved]=await Promise.all([api('/editor/library'+(scope==='today'?'?after='+start+'&before='+end:'')),api('/editor/projects?summary=true')]);
    if(token!==epoch||!me)return;
    bundlesSupported=data.timeline_bundles===true;if(libraryComplete&&scope==='today'&&data.time_range_filter===true){const latest=new Map(data.items.map(item=>[item.id,item]));library=library.filter(item=>!(item.created>=start&&item.created<end)||latest.has(item.id)).map(item=>latest.get(item.id)||item);const existing=new Set(library.map(item=>item.id));library.unshift(...data.items.filter(item=>!existing.has(item.id)));}else{library=data.items;libraryComplete=scope!=='today'||data.time_range_filter!==true;}projects=saved;
    if($('library-scope').value!=='today'&&!libraryComplete)await ensureFullLibrary();
    if(!data.available)fail('执行机缺少导出工具，请联系管理员');
    renderLibrary();renderProjects();
  }
  async function ensureFullLibrary(){
    if(libraryComplete)return;
    const token=epoch,data=await api('/editor/library');
    if(token!==epoch||!me)return;
    library=data.items;libraryComplete=true;renderLibrary();
  }
  async function readProject(id){
    const existing=projects.find(p=>p.id===id);
    if(existing?.body)return structuredClone(existing); // Older services return full projects even with summary=true.
    return api('/editor/projects/'+encodeURIComponent(id));
  }
  async function open(){
    initAsr();
    if(!loaded){
      if(opening)return opening;
      const token=epoch;
      opening=(async()=>{await refresh();if(token!==epoch||!me)return;const recovery=readRecovery();if(recovery?.project?.body&&(recovery.project.body.clips?.length||recovery.project.body.audio_clips?.length))await ensureFullLibrary();if(token!==epoch||!me)return;project=recovery?recovery.project:fresh();dirty=!!recovery?.dirty;position=Math.max(0,Number(recovery?.position)||0);loaded=true;historyReset();render();if(recovery){seek(Math.min(position,total()));$('edit-save-state').textContent=dirty?'已恢复本机自动保存的剪辑（尚未保存到项目）':'已恢复上次剪辑';}await exports();})().finally(()=>{opening=null;});
      return opening;
    }
    await exports();
  }
  async function fromTask(id){navigate('editor');await open();if(!source(id))await ensureFullLibrary();if(!source(id))await refresh();if(!source(id))await ensureFullLibrary();add(id);}
  async function selectProject(id){
    await open();
    if(!await confirmProjectChange('切换项目'))return false;
    const token=epoch,previous=project,revision=project?snapshot():null;
    await refresh();const next=id?await readProject(id):null;
    if(next?.body&&(next.body.clips?.length||next.body.audio_clips?.length))await ensureFullLibrary();
    if(token!==epoch||!me||project!==previous||(project?snapshot():null)!==revision)throw Error('读取期间项目已变化，请重新选择');
    if(id&&!next)throw Error('项目不存在，请刷新后重试');
    pause();project=next?structuredClone(next):fresh();selected=0;position=0;dirty=false;
    requestKey=crypto.randomUUID();historyReset();render();if(clips().length)seek(0);saveRecovery();
    return true;
  }
  function announce(){window.dispatchEvent(new CustomEvent('hub-project',{detail:project?structuredClone(project):null}));}
  async function refreshVoiceProject(id){
    if(project?.id!==id||dirty)return false;
    const target=project,revision=JSON.stringify(project);
    await refresh();
    if(project!==target||dirty||JSON.stringify(project)!==revision)return false;
    const next=await readProject(id);
    if(project!==target||dirty||JSON.stringify(project)!==revision)return false;
    pause();project=structuredClone(next);historyReset();render();seek(position);return true;
  }  function add(id,start=0,end=null){
    const item=source(id);if(!item)return fail('原视频暂不可用，请刷新素材');
    if(clips().length>=50)return fail('每个项目最多 50 个片段');
    end=end===null?item.duration:end;if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end>item.duration||end-start<.1)return fail('请选择至少 0.1 秒的有效片段');
    const main=HubLayout.mainTrack(project.body);pause();editTimeline(()=>{clips().push({task_id:id,start,end,volume:1,speed:1,at:mainEnd(),track:main});},null,null,{main});selected=clips().length-1;mark();render();seek(offset(selected));
  }
  let projectPage=0,libraryPage=0,libraryScope='';
  function renderProjects(){
    const select=$('edit-projects');select.replaceChildren(new Option('打开项目…',''));
    const pageSize=50,pages=Math.max(1,Math.ceil(projects.length/pageSize));projectPage=Math.min(projectPage,pages-1);
    let controls=$('edit-project-pagination');if(!controls){controls=el('span',undefined,'fine');controls.id='edit-project-pagination';select.parentElement.append(controls);}
    controls.replaceChildren();if(pages>1){const prev=el('button','上一页','secondary'),next=el('button','下一页','secondary'),label=el('span',` ${projectPage+1} / ${pages} `);prev.type=next.type='button';prev.disabled=projectPage===0;next.disabled=projectPage===pages-1;prev.onclick=()=>{projectPage--;renderProjects();};next.onclick=()=>{projectPage++;renderProjects();};controls.append(prev,label,next);}
    const pageProjects=projects.slice(projectPage*pageSize,(projectPage+1)*pageSize),current=projects.find(p=>p.id===project?.id);if(current&&!pageProjects.some(p=>p.id===current.id))pageProjects.unshift(current);
    const groups=new Map();for(const p of pageProjects){const d=p.created?new Date(p.created*1000):null;const key=d&&!isNaN(d)?`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`:'未知日期';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p);}
    for(const [key,items] of groups){const group=document.createElement('optgroup');group.label=key;for(const p of items)group.append(new Option(p.title,p.id));select.append(group);}
    select.value=project?.id||'';
  }
  let subtitleFonts=[{id:'default',label:'默认 · 微软雅黑',group:'中文',css:'Microsoft YaHei, sans-serif'}];
  const fontCss=id=>subtitleFonts.find(f=>f.id===id)?.css||subtitleFonts[0].css;
  const fontOptions=select=>{const groups=new Map();for(const f of subtitleFonts){const key=f.group||'其他字体';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(f);}
    for(const [name,items] of groups){const box=document.createElement('optgroup');box.label=name;box.append(...items.map(f=>new Option(f.label,f.id)));select.append(box);}return select;};
  fetch('/static/fonts/fonts.json').then(r=>r.ok?r.json():Promise.reject(Error('字体清单读取失败'))).then(list=>{
    subtitleFonts=list.map(f=>{if(!f.file)return f;document.fonts.add(new FontFace('Hub '+f.id,`url("/static/fonts/${f.file}")`,{display:'swap'}));return {...f,css:`"Hub ${f.id}", sans-serif`};});
    renderCaptions();paint();
  }).catch(()=>{});
  let libraryObserver=null;
  function renderLibrary(){
    const list=$('edit-library-list');
    const filtered=window.hubWorkspace?.filterLibrary(library)||library,scope=$('library-scope').value;if(scope!==libraryScope){libraryScope=scope;libraryPage=0;}
    const pageSize=36,pages=Math.max(1,Math.ceil(filtered.length/pageSize));libraryPage=Math.min(libraryPage,pages-1);const visible=filtered.slice(libraryPage*pageSize,(libraryPage+1)*pageSize);
    let controls=$('edit-library-pagination');if(!controls){controls=el('div',undefined,'fine');controls.id='edit-library-pagination';list.insertAdjacentElement('afterend',controls);}controls.replaceChildren();if(pages>1){const prev=el('button','上一页','secondary'),next=el('button','下一页','secondary');prev.type=next.type='button';prev.disabled=libraryPage===0;next.disabled=libraryPage===pages-1;prev.onclick=()=>{libraryPage--;renderLibrary();};next.onclick=()=>{libraryPage++;renderLibrary();};controls.append(prev,el('span',` 第 ${libraryPage+1} / ${pages} 页 · ${filtered.length} 个 `),next);}
    const signature=JSON.stringify([libraryPage,visible]);if(list.dataset.signature===signature)return;
    list.dataset.signature=signature;endSourcePreview();libraryObserver?.disconnect();list.replaceChildren();
    libraryObserver=typeof IntersectionObserver==='function'?new IntersectionObserver(entries=>{for(const entry of entries){if(!entry.isIntersecting)continue;const video=entry.target;if(video.dataset.lazySrc){video.src=video.dataset.lazySrc;delete video.dataset.lazySrc;primeThumbnail(video,.1);}libraryObserver?.unobserve(video);}}, {root:null,rootMargin:'200px'}):null;
    if(!visible.length){list.append(el('p','当前范围暂无视频。可导入素材，或切换“全部日期”查看历史素材。','fine'));window.dispatchEvent(new Event('hub-library-render'));return;}
    const dayOf=t=>{const d=new Date(Number(t)*1000);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
    const groups=new Map();for(const item of visible){const key=item.created?dayOf(item.created):'未知日期';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(item);}
    let firstGroup=true;
    for(const [key,items] of groups){
     const section=el('details',undefined,'edit-day');section.open=firstGroup;firstGroup=false;
     const summary=el('summary',undefined,'edit-day-summary');summary.append(el('strong',key),el('span',` · ${items.length} 个`,'fine'));
     const body=el('div',undefined,'edit-day-body');section.append(summary,body);list.append(section);
     const fill=()=>{if(body.dataset.filled)return;body.dataset.filled='1';for(const item of items)body.append(renderSource(item));};
     section.addEventListener('toggle',()=>{if(section.open)fill();});
     if(section.open)fill();
    }
    window.dispatchEvent(new Event('hub-library-render'));
  }
  $('edit-footage-upload').onchange=async event=>{
    const input=event.target,files=[...input.files],status=$('edit-footage-status');if(!files.length)return;
    input.disabled=true;const errors=[];let ok=0;const token=epoch;
    for(const [index,file] of files.entries()){
      status.textContent=`正在上传 ${index+1}/${files.length}：${file.name}`;
      try{
        const response=await fetch('/api/editor/footage',{method:'POST',headers:{'X-Hub-Request':'1','Content-Type':'application/octet-stream','X-File-Name':encodeURIComponent(file.name)},body:file});
        if(!response.ok){let data;try{data=await response.json();}catch{}throw Error(data?.detail||`上传失败 (${response.status})`);}ok++;
      }catch(e){errors.push(`${file.name}：${e.message}`);}
      if(token!==epoch)break;
    }
    input.value='';input.disabled=false;if(token!==epoch)return;
    $('library-scope').value='today';status.textContent=`成功 ${ok} 个${errors.length?'；失败 '+errors.length+' 个：'+errors.join('；'):''}`;
    try{await refresh();}catch(e){status.textContent+='；刷新失败：'+e.message;}
  };
  // 左侧素材卡预览时，同一段素材同步投到剪辑台预览台，空格键在预览台控制播放/暂停。
  const sourcePreview=document.createElement('video');
  sourcePreview.id='edit-source-preview';sourcePreview.playsInline=true;sourcePreview.preload='auto';sourcePreview.hidden=true;
  const sourcePreviewTip=el('div','素材预览 · 空格 暂停','source-preview-tip');
  sourcePreviewTip.id='edit-source-preview-tip';sourcePreviewTip.hidden=true;
  $('edit-stage').append(sourcePreview,sourcePreviewTip);
  let previewCard=null,previewEmptyHidden=null;
  const paintPreviewTip=()=>{sourcePreviewTip.textContent='素材预览 · 点击或空格 '+(sourcePreview.paused?'播放':'暂停');};
  // 子卡片播放时间才是准的；预览台只做跟随，漂移超过一帧多才纠正，避免每帧 seek。
  function mirrorPreviewTime(){
    if(!previewCard||sourcePreview.paused)return;
    const time=previewCard.thumb.currentTime||0;
    if(Math.abs(sourcePreview.currentTime-time)>.3)sourcePreview.currentTime=time;
  }
  function endSourcePreview(){
    if(!previewCard)return;
    const card=previewCard;previewCard=null;
    card.thumb.removeEventListener('timeupdate',mirrorPreviewTime);
    try{card.thumb.pause();}catch(error){}
    sourcePreview.pause();sourcePreview.hidden=true;sourcePreviewTip.hidden=true;
    sourcePreview.removeAttribute('src');delete sourcePreview.dataset.url;sourcePreview.load();
    // 预览台占位文案归剪辑台自己管，退出预览时原样还原。
    if(previewEmptyHidden!==null){$('edit-empty').hidden=previewEmptyHidden;previewEmptyHidden=null;}
  }
  function startSourcePreview(item,thumb){
    const url=thumb.currentSrc||thumb.src||thumb.dataset.lazySrc||'/api/tasks/'+item.id+'/video';
    if(!url)return;
    if(previewCard&&previewCard.thumb!==thumb)endSourcePreview();
    // 预览台同一时间只放一种画面：素材预览开始就停时间轴，避免两路声音叠在一起。
    if(playing)pause();
    previewCard={item,thumb};
    if(sourcePreview.dataset.url!==url){sourcePreview.dataset.url=url;sourcePreview.src=url;sourcePreview.muted=false;}
    if(previewEmptyHidden===null)previewEmptyHidden=$('edit-empty').hidden;
    sourcePreview.hidden=false;sourcePreviewTip.hidden=false;$('edit-empty').hidden=true;
    thumb.addEventListener('timeupdate',mirrorPreviewTime);
    const seek=()=>{try{sourcePreview.currentTime=thumb.currentTime||0;}catch(error){}};
    if(sourcePreview.readyState>=1)seek();else sourcePreview.addEventListener('loadedmetadata',seek,{once:true});
    const started=sourcePreview.play();
    // 有声音的自动播放可能被浏览器拦住，退成静音继续放，预览画面不能因此卡住。
    if(started&&typeof started.catch==='function')started.catch(error=>{
      if(error&&error.name==='AbortError')return;
      sourcePreview.muted=true;const again=sourcePreview.play();
      if(again&&typeof again.catch==='function')again.catch(err=>{if(err&&err.name!=='AbortError')fail('视频无法播放，请检查格式或重新加载');});
    });
    paintPreviewTip();
  }
  function toggleSourcePreview(){
    if(!previewCard)return false;
    if(sourcePreview.paused){tryPlay(previewCard.thumb);tryPlay(sourcePreview);}
    else{previewCard.thumb.pause();sourcePreview.pause();}
    paintPreviewTip();return true;
  }
  sourcePreview.addEventListener('click',()=>toggleSourcePreview());
  sourcePreview.addEventListener('play',paintPreviewTip);
  sourcePreview.addEventListener('pause',paintPreviewTip);
  function renderSource(item){
    const card=el('div',undefined,'edit-source source-card'), frame=el('div',undefined,'source-frame');
    const thumb=el('video');thumb.preload='metadata';thumb.muted=true;thumb.playsInline=true;
    const url='/api/tasks/'+item.id+'/video';if(libraryObserver){thumb.dataset.lazySrc=url;libraryObserver.observe(thumb);}else{thumb.src=url;primeThumbnail(thumb,.1);}
    let start=0,end=item.duration;
    const duration=el('span',`${Math.floor(item.duration/60)}:${String(Math.floor(item.duration%60)).padStart(2,'0')}`,'source-duration');
    const range=el('div',undefined,'source-trim'),left=el('button',undefined,'source-trim-handle source-trim-in'),right=el('button',undefined,'source-trim-handle source-trim-out');
    for(const [handle,label] of [[left,'调整入点'],[right,'调整出点']]){handle.type='button';handle.setAttribute('aria-label',label);handle.title=label;}
    range.append(left,right);range.hidden=true;
    const playhead=el('div',undefined,'source-playhead');playhead.hidden=true;playhead.setAttribute('role','slider');playhead.setAttribute('aria-label','预览位置');playhead.setAttribute('aria-valuemin','0');playhead.setAttribute('aria-valuemax',String(item.duration));playhead.tabIndex=0;
    const paintPlayhead=()=>{const time=Math.max(0,Math.min(item.duration,thumb.currentTime||0));playhead.style.left=(time/item.duration*100)+'%';playhead.setAttribute('aria-valuenow',time.toFixed(2));};
    const paintRange=()=>{range.style.left=(start/item.duration*100)+'%';range.style.width=((end-start)/item.duration*100)+'%';};
    const activate=()=>{document.querySelectorAll('#edit-library-list .source-card.is-active').forEach(other=>{if(other!==card){other.classList.remove('is-active');other.querySelector('video').pause();other.querySelector('.source-trim').hidden=true;other.querySelector('.source-playhead').hidden=true;}});if(previewCard&&previewCard.thumb!==thumb)endSourcePreview();card.classList.add('is-active');range.hidden=false;playhead.hidden=false;paintRange();paintPlayhead();};
    thumb.addEventListener('timeupdate',paintPlayhead);thumb.addEventListener('seeked',paintPlayhead);thumb.addEventListener('ended',paintPlayhead);
    // 卡片自身开始播放/暂停时，预览台跟着走；空格键的开关也复用这条链路。
    thumb.addEventListener('play',()=>startSourcePreview(item,thumb));
    thumb.addEventListener('pause',()=>{if(previewCard&&previewCard.thumb===thumb)sourcePreview.pause();});
    frame.draggable=true;frame.title='点击播放或暂停预览；拖动画面到时间轴';frame.addEventListener('click',()=>{activate();if(!thumb.paused){thumb.pause();return;}if(thumb.ended)thumb.currentTime=0;const playing=thumb.play();if(playing?.catch)playing.catch(()=>fail('视频无法播放，请检查格式或重新加载'));});
    const seekFromPointer=e=>{const r=frame.getBoundingClientRect();thumb.currentTime=Math.max(0,Math.min(item.duration,(e.clientX-r.left)/r.width*item.duration));paintPlayhead();};
    playhead.onpointerdown=e=>{e.preventDefault();e.stopPropagation();thumb.pause();playhead.setPointerCapture(e.pointerId);seekFromPointer(e);};
    playhead.onpointermove=e=>{if(playhead.hasPointerCapture(e.pointerId))seekFromPointer(e);};
    playhead.onclick=e=>e.stopPropagation();playhead.ondragstart=e=>{e.preventDefault();e.stopPropagation();};
    playhead.onkeydown=e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();e.stopPropagation();thumb.pause();thumb.currentTime=Math.max(0,Math.min(item.duration,(thumb.currentTime||0)+(e.key==='ArrowRight'?.1:-.1)));paintPlayhead();};
    frame.ondragstart=e=>{if(e.target.closest('button,input')){e.preventDefault();return;}activate();e.dataTransfer.setData('application/x-seedance-task',item.id);e.dataTransfer.setData('application/x-seedance-range',JSON.stringify({start,end}));e.dataTransfer.effectAllowed='copy';};
    for(const [handle,edge] of [[left,'in'],[right,'out']]){
      handle.onpointerdown=e=>{e.preventDefault();e.stopPropagation();activate();handle.setPointerCapture(e.pointerId);};
      handle.onpointermove=e=>{if(!handle.hasPointerCapture(e.pointerId))return;const r=frame.getBoundingClientRect(),t=Math.max(0,Math.min(item.duration,(e.clientX-r.left)/r.width*item.duration));if(edge==='in')start=Math.min(t,end-.1);else end=Math.max(t,start+.1);thumb.currentTime=edge==='in'?start:end;paintPlayhead();paintRange();};
      handle.onclick=e=>e.stopPropagation();
      handle.onkeydown=e=>{if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();e.stopPropagation();activate();const t=(edge==='in'?start:end)+(e.key==='ArrowRight'?.1:-.1);if(edge==='in')start=Math.max(0,Math.min(t,end-.1));else end=Math.min(item.duration,Math.max(t,start+.1));thumb.currentTime=edge==='in'?start:end;paintPlayhead();paintRange();};
    }
    const addButton=el('button','+','source-add');addButton.type='button';addButton.title='将选中片段加入时间轴';addButton.setAttribute('aria-label','加入选中片段：'+(item.title||'视频'));addButton.onclick=e=>{e.stopPropagation();add(item.id,start,end);};
    frame.append(thumb,duration,range,playhead,addButton);const title=el('strong',item.title||'生成视频');title.title=item.title||'生成视频';card.append(frame,title);paintRange();return card;
  }
  function render(){
    if(!project)return;HubTimeline.migrate(project.body);position=HubTimeline.clamp(position,total());
    $('edit-title').value=project.title;$('edit-ratio').value=project.body.ratio;
    $('edit-stage').className='edit-stage '+({'9:16':'portrait','16:9':'landscape','1:1':'square'}[project.body.ratio]);
    $('edit-empty').hidden=clips().length>0;$('edit-player').hidden=true;
    $('edit-export').disabled=busy||!total();$('edit-play').disabled=!total();
    $('edit-save-state').textContent=dirty?'有未保存的更改':project.id?'已保存':'尚未保存';
    $('edit-seek').max=HubTimeline.lastFrame(total());renderTimeline();renderProperties();renderSpeed();renderCaptions();renderProjects();renderAudio();renderDetached();renderCaptionPanels();window.hubMultitrackPreview?.sync(project.body,position,playing);paint();announce();paintPlayhead();if(lastEdit===null)historyReset();$('edit-undo').disabled=!undo.length;$('edit-redo').disabled=!redo.length;
  }
  // 字幕「效果 / 动画」面板跟随项目内容刷新：统一模式下不选字幕也能直接套用，面板不该停在空状态。
  function renderCaptionPanels(){
    if($('editor-subtitle-effects'))renderSubtitleEffects();
    if($('editor-subtitle-animations'))renderSubtitleAnimations();
  }
  function renderTimeline(){
    const list=$('edit-clips');list.replaceChildren();timelineVideoNodes=[];
    for(const clip of videoSelection)if(!clips().includes(clip))videoSelection.delete(clip);
    if(!clips().length){queueMicrotask(()=>drawTracks());return;}
    clips().forEach((clip,i)=>{
      const button=el('button',undefined,'edit-clip'+((videoSelection.size?videoSelection.has(clip):!trackSelection&&selected===i)?' selected':''));button.draggable=true;button.type='button';button.setAttribute('aria-pressed',String(videoSelection.size?videoSelection.has(clip):!trackSelection&&selected===i));
      button.dataset.timelineKey='video:'+i;
      button.style.flex=`0 0 ${length(clip)*(window.hubTimelineScale||32)}px`;
      const thumb=el('div',undefined,'timeline-preview frame-ready');thumb.setAttribute('role','img');thumb.setAttribute('aria-label','视频缩略图胶片');thumb.style.backgroundImage='url("/api/editor/thumbnail/'+encodeURIComponent(clip.task_id)+'?at='+Math.max(0,clip.start).toFixed(3)+'")';button.append(thumb);
      for(const edge of ['start','end']){const handle=el('span',undefined,'trim-handle trim-'+edge);handle.title=edge==='start'?'拖动裁剪入点':'拖动裁剪出点';handle.onpointerdown=e=>beginTrim(e,clip,i,edge,button);handle.onclick=e=>e.stopPropagation();button.append(handle);}
      const rate=clip.speed||1;
      button.append(el('span',`片段 ${i+1} · ${seconds(length(clip))} 秒${Math.abs(rate-1)>.001?` · ${rate}×`:''}`,'clip-meta'),el('strong',source(clip.task_id)?.title||'视频片段','clip-title'),el('small',`${seconds(clip.start)} → ${seconds(clip.end)} 秒`,'clip-range'));
      button.onclick=event=>{if(suppressTimelineClick)return;marqueeSelectionActive=false;if(expandKeys(['video:'+i]).length>1){setTimelineSelection(event.ctrlKey||event.metaKey||event.shiftKey?[...selectedKeys(),'video:'+i]:['video:'+i]);scroll.focus({preventScroll:true});return;}timelineSelection.clear();trackSelection=null;pause();if(event.shiftKey){for(let n=Math.min(selectionAnchor,i);n<=Math.max(selectionAnchor,i);n++)videoSelection.add(clips()[n]);}else if(event.ctrlKey||event.metaKey){if(videoSelection.has(clip))videoSelection.delete(clip);else videoSelection.add(clip);selectionAnchor=i;}else{videoSelection.clear();videoSelection.add(clip);selectionAnchor=i;}selected=i;renderTimeline();renderProperties();renderSpeed();paintRange();timelineVideoNodes[i]?.focus({preventScroll:true});};
      button.oncontextmenu=event=>{event.preventDefault();timelineSelection.clear();trackSelection=null;pause();if(!videoSelection.has(clip)){videoSelection.clear();videoSelection.add(clip);}selected=i;renderTimeline();renderProperties();if(expandKeys(['video:'+i]).length>1)setTimelineSelection(['video:'+i]);openClipMenu(event.clientX,event.clientY);};
      button.onkeydown=event=>{if(event.key==='ContextMenu'||(event.shiftKey&&event.key==='F10')){event.preventDefault();selected=i;renderProperties();const box=button.getBoundingClientRect();openClipMenu(box.left,box.bottom);}};
      button.ondragstart=event=>{if(expandKeys(['video:'+i]).length>1)setTimelineSelection(['video:'+i]);if(!videoSelection.has(clip)){videoSelection.clear();videoSelection.add(clip);}dragIndex=i;event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',String(i));};
      button.ondragover=event=>showInsertion(event);button.ondrop=event=>dropInsertion(event);button.ondragend=()=>{dragIndex=null;clearInsertion();};timelineVideoNodes.push(button);list.append(button);
    });
    queueMicrotask(()=>drawTracks());
  }
  function insertionAt(x){
    const nodes=[...$('edit-clips').querySelectorAll('.edit-clip')];
    const index=nodes.findIndex(n=>{const r=n.getBoundingClientRect();return x<r.left+r.width/2;});
    return index<0?clips().length:index;
  }
  function clearInsertion(){ const list=$('edit-clips');list.classList.remove('drop-target');list.querySelectorAll('.drop-before,.drop-after').forEach(n=>n.classList.remove('drop-before','drop-after')); }
  function showInsertion(event){
    if(busy)return;const types=Array.from(event.dataTransfer?.types||[]);
    const items=[...(event.dataTransfer?.items||[])].filter(i=>i.kind==='file');
    // 视频文件拖进时间轴要按「插入视频片段」处理，不能沿用音频轨高亮。
    const fileAudio=items.length?items.some(i=>/^audio\//i.test(i.type||''))&&!items.some(i=>/^video\//i.test(i.type||'')):types.includes('Files');
    const audio=types.includes('application/x-seedance-audio')||fileAudio;
    event.preventDefault();event.stopPropagation();
    if(audio&&!dragIndex&&!types.includes('application/x-seedance-task')){
      const lane=$('edit-clips');lane.classList.add('drop-target');
      const r=scroll.getBoundingClientRect();if(event.clientX>r.right-48)scroll.scrollLeft+=24;else if(event.clientX<r.left+104+48)scroll.scrollLeft-=24;
      return;
    }
    clearInsertion();
    const nodes=$('edit-clips').querySelectorAll('.edit-clip'),i=insertionAt(event.clientX);
    if(nodes.length)nodes[Math.min(i,nodes.length-1)].classList.add(i===nodes.length?'drop-after':'drop-before');
    const r=scroll.getBoundingClientRect();if(event.clientX>r.right-48)scroll.scrollLeft+=24;else if(event.clientX<r.left+104+48)scroll.scrollLeft-=24;
  }
  function dropInsertion(event){
    event.preventDefault();event.stopPropagation();clearInsertion();$('edit-clips').classList.remove('drop-target');if(busy||!project)return;
    const audioId=event.dataTransfer.getData('application/x-seedance-audio'),files=[...(event.dataTransfer.files||[])];
    const at0=Math.max(0,(event.clientX-$('timeline-ruler').getBoundingClientRect().left-104)/(window.hubTimelineScale||32));
    if(audioId){insertAudioAssetAt(audioId,null,at0).catch(err=>fail(err));return;}
    if(!event.dataTransfer.getData('application/x-seedance-task')&&files.length){insertDroppedFiles(files,null,at0).catch(err=>fail(err));return;}
    const at=insertionAt(event.clientX),all=clips();let insert=[];
    if(dragIndex!==null&&expandKeys(['video:'+dragIndex]).length>1){setTimelineSelection(['video:'+dragIndex]);moveSelectionTo(offset(Math.min(at,clips().length)));dragIndex=null;return;}
    if(dragIndex!==null){insert=all.filter(c=>videoSelection.has(c));if(!insert.length&&all[dragIndex])insert=[all[dragIndex]];}
    else {const item=source(event.dataTransfer.getData('application/x-seedance-task'));if(!item)return;if(all.length>=50)return fail('最多 50 个片段');insert=[{task_id:item.id,start:0,end:item.duration,volume:1,speed:1}];}
    const before=all.slice(0,at).filter(c=>!insert.includes(c)).length,rest=all.filter(c=>!insert.includes(c));rest.splice(before,0,...insert);
    dragIndex=null;if(rest.length===all.length&&rest.every((c,i)=>c===all[i]))return;
    const main=HubLayout.mainTrack(project.body);pause();editTimeline(()=>{project.body.clips=rest;let cursor=0;for(const c of rest){if((c.track||HubLayout.MAIN)!==main&&!insert.includes(c))continue;c.track=main;c.at=HubLayout.q(cursor);cursor+=length(c);}},null,null,{main});videoSelection.clear();insert.forEach(c=>videoSelection.add(c));selected=before;mark();render();seek(offset(selected));
  }
  function trackMuted(id){return !!project?.body.tracks?.find(t=>t.id===id)?.muted;}
  function drawTracks(){
    if(!project||!window.hubMultitrackView)return;HubTimeline.migrate(project.body);audioTimeline();
    window.hubMultitrackView.render(project.body,timelineVideoNodes,[...$('track-detached').children],{
      suppressed:()=>suppressTimelineClick,
      select:(key,node)=>{const [kind,index]=key.split(':');if(kind==='caption')primaryCaption=Number(index);selectTrack(kind,Number(index),node);if(kind==='caption'){runSelectionSync(true);window.hubEditorShell?.openRight?.('text');}},
      seekAt:event=>{const r=$('timeline-ruler').getBoundingClientRect();pause();seek((event.clientX-r.left-104)/(window.hubTimelineScale||32));},
      move:beginTimelineMove,
      selectCaptionTrack:id=>{const keys=project.body.captions.flatMap((c,i)=>(c.track||'caption-main')===id?['caption:'+i]:[]);if(!keys.length)return;if(keys.some(k=>project.body.captions[Number(k.slice(8))].locked))return fail('该字幕轨包含锁定字幕，请先解锁');if(expandKeys(keys).some(k=>!keys.includes(k)))return fail('本轨字幕与其他轨道组合，请先取消组合或解除复合片段');setTimelineSelection(keys,{primary:Number(keys[0].slice(8))});toast(`已选中本轨 ${keys.length} 条字幕，可拖动整轨`);scroll.focus({preventScroll:true});},
      resizeCaption:beginCaptionTrim,
      reorderTrack:(id,delta)=>{
        const tracks=project.body.tracks,index=tracks.findIndex(t=>t.id===id),target=index+delta;
        if(index<0||target<0||target>=tracks.length)return;
        commitEdits();pause();
        [tracks[index],tracks[target]]=[tracks[target],tracks[index]];
        mark();render();seek(position);
      },
      mute:id=>{const t=project.body.tracks.find(t=>t.id===id);if(t){pause();t.muted=!t.muted;mark();render();seek(position);}},
      addTrack:()=>{if(project.body.tracks.length>=100)return fail('最多 100 条轨道');const id='track-'+crypto.randomUUID();project.body.tracks.push({id,muted:false});window.hubMultitrackView.revealEmpty(id);mark();render();},
      insertAudio:(id,track,time)=>{insertAudioAssetAt(id,track,time).then(at=>seek(at)).catch(err=>fail(err));},
      insertAudioFiles:(files,track,time)=>{insertDroppedFiles(files,track,time).catch(err=>fail(err));},
      insertSticker:(style,track,time)=>{window.hubStickers?.add(style,time,track);},
      volume:(key,anchor)=>openVolumePopover(key,anchor),
      // With main-track magnet enabled, insert at the nearest existing clip boundary.
      insert:(id,track,time,range)=>{
        endSourcePreview();
        const item=source(id);if(!item)return fail('原视频暂不可用，请刷新素材');
        const start=range?.start??0,end=range?.end??item.duration;
        if(!Number.isFinite(start)||!Number.isFinite(end)||start<0||end>item.duration||end-start<.1-1e-7)return fail('请选择至少 0.1 秒的有效片段');
        if(clips().length>=50)return fail('每个项目最多 50 个片段');
        const first=!clips().length,knownMain=project.body.main_track||project.body.tracks.some(t=>t.id===HubLayout.MAIN),currentMain=HubLayout.mainTrack(project.body);
        const createTrack=!track&&!(first&&magnetOn);if(createTrack&&project.body.tracks.length>=100)return fail('最多 100 条轨道');
        if(!track)track=first&&magnetOn?currentMain:'track-'+crypto.randomUUID();
        const main=first&&!knownMain?track:currentMain,packDrop=magnetOn&&track===main;
        pause();
        const span=HubLayout.len({start,end,speed:1}),drop=Math.max(0,HubLayout.q(time));
        let at=drop,order=null;
        if(packDrop){
          order=clips().filter(c=>(c.track||HubLayout.MAIN)===main).sort((a,b)=>a.at-b.at);
          const slot=order.findIndex(c=>drop<(c.at||0)+HubLayout.len(c)/2);if(slot<0)order.push(null);else order.splice(slot,0,null);
        }else{
          const snapped=snapSpan(drop,drop+span,[position,...boundaries()]);showGuide(null);
          const proposed=Math.max(0,HubLayout.q(snapped));
          const peers=timelineEntries().filter(r=>!r.key.startsWith('caption:')&&r.key!=='audio:0'&&laneOf(r)===track).map(r=>({start:r.start,end:r.end,lane:track}));
          const free=HubLayout.resolveMove([{start:proposed,end:proposed+span,lane:track}],peers,0);
          if(free===null)return fail('该位置已被占用，请放到空闲位置');at=Math.max(0,proposed+free);
        }
        const clip={task_id:id,start,end,speed:1,volume:1,at,track};
        editTimeline(()=>{if(createTrack||!project.body.tracks.some(t=>t.id===track))project.body.tracks.push({id:track,muted:false});clips().push(clip);if(order){let cursor=0;for(const existing of order){const c=existing||clip;c.at=HubLayout.q(cursor);cursor+=HubLayout.len(c);}}},null,null,{main,magnet:packDrop});
        selected=clips().length-1;mark();render();revealAt(clip.at,span);seek(offset(selected));
      }
    });paintPlayhead();paintRange();window.dispatchEvent(new Event('hub-bundles'));
  }
  // Scroll the timeline horizontally so a freshly dropped clip is fully visible (centred when too wide).
  function revealAt(at,span){
    if(!scroll)return;const scale=window.hubTimelineScale||32,view=Math.max(1,scroll.clientWidth-104);
    const startPx=104+at*scale,endPx=104+(at+span)*scale,left=scroll.scrollLeft,right=left+scroll.clientWidth;
    if(startPx>=left+24&&endPx<=right-24)return;
    if(endPx-startPx>view-48){scroll.scrollLeft=Math.max(0,startPx-24);return;}
    scroll.scrollLeft=Math.max(0,(startPx+endPx)/2-scroll.clientWidth/2);
  }
  let volumePopover=null;
  function closeVolumePopover(){
    if(!volumePopover)return;
    volumePopover.remove();volumePopover=null;
    document.removeEventListener('pointerdown',volumeOutside,true);
    document.removeEventListener('keydown',volumeEscape,true);
    scroll?.removeEventListener('scroll',closeVolumePopover);
  }
  function volumeOutside(event){if(volumePopover&&!volumePopover.contains(event.target)&&!event.target.closest?.('.clip-vol'))closeVolumePopover();}
  function volumeEscape(event){if(event.key==='Escape')closeVolumePopover();}
  // Resolve a timeline key to the volume it edits, plus live-preview plumbing.
  function volumeTarget(key){
    const [kind,index]=String(key).split(':'),i=Number(index);
    if(kind==='video'){const clip=clips()[i];if(!clip)return null;return {clip,label:'视频音量',get:()=>clip.volume??1,set:value=>{clip.volume=value;if(Number(player.dataset.clip)===i)player.volume=Math.min(1,value);window.hubMultitrackPreview?.sync(project.body,position,playing);},muted:()=>false,setMuted:null};}
    if(kind==='detached'){const clip=(project.body.audio_clips||[])[i];if(!clip)return null;return {clip,label:'音频音量',get:()=>clip.volume??1,set:value=>{clip.volume=value;const audio=detachedPlayers[i];if(audio)audio.volume=clip.muted?0:Math.min(1,value);},muted:()=>!!clip.muted,setMuted:muted=>{clip.muted=!!muted;const audio=detachedPlayers[i];if(audio)audio.volume=muted?0:Math.min(1,clip.volume??1);}};}
    if(kind==='audio'){const clip=project.body.audio;if(!clip)return null;return {clip,label:'配乐音量',get:()=>clip.volume??.7,set:value=>{clip.volume=value;voice.volume=Math.min(1,value);},muted:()=>false,setMuted:null};}
    return null;
  }
  function refreshVolumeChip(key,value){
    const node=[...document.querySelectorAll('#multi-tracks [data-timeline-key]')].find(n=>n.dataset.timelineKey===key),chip=node?.querySelector('.clip-vol');
    if(chip){chip.textContent=value<=0?'🔇':'🔊';chip.title=`音量 ${Math.round(value*100)}%（点击调节）`;chip.setAttribute('aria-label',chip.title);}
    if(String(key).startsWith('detached:'))audioTimeline();
  }
  // CapCut-style volume popover: 0–200 % slider plus mute / reset, anchored above the clip button.
  function openVolumePopover(key,anchor){
    const keys=selectedKeys(),targets=(keys.length>1&&keys.includes(key)?keys:[key]).map(k=>({key:k,target:volumeTarget(k)})).filter(x=>x.target);if(!targets.length)return;
    const first=targets[0].target,target=targets.length===1?first:{label:`统一音量（${targets.length} 个片段）`,get:first.get,muted:()=>targets.every(x=>x.target.muted()),set:value=>targets.forEach(x=>{x.target.set(value);refreshVolumeChip(x.key,value);}),setMuted:muted=>targets.forEach(x=>x.target.setMuted?.(muted))};
    closeVolumePopover();pause();
    const pop=el('div',undefined,'volume-pop');pop.setAttribute('role','dialog');pop.setAttribute('aria-label',target.label);
    const head=el('div',undefined,'volume-pop-head'),title=el('strong',target.label),read=el('span','','volume-pop-value');
    head.append(title,read);
    const range=el('input');range.type='range';range.min=0;range.max=200;range.step=5;range.className='volume-pop-range';range.setAttribute('aria-label',target.label+'百分比');
    const mute=el('button',undefined,'secondary');mute.type='button';
    const reset=el('button','100%','secondary');reset.type='button';reset.title='恢复默认音量';
    const sync=()=>{
      const value=Math.max(0,Math.min(2,Number(target.get())||0)),silent=target.muted()||value<=0;
      range.value=String(Math.round(value*100));read.textContent=Math.round(value*100)+'%';
      mute.textContent=silent?'恢复声音':'静音';mute.setAttribute('aria-pressed',String(silent));
    };
    let restore=Math.max(.1,Math.min(2,Number(target.get())||1));
    range.oninput=()=>{const value=Number(range.value)/100;if(value>0){restore=value;target.setMuted?.(false);}target.set(value);read.textContent=range.value+'%';mute.textContent=value<=0?'恢复声音':'静音';mark();refreshVolumeChip(key,value);};
    range.onchange=()=>{mark();};
    mute.onclick=()=>{
      const silent=target.muted()||Number(target.get())<=0;
      if(target.setMuted)target.setMuted(!silent);
      target.set(silent?restore:0);
      mark();refreshVolumeChip(key,target.get());sync();
    };
    reset.onclick=()=>{target.setMuted?.(false);target.set(1);mark();refreshVolumeChip(key,1);sync();};
    const foot=el('div',undefined,'volume-pop-foot');foot.append(mute,reset);
    pop.append(head,range,foot);
    document.body.append(pop);volumePopover=pop;
    const box=anchor.getBoundingClientRect(),width=pop.offsetWidth||216,height=pop.offsetHeight||96;
    pop.style.left=Math.max(8,Math.min(window.innerWidth-width-8,box.left+box.width/2-width/2))+'px';
    pop.style.top=Math.max(8,box.top-height-8)+'px';
    document.addEventListener('pointerdown',volumeOutside,true);
    document.addEventListener('keydown',volumeEscape,true);
    scroll?.addEventListener('scroll',closeVolumePopover);
    sync();range.focus({preventScroll:true});
  }
  let suppressTimelineClick=false;
  function beginCaptionTrim(event,index,edge,node){
    if(event.button===0&&!busy&&beginMultiVideoTrim(event,null,'caption:'+index,edge))return;
    if(event.button!==0||busy)return;event.preventDefault();event.stopPropagation();pause();
    const caption=project.body.captions[index],target=project;if(!caption)return;const original={start:caption.start,end:caption.end},scale=window.hubTimelineScale||32,x=event.clientX;
    const peers=project.body.captions.filter(c=>c!==caption&&(c.track||'caption-main')===(caption.track||'caption-main'));
    const before=Math.max(0,...peers.filter(c=>c.end<=original.start+1e-6).map(c=>c.end)),after=Math.min(Infinity,...peers.filter(c=>c.start>=original.end-1e-6).map(c=>c.start));
    const points=[0,position,...timelineEntries().filter(r=>r.item!==caption).flatMap(r=>[r.start,r.end])];let value=original[edge];
    const move=e=>{const raw=snapTime(original[edge]+(e.clientX-x)/scale,points);value=qf(edge==='start'?Math.max(before,Math.min(original.end-1/24,raw)):Math.min(after,Math.max(original.start+1/24,raw)));node.style.left=(edge==='start'?value:original.start)*scale+'px';node.style.width=((edge==='start'?original.end-value:value-original.start)*scale)+'px';};
    const clean=()=>{window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('blur',cancel);showGuide(null);};
    const finish=()=>{clean();if(project===target&&value!==original[edge]){caption[edge]=value;mark();render();setTimelineSelection(['caption:'+index],{primary:index});}else renderTimeline();};const cancel=()=>{clean();renderTimeline();};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('blur',cancel);
  }
  function beginTimelineMove(event,key,node){
    if(event.button!==0||busy||event.target.closest('.trim-handle,.audio-grip'))return;
    commitEdits();if(key.startsWith('caption:'))primaryCaption=Number(key.slice(8));
    const before=new Set(selectedKeys());if(event.shiftKey&&key.startsWith('video:')){const i=Number(key.split(':')[1]);for(let n=Math.min(selected,i);n<=Math.max(selected,i);n++)before.add('video:'+n);setTimelineSelection([...before]);}else if(event.ctrlKey||event.metaKey){if(before.has(key))before.delete(key);else before.add(key);setTimelineSelection([...before]);}else if(!before.has(key))setTimelineSelection([key]);
    const keys=new Set(expandKeys(selectedKeys())),entries=timelineEntries().filter(r=>keys.has(r.key));if(entries.some(r=>r.item.locked)||entries.some(r=>r.key==='audio:0'))return;
    pause();const x=event.clientX,y=event.clientY,scale=window.hubTimelineScale||32,start=Math.min(...entries.map(r=>r.start)),trackIndex=project.body.tracks.findIndex(t=>t.id===entries.find(r=>r.key===key)?.item.track),points=[0,position,...rangePoints(),...timelineEntries().filter(r=>!keys.has(r.key)).flatMap(r=>[r.start,r.end])];let dx=0,dy=0,moved=false,last=event,pending=0;
    if(!entries.length)return;
    let ghosts=[],snapLatch=null;
    const visualRows=[...scroll.querySelectorAll('#multi-tracks .multi-track:not(.new-track)')];
    const visual=visualRows.map(n=>n.dataset.trackId),sourceVisual=visual.indexOf(entries.find(r=>r.key===key)?.item.track);
    const landing=()=>{
      const target=document.elementFromPoint(last.clientX,last.clientY)?.closest('[data-track-id]');
      const targetVisual=visual.indexOf(target?.dataset.trackId),lanes=new Map();
      for(const r of entries){const old=visual.indexOf(r.item.track),index=Math.max(0,Math.min(visual.length-1,old+(targetVisual<0?0:targetVisual-sourceVisual)));lanes.set(r.key,visual[index]||r.item.track);}
      return {target,lanes};
    };
    const makeGhosts=()=>{
      const nodes=[...scroll.querySelectorAll('[data-timeline-key],[data-timeline-keys]')].filter(n=>!n.classList.contains('compound-member-hidden')&&(keys.has(n.dataset.timelineKey)||n.dataset.timelineKeys&&JSON.parse(n.dataset.timelineKeys).some(k=>keys.has(k))));
      for(const original of nodes){
        const box=original.getBoundingClientRect(),copy=original.cloneNode(true);
        const originals=[original,...original.querySelectorAll('*')],copies=[copy,...copy.querySelectorAll('*')];
        originals.forEach((n,i)=>{const style=getComputedStyle(n);for(const prop of style)copies[i].style.setProperty(prop,style.getPropertyValue(prop));copies[i].style.setProperty('pointer-events','none','important');copies[i].removeAttribute('id');copies[i].removeAttribute('data-timeline-key');copies[i].removeAttribute('data-timeline-keys');});
        copy.style.cssText+=`;position:fixed!important;left:${box.left}px!important;top:${box.top}px!important;width:${box.width}px!important;height:${box.height}px!important;bottom:auto!important;margin:0!important;z-index:2147483000!important;pointer-events:none!important;opacity:.85!important;transition:none!important;`;
        copy.setAttribute('aria-hidden','true');document.body.append(copy);
        ghosts.push({original,copy,opacity:original.style.opacity,track:original.closest('[data-track-id]')?.dataset.trackId});original.style.opacity='.25';
      }
    };
    const apply=()=>{pending=0;dx=last.clientX-x+pan.delta();dy=last.clientY-y;if(!moved&&Math.hypot(dx,dy)<4)return;
      if(!moved)makeGhosts();moved=true;trimmingActive=true;
      const span=Math.max(...entries.map(r=>r.end))-start,raw=start+dx/scale;
      let snapped;
      if(snapLatch!==null&&snapEnabled&&!altHeld&&Math.abs(raw-snapLatch)*scale<14){snapped=snapLatch;}
      else {snapped=snapSpan(raw,raw+span,points,entries.flatMap(r=>[r.start-start,r.end-start]));snapLatch=snapEnabled&&!altHeld&&Math.abs(snapped-raw)>1e-7?snapped:null;}
      const {target,lanes}=landing(),newLane=['new','new-caption'].includes(target?.dataset.trackId);
      const wanted=Math.max(0,Math.round(snapped*24)/24)-start;
      const free=newLane?wanted:resolveDelta(entries,wanted,lanes);
      const invalid=free===null||(target?.dataset.trackId==='new-caption'&&(entries.length!==1||!key.startsWith('caption:')));
      dx=(free===null?wanted:free)*scale;
      if(free!==null&&Math.abs(free-wanted)>1e-6){showGuide(null);snapLatch=null;}
      for(const g of ghosts){const targetTrack=lanes.get(g.original.dataset.timelineKey)||lanes.get(key),from=visualRows.find(n=>n.dataset.trackId===g.track),to=visualRows.find(n=>n.dataset.trackId===targetTrack);
        const vertical=newLane?dy:from&&to?to.getBoundingClientRect().top-from.getBoundingClientRect().top:dy;
        g.copy.style.transform=`translate(${dx-pan.delta()}px,${vertical}px)`;
        g.copy.style.outline=invalid?'2px solid #f0b0aa':'1px solid #d5e5f0';
      }
      dragNote.textContent=invalid?'无法放置':(start+dx/scale).toFixed(2)+' 秒'+(Math.abs(dx/scale-wanted)>1e-6?' · 避让相邻片段':snapLatch!==null?' · 已吸附':'');
    };
    const move=e=>{last={clientX:e.clientX,clientY:Number.isFinite(e.clientY)?e.clientY:last.clientY};if(!pending)pending=requestAnimationFrame(apply);};
    const pan=edgeScroll(event,move);
    const clean=()=>{pan.stop();cancelAnimationFrame(pending);pending=0;trimmingActive=false;for(const g of ghosts){g.original.style.opacity=g.opacity;g.copy.remove();}ghosts=[];showGuide(null);dragNote.textContent='';window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('blur',cancel);window.removeEventListener('keydown',escape);};
    const finish=()=>{if(pending){cancelAnimationFrame(pending);apply();}clean();if(!moved)return;suppressTimelineClick=true;setTimeout(()=>suppressTimelineClick=false,0);
      const target=document.elementFromPoint(last.clientX,last.clientY)?.closest('[data-track-id]');let to=target?project.body.tracks.findIndex(t=>t.id===target.dataset.trackId):trackIndex;
      const trackCount=project.body.tracks.length;
      if(target?.dataset.trackId==='new-caption'&&(entries.length!==1||!entries[0].key.startsWith('caption:'))){render();return fail('请拖动一条字幕到此区域以创建轨道');}
      if(target?.dataset.trackId==='new'||target?.dataset.trackId==='new-caption'){project.body.tracks.push({id:(target.dataset.trackId==='new-caption'?'caption-':'track-')+crypto.randomUUID(),muted:false});to=project.body.tracks.length-1;}
      const visual=[...scroll.querySelectorAll('#multi-tracks .multi-track:not(.new-track)')].map(n=>n.dataset.trackId),sourceVisual=visual.indexOf(entries.find(r=>r.key===key)?.item.track),targetVisual=visual.indexOf(target?.dataset.trackId);
      const lanes=new Map();if(to>=0)for(const r of entries){if(entries.length===1){lanes.set(r.key,project.body.tracks[to].id);continue;}const old=visual.indexOf(r.item.track),index=Math.max(0,Math.min(visual.length-1,old+(targetVisual<0?0:targetVisual-sourceVisual)));lanes.set(r.key,visual[index]||r.item.track);}
      const free=resolveDelta(entries,dx/scale,lanes);
      if(free===null){project.body.tracks.length=trackCount;render();return fail('该位置已被占用，请放到空闲位置');}
      editTimeline(()=>{for(const r of entries){if(r.key.startsWith('caption:')||r.key.startsWith('sticker:')){const d=Math.max(free,-r.item.start);r.item.start+=d;r.item.end+=d;}else r.item.at=Math.max(0,r.start+free);if(lanes.has(r.key))r.item.track=lanes.get(r.key);}},undefined,new Set(entries.map(r=>r.item)));
      mark();render();setTimelineSelection([...keys]);
    };
    const cancel=()=>{clean();};const escape=e=>{if(e.key==='Escape'){e.preventDefault();cancel();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('blur',cancel);window.addEventListener('keydown',escape);
  }
  function primeThumbnail(video,time){
    const showFrame=()=>{
      if(!Number.isFinite(video.duration)||video.duration<=0)return;
      const target=Math.max(0,Math.min(Number(time)||0,Math.max(0,video.duration-.04)));
      if(Math.abs(video.currentTime-target)>.01)video.currentTime=target;
    };
    video.addEventListener('loadedmetadata',showFrame,{once:true});
    video.addEventListener('seeked',()=>video.classList.add('frame-ready'),{once:true});
    if(video.readyState>=1)showFrame();
  }
  function renderProperties(){
    selected=Math.max(0,Math.min(selected,clips().length-1));const rows=selectedRows(),clip=rows.length===1&&rows[0].key.startsWith('video:')?rows[0].item:null;
    $('edit-clip-fields').disabled=!clip;$('edit-detach').disabled=!clip;$('edit-remove').disabled=!canDeleteSelection();
    $('edit-selection').textContent=clip?`片段 ${selected+1} · 原片 ${seconds(source(clip.task_id)?.duration||clip.end)} 秒`:rows.length?`已选择 ${rows.length} 个时间轴对象`:'先在时间轴选择片段';
    if(clip){
      const max=source(clip.task_id)?.duration||clip.end;
      for(const id of ['edit-in','edit-in-range']){$(id).max=max;$(id).value=seconds(clip.start);}
      for(const id of ['edit-out','edit-out-range']){$(id).max=max;$(id).value=seconds(clip.end);}
      $('edit-volume').value=clip.volume;$('edit-earlier').disabled=selected===0;$('edit-later').disabled=selected===clips().length-1;
    }
    document.querySelectorAll('[data-edit-action]').forEach(b=>{const id=b.dataset.editAction;b.disabled=id==='edit-remove'?$('edit-remove').disabled:id==='edit-split'&&(selectedCompound()||selectedRows().some(r=>r.key.startsWith('sticker:')))?false:!clip||$(id).disabled;});
  }
  const speedPanel=el('div',undefined,'editor-side-panel');speedPanel.id='editor-speed-panel';
  const speedSelection=el('p','先在时间轴选择片段','fine');speedSelection.id='speed-selection';
  const speedFields=el('fieldset');speedFields.id='speed-fields';speedFields.disabled=true;
  const presets=el('div',undefined,'speed-presets');presets.id='speed-presets';presets.setAttribute('role','group');presets.setAttribute('aria-label','常用倍速');
  for(const value of [.5,.75,1,1.5,2,3]){const button=el('button',value+'×','secondary');button.type='button';button.dataset.speed=String(value);button.setAttribute('aria-pressed',String(value===1));button.onclick=()=>applySpeed(value);presets.append(button);}
  const speedValue=el('input');speedValue.type='number';speedValue.id='speed-value';speedValue.min='0.25';speedValue.max='4';speedValue.step='0.05';speedValue.setAttribute('aria-label','变速倍率');
  const valueLabel=el('label','倍率 0.25–4');valueLabel.append(speedValue);
  const speedRange=el('input');speedRange.type='range';speedRange.id='speed-range';speedRange.min='0.25';speedRange.max='4';speedRange.step='0.05';speedRange.setAttribute('aria-label','拖动调节变速倍率');
  const rangeLabel=el('label','拖动调节');rangeLabel.append(speedRange);
  const speedResult=el('p','','fine');speedResult.id='speed-result';
  const speedReset=el('button','恢复 1×','text-button');speedReset.type='button';speedReset.id='speed-reset';speedReset.onclick=()=>applySpeed(1);
  speedFields.append(presets,valueLabel,rangeLabel,speedResult,speedReset);
  speedPanel.append(el('h2','变速'),speedSelection,speedFields,el('p','成片时长 = 原片时长 ÷ 倍率。预览按倍速播放，导出时画面与声音同步变速并保持原调，时间轴会自动顺延后续字幕与独立音轨。','fine'));
  document.querySelector('.edit-properties').append(speedPanel);
  function speedRate(){const clip=clips()[selected];return clip?(clip.speed||1):1;}
  function speedClips(){return selectedRows().filter(r=>r.key.startsWith('video:')).map(r=>r.item);}
  function renderSpeed(){
    const chosen=speedClips(),clip=chosen[0],rate=clip?(clip.speed||1):1,mixed=chosen.some(c=>Math.abs((c.speed||1)-rate)>.001),changed=clips().filter(c=>Math.abs((c.speed||1)-1)>.001).length;
    if(typeof renderAdjust==='function'&&document.getElementById('editor-adjust-panel'))renderAdjust();
    speedFields.disabled=!chosen.length;
    speedSelection.textContent=chosen.length>1?`已选择 ${chosen.length} 个视频片段${mixed?' · 倍率不一致':''}`:clip?`片段 ${clips().indexOf(clip)+1} · 原片 ${seconds(clip.end-clip.start)} 秒`:'先在时间轴选择视频片段';
    speedValue.value=clip&&!mixed?rate.toFixed(2):'';speedValue.placeholder=mixed?'不同倍率':'1.00';speedRange.value=clip?rate:1;
    for(const button of presets.querySelectorAll('[data-speed]')){const on=!!clip&&!mixed&&Math.abs(Number(button.dataset.speed)-rate)<.001;button.classList.toggle('active',on);button.setAttribute('aria-pressed',String(on));}
    const suffix=changed?' · 全片 '+changed+' 个片段已变速':'';
    speedResult.textContent=(clip?(chosen.length>1?'选中片段合计 ':'成片 ')+seconds(chosen.reduce((sum,c)=>sum+length(c),0))+' 秒'+(!mixed&&Math.abs(rate-1)>.001?' · '+rate+'×':''):'')+suffix;
  }
  function applySpeed(raw){
    const chosen=speedClips();if(!chosen.length)return fail('请选择视频片段调整变速');
    const next=Math.round(Number(raw)*100)/100;
    if(!Number.isFinite(next)||next<.25||next>4){fail('变速范围 0.25–4 倍');renderSpeed();return;}
    if(chosen.every(clip=>Math.abs(next-(clip.speed||1))<.001)){renderSpeed();return;}
    pause();
    editTimeline(()=>{for(const clip of chosen)clip.speed=next;},null,new Set(chosen),{preserveOrder:true});
    mark();render();seek(offset(selected));
  }
  speedValue.onchange=()=>applySpeed(Number(speedValue.value));
  speedRange.oninput=()=>{const chosen=speedClips();if(!chosen.length)return;const value=Number(speedRange.value);speedValue.value=value.toFixed(2);speedResult.textContent=`${chosen.length>1?'选中片段合计':'成片'} ${seconds(chosen.reduce((sum,clip)=>sum+(clip.end-clip.start)/value,0))} 秒 · ${value}×`;};
  speedRange.onchange=()=>applySpeed(Number(speedRange.value));
  window.addEventListener('hub-editor-shell-ready',renderSpeed);
  const adjustPanel=el('div',undefined,'editor-side-panel adjust-panel');adjustPanel.id='editor-adjust-panel';
  const adjustInfo=el('p','先在时间轴选择一个视频片段','fine'), adjustTabs=el('div',undefined,'editor-panel-tabs adjust-tabs'), adjustContent=el('div',undefined,'adjust-content');
  adjustTabs.setAttribute('role','tablist');adjustTabs.setAttribute('aria-label','调整分类');
  let adjustCategory='basic',adjustChannel='red',adjustPreviewFrame=0;
  function scheduleAdjustPreview(){
    if(adjustPreviewFrame)return;
    adjustPreviewFrame=requestAnimationFrame(()=>{adjustPreviewFrame=0;if(project)window.hubMultitrackPreview?.sync(project.body,position,playing);});
  }
  for(const [key,label] of [['basic','基础调色'],['hsl','HSL']]){const b=el('button',label);b.type='button';b.dataset.category=key;b.setAttribute('role','tab');b.onclick=()=>{adjustCategory=key;renderAdjust();};adjustTabs.append(b);}
  adjustPanel.append(adjustTabs,adjustInfo,adjustContent);document.querySelector('.edit-properties').append(adjustPanel);
  function selectedColorClip(){const rows=selectedRows();return rows.find(r=>r.key.startsWith('video:')&&!r.item.locked)?.item||null;}
  function renderAdjust(){
    const clip=selectedColorClip();adjustInfo.textContent=clip?'调整作用于所选视频片段':'先在时间轴选择一个视频片段';const oldSelector=adjustContent.querySelector('.adjust-colors');if(oldSelector&&(!clip||adjustCategory!=='hsl'))window.hubHslSelector?.unmount(oldSelector);adjustContent.replaceChildren();
    for(const b of adjustTabs.querySelectorAll('button')){const active=b.dataset.category===adjustCategory;b.classList.toggle('active',active);b.setAttribute('aria-selected',String(active));}
    if(!clip)return;
    const color=clip.color||{},hsl=color.hsl||{};
    if(adjustCategory==='hsl'){const choices=oldSelector||el('div',undefined,'adjust-colors');adjustContent.append(choices);const select=key=>{adjustChannel=key;renderAdjust();};if(window.hubHslSelector)window.hubHslSelector.render(choices,adjustChannel,select);else {choices.replaceChildren();for(const [key,label,hex] of [['red','红','#e65c58'],['orange','橙','#f2934d'],['yellow','黄','#e3cb53'],['green','绿','#70bd6b'],['cyan','青','#56c7bd'],['blue','蓝','#5999e4'],['purple','紫','#966fd1'],['magenta','洋红','#d66cad']]){const b=el('button',label);b.type='button';b.style.setProperty('--swatch',hex);b.title=label;b.setAttribute('aria-label',label);b.classList.toggle('active',key===adjustChannel);b.setAttribute('aria-pressed',String(key===adjustChannel));b.onclick=()=>select(key);choices.append(b);}}}
    const items=adjustCategory==='basic'?[['brightness','亮度'],['contrast','对比度'],['saturation','饱和度']]:[['h','色相'],['s','饱和度'],['l','明度']];
    for(const [key,label] of items){const row=el('label',undefined,'adjust-row'),head=el('span',label),value=el('output'),input=el('input');input.type='range';input.min='-100';input.max='100';input.step='1';input.value=adjustCategory==='basic'?(color[key]||0):(hsl[adjustChannel]?.[key]||0);value.value=input.value;input.setAttribute('aria-label',label);if(adjustCategory==='hsl'){const hue={red:0,orange:30,yellow:60,green:120,cyan:180,blue:240,purple:270,magenta:315}[adjustChannel];row.classList.add('adjust-hsl-row');input.dataset.hsl=key;input.style.setProperty('--hsl-hue',hue);input.style.setProperty('--hsl-track',key==='h'?`linear-gradient(90deg,hsl(${(hue+300)%360} 100% 50%),hsl(${hue} 100% 50%),hsl(${(hue+60)%360} 100% 50%))`:key==='s'?`linear-gradient(90deg,hsl(${hue} 0% 50%),hsl(${hue} 100% 50%),hsl(${hue} 100% 50%))`:`linear-gradient(90deg,#000,hsl(${hue} 100% 50%),#fff)`);}row.append(head,value,input);input.oninput=()=>{if(selectedColorClip()!==clip)return;for(const {item:target} of selectedRows().filter(r=>r.key.startsWith('video:')&&!r.item.locked)){target.color=target.color||{};if(adjustCategory==='basic')target.color[key]=Number(input.value);else {target.color.hsl=target.color.hsl||{};target.color.hsl[adjustChannel]=target.color.hsl[adjustChannel]||{};target.color.hsl[adjustChannel][key]=Number(input.value);}}value.value=input.value;editedLive();scheduleAdjustPreview();};input.onchange=()=>commitEdits();adjustContent.append(row);}
    const reset=el('button',adjustCategory==='basic'?'重置基础调色':'重置当前颜色','secondary');reset.type='button';reset.onclick=()=>{clip.color=clip.color||{};if(adjustCategory==='basic'){for(const key of ['brightness','contrast','saturation'])delete clip.color[key];}else if(clip.color.hsl)delete clip.color.hsl[adjustChannel];editedLive();commitEdits();renderAdjust();window.hubMultitrackPreview?.sync(project.body,position,playing);};adjustContent.append(reset,el('p','预览与导出使用相同的色彩调整；HSL 按色相范围柔和过渡。','fine'));
  }
  window.addEventListener('hub-adjust-refresh',renderAdjust);
  window.addEventListener('hub-hsl-selector-ready',()=>{if(adjustCategory==='hsl')renderAdjust();});
  const CAPTION_STYLE={size:150,color:'#ffffff',outline:3,outline_color:'#101010',align:'center',bold:false,italic:false,spacing:0,case:'none'};
  function captionStyle(caption){
    const style={...CAPTION_STYLE};
    for(const key of Object.keys(CAPTION_STYLE)){const value=caption[key];if(value===undefined||value===null||value==='')continue;style[key]=key==='size'||key==='outline'||key==='spacing'?Number(value):value;}
    for(const flag of ['bold','italic'])style[flag]=!([undefined,null,false,0,'false','0',''].includes(caption[flag]));
    if(!['left','center','right'].includes(style.align))style.align='center';
    if(!['none','upper','lower'].includes(style.case))style.case='none';
    if(caption.x!==undefined&&caption.x!==null&&caption.y!==undefined&&caption.y!==null&&Number.isFinite(Number(caption.x))&&Number.isFinite(Number(caption.y))){style.x=Math.min(100,Math.max(0,Number(caption.x)));style.y=Math.min(100,Math.max(0,Number(caption.y)));}
    return style;
  }
  // Every key edited in the 文本 panel that belongs to a caption's look. New style keys added to
  // CAPTION_STYLE (and to the matching backend defaults) are covered by the lane rule automatically.
  const STYLE_KEYS=[...Object.keys(CAPTION_STYLE),'font','x','y'];
  // ── 字幕动画（入场 / 出场 / 循环）──────────────────────────────────────────────
  // 与字幕效果不同，动画不是静态样式：它按播放头时间计算透明度、缩放、位移、旋转和逐字进度。
  // 后端 write_ass 用同一组参数生成 \fad / \move / \t / \k 标签，所以预览与烧录保持同一套时间线。
  const CAPTION_ANIMS={in:['fade','rise','zoom','pop','type'],out:['fade','sink','shrink'],loop:['breathe','shake','karaoke','spoken']};
  const KARAOKE_COLOR='#23a9bd';
  function captionAnim(caption){
    const raw=caption?.anim;if(!raw||typeof raw!=='object'||Array.isArray(raw))return {};
    const result={};
    for(const slot of ['in','out','loop']){
      const item=raw[slot];if(!item)continue;
      const id=typeof item==='string'?item:String(item.id||'');
      if(!CAPTION_ANIMS[slot].includes(id))continue;
      if(id==='karaoke'){result[slot]={id};continue;}
      if(id==='spoken'){result[slot]={id,color:/^#[0-9a-f]{6}$/i.test(item.color||'')?item.color:'#ff0000'};continue;}
      const dur=Number(item.dur);result[slot]={id,dur:Number.isFinite(dur)?Math.min(2,Math.max(.1,dur)):.4};
    }
    return result;
  }
  const ANIM_LABELS={
    fade:'淡入 / 淡出',rise:'上滑淡入',zoom:'缩放入场',pop:'弹入',type:'打字机',
    sink:'下滑淡出',shrink:'缩小淡出',breathe:'呼吸',shake:'轻微抖动',karaoke:'逐字高亮'
  };
  const CAPTION_ALIGN_LABEL={left:'左对齐',center:'居中',right:'右对齐'};  const captionText=(text,style)=>style.case==='upper'?String(text).toUpperCase():style.case==='lower'?String(text).toLowerCase():String(text);
  const captionFontLabel=caption=>(subtitleFonts.find(font=>font.id===(caption.font||'default'))?.label||'默认字体');
  const captionNote=(caption,style)=>`${captionFontLabel(caption)} · 字号 ${Math.round(style.size)}% · ${CAPTION_ALIGN_LABEL[style.align]}${style.bold?' · 粗':''}${style.italic?' · 斜':''}`;
  // Caption indexes the user has picked: any caption block selected on the timeline (click, drag, marquee),
  // or the one chosen from the 字幕 list.
  function selectedCaptionIndexes(){
    const captions=project?.body.captions||[];
    if(timelineSelection.size)return [...timelineSelection].filter(k=>k.startsWith('caption:')).map(k=>Number(k.slice(8))).filter(i=>captions[i]).sort((a,b)=>a-b);
    if(videoSelection.size)return [];
    return trackSelection?.kind==='caption'&&captions[trackSelection.index]?[trackSelection.index]:[];
  }
  function captionTarget(){
    const captions=project?.body.captions||[],picked=selectedCaptionIndexes();if(!picked.length)return null;
    const index=picked.includes(primaryCaption)?primaryCaption:picked[0];
    return {index,caption:captions[index]};
  }
  let captionScopeMode='track';
  function setCaptionScopeMode(next){
    if(!['track','selected','all'].includes(next)||next===captionScopeMode)return;
    captionScopeMode=next;
    renderTextPanel();renderSubtitleEffects();renderSubtitleAnimations();
  }
  function captionEditTarget(){return captionTarget();}
  function captionScope(){
    const captions=project?.body.captions||[],picked=selectedCaptionIndexes(),target=captionTarget();
    let indexes=[];
    if(target){const lane=target.caption.track||'caption-main';indexes=captionScopeMode==='all'?captions.map((_,i)=>i):captionScopeMode==='track'?captions.flatMap((c,i)=>(c.track||'caption-main')===lane?[i]:[]):[target.index];}
    return {indexes,all:captionScopeMode==='all',uniform:captionScopeMode!=='selected',picked:picked.length,label:captionScopeMode==='all'?'全部轨道':captionScopeMode==='track'?'当前轨道':'当前字幕'};
  }
  // 「应用范围」切换条：统一模式（全部字幕）/ 逐条模式（仅所选）。
  function scopeSwitch(){
    const captions=project?.body.captions||[];
    const bar=el('div',undefined,'caption-scope');
    bar.setAttribute('role','group');bar.setAttribute('aria-label','字幕应用范围');
    bar.append(el('span','应用范围','caption-scope-label'));
    for(const [key,label,hint] of [['track','当前轨道','应用到当前字幕所在轨道'],['selected','仅当前字幕','只更改当前字幕'],['all','全部轨道','应用到所有字幕轨道']]){
      const button=el('button',label,'scope-chip');button.type='button';button.dataset.scope=key;button.title=hint;
      const on=captionScopeMode===key;
      button.setAttribute('aria-pressed',String(on));
      button.disabled=!captions.length;
      button.onclick=()=>setCaptionScopeMode(key);
      bar.append(button);
    }
    const scope=captionScope();bar.append(el('em',scope.indexes.length?`${scope.label} · ${scope.indexes.length} 条`:'请先选择字幕','caption-scope-note on'));
    return bar;
  }
  function selectCaption(index,quiet=false){
    const captions=project?.body.captions||[];if(!captions[index])return;
    commitEdits();primaryCaption=index;
    videoSelection.clear();
    if(quiet){timelineSelection.clear();trackSelection={kind:'caption',index};panelSig='';renderCaptions();return;}
    setTimelineSelection(['caption:'+index],{primary:index});
    runSelectionSync(true);
    seek(Math.max(0,captions[index].start));
  }
  // Keeps the 文本 panel, the 字幕 list highlight and the preview in step with the timeline selection.
  function selectionSignature(){const t=captionTarget();return t?t.index+'|'+selectedCaptionIndexes().join(',')+'|'+(project?.body.captions.length||0):'';}
  function scheduleSelectionSync(){if(!syncPending)syncPending=requestAnimationFrame(()=>{syncPending=0;runSelectionSync(false);});}
  function runSelectionSync(force){
    if(syncPending){cancelAnimationFrame(syncPending);syncPending=0;}
    if(!project)return;
    const sig=selectionSignature();if(!force&&sig===panelSig)return;
    panelSig=sig;
    const picked=selectedCaptionIndexes(),target=captionTarget();
    [...$('edit-captions').children].forEach((row,i)=>{const on=picked.includes(i);row.classList.toggle('selected',on);row.querySelector('.caption-preview')?.setAttribute('aria-pressed',String(on));});
    renderTextPanel();paintCaptions();
    if($('editor-subtitle-effects'))renderSubtitleEffects();
    if($('editor-subtitle-animations'))renderSubtitleAnimations();
    if(target){
      const onlyCaptions=timelineSelection.size?[...timelineSelection].every(k=>k.startsWith('caption:')):true;
      if(onlyCaptions)window.hubEditorShell?.openRight?.('text');
      // Selecting a caption never moves the playhead.
    }
  }
  // Applies a style patch to every caption in scope. Keeps the main thread free while a colour picker or
  // slider streams `input` events: only the preview is repainted; the undo step / timeline sync is deferred
  // to commitEdits() (on `change`, or after a short idle).
  function applyStyle(patch){
    const scope=captionScope();if(!scope.indexes.length)return;
    for(const index of scope.indexes){const caption=project.body.captions[index];for(const key of Object.keys(patch)){if(!STYLE_KEYS.includes(key))continue;if(patch[key]===undefined)delete caption[key];else caption[key]=patch[key];}}
    editedLive();for(const index of scope.indexes)syncCaptionRow(index);paintCaptions();
  }
  function editedLive(){
    dirty=true;requestKey=crypto.randomUUID();$('edit-save-state').textContent=saveRecovery()?'已自动保存到本机（未保存到项目）':'有未保存的更改';$('edit-error').textContent='';
    clearTimeout(pendingCommit);pendingCommit=setTimeout(commitEdits,400);
  }
  function commitEdits(){
    if(!pendingCommit)return;clearTimeout(pendingCommit);pendingCommit=0;
    markCore(true);paintSelectionClasses();
  }
  function syncCaptionRow(index){
    const row=$('edit-captions')?.children[index],caption=project?.body.captions[index];if(!row||!caption)return;
    const style=captionStyle(caption),text=row.querySelector('.caption-text'),note=row.querySelector('.caption-style-note');
    if(text)text.textContent=captionText(caption.text,style).replace(/\s+/g,' ').trim()||'（空字幕）';
    if(note)note.textContent=captionNote(caption,style);
  }
  function renderCaptions(){
    const list=$('edit-captions');list.replaceChildren();
    const target=captionTarget(),pickedNow=selectedCaptionIndexes();
    if(!project.body.captions.length)list.append(el('p','还没有字幕。点“添加字幕”，再切到「文本」填写文字和样式。','fine'));
    project.body.captions.forEach((caption,i)=>{
      const style=captionStyle(caption),selected=pickedNow.includes(i);
      const row=el('div',undefined,'edit-caption-row'+(selected?' selected':''));
      const preview=el('button',undefined,'caption-preview');preview.type='button';preview.setAttribute('aria-pressed',String(selected));
      preview.setAttribute('aria-label',`选中字幕 ${i+1}，切到文本编辑`);
      preview.append(el('span',`字幕 ${i+1}`,'caption-index'),el('span',captionText(caption.text,style).replace(/\s+/g,' ').trim()||'（空字幕）','caption-text'),el('small',captionNote(caption,style),'caption-style-note'));
      preview.onclick=()=>selectCaption(i);
      row.append(preview);
      for(const [key,title] of [['start','开始 / 秒'],['end','结束 / 秒']]){const l=el('label',title),input=el('input');input.type='number';input.min='0';input.step='.01';input.value=seconds(caption[key]);input.onchange=()=>{if(Number(input.value)!==caption[key])delete caption.words;caption[key]=Number(input.value);mark();render();};l.append(input);row.append(l);}
      const remove=el('button','删除','text-button');remove.setAttribute('aria-label',`删除字幕 ${i+1}`);remove.onclick=()=>{commitEdits();trackSelection=null;timelineSelection.clear();primaryCaption=null;project.body.captions.splice(i,1);mark();render();};row.append(remove);list.append(row);
    });
    renderTextPanel();
  }
  function renderTextPanel(){
    const box=$('edit-text-panel'),note=$('edit-text-target');if(!box)return;
    const target=captionEditTarget();window.hubColorPicker?.destroyAll?.();box.replaceChildren();panelSig=selectionSignature();
    const scope=captionScope(),picked=selectedCaptionIndexes();
    if(note)note.textContent=target?(picked.length>1?`已选 ${picked.length} 条字幕 · 主要：字幕 ${target.index+1}`:`正在编辑 字幕 ${target.index+1} · ${seconds(target.caption.start)}–${seconds(target.caption.end)} 秒`):'未选中字幕';
    if(!target){box.append(el('p','在时间轴上点选任意一块字幕（或框选），或在「字幕」列表里点一条，这里就会自动对应并可编辑文字和样式。','fine text-panel-empty'));return;}
    box.append(scopeSwitch());
    const caption=target.caption,style=captionStyle(caption);
    // Style controls: `input` repaints the preview only; `change` (picker closed / value committed) records one undo step.
    const live=patch=>applyStyle(patch);
    box.onchange=()=>commitEdits();
    const textLabel=el('label','文字内容'),area=el('textarea');
    area.rows=3;area.maxLength=300;area.value=caption.text;area.setAttribute('placeholder','输入字幕文字，回车可以分成两行');
    area.oninput=()=>{if(caption.text!==area.value)delete caption.words;caption.text=area.value;editedLive();syncCaptionRow(target.index);paintCaptions();};
    textLabel.append(area);box.append(textLabel);
    box.append(el('p',`样式范围：${scope.label}，共 ${scope.indexes.length} 条；文字内容只改当前这一条。`,'fine text-scope-note'));
    const fontLabel=el('label','字体'),font=fontOptions(el('select'));
    font.value=caption.font||'default';font.setAttribute('aria-label','字幕字体');font.onchange=()=>{live({font:font.value});commitEdits();};
    fontLabel.append(font);box.append(fontLabel);
    const sizeLabel=el('label','字号（相对画面宽度 %）'),sizeBox=el('span',undefined,'text-slider');
    const sizeRange=el('input'),sizeNumber=el('input');
    sizeRange.type='range';sizeRange.min='1';sizeRange.max='300';sizeRange.step='1';sizeRange.value=String(style.size);sizeRange.setAttribute('aria-label','字号滑杆');
    sizeNumber.type='number';sizeNumber.min='1';sizeNumber.max='300';sizeNumber.step='1';sizeNumber.value=String(style.size);sizeNumber.setAttribute('aria-label','字号数值');
    const applySize=raw=>{const value=Math.min(300,Math.max(1,Math.round(Number(raw))));if(!Number.isFinite(value))return;sizeRange.value=String(value);sizeNumber.value=String(value);live({size:value});};
    sizeRange.oninput=()=>applySize(sizeRange.value);
    sizeNumber.oninput=()=>{const value=Number(sizeNumber.value);if(Number.isFinite(value)&&value>=1&&value<=300)applySize(value);};
    sizeBox.append(sizeRange,sizeNumber);sizeLabel.append(sizeBox);box.append(sizeLabel);
    // 文字颜色 / 描边颜色：@beui/color-picker 式取色器（芯片形变为饱和度亮度区、拖动放大镜、色相滑杆、
    // 十六进制输入、预设色、吸管、键盘）。只写不透明 #rrggbb，input 只重绘预览，收手才记一步撤销。
    const colorRow=el('div',undefined,'text-row');
    const pickColor=(value,label,key)=>{
      if(!window.hubColorPicker){const input=el('input');input.type='color';input.value=value;input.setAttribute('aria-label',label);input.oninput=()=>live({[key]:input.value});return input;}
      return window.hubColorPicker.mount({value,label,onInput:hex=>live({[key]:hex}),onCommit:commitEdits}).el;
    };
    const colorLabel=el('label','文字颜色'),edgeLabel=el('label','描边颜色');
    colorLabel.append(pickColor(style.color,'字幕文字颜色','color'));
    edgeLabel.append(pickColor(style.outline_color,'字幕描边颜色','outline_color'));
    colorRow.append(colorLabel,edgeLabel);box.append(colorRow);
    const spoken=captionAnim(caption).loop;
    const highlightLabel=el('label','跟读高亮颜色');
    if(spoken?.id==='spoken'){
      const setColor=hex=>{for(const i of scope.indexes){const c=project.body.captions[i],anim=captionAnim(c);if(anim.loop?.id==='spoken'){anim.loop.color=hex;c.anim=anim;}}editedLive();paintCaptions();};
      if(window.hubColorPicker)highlightLabel.append(window.hubColorPicker.mount({value:spoken.color,label:'跟读高亮颜色',onInput:setColor,onCommit:commitEdits}).el);
      else{const input=el('input');input.type='color';input.value=spoken.color;input.setAttribute('aria-label','跟读高亮颜色');input.oninput=()=>setColor(input.value);highlightLabel.append(input);}
      if(!caption.words?.length)box.append(el('p','此字幕没有词级时间，跟读变色不会生效；请重新语音识别。','fine'));
    }else{
      highlightLabel.append(el('span','请先在「动画 → 循环」选择“跟读变色”，再返回这里调色。','fine'));
    }
    box.append(highlightLabel);
    const measureRow=el('div',undefined,'text-row');
    const outlineLabel=el('label','描边粗细'),outline=el('input');outline.type='number';outline.min='0';outline.max='12';outline.step='.5';outline.value=String(style.outline);outline.setAttribute('aria-label','描边粗细');
    outline.oninput=()=>{const value=Number(outline.value);if(outline.value!==''&&Number.isFinite(value)&&value>=0&&value<=12)live({outline:value});};
    outlineLabel.append(outline);measureRow.append(outlineLabel);
    const spacingLabel=el('label','字间距'),spacing=el('input');spacing.type='number';spacing.min='-10';spacing.max='40';spacing.step='.5';spacing.value=String(style.spacing);spacing.setAttribute('aria-label','字间距');
    spacing.oninput=()=>{const value=Number(spacing.value);if(spacing.value!==''&&Number.isFinite(value)&&value>=-10&&value<=40)live({spacing:value});};
    spacingLabel.append(spacing);measureRow.append(spacingLabel);box.append(measureRow);
    const alignRow=el('div',undefined,'text-row');
    const alignLabel=el('label','对齐方式'),alignBox=el('div',undefined,'text-align');
    for(const value of ['left','center','right']){
      const button=el('button',{left:'左',center:'中',right:'右'}[value],'secondary');button.type='button';button.title=CAPTION_ALIGN_LABEL[value];button.setAttribute('aria-label',`字幕${CAPTION_ALIGN_LABEL[value]}`);button.setAttribute('aria-pressed',String(style.align===value));
      button.onclick=()=>{[...alignBox.children].forEach(node=>node.setAttribute('aria-pressed',String(node===button)));live({align:value});commitEdits();};
      alignBox.append(button);
    }
    alignLabel.append(alignBox);alignRow.append(alignLabel);box.append(alignRow);
    const shapeRow=el('div',undefined,'text-row');
    const shapeLabel=el('label','字形与大小写'),shapeBox=el('div',undefined,'text-align text-flags');
    for(const [key,title,label] of [['bold','粗体','B'],['italic','斜体','I']]){
      const button=el('button',label,'secondary');button.type='button';button.title=title;button.setAttribute('aria-label',`字幕${title}`);button.setAttribute('aria-pressed',String(style[key]));
      if(key==='bold')button.style.fontWeight='800';else button.style.fontStyle='italic';
      button.onclick=()=>{const next=!captionStyle(target.caption)[key];button.setAttribute('aria-pressed',String(next));live({[key]:next});commitEdits();};
      shapeBox.append(button);
    }
    const caseSelect=el('select');caseSelect.setAttribute('aria-label','字幕大小写');
    caseSelect.replaceChildren(new Option('原文','none'),new Option('全部大写','upper'),new Option('全部小写','lower'));
    caseSelect.value=style.case;caseSelect.onchange=()=>{live({case:caseSelect.value});commitEdits();};shapeBox.append(caseSelect);
    shapeLabel.append(shapeBox);shapeRow.append(shapeLabel);box.append(shapeRow);
    const placeRow=el('div',undefined,'text-row text-place');
    const placeNote=el('span',style.x===undefined?'位置：默认（画面底部居中）。在预览里直接拖动字幕即可自由摆放。':`位置：横向 ${style.x.toFixed(1)}% · 纵向 ${style.y.toFixed(1)}%（预览里可继续拖动）`,'fine');
    placeRow.append(placeNote);
    if(style.x!==undefined){const reset=el('button','重置位置','secondary');reset.type='button';reset.onclick=()=>{live({x:undefined,y:undefined});commitEdits();renderTextPanel();};placeRow.append(reset);}
    box.append(placeRow);
    box.append(el('p','改动立即反映到预览；保存项目后写入导出。字幕出现时间在「字幕」列表里调整。','fine'));
  }
  // ── 字幕效果（字幕模板）────────────────────────────────────────────────────────
  // 每个效果就是一整套「文本」面板字段（字体/字号/颜色/描边/对齐/位置…）。点击后走和其它
  // 样式控件完全一样的 applyStyle 路径，所以浏览器预览与烧录的 ASS 字幕天然一致，
  // 也不需要任何新的后端字段。
  const EFFECT_GROUPS=[{key:'all',label:'全部'},{key:'fav',label:'收藏'},{key:'hot',label:'热门'},{key:'edge',label:'描边'},{key:'place',label:'位置'},{key:'font',label:'字体'},{key:'bw',label:'黑白'}];
  const EFFECT_BASE={size:100,color:'#ffffff',outline:2,outline_color:'#101010',align:'center',bold:false,italic:false,spacing:0,case:'none',x:undefined,y:undefined};
  const SUBTITLE_EFFECTS=[
    {id:'white-edge',group:'hot',name:'白字黑边',sample:'字幕效果',patch:{...EFFECT_BASE}},
    {id:'big-title',group:'hot',name:'大标题',sample:'大标题',patch:{...EFFECT_BASE,size:170,bold:true,outline:3,outline_color:'#000000'}},
    {id:'cinema-small',group:'hot',name:'电影小字',sample:'电影小字',patch:{...EFFECT_BASE,size:72,outline:1,color:'#f1f1f1',outline_color:'#000000'}},
    {id:'edge-title',group:'hot',name:'粗描边标题',sample:'标题',patch:{...EFFECT_BASE,size:150,bold:true,outline:7}},
    {id:'edge-thin',group:'edge',name:'细描边',sample:'细描边',patch:{...EFFECT_BASE,outline:1}},
    {id:'edge-thick',group:'edge',name:'粗描边',sample:'粗描边',patch:{...EFFECT_BASE,outline:6,outline_color:'#000000'}},
    {id:'edge-accent',group:'edge',name:'青色描边',sample:'青色描边',patch:{...EFFECT_BASE,outline:4,outline_color:'#23a9bd'}},
    {id:'edge-none',group:'edge',name:'无描边',sample:'无描边',patch:{...EFFECT_BASE,outline:0}},
    {id:'place-top',group:'place',name:'顶部标题',sample:'顶部标题',patch:{...EFFECT_BASE,size:120,bold:true,outline:3,outline_color:'#000000',x:50,y:12}},
    {id:'place-left',group:'place',name:'左下角',sample:'左下角',patch:{...EFFECT_BASE,size:90,align:'left',x:6,y:84}},
    {id:'place-right',group:'place',name:'右下角',sample:'右下角',patch:{...EFFECT_BASE,size:90,align:'right',x:94,y:84}},
    {id:'place-bottom',group:'place',name:'底部居中',sample:'底部居中',patch:{...EFFECT_BASE}},
    {id:'font-source-han',group:'font',name:'思源黑体',sample:'思源黑体',patch:{...EFFECT_BASE,font:'source-han-sans'}},
    {id:'font-kuaile',group:'font',name:'站酷快乐体',sample:'快乐体',patch:{...EFFECT_BASE,font:'zcool-kuaile',size:110,bold:true,outline:3}},
    {id:'font-bebas',group:'font',name:'英文大写标题',sample:'THE QUICK',patch:{...EFFECT_BASE,font:'bebas-neue',size:150,case:'upper',spacing:2,outline:3}},
    {id:'bw-invert',group:'bw',name:'反白黑字',sample:'反白黑字',patch:{...EFFECT_BASE,color:'#101010',outline_color:'#ffffff',outline:5,bold:true}},
    {id:'bw-plain',group:'bw',name:'纯白字幕',sample:'纯白字幕',patch:{...EFFECT_BASE,outline:0,color:'#ffffff'}}
  ];
  const EFFECT_FAV_KEY='hubSubtitleEffectsFav';
  const effectFavs=()=>{try{const list=JSON.parse(localStorage.getItem(EFFECT_FAV_KEY)||'[]');return Array.isArray(list)?list.filter(id=>SUBTITLE_EFFECTS.some(e=>e.id===id)):[];}catch{return[];}};
  function toggleEffectFav(id){
    const next=new Set(effectFavs());next.has(id)?next.delete(id):next.add(id);
    try{localStorage.setItem(EFFECT_FAV_KEY,JSON.stringify([...next]));}catch{}
    return [...next];
  }
  // What the caption looks like right now, in the same shape as an effect patch (font included).
  function effectTargetStyle(){
    const target=captionEditTarget();if(!target)return null;
    const style=captionStyle(target.caption);
    return {...style,font:target.caption.font||'default'};
  }
  const effectMatches=(style,preset)=>Object.entries(preset.patch).every(([key,value])=>value===undefined?style[key]===undefined:key==='size'||key==='outline'||key==='spacing'||key==='x'||key==='y'?Math.abs(Number(style[key])-Number(value))<0.01:String(style[key]??'').toLowerCase()===String(value).toLowerCase());
  // Thumbnail: the sample line is drawn with the same colour/stroke/font rules as the real preview;
  // the stroke is drawn a little thicker than scale so hairline outlines stay visible in a 150px card.
  function effectSample(preset,font){
    const style={...CAPTION_STYLE,...preset.patch};
    const frame=el('span',undefined,'effect-frame');
    const line=el('span',preset.sample,'effect-line');
    line.style.fontFamily=fontCss(preset.patch.font||font||'default');
    line.style.fontSize=(11*style.size/100).toFixed(1)+'px';
    line.style.color=style.color;
    line.style.fontWeight=style.bold?'800':'400';
    line.style.fontStyle=style.italic?'italic':'normal';
    line.style.letterSpacing=(style.spacing/9).toFixed(2)+'px';
    line.style.textShadow=style.outline?`0 0 ${Math.min(3,style.outline*.42).toFixed(2)}px ${style.outline_color},${(Math.min(2.4,style.outline*.28)).toFixed(2)}px ${(Math.min(2.4,style.outline*.28)).toFixed(2)}px 0 ${style.outline_color}`:'none';
    if(style.x!==undefined){line.style.left=style.x+'%';line.style.top=style.y+'%';line.style.transform=`translate(${{left:'0',center:'-50%',right:'-100%'}[style.align]},-50%)`;}
    else{line.style.left='50%';line.style.top='86%';line.style.transform='translate(-50%,-50%)';}
    frame.append(line);return frame;
  }
  let effectGroup='all',effectHostSig='';
  function renderSubtitleEffects(){
    const host=$('editor-subtitle-effects');if(!host)return;
    const favs=effectFavs(),target=effectTargetStyle();
    const scoped=captionScope();
    host.replaceChildren();
    const chips=el('div',undefined,'effect-groups');chips.setAttribute('role','group');chips.setAttribute('aria-label','字幕效果分类');
    for(const group of EFFECT_GROUPS){
      const chip=el('button',group.label,'effect-chip');chip.type='button';chip.dataset.group=group.key;
      chip.setAttribute('aria-pressed',String(effectGroup===group.key));
      chip.onclick=()=>{effectGroup=group.key;renderSubtitleEffects();};
      chips.append(chip);
    }
    host.append(chips);
    host.append(scopeSwitch());
    const list=SUBTITLE_EFFECTS.filter(effect=>effectGroup==='all'||effectGroup==='fav'?effectGroup==='all'||favs.includes(effect.id):effect.group===effectGroup);
    const hint=el('p',undefined,'effect-hint');
    hint.textContent=!target?'先在时间轴点选或框选字幕，效果只应用到所选字幕。'
      :`套用范围：${scoped.label} ${scoped.indexes.length} 条字幕 · 当前字体 ${subtitleFonts.find(f=>f.id===(captionEditTarget()?.caption.font||'default'))?.label||'默认'}`;
    host.append(hint);
    if(!list.length){host.append(el('p','还没有收藏。点效果卡片右上角的星标即可收藏。','fine'));return;}
    const grid=el('div',undefined,'effect-grid');
    for(const preset of list){
      const card=el('div',undefined,'effect-card'+(target&&effectMatches(target,preset)?' active':''));
      const apply=el('button',undefined,'effect-apply');apply.type='button';apply.dataset.effect=preset.id;
      apply.setAttribute('aria-label',`应用字幕效果：${preset.name}`);
      apply.title=`应用「${preset.name}」`;
      apply.append(effectSample(preset,target?.font),el('span',preset.name,'effect-name'));
      apply.disabled=!target;
      apply.onclick=()=>{
        if(!captionEditTarget()){resetEffectHint('先选中一条字幕');return;}
        applyStyle(preset.patch);commitEdits();
        renderTextPanel();renderSubtitleEffects();
        const again=document.querySelector(`.effect-apply[data-effect="${preset.id}"]`);again?.focus({preventScroll:true});
        resetEffectHint(`已应用「${preset.name}」到 ${captionScope().indexes.length} 条字幕，可继续在「文本」里微调。`);
      };
      const fav=el('button',favs.includes(preset.id)?'★':'☆','effect-fav');fav.type='button';
      fav.setAttribute('aria-pressed',String(favs.includes(preset.id)));
      fav.setAttribute('aria-label',`${favs.includes(preset.id)?'取消收藏':'收藏'}：${preset.name}`);
      fav.title=fav.getAttribute('aria-label');
      fav.onclick=event=>{event.preventDefault();event.stopPropagation();toggleEffectFav(preset.id);renderSubtitleEffects();};
      card.append(apply,fav);grid.append(card);
    }
    host.append(grid);
    host.append(el('p','效果只改样式，不改字幕文字与时间；改动会立即反映到预览，保存项目后随导出烧录进画面。','fine effect-foot'));
    effectHostSig=effectGroup+'|'+favs.join(',')+'|'+(target?presetKeyOf(target):'')+'|'+scoped.indexes.length;
  }
  const presetKeyOf=style=>SUBTITLE_EFFECTS.filter(preset=>effectMatches(style,preset)).map(preset=>preset.id).join(',');
  function resetEffectHint(text){
    const hint=$('editor-subtitle-effects')?.querySelector('.effect-hint');
    if(!hint)return;hint.textContent=text;
    clearTimeout(resetEffectHint.timer);resetEffectHint.timer=setTimeout(()=>renderSubtitleEffects(),1600);
  }
  window.addEventListener('hub-editor-shell-ready',()=>{effectHostSig='';renderSubtitleEffects();renderSubtitleAnimations();});

  // ── 字幕动画面板 ────────────────────────────────────────────────────────────────
  // 三类：入场 / 出场 / 循环。每个按钮直接写 caption.anim，后端 validate 白名单校验、
  // write_ass 转成 ASS 标签；预览用同一个参数逐帧计算，所以两边表现一致。
  const ANIM_SLOTS=[{key:'in',label:'入场'},{key:'out',label:'出场'},{key:'loop',label:'循环'}];
  const ANIM_OPTIONS={
    in:[{id:'fade',label:'淡入'},{id:'rise',label:'上滑淡入'},{id:'zoom',label:'缩放入场'},{id:'pop',label:'弹入'},{id:'type',label:'打字机'}],
    out:[{id:'fade',label:'淡出'},{id:'sink',label:'下滑淡出'},{id:'shrink',label:'缩小淡出'}],
    loop:[{id:'breathe',label:'呼吸'},{id:'shake',label:'轻微抖动'},{id:'karaoke',label:'逐字高亮'},{id:'spoken',label:'跟读变色'}]
  };
  const ANIM_DEFAULT_DUR={in:.4,out:.4,loop:.6};
  let animSlot='in';
  function setCaptionAnim(slot,value){
    const scope=captionScope();if(!scope.indexes.length)return null;
    for(const index of scope.indexes){
      const caption=project.body.captions[index],anim={...captionAnim(caption)};
      if(value===null)delete anim[slot];else anim[slot]={...(typeof value==='string'?{id:value}:value)};
      if(Object.keys(anim).length)caption.anim=anim;else delete caption.anim;
    }
    editedLive();paintCaptions();renderSubtitleAnimations();renderTextPanel();
    return scope.indexes.length;
  }
  function renderSubtitleAnimations(){
    const host=$('editor-subtitle-animations');if(!host)return;
    const target=captionEditTarget(),anim=target?captionAnim(target.caption):{},scope=captionScope();
    host.replaceChildren();
    host.append(el('h4','字幕动画','anim-heading'));
    host.append(scopeSwitch());
    const chips=el('div',undefined,'effect-groups');chips.setAttribute('role','group');chips.setAttribute('aria-label','字幕动画分类');
    for(const slot of ANIM_SLOTS){
      const chip=el('button',slot.label,'effect-chip');chip.type='button';chip.dataset.slot=slot.key;
      chip.setAttribute('aria-pressed',String(animSlot===slot.key));
      chip.onclick=()=>{animSlot=slot.key;renderSubtitleAnimations();};
      chips.append(chip);
    }
    host.append(chips);
    const hint=el('p',undefined,'effect-hint');
    hint.textContent=!target?'先在时间轴点选或框选字幕，动画只应用到所选字幕。'
      :`套用范围：${scope.label} ${scope.indexes.length} 条字幕 · 再点一次取消`;
    host.append(hint);
    const grid=el('div',undefined,'anim-grid');
    const active=anim[animSlot];
    // 统一模式下即使没有选中字幕也能直接套用（apply 目标 = 全部字幕）。
    const canApply=!!target&&scope.indexes.length>0;
    const none=el('button','无','anim-option');none.type='button';none.dataset.anim='none';
    none.setAttribute('aria-pressed',String(!active));none.disabled=!canApply;
    none.title=`移除${ANIM_SLOTS.find(s=>s.key===animSlot).label}动画`;
    none.onclick=()=>{if(!setCaptionAnim(animSlot,null))return;commitEdits();renderSubtitleAnimations();};
    grid.append(none);
    for(const option of ANIM_OPTIONS[animSlot]){
      const button=el('button',option.label,'anim-option');button.type='button';button.dataset.anim=option.id;
      const on=active?.id===option.id;
      button.setAttribute('aria-pressed',String(on));button.disabled=!canApply;
      button.title=`${ANIM_SLOTS.find(s=>s.key===animSlot).label}：${option.label}`;
      button.onclick=()=>{
        if(on){if(setCaptionAnim(animSlot,null)){commitEdits();renderSubtitleAnimations();}return;}
        const dur=['karaoke','spoken'].includes(option.id)?undefined:(anim[animSlot]?.dur||ANIM_DEFAULT_DUR[animSlot]);
        if(!setCaptionAnim(animSlot,{id:option.id,...(dur?{dur}:{})}))return;
        commitEdits();renderSubtitleAnimations();
      };
      grid.append(button);
    }
    host.append(grid);
    const current=anim[animSlot];
    if(current&&!['karaoke','spoken'].includes(current.id)){
      const row=el('label','时长'),box=el('span',undefined,'text-slider');
      const range=el('input');range.type='range';range.min='0.1';range.max='2';range.step='0.1';range.value=String(current.dur||ANIM_DEFAULT_DUR[animSlot]);
      range.setAttribute('aria-label','动画时长（秒）');
      const value=el('output',`${Number(range.value).toFixed(1)}s`,'anim-duration');
      range.oninput=()=>{value.textContent=`${Number(range.value).toFixed(1)}s`;setCaptionAnim(animSlot,{id:current.id,dur:Number(range.value)});};
      range.onchange=()=>commitEdits();
      box.append(range,value);row.append(box);host.append(row);
    }
    const foot=el('p',undefined,'fine effect-foot');
    foot.textContent=anim.loop?.id==='spoken'
      ?'跟读变色需要重新语音识别生成词级时间；翻译字幕或修改文字后需重新识别。高亮颜色和字体可在文本栏调整。'
      :anim.loop?.id==='karaoke'
      ?'逐字高亮按字数平均分配时间（不识别真实语音节奏），导出时写成 ASS 的 \\kf 卡拉OK标签。'
      :'动画按播放头计时，暂停和拖动进度条时预览都停在对应姿态；导出时写成 ASS 的 \\fad / \\move / \\t 标签。';
    host.append(foot);
  }

  const asrState={info:null,busy:false,language:'auto',target:''};
  function asrStatus(text,bad=false){const node=$('edit-asr-status');if(!node)return;node.textContent=text;node.classList.toggle('error',bad);}
  async function initAsr(){
    const box=$('edit-asr');if(!box||asrState.info)return;
    try{
      const info=await api('/editor/asr');asrState.info=info;
      const language=$('edit-asr-language'),target=$('edit-asr-target');
      language.replaceChildren(new Option('自动识别','auto'),...info.languages.map(l=>new Option(l.label,l.id)));
      target.replaceChildren(new Option('不翻译',''),new Option('中英双语','zh-en'),...info.languages.map(l=>new Option(l.label,l.id)));
      language.value=asrState.language;target.value=asrState.target;
      language.onchange=()=>{asrState.language=language.value;};
      target.onchange=()=>{asrState.target=target.value;};
      const button=$('edit-asr-run');
      if(!info.installed){button.disabled=true;asrStatus('这台执行机未安装语音识别引擎，请联系管理员安装 faster-whisper。',true);return;}
      if(!info.model_ready){button.disabled=true;asrStatus(`识别模型 ${info.model} 还没下载完成，下载后即可使用。`,true);return;}
      asrStatus(`识别在本机执行，音视频不出本机；翻译只发送字幕文本。单次最长 ${Math.round(info.max_seconds/60)} 分钟。`);
    }catch(e){asrStatus(e.message||String(e),true);}
  }
  async function runAsr(){
    if(!project||asrState.busy)return;
    const rows=selectedRows(),scoped=rows.length>0;
    const audioRows=rows.filter(r=>r.key.startsWith('video:')||r.key.startsWith('detached:')||r.key==='audio:0');
    if(scoped&&!audioRows.length)return fail('请选中需要识别的视频或音频片段');
    const existing=project.body.captions.length;
    if(!scoped&&existing&&!confirm(`未选择片段，识别会替换当前 ${existing} 条字幕，继续吗？`))return;
    const base=scoped?Math.min(...audioRows.map(r=>r.start)):0;
    const asrBody=structuredClone(project.body);asrBody.captions=[];asrBody.export_range=null;
    if(scoped){const keys=new Set(audioRows.map(r=>r.key));asrBody.clips=asrBody.clips.filter((_,i)=>keys.has('video:'+i)).map(c=>({...c,at:Math.max(0,c.at-base)}));asrBody.audio_clips=(asrBody.audio_clips||[]).filter((_,i)=>keys.has('detached:'+i)).map(c=>({...c,at:Math.max(0,c.at-base)}));if(!keys.has('audio:0'))asrBody.audio=null;}
    const revision=JSON.stringify(project);
    const button=$('edit-asr-run'),label=button.textContent;
    const box=$('edit-asr');asrState.busy=true;button.disabled=true;button.textContent='正在识别…';box.classList.add('busy');
    asrStatus(scoped?'正在识别选中的音视频片段，原有字幕会保留…':'未选择片段，正在识别整条时间轴…');
    const token=epoch,target=project;
    try{
      const result=await api('/editor/asr/recognize',{title:project.title,body:asrBody,language:asrState.language,target_language:asrState.target});
      if(token!==epoch||project!==target)return;
      if(JSON.stringify(project)!==revision)throw Error('识别期间项目内容发生变化，未应用结果，请重新识别');
      const look={...inheritCaptionLook(target.body.captions[0]||null),size:14,outline:0};
      const bilingual=result.target==='zh-en', lanes={};
      if(bilingual){
        const used=new Set((project.body.tracks||[]).map(t=>t.id));
        for(const lang of ['zh','en']){let id='caption-bilingual-'+lang,n=2;while(used.has(id))id='caption-bilingual-'+lang+'-'+n++;used.add(id);lanes[lang]=id;}
      }
      const generated=result.captions.map(c=>({...CAPTION_STYLE,...look,...c,font:c.font||look.font||'default',start:c.start+base,end:c.end+base,...(bilingual?{track:lanes[c.lang],x:50,y:c.lang==='zh'?82:88}:{})}));
      if((scoped?project.body.captions.length:0)+generated.length>600)throw Error('生成字幕超过 600 条上限，请缩短片段后重试');
      project.body.captions=scoped?[...project.body.captions,...generated]:generated;
      mark();render();
      const langLabel=asrState.info?.languages.find(l=>l.id===result.language)?.label||result.language;
      const targetLabel=result.target?`，已翻译成${result.target==='zh-en'?'中英双语（分别位于两条字幕轨）':asrState.info?.languages.find(l=>l.id===result.target)?.label||result.target}`:'';
      asrStatus(`识别完成：${result.captions.length} 条字幕，识别语种 ${langLabel}${targetLabel}。请检查后保存项目。`);
      toast('已识别 '+result.captions.length+' 条字幕');
    }catch(e){asrStatus(e.message||String(e),true);fail(e);}
    finally{asrState.busy=false;button.disabled=false;button.textContent=label;box.classList.remove('busy');}
  }
  function renderAudio(){
    const audio=project.body.audio;$('edit-audio-name').textContent=audio?'已添加配音 / 背景音乐':'未添加音频';$('edit-audio-volume').value=audio?.volume??.7;
    if(audio){const url='/api/assets/'+audio.asset_id;if(voice.getAttribute('src')!==url)voice.src=url;voice.volume=trackMuted(audio.track)?0:Math.min(1,audio.volume??.7);}
    else{voice.pause();voice.removeAttribute('src');}
  }
  function move(from,to){if(to<0||to>=clips().length||from===to)return;setTimelineSelection(['video:'+from]);moveSelectionTo(offset(to));}

  function seek(time,keepPlaying=false){
    if(!project)return;
    endSourcePreview();
    clearHoverPreview(false);
    const requested=HubTimeline.clamp(time,total());
    position=requested;
    window.hubMultitrackPreview?.sync(project.body,requested,keepPlaying);
    if(project.body.audio&&Number.isFinite(voice.duration)){
      voice.currentTime=Math.min(requested,voice.duration);
      if(keepPlaying&&requested<voice.duration)tryPlay(voice);else voice.pause();
    }
    syncDetached(true,keepPlaying);paint();
  }
  function startPlayback(){
    endSourcePreview();pause();if(!total())return;
    window.voicePanel?.stopAllAudio();playing=true;$('edit-play').textContent='暂停';
    seek(position>=total()?0:position,true);playClock=performance.now();
    let buffering=false,lastPaint=playClock,lastFrame=playClock;const tick=now=>{
      if(!playing)return;
      // Preview up to 30 fps without changing the 24 fps edit/timecode grid.
      const frameInterval=1000/30,frameElapsed=now-lastFrame;
      if(frameElapsed<frameInterval){playTimer=requestAnimationFrame(tick);return;}
      lastFrame=now-frameElapsed%frameInterval;const interval=1000/FPS,elapsed=now-lastPaint;
      if(!window.hubMultitrackPreview?.ready(project.body,position)){buffering=true;window.hubMultitrackPreview?.pause();voice.pause();detachedPlayers.forEach(a=>a.pause());playClock=now;playTimer=requestAnimationFrame(tick);return;}
      if(buffering){buffering=false;if(project.body.audio){voice.currentTime=Math.min(position,voice.duration||0);tryPlay(voice);}syncDetached(true,true);}
      const next=position+(now-playClock)/1000;playClock=now;
      if(next>=total()){pause();seek(HubTimeline.lastFrame(total()));return;}
      position=next;window.hubMultitrackPreview?.sync(project.body,position,true);syncDetached(false,true);if(elapsed>=interval){lastPaint=now-elapsed%interval;paint();}playTimer=requestAnimationFrame(tick);
    };playTimer=requestAnimationFrame(tick);
  }

  const captionOutline=style=>{
    if(!style.outline)return 'none';
    const width=style.outline/7.2,rings=[];
    for(let step=0;step<8;step++){const angle=step*Math.PI/4;rings.push(`${(Math.cos(angle)*width).toFixed(3)}cqw ${(Math.sin(angle)*width).toFixed(3)}cqw 0 ${style.outline_color}`);}
    return rings.join(',');
  };
  function paint(){
    const clock=$('edit-clock'),seekBar=$('edit-seek'),last=HubTimeline.lastFrame(total()),label=`${tc(position)} / ${tc(last)}`;
    if(clock.textContent!==label)clock.textContent=label;
    if(Number(seekBar.max)!==last)seekBar.max=last;
    seekBar.value=position;paintPlayhead();
    paintCaptions();
  }
  // Preview captions only (no clock / playhead layout work), so style edits stay cheap.
  // Lines with x/y live in the free layer at that spot; the rest stack bottom-centre as before.
  function paintCaptions(){
    const stacked=$('edit-caption'),free=$('edit-caption-free');if(!stacked)return;
    const picked=selectedCaptionIndexes(),rows=[];
    (project?.body.captions||[]).forEach((c,i)=>{if(position>=c.start&&position<c.end)rows.push({c,i,style:captionStyle(c),anim:captionAnim(c),on:picked.includes(i)});});
    const signature=JSON.stringify(rows.map(r=>[r.i,r.c.text,r.c.font||'',r.style,r.on,r.anim]));
    if(stacked.dataset.signature===signature){paintCaptionAnimations();return;}
    stacked.dataset.signature=signature;stacked.replaceChildren();free?.replaceChildren();
    for(const {c,i,style,on} of rows){
      const line=el('div',captionText(c.text,style),'edit-caption-line'+(on?' selected':''));
      line.dataset.caption=String(i);line.title='按住拖动，可自由摆放字幕位置';
      line.style.fontFamily=fontCss(c.font);line.style.fontSize=`${(4.5*style.size/100).toFixed(2)}cqw`;line.style.color=style.color;line.style.textAlign=style.align;line.style.fontWeight=style.bold?'800':'400';line.style.fontStyle=style.italic?'italic':'normal';line.style.letterSpacing=`${(style.spacing/7.2).toFixed(2)}cqw`;line.style.textShadow=captionOutline(style);
      line.onpointerdown=event=>beginCaptionDrag(event,i);
      if(style.x!==undefined&&free){
        line.classList.add('free');line.style.left=style.x+'%';line.style.top=style.y+'%';
        line.style.transform=`translate(${{left:'0',center:'-50%',right:'-100%'}[style.align]},-50%)`;
        line.style.maxWidth=Math.max(8,style.align==='left'?100-style.x:style.align==='right'?style.x:2*Math.min(style.x,100-style.x))+'%';
        line.dataset.baseTransform=line.style.transform;
        free.append(line);
      }else stacked.append(line);
    }
    paintCaptionAnimations();
  }
  // Per-frame animation state for the caption lines currently on screen. Pure function of the playhead,
  // so a paused frame, a scrubbed frame and a burned-in frame all show the same pose.
  function captionPose(caption,anim,now){
    const span=Math.max(.05,caption.end-caption.start),local=Math.max(0,Math.min(span,now-caption.start));
    const pose={alpha:1,scale:1,shift:0,rotate:0,reveal:1,lit:-1};
    const enter=anim.in,leave=anim.out,loop=anim.loop;
    if(enter){
      const window_=Math.min(enter.dur,span),p=Math.max(0,Math.min(1,local/window_));
      if(enter.id==='fade')pose.alpha=Math.min(pose.alpha,p);
      else if(enter.id==='rise'){pose.alpha=Math.min(pose.alpha,p);pose.shift=(1-p)*12;}
      else if(enter.id==='zoom'){pose.alpha=Math.min(pose.alpha,p);pose.scale=1+.65*(1-p);}
      else if(enter.id==='pop'){
        pose.alpha=Math.min(pose.alpha,p);
        const mid=window_*.55;
        pose.scale=local<mid?.55+.57*(local/mid):1.12-.12*Math.min(1,(local-mid)/Math.max(.01,window_-mid));
      }else if(enter.id==='type')pose.reveal=p;
    }
    if(leave){
      const window_=Math.min(leave.dur,span),start=caption.end-window_,p=Math.max(0,Math.min(1,(now-start)/window_));
      if(leave.id==='fade')pose.alpha=Math.min(pose.alpha,1-p);
      else if(leave.id==='sink'){pose.alpha=Math.min(pose.alpha,1-p);pose.shift+=p*12;}
      else if(leave.id==='shrink'){pose.alpha=Math.min(pose.alpha,1-p);pose.scale*=1-.28*p;}
    }
    if(loop){
      if(loop.id==='breathe')pose.scale*=1+.05*Math.sin(2*Math.PI*local/Math.max(.2,loop.dur*2));
      else if(loop.id==='shake')pose.rotate=2*Math.sin(2*Math.PI*local/Math.max(.15,loop.dur*.7));
    }
    return pose;
  }
  function paintCaptionAnimations(){
    const stage=$('edit-stage'),lines=document.querySelectorAll('.edit-caption-line');if(!lines.length)return;
    const stageHeight=stage?.clientHeight||0,captions=project?.body.captions||[];
    for(const line of lines){
      const caption=captions[Number(line.dataset.caption)];if(!caption)continue;
      const anim=captionAnim(caption),text=captionText(caption.text,captionStyle(caption));
      if(!Object.keys(anim).length){
        if(line.dataset.karaoke){line.dataset.karaoke='';line.textContent=text;}
        line.style.opacity='';const base=line.dataset.baseTransform||'';line.style.transform=base;continue;
      }
      const pose=captionPose(caption,anim,position);
      const karaoke=anim.loop?.id==='karaoke';
      if(anim.loop?.id==='spoken'){
        const word=(caption.words||[]).find(w=>position-caption.start>=w.start&&position-caption.start<w.end&&caption.text.slice(w.from,w.to)===w.text);
        const highlight=anim.loop.color;
        const key=JSON.stringify([text,word?.from,word?.to,highlight]);
        if(line.dataset.karaoke!==key){
          if(word&&text.length===caption.text.length){const active=el('span',text.slice(word.from,word.to));active.style.color=highlight;line.replaceChildren(document.createTextNode(text.slice(0,word.from)),active,document.createTextNode(text.slice(word.to)));}
          else line.textContent=text;
          line.dataset.karaoke=key;
        }
      }else if(karaoke){
        if(line.dataset.karaoke!==text){
          line.replaceChildren(...[...text].map(char=>{const span=el('span',char,'caption-kara');return span;}));
          line.dataset.karaoke=text;
        }
        const chars=line.children,lit=Math.floor((Math.max(0,position-caption.start)/Math.max(.05,caption.end-caption.start))*chars.length);
        [...chars].forEach((span,index)=>{span.style.color=index<lit?KARAOKE_COLOR:'';});
      }else{
        let shown=text;
        if(pose.reveal<1)shown=text.slice(0,Math.max(1,Math.ceil(pose.reveal*text.length)));
        if(line.dataset.karaoke||line.textContent!==shown){line.dataset.karaoke='';line.textContent=shown;}
      }
      line.style.opacity=String(Math.max(0,Math.min(1,pose.alpha)));
      const moves=[];
      const base=line.dataset.baseTransform;
      if(base)moves.push(base);
      if(pose.shift)moves.push(`translateY(${(pose.shift/100*stageHeight).toFixed(1)}px)`);
      if(Math.abs(pose.scale-1)>.001)moves.push(`scale(${pose.scale.toFixed(3)})`);
      if(pose.rotate)moves.push(`rotate(${pose.rotate.toFixed(2)}deg)`);
      line.style.transform=moves.join(' ');
    }
  }
  // Drag a caption in the preview. Every caption in the same lane follows (all lanes if everything is
  // selected); other lanes stay put. The whole gesture is one undo step.
  function beginCaptionDrag(event,index){
    if(event.button!==0||busy||!project)return;
    const captions=project.body.captions,stage=$('edit-stage'),line=event.currentTarget;if(!captions[index])return;
    event.preventDefault();event.stopPropagation();pause();commitEdits();
    const stageBox=stage.getBoundingClientRect(),lineBox=line.getBoundingClientRect();if(!stageBox.width||!stageBox.height)return;
    const align=captionStyle(captions[index]).align;
    const anchorX=align==='left'?lineBox.left:align==='right'?lineBox.right:lineBox.left+lineBox.width/2,anchorY=lineBox.top+lineBox.height/2;
    const grabX=event.clientX-anchorX,grabY=event.clientY-anchorY;
    if(!selectedCaptionIndexes().includes(index)){setTimelineSelection(['caption:'+index],{primary:index});runSelectionSync(true);}
    else primaryCaption=index;
    // 预览位置跟随应用范围，锁定字幕不移动。
    const scope=captionScope().indexes.filter(i=>!captions[i].locked),before=new Map(scope.map(i=>[i,{x:captions[i].x,y:captions[i].y}]));
    const x0=event.clientX,y0=event.clientY;let moved=false,last=event,pending=0;
    const place=()=>{
      pending=0;if(!moved&&Math.hypot(last.clientX-x0,last.clientY-y0)<4)return;moved=true;
      const x=Math.min(100,Math.max(0,Math.round((last.clientX-grabX-stageBox.left)/stageBox.width*1000)/10)),y=Math.min(100,Math.max(0,Math.round((last.clientY-grabY-stageBox.top)/stageBox.height*1000)/10));
      for(const i of scope){captions[i].x=x;captions[i].y=y;}
      paintCaptions();
    };
    const move=e=>{last=e;if(!pending)pending=requestAnimationFrame(place);};
    const detach=()=>{cancelAnimationFrame(pending);pending=0;window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('keydown',escape);};
    const finish=()=>{if(pending){cancelAnimationFrame(pending);place();}detach();if(!moved)return;for(const i of scope)syncCaptionRow(i);editedLive();commitEdits();renderTextPanel();};
    const cancel=()=>{detach();if(!moved)return;for(const [i,old] of before){if(old.x===undefined)delete captions[i].x;else captions[i].x=old.x;if(old.y===undefined)delete captions[i].y;else captions[i].y=old.y;}paintCaptions();};
    const escape=e=>{if(e.key==='Escape'){e.preventDefault();cancel();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('keydown',escape);
  }
  player.ontimeupdate=()=>{};
  player.onended=()=>{};
  player.onerror=()=>{pause();fail('视频预览读取失败，请刷新素材或重新登录');};
  voice.onloadedmetadata=()=>{if(project?.body.audio&&Number.isFinite(voice.duration)&&project.body.audio.duration!==voice.duration){project.body.audio.duration=voice.duration;mark();render();}if(playing&&project?.body.audio&&position<voice.duration){voice.currentTime=position;tryPlay(voice);}};
  async function save(){
    if(!project)return;
    commitEdits();const target=project;
    // Every caller (toolbar, workspace, voice and export) shares the same in-flight save.
    // Never retry a request here: a rejected/unknown response may already have been persisted.
    if(pendingSaves.has(target))return pendingSaves.get(target);
    const token=epoch,revision=JSON.stringify(target),payload=JSON.parse(revision);
    const pending=(async()=>{
      const result=await api('/editor/projects',payload);
      if(token!==epoch||!me)return;
      projects=projects.filter(p=>p.id!==result.id);projects.unshift(result);
      if(project!==target){renderProjects();throw Error('原项目已保存，但当前项目已切换，未继续后续操作');}
      if(JSON.stringify(target)===revision){Object.assign(target,result);dirty=false;lastEdit=snapshot();}
      else{target.id=result.id;target.version=result.version;dirty=true;}
      render();saveRecovery();$('edit-save-state').textContent=dirty?'保存后又有新更改':'已保存';return result;
    })();
    pendingSaves.set(target,pending);
    try{return await pending;}finally{if(pendingSaves.get(target)===pending)pendingSaves.delete(target);}
  }
  let projectChangePending=false;
  async function confirmProjectChange(action){
    if(projectChangePending)return false;
    if(!dirty)return true;
    projectChangePending=true;const original=project,token=epoch;
    try{
      const choice=await new Promise(resolve=>{
        const dialog=el('dialog',undefined,'editor-unsaved-dialog'),heading=el('h2','当前剪辑尚未保存'),text=el('p',`${action}前，是否保存当前剪辑的更改？`),actions=el('div',undefined,'editor-unsaved-actions');
        const cancel=el('button','取消'),discard=el('button','不保存，继续'),saveButton=el('button','保存并继续','primary');
        [cancel,discard,saveButton].forEach(button=>button.type='button');actions.append(cancel,discard,saveButton);dialog.append(heading,text,actions);dialog.setAttribute('aria-label','未保存的剪辑');document.body.append(dialog);
        let result='cancel';cancel.onclick=()=>dialog.close();discard.onclick=()=>{result='discard';dialog.close();};saveButton.onclick=()=>{result='save';dialog.close();};dialog.addEventListener('close',()=>{dialog.remove();resolve(result);},{once:true});dialog.showModal();cancel.focus();
      });
      if(choice==='cancel'||project!==original||epoch!==token)return false;
      if(choice==='save'){
        lock(true);try{const result=await save();if(!result||project!==original||epoch!==token||dirty){toast('保存后剪辑仍有更改，请确认后再切换',true);return false;}toast('剪辑已保存');}
        catch(e){fail(e);return false;}finally{if(epoch===token)lock(false);}
      }
      return project===original&&epoch===token;
    }finally{projectChangePending=false;}
  }
  const EXPORT_STATES={queued:'等待导出',rendering:'正在导出',ready:'已完成',failed:'失败'};
  function exportRowNode(job){
    const row=el('div',undefined,'edit-export-row');
    const chip=el('span',EXPORT_STATES[job.state]||job.state,'status');
    const error=el('span','','error');error.hidden=true;
    row.append(el('span',job.name||projects.find(p=>p.id===job.project_id)?.title||'剪辑项目'),chip,error);
    return {node:row,chip,error,ready:false};
  }
  function updateExportRow(entry,job){
    if(job.archive){
      if(!entry.archive){entry.archive=el('span','','fine');entry.node.append(entry.archive);}
      const labels={waiting:'飞书：等待上传',uploading:'飞书：上传中',ready:'飞书：已上传',attention:'飞书：需重试（归档设置）',failed:'飞书：未上传'};
      entry.archive.textContent=job.archive.state==='waiting'&&job.state!=='ready'?'飞书：等待视频导出完成':labels[job.archive.state]||'飞书归档';entry.archive.title=job.archive.error||'';
      if(job.archive.file_token&&!entry.archiveLink){const link=el('a','打开飞书文件');link.href='https://www.feishu.cn/file/'+encodeURIComponent(job.archive.file_token);link.target='_blank';link.rel='noopener';entry.node.append(link);entry.archiveLink=link;}
    }
    if(!entry.chip.dataset.broken)entry.chip.textContent=EXPORT_STATES[job.state]||job.state;
    entry.error.textContent=job.error||'';entry.error.hidden=!job.error;
    if(job.state!=='ready'||entry.ready)return;
    const link=el('a','下载 MP4');link.href='/api/editor/exports/'+job.id+'/video?download=true';
    const details=el('details'),summary=el('summary','预览成品'),video=el('video');
    details.dataset.job=job.id;details.open=exportOpen.has(job.id);
    const loadPreview=()=>{if(!video.getAttribute('src'))video.src='/api/editor/exports/'+job.id+'/video';};
    details.addEventListener('toggle',()=>{if(details.open){exportOpen.add(job.id);loadPreview();}else{exportOpen.delete(job.id);video.pause();}});
    video.controls=true;video.preload='metadata';
    if(details.open)loadPreview();
    video.addEventListener('error',()=>{summary.textContent='预览成品（读取失败，请重新导出）';entry.chip.dataset.broken='1';entry.chip.textContent='文件不可读';});
    details.append(summary,video);entry.node.append(link,details);entry.ready=true;
  }
  async function exports(){
    const token=epoch;const jobs=await api('/editor/exports');if(token!==epoch||!me)return;
    hubNotice.observe('export:',jobs);
    exportPending=jobs.some(job=>job.state==='queued'||job.state==='rendering'||['waiting','uploading'].includes(job.archive?.state));
    const list=$('edit-exports-list');
    const ids=jobs.map(job=>job.id).join('|');
    if(exportIds!==ids){
      exportIds=ids;const placeholder=list.querySelector(':scope > p');const wanted=new Set(jobs.map(job=>job.id));
      for(const [id,entry] of [...exportRows])if(!wanted.has(id)){entry.node.remove();exportRows.delete(id);}
      const opened=new Set([...list.querySelectorAll('details.export-day[open]')].map(n=>n.dataset.day));list.replaceChildren();const groups=new Map();
      jobs.forEach(job=>{const day=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai'}).format(new Date(job.created*1000));let group=groups.get(day);if(!group){group=el('details',undefined,'export-day');group.dataset.day=day;group.open=opened.has(day)||groups.size===0;group.append(el('summary',day));groups.set(day,group);list.append(group);}let entry=exportRows.get(job.id);if(!entry){entry=exportRowNode(job);exportRows.set(job.id,entry);}group.append(entry.node);});
      if(jobs.length)placeholder?.remove();
      else if(!placeholder)list.append(el('p','导出的成品会出现在这里。','fine'));
    }
    for(const job of jobs)updateExportRow(exportRows.get(job.id),job);
  }
  function refreshExports(){return exports().catch(()=>{});}
  $('edit-clips').ondragover=showInsertion;
  $('edit-clips').ondrop=dropInsertion;
  $('edit-clips').ondragleave=event=>{if(!$('edit-clips').contains(event.relatedTarget))clearInsertion();};
  $('edit-new').onclick=async()=>{if(!await confirmProjectChange('新建项目'))return;pause();project=fresh();selected=0;dirty=false;position=0;requestKey=crypto.randomUUID();player.removeAttribute('src');historyReset();render();saveRecovery();};
  $('edit-projects').onchange=async event=>{const id=event.target.value;if(!projects.some(p=>p.id===id))return;if(!await confirmProjectChange('打开其他项目')){renderProjects();return;}const token=epoch,previous=project,revision=project?snapshot():null;try{const next=await readProject(id);if(next?.body&&(next.body.clips?.length||next.body.audio_clips?.length))await ensureFullLibrary();if(token!==epoch||!me)return;if(project!==previous||(project?snapshot():null)!==revision)throw Error('读取期间项目已变化，请重新选择');pause();project=structuredClone(next);selected=0;position=0;dirty=false;requestKey=crypto.randomUUID();historyReset();render();if(clips().length)seek(0);saveRecovery();}catch(e){renderProjects();fail(e);}};
  $('edit-title').oninput=event=>{if(project){project.title=event.target.value;mark();}};
  $('edit-ratio').onchange=event=>{project.body.ratio=event.target.value;mark();render();};
  $('edit-refresh').onclick=()=>refresh().catch(fail);
  $('edit-save').onclick=async()=>{lock(true);try{await save();}catch(e){fail(e);}finally{lock(false);}};
  function askExportName(){return new Promise(resolve=>{
    const dialog=el('dialog',undefined,'export-name-dialog'),form=el('form'),heading=el('h2','命名导出视频'),label=el('label','视频名称'),input=el('input'),actions=el('div',undefined,'export-name-actions');
    input.value=project?.title||'未命名视频';input.maxLength=100;input.required=true;input.setAttribute('aria-label','视频名称');label.append(input);
    const cancel=el('button','取消'),confirm=el('button','导出 MP4');cancel.type='button';confirm.type='submit';actions.append(cancel,confirm);form.append(heading,label,actions);dialog.append(form);document.body.append(dialog);
    let value=null;cancel.onclick=()=>dialog.close();form.onsubmit=e=>{e.preventDefault();if(!input.value.trim())return;value=input.value.trim();dialog.close();};dialog.addEventListener('close',()=>{dialog.remove();resolve(value);},{once:true});dialog.showModal();input.focus();input.select();
  });}
  $('edit-export').onclick=async()=>{const target=project,revision=snapshot(),selection=exportSelection();const name=await askExportName();if(name===null)return;lock(true);try{const capability=await api('/editor/selection-export-capability').catch(()=>null);if(capability?.selection_export!==1)throw Error('导出功能尚未更新，请联系管理员安全重启服务后再试');if(project!==target||snapshot()!==revision)throw Error('剪辑已变更，请核对当前项目和选区后重新导出');const result=await save();if(!result)return;if(project!==target||project.id!==result.id||project.version!==result.version||dirty)throw Error('保存期间剪辑有变化，请核对后重新导出');const job=await api('/editor/projects/'+result.id+'/export',{request_key:crypto.randomUUID(),version:result.version,selection,name});hubNotice.begin('export:'+job.id,selection?'选中内容已加入导出队列':'时间轴已加入导出队列','查看导出任务','editor','#edit-exports-list');await exports();}catch(e){fail(e);}finally{lock(false);}};
  $('edit-play').onclick=()=>playing?pause():startPlayback();
  $('edit-seek').oninput=event=>{pause();seek(Number(event.target.value));};
  function trim(key,value){const clip=clips()[selected];if(!clip)return;pause();const max=source(clip.task_id)?.duration||clip.end;value=Number(value);if(!Number.isFinite(value)||value<0||value>max||(key==='start'?clip.end-value:value-clip.start)<.1){renderProperties();return fail('入点必须早于出点，且至少保留 0.1 秒');}const lim=trimLimits(clip,key);if(value<lim.min-1e-6||value>lim.max+1e-6){renderProperties();return fail('与相邻片段重叠，请先留出空间');}const newAt=offset(selected)+(value-clip.start)/(clip.speed||1);editTimeline(()=>{if(key==='start')clip.at=newAt;clip[key]=value;clampCaptions();},new Set([clip]));mark();render();seek(offset(selected));}
  for(const id of ['edit-in','edit-in-range'])$(id).onchange=e=>trim('start',e.target.value);
  for(const id of ['edit-out','edit-out-range'])$(id).onchange=e=>trim('end',e.target.value);
  $('edit-volume').oninput=e=>{const clip=clips()[selected];if(clip){clip.volume=Number(e.target.value);if(Number(player.dataset.clip)===selected)player.volume=Math.min(1,clip.volume);mark();}};
  $('edit-earlier').onclick=()=>move(selected,selected-1);$('edit-later').onclick=()=>move(selected,selected+1);
  $('edit-remove').onclick=deleteSelection;
  $('edit-split').onclick=()=>{const compound=selectedCompound();if(compound)return splitCompound(compound);const rows=selectedRows(),clip=rows.length===1&&rows[0].key==='video:'+selected?rows[0].item:null;if(!clip)return fail('请选择一个视频片段再分割');if(clip.edit_compound&&!expandedCompounds.has(clip.edit_compound))return fail('请双击展开复合片段，再分割内部片段');const rate=clip.speed||1,at=clip.start+(position-offset(selected))*rate;if((at-clip.start)/rate<.1||(clip.end-at)/rate<.1)return fail('请把播放位置移到当前片段中间，再分割');if(clips().length>=50)return fail('最多 50 个片段');pause();clips().splice(selected,1,{...clip,end:at},{...clip,start:at,at:position});mark();render();seek(position);};
  $('edit-asr-run').onclick=()=>runAsr();
  // 新字幕继承「字幕模板」：选中字幕 > 统一模式下取第一条 > 项目默认。样式和动画一起继承，
  // 这样统一设置过的字幕风格与动画对后续新增/识别的字幕自动生效。
  function captionTemplate(){
    return captionTarget()?.caption||null;
  }
  function inheritCaptionLook(template){
    const look={};
    if(!template)return look;
    look.track=template.track||'caption-main';
    for(const key of STYLE_KEYS)if(template[key]!==undefined)look[key]=template[key];
    if(template.font)look.font=template.font;
    if(template.anim)look.anim=structuredClone(template.anim);
    return look;
  }
  $('edit-add-caption').onclick=()=>{if(project.body.captions.length>=600)return fail('最多 600 条字幕');commitEdits();const inherited=inheritCaptionLook(captionTemplate());const start=Math.max(0,position),end=start+2;let track='caption-main';if(project.body.captions.some(c=>(c.track||'caption-main')===track&&c.start<end&&c.end>start))track='caption-'+crypto.randomUUID();project.body.tracks||=[];if(!project.body.tracks.some(t=>t.id===track))project.body.tracks.push({id:track,muted:false});project.body.captions.push({text:'请输入字幕',start,end,...CAPTION_STYLE,...inherited,track});trackSelection={kind:'caption',index:project.body.captions.length-1};timelineSelection.clear();primaryCaption=project.body.captions.length-1;mark();render();window.hubEditorShell?.openRight?.('text');setTimeout(()=>$('edit-text-panel')?.querySelector('textarea')?.focus({preventScroll:true}),0);};
  $('edit-audio-file').onchange=async event=>{const file=event.target.files[0];if(!file||!project)return;const token=epoch,target=project;if(file.size>64*1024*1024)return fail('音频不能超过 64 MB');try{const r=await fetch('/api/assets',{method:'POST',credentials:'same-origin',headers:{'Content-Type':audioMime(file),'X-Hub-Request':'1','X-File-Name':encodeURIComponent(file.name)},body:file});const asset=await r.json();if(!r.ok)throw Error(asset.detail||'音频上传失败');if(token!==epoch||project!==target)return;project.body.audio={asset_id:asset.id,volume:.7};mark();renderAudio();$('edit-audio-name').textContent=file.name;}catch(e){fail(e);}finally{event.target.value='';}};
  $('edit-audio-volume').oninput=e=>{if(project?.body.audio){project.body.audio.volume=Number(e.target.value);voice.volume=Math.min(1,project.body.audio.volume);mark();}};
  $('edit-audio-remove').onclick=()=>{if(project){project.body.audio=null;mark();renderAudio();}};
  const actions=el('div',undefined,'edit-actions');
  for(const [id,text]of [['edit-undo','撤销'],['edit-redo','重做'],['edit-detach','分离音频']]){const b=el('button',text,'secondary');b.id=id;b.type='button';actions.append(b);}
  const replacement=el('select');replacement.id='edit-replacement';replacement.setAttribute('aria-label','替换画面素材');
  const replace=el('button','保留原声，替换画面','secondary');replace.type='button';actions.append(replacement,replace);$('edit-clip-fields').after(actions);
  const audioPanel=el('section'),audioTitle=el('h2','独立原声音轨'),audioList=el('div');audioList.id='edit-detached-list';audioPanel.append(audioTitle,el('p','锁定后保留当前时间位置。','fine'),audioList);document.querySelector('.edit-bottom').append(audioPanel);
  function renderDetached(){
    const previousPlayers=detachedPlayers.slice(),usedPlayers=new Set();detachedPlayers=[];audioList.replaceChildren();
    const prev=replacement.value;replacement.replaceChildren(new Option('选择替换画面…',''));for(const t of library)replacement.append(new Option(t.title||'生成视频',t.id));replacement.value=prev;
    const sounds=project.body.audio_clips||[];
    if(!sounds.length)audioList.append(el('p','选择视频片段，再点击“分离音频”。','fine'));
    sounds.forEach((clip,i)=>{
      const url=soundUrl(clip);let audio=previousPlayers.find(a=>!usedPlayers.has(a)&&a.dataset.source===url);
      if(!audio){audio=el('audio');audio.src=url;audio.dataset.source=url;audio.preload='metadata';audio.dataset.timelineAudio='true';audio.hidden=true;audio.onloadedmetadata=()=>syncDetached(true,playing);audio.onerror=()=>fail('独立原声读取失败');}
      usedPlayers.add(audio);audio.volume=clip.muted?0:Math.min(1,clip.volume??1);audioList.append(audio);detachedPlayers.push(audio);
      const row=el('div',undefined,'detached-row');row.append(el('strong',(clip.source==='voice'?'AI 配音 ':'原声 ')+(i+1)));
      const mute=el('button',clip.muted?'已静音 · 恢复声音':'静音');mute.type='button';mute.setAttribute('aria-pressed',String(!!clip.muted));mute.onclick=()=>{pause();clip.muted=!clip.muted;mark();render();};row.append(mute);
      const lock=el('button',clip.locked?'已锁定 · 点击解锁':'未锁定 · 点击锁定');lock.type='button';lock.setAttribute('aria-pressed',String(clip.locked));lock.onclick=()=>{pause();clip.locked=!clip.locked;mark();render();};row.append(lock);
      for(const [key,title]of [['at','时间轴位置 / 秒'],['start','素材入点 / 秒'],['end','素材出点 / 秒'],['volume','音量 0–1'],['fade_in','淡入 / 秒'],['fade_out','淡出 / 秒']]){
        const label=el('label',title),input=el('input');input.type='number';input.step=key==='volume'?'.05':'.01';input.min=0;if(key==='volume')input.max=2;input.value=clip[key]??0;input.disabled=clip.locked;
        input.onchange=()=>{const value=Number(input.value);const next={...clip,[key]:value};if(!Number.isFinite(value)||value<0||next.end-next.start<.1||next.volume>2||(next.fade_in||0)+(next.fade_out||0)>next.end-next.start||next.end>soundMax(clip)+.05){input.value=clip[key];return fail('原声位置、时长或音量无效');}pause();linkedCaptions(clip,next);clip[key]=value;mark();render();};label.append(input);row.append(label);
      }
      if(clip.source==='voice'){const link=el('button',clip.link_captions===false?'字幕独立 · 点击联动':'字幕联动 · 点击解除');link.onclick=()=>{clip.link_captions=clip.link_captions===false;mark();render();};row.append(link);}
      const remove=el('button','移除音轨');remove.disabled=clip.locked;remove.onclick=()=>{pause();sounds.splice(i,1);mark();render();};row.append(remove);audioList.append(row);
    });
    previousPlayers.filter(a=>!usedPlayers.has(a)).forEach(a=>{a.pause();a.removeAttribute('src');a.load();a.remove();});
    replace.disabled=!clips()[selected];
  }
  function syncDetached(force,play){
    (project?.body.audio_clips||[]).forEach((c,i)=>{const a=detachedPlayers[i];if(!a)return;const active=position>=c.at&&position<c.at+c.end-c.start;const time=c.start+position-c.at;
      if(active&&a.readyState>=1){if(force||Math.abs(a.currentTime-time)>.15)a.currentTime=time;const elapsed=position-c.at,remaining=c.end-c.start-elapsed;const gain=Math.min(1,c.fade_in?elapsed/c.fade_in:1,c.fade_out?remaining/c.fade_out:1);a.volume=c.muted||trackMuted(c.track)?0:Math.min(1,c.volume*Math.max(0,gain));if(play&&a.paused)tryPlay(a);if(!play)a.pause();}else a.pause();
    });
  }
  function detach(){
    const clip=clips()[selected];if(!clip)throw Error('请先选择视频片段');
    if(Math.abs((clip.speed||1)-1)>.001)throw Error('该片段已变速，请先恢复 1× 再分离原声，避免音画不同步');
    if(clip.volume===0)throw Error('该片段已静音；若已分离，可在独立原声音轨中管理');
    project.body.audio_clips??=[];if(project.body.audio_clips.length>=50)throw Error('最多 50 段独立原声');
    project.body.audio_clips.push({task_id:clip.task_id,start:clip.start,end:clip.end,at:offset(selected),track:'audio-'+crypto.randomUUID(),volume:clip.volume,locked:false});clip.volume=0;clip.audio_detached=true;
  }
  $('edit-detach').onclick=async()=>{try{const rows=selectedRows(),clip=rows.length===1&&rows[0].key==='video:'+selected?rows[0].item:null;if(!clip)return fail('请选择一个视频片段再分离音频');const target=project,info=await api('/media/source/'+clip.task_id);if(project!==target||selectedRows().length!==1||selectedRows()[0].item!==clip)return;if(!info.has_audio)throw Error('该片段没有音轨');pause();detach();mark();render();seek(position);}catch(e){fail(e);}};
  replace.onclick=async()=>{try{const clip=clips()[selected],item=source(replacement.value);if(!clip||!item)throw Error('请选择视频片段和替换素材');if(Math.abs((clip.speed||1)-1)>.001)throw Error('画面替换不支持已变速片段，请先在“变速”里恢复 1×');const span=clip.end-clip.start;if(item.duration<span)throw Error('替换素材不足原片段时长，请先裁剪片段或选择更长素材');
    const target=project,info=await api('/media/source/'+clip.task_id);if(project!==target||clips()[selected]!==clip)return;pause();if(clip.volume>0&&info.has_audio)detach();clip.task_id=item.id;clip.start=0;clip.end=span;clip.volume=0;mark();render();seek(offset(selected));
  }catch(e){fail(e);}};
  function historyStep(from,to){commitEdits();if(!from.length||!project)return;primaryCaption=null;panelSig='';pause();to.push(snapshot());const state=JSON.parse(from.pop());marqueeSelectionActive=false;timelineSelection.clear();videoSelection.clear();trackSelection=null;project.title=state.title;project.body=state.body;lastEdit=snapshot();dirty=true;requestKey=crypto.randomUUID();position=Math.min(position,Math.max(0,total()-.001));render();if(clips().length)seek(position);}
  $('edit-undo').onclick=()=>historyStep(undo,redo);$('edit-redo').onclick=()=>historyStep(redo,undo);


  const tlPrefs=(()=>{try{return JSON.parse(localStorage.getItem('hub-timeline-prefs')||'{}')||{};}catch{return {};}})();
  let snapEnabled=tlPrefs.snap!==false,magnetOn=tlPrefs.magnet!==false,linkOn=tlPrefs.link!==false,trimmingActive=false,altHeld=false;
  const savePrefs=()=>{try{localStorage.setItem('hub-timeline-prefs',JSON.stringify({snap:snapEnabled,magnet:magnetOn,link:linkOn,hover:hoverEnabled}));}catch{}};
  const scroll=document.querySelector('.track-scroll');
  const head=el('div',undefined,'timeline-playhead');head.setAttribute('aria-hidden','true');scroll.append(head);
  const dragNote=el('span','','trim-feedback');dragNote.setAttribute('role','status');document.querySelector('.edit-timeline .edit-section-heading').append(dragNote);
  const tlTools=el('div','','timeline-tools');tlTools.setAttribute('role','toolbar');tlTools.setAttribute('aria-label','时间轴工具');
  document.querySelector('.edit-timeline .edit-section-heading').insertAdjacentElement('afterend',tlTools);
  const toolButton=(text,title,onclick)=>{const b=el('button',text,'secondary tl-tool');b.type='button';b.title=title;b.onclick=onclick;tlTools.append(b);return b;};
  const toggleButton=(text,title,get,set)=>{const b=toolButton(text,title,()=>{set(!get());savePrefs();paint();});const paint=()=>{b.setAttribute('aria-pressed',String(get()));b.classList.toggle('active',get());};paint();return b;};
  let hoverEnabled=tlPrefs.hover!==false,hoverTime=null,hoverFrame=0,hoverX=0,hoverLastPaint=0;
  const hoverHead=el('div',undefined,'timeline-hoverhead');hoverHead.hidden=true;hoverHead.setAttribute('aria-hidden','true');scroll.append(hoverHead);
  function clearHoverPreview(restore=true){
    cancelAnimationFrame(hoverFrame);hoverFrame=0;if(!hoverHead.hidden)hoverHead.hidden=true;
    const active=hoverTime!==null;hoverTime=null;
    if(restore&&active&&project){window.hubMultitrackPreview?.sync(project.body,position,playing);paint();}
  }
  function showHoverPreview(now){
    hoverFrame=0;
    // Coalesce mouse movement to at most 24 decoded preview requests per second.
    if(now-hoverLastPaint<1000/FPS){hoverFrame=requestAnimationFrame(showHoverPreview);return;}
    hoverLastPaint=now;
    if(!hoverEnabled||!project||!total()||playing||busy||trimmingActive||view!=='editor')return clearHoverPreview();
    const rect=$('timeline-ruler').getBoundingClientRect(),scale=window.hubTimelineScale||32;
    const raw=(hoverX-rect.left-104)/scale;
    if(raw<0||raw>total())return clearHoverPreview();
    const at=HubTimeline.clamp(Math.floor(raw*FPS)/FPS,total());
    // Keep the line visible even when the pointer moves between descendants of
    // the same clip without changing the quantized preview frame.
    // Read layout before writes, and avoid invalidating styles for identical values.
    const hoverHeight=scroll.scrollHeight+'px',hoverLeft=(104+at*scale)+'px';
    if(hoverHead.style.height!==hoverHeight)hoverHead.style.height=hoverHeight;
    if(hoverHead.style.left!==hoverLeft)hoverHead.style.left=hoverLeft;
    if(hoverHead.hidden)hoverHead.hidden=false;
    if(at===hoverTime)return;
    hoverTime=at;
    window.hubMultitrackPreview?.sync(project.body,at,false);
    const saved=position;try{position=at;paintCaptions();$('edit-clock').textContent=`${tc(at)} / ${tc(HubTimeline.lastFrame(total()))}`;}finally{position=saved;}
  }
  scroll.addEventListener('pointermove',e=>{
    const clip=e.target.closest('[data-timeline-key]');
    if(!hoverEnabled||!project||playing||busy||trimmingActive||view!=='editor'||e.pointerType==='touch'||e.buttons||(!clip&&e.target.closest('.track-label,button,input,select')))return clearHoverPreview();
    hoverX=e.clientX;if(!hoverFrame)hoverFrame=requestAnimationFrame(showHoverPreview);
  },true);
  scroll.addEventListener('pointerleave',()=>clearHoverPreview());
  // A ruler/playhead press immediately seeks to the clicked position; restoring the
  // old frame first would issue an unnecessary extra seek before that new seek.
  scroll.addEventListener('pointerdown',e=>clearHoverPreview(!(e.button===0&&project&&!busy&&(e.target===head||e.target.closest('#timeline-ruler,.timeline-playhead,#multi-tracks [data-timeline-key]'))&&!e.target.closest('.trim-handle,.audio-grip,.clip-vol'))),true);
  scroll.addEventListener('scroll',()=>clearHoverPreview(),{passive:true});
  window.addEventListener('blur',()=>clearHoverPreview());
  toggleButton('预览轴','鼠标移动预览画面；移出恢复播放头画面',()=>hoverEnabled,v=>{hoverEnabled=v;clearHoverPreview();});
  const tlToggles={};
  tlToggles.snap=toggleButton('吸附','拖动时吸附到片段边缘、播放头，按住 Alt 临时关闭',()=>snapEnabled,v=>{snapEnabled=v;});
  tlToggles.magnet=toggleButton('主轨磁吸','主轨片段首尾相接；删除、缩短或移动后，后面的片段自动补位',()=>magnetOn,v=>{magnetOn=v;if(v)closeGaps();});
  tlToggles.link=toggleButton('联动','移动、裁剪、删除主轨片段时，位于其上的字幕、音频和叠加片段一起跟随',()=>linkOn,v=>{linkOn=v;});
  // Export scope follows the clicked or marquee-selected timeline objects.
  const exportRangeLabel=el('span','','range-label');exportRangeLabel.setAttribute('role','status');tlTools.append(exportRangeLabel);
  tlTools.append(dragNote);
  const timelineZoom=document.querySelector('.edit-timeline .timeline-zoom');if(timelineZoom)tlTools.append(timelineZoom);
  function editTimeline(mutator,stay,exclude,options){HubTimeline.migrate(project.body);return HubLayout.edit(project.body,mutator,{link:linkOn,magnet:magnetOn,exclude:exclude||new Set(),stay:stay||new Set(),...(options||{})});}
  function closeGaps(){if(!project||busy)return;const before=JSON.stringify(project.body);editTimeline(()=>{});if(JSON.stringify(project.body)!==before){pause();mark();render();seek(Math.min(position,total()));}}
  const mainEnd=()=>{const main=HubLayout.mainTrack(project.body);return Math.max(0,...clips().map((c,i)=>(c.track||HubLayout.MAIN)===main?offset(i)+length(c):0));};
  function paintPlayhead(){const height=scroll.scrollHeight+'px',left=(104+position*(window.hubTimelineScale||32))+'px',hidden=!project;if(head.style.height!==height)head.style.height=height;if(head.style.left!==left)head.style.left=left;if(head.hidden!==hidden)head.hidden=hidden;}
  const getRange=()=>null; // Legacy saved ranges do not override the current visible selection.
  const rangePoints=()=>{const r=getRange();return r?[r.start,r.end]:[];};
  function boundaries(){return [0,...rangePoints(),...timelineEntries().flatMap(r=>[r.start,r.end])];}
  const guide=el('div','','snap-guide');guide.hidden=true;guide.setAttribute('aria-hidden','true');scroll.append(guide);
  function showGuide(time){if(time===null||!Number.isFinite(time)){guide.hidden=true;return;}guide.style.height='0px';guide.style.left=(104+time*(window.hubTimelineScale||32))+'px';guide.style.height=scroll.scrollHeight+'px';guide.hidden=false;}
  function nearestSnap(value,points){if(!snapEnabled||altHeld)return null;let best=null,distance=10/(window.hubTimelineScale||32);for(const p of points){const d=Math.abs(p-value);if(d<distance){best=p;distance=d;}}return best;}
  function snapTime(value,points){const hit=nearestSnap(value,points);showGuide(hit);return hit===null?value:hit;}
  function snapSpan(start,end,points,edges=[0,end-start]){
    let hit=null,delta=0,distance=Infinity;
    for(const edge of edges){const at=start+edge,target=nearestSnap(at,points);if(target===null)continue;const d=Math.abs(target-at);if(d<distance){distance=d;hit=target;delta=target-at;}}
    showGuide(hit);return hit===null?start:start+delta;
  }
  for(const type of ['pointerup','pointercancel','blur'])window.addEventListener(type,()=>setTimeout(()=>showGuide(null),0));
  window.addEventListener('keydown',e=>{if(e.key==='Alt')altHeld=true;});window.addEventListener('keyup',e=>{if(e.key==='Alt')altHeld=false;});window.addEventListener('blur',()=>{altHeld=false;});
  const qf=n=>Math.round(n*24)/24;
  const rangeShade=el('div','','range-shade'),rangeIn=el('div','','range-handle range-in'),rangeOut=el('div','','range-handle range-out');
  rangeShade.setAttribute('aria-hidden','true');
  for(const [handle,edge,name] of [[rangeIn,'start','入点'],[rangeOut,'end','出点']]){handle.hidden=true;handle.setAttribute('role','slider');handle.setAttribute('aria-label','导出选区'+name);handle.title='拖动调整导出'+name;handle.addEventListener('pointerdown',e=>dragRange(e,edge));}
  rangeShade.hidden=true;scroll.append(rangeShade,rangeIn,rangeOut);
  function paintRange(){
    for(const n of [rangeShade,rangeIn,rangeOut])n.hidden=true;
    const rows=selectedRows();
    exportRangeLabel.textContent=rows.length?`已选 ${rows.length} 个对象 · 仅导出所选内容`:'未选择内容 · 导出完整时间轴';
    $('edit-export').textContent=rows.length?'导出所选 MP4':'导出 MP4';
  }
  function setRange(start,end){const s=qf(Math.max(0,start)),e=qf(end);if(!(e-s>1/24-1e-6))return fail('请先移动播放头再设置选区');project.body.export_range={start:s,end:e};mark();paintRange();}
  function markRange(which){if(!project)return;const r=getRange(),t=qf(Math.max(0,position)),all=qf(total());if(which==='in')setRange(t,r&&r.end>t?r.end:all);else setRange(r&&r.start<t?r.start:0,t);}
  function clearRange(){if(!project||!getRange())return;project.body.export_range=null;mark();paintRange();}
  function rangeFromSelection(){if(!project)return;const keys=new Set(expandKeys(selectedKeys())),rows=timelineEntries().filter(r=>keys.has(r.key));if(!rows.length)return fail('请先选择时间轴上的片段');setRange(Math.min(...rows.map(r=>r.start)),Math.max(...rows.map(r=>r.end)));}
  function dragRange(e,edge){
    const r0=getRange();if(e.button!==0||busy||!r0)return;e.preventDefault();e.stopPropagation();pause();trimmingActive=true;
    const target=project,orig={start:r0.start,end:r0.end},scale=window.hubTimelineScale||32,x0=e.clientX,points=[position,...boundaries()],limit=qf(total());
    const move=event=>{const snapped=snapTime(orig[edge]+(event.clientX-x0+pan.delta())/scale,points);
      const value=qf(edge==='start'?Math.max(0,Math.min(snapped,orig.end-1/24)):Math.min(limit,Math.max(snapped,orig.start+1/24)));
      if(project===target&&project.body.export_range){project.body.export_range[edge]=value;paintRange();dragNote.textContent=(edge==='start'?'选区入点 ':'选区出点 ')+value.toFixed(2)+' 秒';}};
    const pan=edgeScroll(e,move);
    const clean=()=>{pan.stop();trimmingActive=false;dragNote.textContent='';showGuide(null);window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('blur',cancel);window.removeEventListener('keydown',escape);};
    const finish=()=>{clean();if(project!==target)return;const cur=project.body.export_range;if(cur&&Math.abs(cur[edge]-orig[edge])>1e-6)mark();paintRange();};
    const cancel=()=>{clean();if(project===target&&project.body.export_range)project.body.export_range={...orig};paintRange();};
    const escape=event=>{if(event.key==='Escape'){event.preventDefault();cancel();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('blur',cancel);window.addEventListener('keydown',escape);
  }
  function scrub(e){
    if(e.button!==0||!project)return;e.preventDefault();e.stopPropagation();pause();scroll.focus({preventScroll:true});
    let x=e.clientX,pending=0,lastAppliedX=null;
    const apply=()=>{pending=0;lastAppliedX=x;seek(snapTime((x-$('timeline-ruler').getBoundingClientRect().left-104)/(window.hubTimelineScale||32),boundaries()));};
    const move=event=>{x=event.clientX;if(!pending)pending=requestAnimationFrame(apply);};
    const pan=edgeScroll(e,move);apply();
    const end=()=>{pan.stop();cancelAnimationFrame(pending);if(pending||x!==lastAppliedX)apply();window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',end);window.removeEventListener('pointercancel',end);window.removeEventListener('blur',end);};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',end);window.addEventListener('pointercancel',end);window.addEventListener('blur',end);
  }
  $('timeline-ruler').onpointerdown=scrub;
  head.onpointerdown=scrub;
  scroll.tabIndex=0;

  function edgeScroll(initial,apply){
    const origin=scroll.scrollLeft;let x=initial.clientX,id=0,active=true,previous=0;
    const receive=e=>{x=e.clientX;};
    const tick=now=>{if(!active)return;const elapsed=previous?Math.min(40,now-previous):16.67;previous=now;const r=scroll.getBoundingClientRect();
      const delta=x>r.right-48?Math.min(18,(x-r.right+48)/3):x<r.left+152?-Math.min(18,(r.left+152-x)/3):0;
      if(delta){const before=scroll.scrollLeft;scroll.scrollLeft=Math.max(0,before+delta*elapsed/16.67);if(scroll.scrollLeft!==before)apply({clientX:x});}
      id=requestAnimationFrame(tick);
    };
    window.addEventListener('pointermove',receive);id=requestAnimationFrame(tick);
    return {delta:()=>scroll.scrollLeft-origin,stop:()=>{active=false;cancelAnimationFrame(id);window.removeEventListener('pointermove',receive);}};
  }
  // Source-time limits for trimming one edge: never past the source, never into a lane neighbour
  // (the magnet's main lane ripples instead of colliding).
  function trimLimits(clip,edge){
    const rate=clip.speed||1,sourceEnd=source(clip.task_id)?.duration||clip.end;
    const base=edge==='start'?{min:0,max:clip.end-.1*rate}:{min:clip.start+.1*rate,max:sourceEnd};
    const lane=clip.track||HubLayout.MAIN;
    if(magnetOn&&lane===HubLayout.mainTrack(project.body))return base;
    const at=offset(clips().indexOf(clip)),end=at+length(clip);
    const peers=timelineEntries().filter(r=>r.item!==clip&&!r.key.startsWith('caption:')&&r.key!=='audio:0'&&laneOf(r)===lane);
    if(edge==='start'){const prev=Math.max(0,...peers.filter(r=>r.end<=at+1e-6).map(r=>r.end));return {min:Math.max(base.min,clip.start-(at-prev)*rate),max:base.max};}
    const next=Math.min(Infinity,...peers.filter(r=>r.start>=end-1e-6).map(r=>r.start));
    return {min:base.min,max:Math.min(base.max,clip.end+(next-end)*rate)};
  }
  function beginMultiVideoTrim(e,clip,index,edge){
    const key=typeof index==='string'?index:'video:'+index,keys=expandKeys(selectedKeys());if(keys.length<2||!keys.includes(key))return false;
    e.preventDefault();e.stopPropagation();
    const rows=timelineEntries().filter(r=>keys.includes(r.key));
    if(rows.some(r=>r.key==='audio:0')){fail('背景音轨请先转换为独立音频片段再统一裁剪');return true;}
    const chosen=rows.map(r=>r.item);
    if(chosen.some(c=>c.locked)){fail('请先解锁所选片段');return true;}
    commitEdits();pause();const target=project,x=e.clientX,scale=window.hubTimelineScale||32;
    const originals=rows.map(r=>{const c=r.item,video=r.key.startsWith('video:'),audio=r.key.startsWith('detached:'),rate=video?(c.speed||1):1;
      let lim=video?trimLimits(c,edge):edge==='start'?{min:audio?Math.max(0,c.start-c.at):0,max:c.end-.1}:{min:c.start+.1,max:audio?soundMax(c):86400};
      if(audio){const room=audioRoom(c);if(edge==='start')lim.min=Math.max(lim.min,c.start-(c.at-room.before));else lim.max=Math.min(lim.max,c.start+room.after-c.at);}
      return {c,start:c.start,end:c.end,at:r.start,rate,lim,media:video||audio,audio};});
    const min=Math.max(...originals.map(o=>(o.lim.min-o[edge])/o.rate));
    const max=Math.min(...originals.map(o=>(o.lim.max-o[edge])/o.rate));let delta=0;trimmingActive=true;
    const previews=typeof document==='undefined'?[]:Array.from(document.querySelectorAll('#multi-tracks [data-timeline-key]')).filter(n=>keys.includes(n.dataset.timelineKey)).map(node=>{const row=rows.find(r=>r.key===node.dataset.timelineKey);return {node,row,left:node.style.left,width:node.style.width};});
    const move=event=>{delta=Math.max(min,Math.min(max,qf((event.clientX-x)/scale)));dragNote.textContent='多选统一裁剪 '+(delta>=0?'+':'')+delta.toFixed(2)+' 秒';
      for(const p of previews){p.node.style.left=(p.row.start+(edge==='start'?delta:0))*scale+'px';p.node.style.width=Math.max(2,(p.row.end-p.row.start+(edge==='start'?-delta:delta))*scale)+'px';p.node.classList.add('trimming');}
    };
    const clean=()=>{for(const p of previews){p.node.style.left=p.left;p.node.style.width=p.width;p.node.classList.remove('trimming');}trimmingActive=false;dragNote.textContent='';window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('blur',cancel);window.removeEventListener('keydown',escape);};
    const finish=()=>{clean();if(project!==target||Math.abs(delta)<1e-7)return;
      editTimeline(()=>{for(const o of originals){o.c[edge]=o[edge]+delta*o.rate;if(edge==='start'&&o.media)o.c.at=o.at+delta;if(o.audio){const span=o.c.end-o.c.start;o.c.fade_in=Math.min(o.c.fade_in||0,span);o.c.fade_out=Math.min(o.c.fade_out||0,span-o.c.fade_in);}}clampCaptions();},new Set(chosen));mark();render();seek(Math.min(position,total()));};
    const cancel=()=>{clean();};const escape=event=>{if(event.key==='Escape'){event.preventDefault();cancel();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('blur',cancel);window.addEventListener('keydown',escape);return true;
  }
  function beginTrim(e,clip,index,edge,button){
    if(e.button===0&&!busy&&beginMultiVideoTrim(e,clip,index,edge))return;
    if(e.button!==0||busy)return;e.preventDefault();e.stopPropagation();trimmingActive=true;pause();videoSelection.clear();videoSelection.add(clip);selected=index;renderProperties();
    const target=project,startX=e.clientX,scale=window.hubTimelineScale||32,original=clip[edge],rate=clip.speed||1,timelineStart=offset(index),max=source(clip.task_id)?.duration||clip.end;
    let value=original;button.draggable=false;button.classList.add('trimming');
    const points=[position,...boundaries()],lim=trimLimits(clip,edge);
    const move=event=>{let candidate=original+(event.clientX-startX+edgePan.delta())/scale*rate;
      const absolute=timelineStart+(candidate-clip.start)/rate;
      const snapped=snapTime(absolute,points);candidate+=(snapped-absolute)*rate;
      value=Math.max(lim.min,Math.min(lim.max,candidate));
      dragNote.textContent=(edge==='start'?'入点 ':'出点 ')+value.toFixed(2)+' 秒'+(Math.abs(snapped-absolute)>.0001?' · 已吸附':'');
      button.style.width=((edge==='start'?clip.end-value:value-clip.start)/(clip.speed||1)*scale)+'px';if(edge==='start')button.style.left=(timelineStart+(value-clip.start)/(clip.speed||1))*scale+'px';
    };
    const edgePan=edgeScroll(e,move);
    const clean=()=>{edgePan.stop();trimmingActive=false;window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('keydown',escape);window.removeEventListener('blur',cancel);button.draggable=true;button.classList.remove('trimming');dragNote.textContent='';};
    const finish=()=>{clean();if(project===target&&clips()[index]===clip&&Math.abs(value-original)>.00001)trim(edge,value);else renderTimeline();};
    const cancel=()=>{clean();renderTimeline();};const escape=event=>{if(event.key==='Escape'){event.preventDefault();cancel();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('keydown',escape);window.addEventListener('blur',cancel);
  }

  const waveCache=new Map();
  const assetNames=new Map();let assetNamesFor='';
  function loadAssetNames(){
    if(!project||assetNamesFor===project.id)return;
    assetNamesFor=project.id;
    api('/workspace/materials').then(rows=>{let added=false;for(const a of rows)if(a.mime?.startsWith('audio/')&&!assetNames.has(a.id)){assetNames.set(a.id,a.name);added=true;}if(added&&project)audioTimeline();}).catch(()=>{});
  }
  // Waveform bars are sampled from real decoded PCM inside [start,end]; amplitude follows the clip
  // volume, mute and fade envelope so silent sentences read as gaps and the shape tracks loudness.
  const WAVE_NS='http://www.w3.org/2000/svg';
  function paintWave(block,clip){
    const data=block._wave;if(!data||!block.isConnected)return;
    block.querySelector('svg.wave')?.remove();
    const scale=window.hubTimelineScale||32,width=Math.max(24,(clip.end-clip.start)*scale),cols=Math.max(4,Math.min(480,Math.round(width/3.4))),unit=40;
    const span=Math.max(1e-3,clip.end-clip.start),start=clip.start||0,peaks=data.peaks;
    const sample=rel=>{const time=start+span*rel,index=Math.min(peaks.length-1,Math.max(0,Math.floor((data.duration?time/data.duration:0)*peaks.length)));return peaks[index]||0;};
    const raw=[];let loudest=0;
    for(let x=0;x<cols;x++){const peak=sample(cols>1?x/(cols-1):0);raw.push(peak);if(peak>loudest)loudest=peak;}
    const norm=loudest>1e-4?1/loudest:0,gain=clip.muted?0:Math.max(0,Math.min(2,Number(clip.volume??1))),fadeIn=clip.fade_in||0,fadeOut=clip.fade_out||0;
    let d='';
    for(let x=0;x<cols;x++){
      const time=span*(cols>1?x/(cols-1):0);let env=1;
      if(fadeIn>0)env=Math.min(env,time/fadeIn);
      if(fadeOut>0)env=Math.min(env,(span-time)/fadeOut);
      const amp=Math.max(0,Math.min(1,raw[x]*norm*gain*Math.max(0,env)));
      const h=Math.max(1,amp*(unit-8));
      d+=`M${(x*2+1).toFixed(2)},${((unit-h)/2).toFixed(2)}v${h.toFixed(2)}`;
    }
    const svg=document.createElementNS(WAVE_NS,'svg');svg.setAttribute('class','wave');svg.setAttribute('viewBox',`0 0 ${cols*2} ${unit}`);svg.setAttribute('preserveAspectRatio','none');svg.setAttribute('aria-label','音频波形（随音量与停顿变化）');
    const path=document.createElementNS(WAVE_NS,'path');path.setAttribute('d',d);svg.append(path);block.append(svg);
  }
  function audioTimeline(){
    const lane=$('track-detached');if(!lane)return;lane.replaceChildren();
    const sounds=project?.body.audio_clips||[];lane.style.height=Math.max(42,sounds.length*64)+'px';
    loadAssetNames();
    sounds.forEach((clip,index)=>{
      const scale=window.hubTimelineScale||32,block=el('div',undefined,'audio-segment');block.style.left=clip.at*scale+'px';block.style.top=index*64+4+'px';block.style.width=(clip.end-clip.start)*scale+'px';block.dataset.timelineKey='detached:'+index;block.dataset.locked=String(clip.locked);block.dataset.muted=String(!!clip.muted);block.tabIndex=0;if(trackSelection?.kind==='detached'&&trackSelection.index===index)block.classList.add('track-selected');
      const name=clip.source==='asset'?assetNames.get(clip.asset_id):null;
      const title=name||(clip.source==='asset'?'音频素材':`${clip.source==='voice'?'AI 配音':'原声'} ${index+1}`);
      const head=el('div',undefined,'audio-head');
      const label=el('span',`${title} · ${seconds(clip.end-clip.start)}s`,'audio-title');label.title=`${title} · ${clip.muted?'静音':clip.locked?'已锁定':'可移动'}`;
      head.append(label);block.append(head);lane.append(block);
      block.onclick=()=>{selectTrack('detached',index,block);window.hubEditorShell?.openLeft('audio');audioList.querySelectorAll('.detached-row')[index]?.scrollIntoView({block:'nearest',behavior:'smooth'});};
      block.onpointerdown=e=>{selectTrack('detached',index,block);audioDrag(e,clip,block,'at');};
      for(const edge of ['start','end']){const grip=el('span',undefined,'audio-grip audio-'+edge);grip.title=clip.locked?'先解锁音轨':'拖动裁剪原声';grip.onpointerdown=e=>audioDrag(e,clip,block,edge);block.append(grip);}
      const waveKey=(clip.source||'video')+':'+soundId(clip);
      if(!waveCache.has(waveKey)){waveCache.set(waveKey,api('/editor/waveform/'+soundId(clip)+'?source='+(clip.source||'video')).catch(()=>null));}
      waveCache.get(waveKey).then(w=>{
        if(!block.isConnected)return;
        if(!w||!w.peaks?.length){block.append(el('small',w?'无音频波形':'波形读取失败；重新打开剪辑台重试','wave-note'));if(!w)waveCache.delete(waveKey);return;}
        block._wave=w;paintWave(block,clip);
      });
    });
  }
  function lanePeers(clip){const lane=clip.track||'audio-'+(project.body.audio_clips||[]).indexOf(clip);return timelineEntries().filter(r=>r.item!==clip&&!r.key.startsWith('caption:')&&r.key!=='audio:0'&&laneOf(r)===lane);}
  function audioRoom(clip){const at=clip.at||0,span=clip.end-clip.start;let before=0,after=Infinity;for(const r of lanePeers(clip)){if(r.end<=at+1e-6)before=Math.max(before,r.end);else if(r.start>=at+span-1e-6)after=Math.min(after,r.start);}return {before,after};}
  function placeFree(clip,time,span){const free=HubLayout.resolveMove([{start:time,end:time+span,lane:'x'}],lanePeers(clip).map(r=>({start:r.start,end:r.end,lane:'x'})),0);return free===null?(clip.at||0):time+free;}
  function audioDrag(e,clip,block,key){
    if(e.button===0&&!busy&&key!=='at'&&beginMultiVideoTrim(e,clip,'detached:'+project.body.audio_clips.indexOf(clip),key))return;
    if(e.button!==0||clip.locked||busy)return;if(key==='at'&&expandKeys(selectedKeys()).length>1){beginBundleMove(e,block);return;}e.preventDefault();e.stopPropagation();pause();trimmingActive=true;
    const origin=e.clientX,scale=window.hubTimelineScale||32,target=project,initial={...clip};let next={...clip};
    const move=event=>{const delta=(event.clientX-origin+edgePan.delta())/scale;next={...initial};const max=soundMax(clip),room=audioRoom(clip);
      if(key==='at'){const span=initial.end-initial.start;next.at=placeFree(clip,Math.max(0,snapSpan(initial.at+delta,initial.at+delta+span,[0,position,...boundaries()])),span);}
      else if(key==='start'){const amount=Math.max(-Math.min(initial.start,initial.at-room.before),Math.min(initial.end-initial.start-.1,delta));next.start=initial.start+amount;next.at=initial.at+amount;}
      else next.end=Math.max(initial.start+.1,Math.min(max,initial.start+room.after-initial.at,initial.end+delta));
      const duration=next.end-next.start;next.fade_in=Math.min(next.fade_in||0,duration);next.fade_out=Math.min(next.fade_out||0,duration-next.fade_in);
      block.style.left=next.at*scale+'px';block.style.width=duration*scale+'px';dragNote.textContent=`原声 ${next.at.toFixed(2)}s · 长度 ${duration.toFixed(2)}s`;
    };
    const edgePan=edgeScroll(e,move);
    const clean=()=>{edgePan.stop();trimmingActive=false;dragNote.textContent='';window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('keydown',escape);window.removeEventListener('blur',cancel);};
    const finish=()=>{clean();if(project===target&&JSON.stringify(initial)!==JSON.stringify(next)){editTimeline(()=>{linkedCaptions(clip,next);Object.assign(clip,next);},undefined,new Set([clip]));mark();render();}};
    const cancel=()=>{clean();audioTimeline();};const escape=event=>{if(event.key==='Escape'){event.preventDefault();cancel();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('keydown',escape);window.addEventListener('blur',cancel);
  }
  // One command surface reuses existing editing handlers and undo history.
  const toolbar=el('div',undefined,'clip-toolbar');toolbar.setAttribute('role','group');toolbar.setAttribute('aria-label','时间轴编辑工具');
  for(const id of ['edit-undo','edit-redo'])toolbar.append($(id));
  const commands=[['edit-split','分割','split'],['edit-remove','删除','deleteSelection'],['edit-detach','分离音频','detach'],['edit-earlier','向前移动',''],['edit-later','向后移动','']];
  const shortcutLabel=id=>!id?'':(window.HubShortcuts?.label(id)||'');
  for(const [id,title,key]of commands){const b=el('button',title,'secondary');b.type='button';b.dataset.editAction=id;b.dataset.shortcut=key||'';b.title=key?title+' · '+shortcutLabel(key):title;b.onclick=()=>{if(id==='edit-remove'){deleteSelection();return;}if(id==='edit-split'&&(selectedCompound()||selectedRows().some(r=>r.key.startsWith('sticker:')))){splitAtPlayhead();return;}const target=$(id);if(project&&clips()[selected]&&!target.disabled)target.click();};toolbar.append(b);}
  async function separateSelected(kind,button){
    let clip=null,claimed=false;
    try{
      const rows=selectedRows();clip=rows.length===1&&rows[0].key.startsWith('video:')?rows[0].item:null;
      if(!clip)throw Error('请选择一个视频片段');
      if(clip.locked)throw Error('请先解锁所选片段');
      if(separatingClips.has(clip))throw Error('该片段正在分离声音，请等待结果');
      if(Math.abs((clip.speed||1)-1)>.001)throw Error('请先将视频恢复为 1× 速度');
      if(Math.round((clip.end-clip.start)*10000)/10000<1||Math.round((clip.end-clip.start)*10000)/10000>60)throw Error('目前仅支持 1–60 秒的视频片段，请先分割');
      if((project.body.audio_clips||[]).length>=50)throw Error('最多 50 段音轨');
      commitEdits();const target=project,token=epoch,revision=JSON.stringify(clip),original={start:clip.start,end:clip.end,at:clip.at};
      separatingClips.add(clip);claimed=true;button.disabled=true;button.textContent='分离中…';
      const asset=await api('/media/vocals',{source_id:clip.task_id,start:original.start,end:original.end,kind});
      if(token!==epoch||!me)return;
      if(asset.kind!==kind||!asset.id)throw Error('服务尚未更新，分离结果与所选类型不符；请先重启服务');
      if(project!==target||!clips().includes(clip)||JSON.stringify(clip)!==revision){fail('分离结果已保存到素材库，但原剪辑已变更，未自动加入');return;}
      pause();commitEdits();
      appendAudioAsset(asset,original.end-original.start,original.at,'audio-'+crypto.randomUUID());
      clip.volume=0;clip.audio_detached=true;mark();render();
    }catch(e){fail(e);}finally{
      if(claimed){separatingClips.delete(clip);button.disabled=false;button.textContent=kind==='vocal'?'仅保留人声':'仅保留背景声';}
    }
  }
  for(const [kind,label] of [['vocal','仅保留人声'],['background','仅保留背景声']]){const b=el('button',label,'secondary');b.type='button';b.title='使用 AI 分离所选视频的声音（1–60 秒）';b.onclick=()=>separateSelected(kind,b);toolbar.append(b);}
  const groupVolume=el('button','统一音量','secondary');groupVolume.type='button';groupVolume.title='调整所选视频和音频片段的统一音量';groupVolume.onclick=()=>{const key=selectedKeys().find(k=>volumeTarget(k));if(!key)return fail('请先选择视频或音频片段');openVolumePopover(key,groupVolume);};toolbar.append(groupVolume);
  const help=el('span','','fine');toolbar.append(help);
  const paintHelp=()=>{help.textContent=['play:播放 / 暂停','split:分割','undo:撤销','shortcuts:快捷键设置'].map(pair=>{const [id,text]=pair.split(':');return `${shortcutLabel(id)||'未设置'} ${text}`;}).join(' · ');};
  paintHelp();
  window.addEventListener('hub-shortcuts-changed',paintHelp);
  const shortcutButton=el('button','快捷键','secondary');shortcutButton.type='button';shortcutButton.className='secondary shortcut-entry';shortcutButton.dataset.shortcut='shortcuts';shortcutButton.onclick=()=>window.HubShortcuts?.openSettings();toolbar.append(shortcutButton);
  $('edit-shortcuts')?.addEventListener('click',()=>window.HubShortcuts?.openSettings());
  document.querySelector('.edit-timeline .track-scroll').before(toolbar);
  const menu=el('div',undefined,'clip-context-menu');menu.hidden=true;menu.setAttribute('role','menu');menu.setAttribute('aria-label','片段操作');document.body.append(menu);
  let menuOrigin=null;
  function closeClipMenu(restore=false){menu.hidden=true;if(restore&&menuOrigin?.isConnected)menuOrigin.focus();}
  function openClipMenu(x,y){
    if(!project||!clips()[selected])return;
    menuOrigin=timelineVideoNodes[selected];menu.replaceChildren();
    commands.forEach(([id,title,key],i)=>{if(i===2||i===3)menu.append(el('hr'));const b=el('button');b.type='button';b.setAttribute('role','menuitem');b.disabled=$(id).disabled;b.append(el('span',title),el('kbd',shortcutLabel(key)));b.onclick=()=>{closeClipMenu();$(id).click();};menu.append(b);});
    menu.hidden=false;menu.style.left=Math.max(8,Math.min(x,innerWidth-menu.offsetWidth-8))+'px';menu.style.top=Math.max(8,Math.min(y,innerHeight-menu.offsetHeight-8))+'px';menu.querySelector('button:not(:disabled)')?.focus();
  }
  menu.onkeydown=e=>{const buttons=[...menu.querySelectorAll('button:not(:disabled)')];const i=buttons.indexOf(document.activeElement);if(e.key==='Escape'){e.preventDefault();closeClipMenu(true);}else if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();buttons[(i+(e.key==='ArrowDown'?1:-1)+buttons.length)%buttons.length]?.focus();}else if(e.key==='Tab')closeClipMenu();};
  document.addEventListener('pointerdown',e=>{if(!menu.contains(e.target))closeClipMenu();});
  window.addEventListener('resize',()=>closeClipMenu());
  document.addEventListener('scroll',()=>closeClipMenu(),true);
  function selectTrack(kind,index,node){
    marqueeSelectionActive=false;
    const key=kind+':'+index;if(expandKeys([key]).length>1){setTimelineSelection([key]);scroll.focus({preventScroll:true});return;}
    timelineSelection.clear();videoSelection.clear();trackSelection={kind,index};
    renderTimeline();renderProperties();renderSpeed();paintRange();
    scroll.querySelectorAll('.track-selected').forEach(n=>n.classList.remove('track-selected'));
    node?.classList.add('track-selected');node?.focus();
  }
  const expandedCompounds=new Set();
  function timelineEntries(){
    const rows=clips().map((item,i)=>({key:'video:'+i,item,start:offset(i),end:offset(i)+length(item)}));
    (project?.body.captions||[]).forEach((item,i)=>rows.push({key:'caption:'+i,item,start:item.start,end:item.end}));
    (project?.body.audio_clips||[]).forEach((item,i)=>rows.push({key:'detached:'+i,item,start:item.at,end:item.at+item.end-item.start}));
    (project?.body.stickers||[]).forEach((item,i)=>rows.push({key:'sticker:'+i,item,start:item.start,end:item.end}));
    if(project?.body.audio)rows.push({key:'audio:0',item:project.body.audio,start:0,end:project.body.audio.duration||total()});
    return rows;
  }
  function selectedKeys(){return timelineSelection.size?[...timelineSelection]:videoSelection.size?clips().flatMap((c,i)=>videoSelection.has(c)?['video:'+i]:[]):trackSelection?[trackSelection.kind+':'+trackSelection.index]:[];}
  function selectedRows(){const keys=new Set(expandKeys(selectedKeys()));return timelineEntries().filter(r=>keys.has(r.key));}
  function exportSelection(){const rows=selectedRows();if(!rows.length)return null;const keys=new Set(rows.map(r=>r.key));const indices=kind=>rows.filter(r=>r.key.startsWith(kind+':')).map(r=>Number(r.key.split(':')[1]));return {clips:indices('video'),captions:indices('caption'),audio_clips:indices('detached'),audio:keys.has('audio:0'),range:{start:Math.max(0,Math.floor(Math.min(...rows.map(r=>r.start))*24)/24),end:Math.ceil(Math.max(...rows.map(r=>r.end))*24-1e-7)/24}};}
  function expandKeys(keys){
    const rows=timelineEntries(),result=new Set(keys.map(k=>k.replace('original:','video:')));let changed=true;
    while(changed){changed=false;for(const row of rows){if(!result.has(row.key))continue;for(const other of rows){if((row.item.edit_group&&other.item.edit_group===row.item.edit_group&&!(row.item.edit_compound&&expandedCompounds.has(row.item.edit_compound)&&other.item.edit_compound===row.item.edit_compound))||(row.item.edit_compound&&!expandedCompounds.has(row.item.edit_compound)&&other.item.edit_compound===row.item.edit_compound)){if(!result.has(other.key)){result.add(other.key);changed=true;}}}}}
    return [...result];
  }
  function bundle(kind,remove=false){
    if(!bundlesSupported)return fail('组合功能需要重新启动中台服务后使用，请先保存当前剪辑');
    const rows=timelineEntries(),keys=new Set(expandKeys(selectedKeys()));let chosen=rows.filter(r=>keys.has(r.key));
    if(!chosen.length)return fail('请先框选片段');
    if(chosen.some(r=>r.key.startsWith('sticker:')))return fail('贴纸暂不支持组合或复合片段');
    if(chosen.some(r=>r.item.locked))return fail('请先解锁所选音轨');
    const field=kind==='compound'?'edit_compound':'edit_group';
    if(remove){const ids=new Set(chosen.map(r=>r.item[field]).filter(Boolean));if(!ids.size)return;rows.forEach(r=>{if(ids.has(r.item[field]))delete r.item[field];});}
    else{
      if(chosen.length<2)return fail('请至少选择两个片段');
      if(kind==='compound'&&chosen.some(r=>r.item.edit_compound))return fail('请先解除已有复合片段，再重新合并');
      const videoIndices=chosen.filter(r=>r.key.startsWith('video:')).map(r=>Number(r.key.split(':')[1]));
      
      // Legacy background audio is promoted to a movable independent track.
      const legacy=chosen.find(r=>r.key==='audio:0');if(legacy){if((project.body.audio_clips||[]).length>=50)return fail('最多 50 段音轨');const a=legacy.item;project.body.audio_clips||=[];const clip={source:'asset',asset_id:a.asset_id,source_duration:a.duration,start:0,end:a.duration,at:0,volume:a.volume,locked:false,muted:false,fade_in:0,fade_out:0};project.body.audio_clips.push(clip);legacy.item=clip;legacy.key='detached:'+(project.body.audio_clips.length-1);project.body.audio=null;}
      const id=crypto.randomUUID();chosen.forEach(r=>r.item[field]=id);
    }
    pause();mark();render();setTimelineSelection(chosen.map(r=>r.key));window.dispatchEvent(new Event('hub-bundles'));
  }
  function bundleRows(){
    const rows=timelineEntries(),ids=[...new Set(rows.map(r=>r.item.edit_compound).filter(Boolean))];
    return ids.map(id=>{const members=rows.filter(r=>r.item.edit_compound===id);return {id,keys:members.map(r=>r.key),start:Math.min(...members.map(r=>r.start)),end:Math.max(...members.map(r=>r.end)),expanded:expandedCompounds.has(id)};});
  }
  function selectedCompound(){
    const rows=selectedRows(),ids=[...new Set(rows.map(r=>r.item.edit_compound))];
    return ids.length===1&&ids[0]&&!expandedCompounds.has(ids[0])?ids[0]:null;
  }
  function applyCompound(id,options){
    commitEdits();pause();
    try{const result=window.HubCompound.edit(project.body,id,options);Object.assign(project.body,result);mark();render();const keys=bundleRows().filter(b=>b.id===id||b.id===options.rightId).flatMap(b=>b.keys);setTimelineSelection(keys);seek(Math.min(position,total()));return true;}
    catch(error){fail(error.message);return false;}
  }
  function splitCompound(id){return applyCompound(id,{split:position,rightId:crypto.randomUUID()});}
  function beginCompoundTrim(event,id,edge,block){
    if(event.button!==0||busy)return;event.preventDefault();event.stopPropagation();commitEdits();pause();
    const bundle=bundleRows().find(b=>b.id===id);if(!bundle)return;
    let limits;try{limits=window.HubCompound.limits(project.body,id);}catch(error){return fail(error.message);}
    const x=event.clientX,scale=window.hubTimelineScale||32,initial=edge==='start'?bundle.start:bundle.end;
    let value=initial,valid=true,moved=false;trimmingActive=true;
    const points=boundaries().filter(t=>Math.abs(t-initial)>.001);
    const move=e=>{moved=moved||Math.abs(e.clientX-x)>3;if(!moved)return;
      const raw=snapTime(initial+(e.clientX-x)/scale,points);
      value=qf(edge==='start'?Math.max(Math.max(0,limits[0]),Math.min(bundle.end-1/24,raw)):Math.min(limits[1],Math.max(bundle.start+1/24,raw)));
      try{window.HubCompound.edit(project.body,id,{[edge]:value});valid=true;}catch(error){valid=false;}
      const start=edge==='start'?value:bundle.start,end=edge==='end'?value:bundle.end;
      block.style.left=start*scale+'px';block.style.width=Math.max(2,(end-start)*scale)+'px';block.style.outline=valid?'1px solid #d5e5f0':'2px solid #f0b0aa';dragNote.textContent=valid?(end-start).toFixed(2)+' 秒':'该切点会留下过短素材';
    };
    const clean=()=>{trimmingActive=false;showGuide(null);dragNote.textContent='';window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('blur',cancel);window.removeEventListener('keydown',escape);};
    const finish=()=>{clean();if(moved&&valid&&Math.abs(value-initial)>1e-7)applyCompound(id,{[edge]:value});else window.dispatchEvent(new Event('hub-bundles'));};
    const cancel=()=>{clean();window.dispatchEvent(new Event('hub-bundles'));};
    const escape=e=>{if(e.key==='Escape'){e.preventDefault();cancel();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('blur',cancel);window.addEventListener('keydown',escape);
  }
  function toggleCompound(id){
    if(!bundleRows().some(b=>b.id===id))return;
    pause();
    if(expandedCompounds.has(id)){expandedCompounds.delete(id);render();const bundle=bundleRows().find(b=>b.id===id);if(bundle)setTimelineSelection(bundle.keys);}
    else {expandedCompounds.clear();expandedCompounds.add(id);setTimelineSelection([]);render();}
    window.dispatchEvent(new Event('hub-bundles'));
  }
  function beginBundleMove(e,node){
    e.preventDefault();e.stopPropagation();pause();trimmingActive=true;
    const chosen=new Set(expandKeys(selectedKeys())),start=Math.min(...timelineEntries().filter(r=>chosen.has(r.key)).map(r=>r.start)),x=e.clientX,scale=window.hubTimelineScale||32;
    const spanEnd=Math.max(...timelineEntries().filter(r=>chosen.has(r.key)).map(r=>r.end))-start,snaps=[0,position,...rangePoints(),...timelineEntries().filter(r=>!chosen.has(r.key)).flatMap(r=>[r.start,r.end])];
    let time=start;const move=event=>{const raw=Math.max(0,start+(event.clientX-x)/scale);time=Math.max(0,snapSpan(raw,raw+spanEnd,snaps));dragNote.textContent='移动到 '+time.toFixed(2)+' 秒';};
    const clean=()=>{trimmingActive=false;dragNote.textContent='';window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('blur',cancel);window.removeEventListener('keydown',escape);};
    const finish=()=>{clean();moveSelectionTo(time);};const cancel=()=>clean();const escape=event=>{if(event.key==='Escape'){event.preventDefault();cancel();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('blur',cancel);window.addEventListener('keydown',escape);
  }
  function laneOf(row,lanes){return lanes?.get(row.key)||row.item.track||(row.key.startsWith('detached:')?'audio-'+row.key.split(':')[1]:HubLayout.MAIN);}
  // Largest move not exceeding `delta` (closest to it) that leaves every moved clip off its lane neighbours.
  // Captions may overlap freely. With the magnet on, main-lane clips are re-packed instead of collision checked.
  function resolveDelta(rows,delta,lanes){
    const keys=new Set(rows.map(r=>r.key)),floor=-Math.min(...rows.map(r=>r.start)),skipMain=magnetOn;
    const main=HubLayout.mainTrack(project.body),movers=rows.filter(r=>!r.key.startsWith('caption:')&&!(skipMain&&laneOf(r,lanes)===main)).map(r=>({start:r.start,end:r.end,lane:laneOf(r,lanes)}));
    if(!movers.length)return Math.max(delta,floor);
    const obstacles=timelineEntries().filter(r=>!r.key.startsWith('caption:')&&!keys.has(r.key)&&r.key!=='audio:0'&&!(skipMain&&laneOf(r)===main)).map(r=>({start:r.start,end:r.end,lane:laneOf(r)}));
    return HubLayout.resolveMove(movers,obstacles,delta);
  }
  function moveSelectionTo(time){
    const entries=timelineEntries(),keys=new Set(expandKeys(selectedKeys())),chosen=entries.filter(r=>keys.has(r.key));if(!chosen.length)return;
    if(chosen.some(r=>r.item.locked))return fail('请先解锁所选音轨');
    if(chosen.some(r=>r.key==='audio:0'))return fail('请先组合音频，再移动');
    const oldStart=Math.min(...chosen.map(r=>r.start)),want=Math.max(0,time)-oldStart;
    if(Math.abs(want)<.00001)return;
    const free=resolveDelta(chosen,want);
    if(free===null)return fail('该位置已被占用，请放到空闲位置');
    if(Math.abs(free)<.00001)return;
    pause();editTimeline(()=>{for(const row of chosen){if(row.key.startsWith('caption:')||row.key.startsWith('sticker:')){const d=Math.max(free,-row.item.start);row.item.start+=d;row.item.end+=d;}else row.item.at=Math.max(0,row.start+free);}},undefined,new Set(chosen.map(r=>r.item)));
    const members=new Set(chosen.map(r=>r.item));mark();render();setTimelineSelection(timelineEntries().filter(r=>members.has(r.item)).map(r=>r.key));
  }
  function setTimelineSelection(keys,options={}){
    marqueeSelectionActive=true;
    timelineSelection.clear();videoSelection.clear();trackSelection=null;
    if(options.primary!==undefined)primaryCaption=options.primary;
    for(const key of expandKeys(keys)){const [kind,raw]=key.split(':'),index=Number(raw);timelineSelection.add(key);if(kind==='video'&&clips()[index])videoSelection.add(clips()[index]);}
    const firstVideo=[...timelineSelection].find(k=>k.startsWith('video:'));if(firstVideo)selected=Number(firstVideo.split(':')[1]);
    paintSelectionClasses();renderProperties();renderSpeed();paintRange();scheduleSelectionSync();
  }
  function paintSelectionClasses(){
    scroll.querySelectorAll('[data-timeline-key]').forEach(n=>{const yes=timelineSelection.has(n.dataset.timelineKey)||n.dataset.timelineKey?.startsWith('original:')&&timelineSelection.has(n.dataset.timelineKey.replace('original:','video:'));n.classList.toggle('track-selected',yes);if(n.classList.contains('edit-clip')){n.classList.toggle('selected',yes);n.setAttribute('aria-pressed',String(yes));}});
  }
  function canDeleteSelection(){
    if(!project)return false;
    const rows=selectedRows();return rows.length>0&&!rows.some(row=>row.item.locked);
  }
  function deleteSelection(){
    if(!project||busy)return false;
    if(!selectedRows().length)return fail('请先选择要删除的内容'),false;
    if(!canDeleteSelection())return fail('所选片段包含锁定音轨，请先解锁'),false;
    if(timelineSelection.size){for(const key of expandKeys([...timelineSelection]))timelineSelection.add(key);return deleteTimelineSelection();}
    if(trackSelection)return deleteTrack();
    for(const key of expandKeys(selectedKeys()))timelineSelection.add(key);
    return deleteTimelineSelection();
  }
  function deleteTimelineSelection(){
    if(!timelineSelection.size)return false;
    if([...timelineSelection].some(k=>k.startsWith('detached:')&&project.body.audio_clips[Number(k.split(':')[1])]?.locked)){fail('所选片段包含锁定音轨，请先解锁');return true;}
    pause();clips().forEach((c,i)=>{if(timelineSelection.has('original:'+i))c.volume=0;});
    editTimeline(()=>{
    project.body.clips=clips().filter((_,i)=>!timelineSelection.has('video:'+i));
    project.body.captions=project.body.captions.filter((_,i)=>!timelineSelection.has('caption:'+i));
    project.body.stickers=(project.body.stickers||[]).filter((_,i)=>!timelineSelection.has('sticker:'+i));
    project.body.audio_clips=(project.body.audio_clips||[]).filter((_,i)=>!timelineSelection.has('detached:'+i));
    if(timelineSelection.has('audio:0'))project.body.audio=null;
    });
    timelineSelection.clear();videoSelection.clear();trackSelection=null;mark();render();seek(Math.min(position,total()));return true;
  }
  function deleteTrack(){
    if(!trackSelection)return false;
    const {kind,index}=trackSelection;
        pause();
    if(kind==='detached'){if(project.body.audio_clips[index]?.locked)return fail('请先解锁音轨'),true;project.body.audio_clips.splice(index,1);}
    else if(kind==='caption')project.body.captions.splice(index,1);
    else if(kind==='sticker')project.body.stickers.splice(index,1);
    else if(kind==='audio')project.body.audio=null;
    else if(kind==='original'&&clips()[index])clips()[index].volume=0;
    trackSelection=null;mark();render();seek(position);return true;
  }
  /* ---------------- 时间轴快捷键（CapCut 习惯，可在快捷键设置里重设） ---------------- */
  const shortcutApi=window.HubShortcuts;
  const repeatable=new Set(['prevFrame','nextFrame','back1s','fwd1s','prevCut','nextCut','zoomIn','zoomOut','nudgeLeft','nudgeRight','nudgeLeftSecond','nudgeRightSecond']);
  const volumeMemory=new WeakMap();
  function press(id){
    const button=$(id);
    if(!button||button.disabled)return false;
    button.click();
    return true;
  }
  function cutPoints(){
    return [...new Set(boundaries().map(value=>Math.round(value*1000)/1000))].sort((a,b)=>a-b);
  }
  function clipAtPlayhead(){
    const list=clips();
    for(let i=0;i<list.length;i++){const start=offset(i),end=start+length(list[i]);if(position>=start-1e-4&&position<end-1e-4)return i;}
    return -1;
  }
  /* 键盘操作不依赖鼠标点选：没有多选时，用当前片段或播放头所在片段。 */
  function ensureSelection(){
    if(selectedRows().length)return selectedRows();
    const index=clips()[selected]?selected:clipAtPlayhead();
    if(index<0)return [];
    setTimelineSelection(['video:'+index]);
    return selectedRows();
  }
  function nudge(delta){
    const rows=ensureSelection();
    if(!rows.length)return fail('请先选择时间轴上的片段'),false;
    const start=Math.min(...rows.map(row=>row.start));
    moveSelectionTo(Math.max(0,start+delta));
    return true;
  }
  function toggleMute(){
    if(!project||busy)return false;
    const rows=selectedRows(),targets=rows.filter(row=>/^(video:|detached:|audio:)/.test(row.key));
    if(!targets.length)return fail('请选择要静音的视频或音频，字幕不影响其他片段'),false;
    if(targets.some(row=>row.item.locked))return fail('所选片段包含锁定音轨，请先解锁'),false;
    const keep=rows.map(row=>row.item),silent=row=>!!row.item.muted||Number(row.item.volume??(row.key==='audio:0'?0.7:1))<=0,mute=!targets.every(silent);
    pause();commitEdits();
    // Volume-only commands must not invoke layout, magnet or unrelated track following.
    for(const row of targets){
      const clip=row.item;
      if(row.key.startsWith('detached:')){
        clip.muted=mute;
        if(!mute&&Number(clip.volume??1)<=0)clip.volume=volumeMemory.get(clip)||1;
      }else if(mute){
        if(Number(clip.volume??1)>0)volumeMemory.set(clip,clip.volume??1);
        clip.volume=0;
      }else{
        clip.volume=volumeMemory.get(clip)||(Number(clip.volume)>0?Number(clip.volume):row.key==='audio:0'?0.7:1);volumeMemory.delete(clip);
      }
    }
    mark();render();setTimelineSelection(timelineEntries().filter(row=>keep.includes(row.item)).map(row=>row.key));seek(position);
    return true;
  }
  let clipClipboard=null;
  function copySelection(){
    const rows=ensureSelection();
    if(!rows.length)return fail('请先选择要复制的片段'),false;
    clipClipboard={origin:Math.min(...rows.map(row=>row.start)),rows:rows.map(row=>({key:row.key,start:row.start,end:row.end,item:structuredClone(row.item)}))};
    window.toast?.(`已复制 ${rows.length} 个时间轴对象`);
    return true;
  }
  function pasteRows(rows,startAt){
    if(!project||!rows.length)return false;
    const origin=Math.min(...rows.map(row=>row.start)),delta=Math.max(0,startAt)-origin,created=[];
    pause();
    editTimeline(()=>{
      for(const row of rows){
        const copy=structuredClone(row.item);
        delete copy.edit_group;
        if(row.key.startsWith('video:')){
          if(clips().length>=50)continue;
          copy.at=Math.max(0,row.start+delta);
          project.body.clips.push(copy);created.push('video:'+(project.body.clips.length-1));
        }else if(row.key.startsWith('caption:')){
          if(project.body.captions.length>=600)continue;
          copy.start=row.start+delta;copy.end=row.end+delta;
          project.body.captions.push(copy);created.push('caption:'+(project.body.captions.length-1));
        }else if(row.key.startsWith('detached:')){
          project.body.audio_clips??=[];
          if(project.body.audio_clips.length>=50)continue;
          copy.at=Math.max(0,row.start+delta);copy.track='audio-'+crypto.randomUUID();
          project.body.audio_clips.push(copy);created.push('detached:'+(project.body.audio_clips.length-1));
        }
      }
    });
    if(!created.length){renderProperties();return fail('粘贴位置已达轨道上限'),false;}
    mark();render();setTimelineSelection(created);seek(position);
    return true;
  }
  function pasteClipboard(){
    if(!clipClipboard)return fail('剪贴板为空，请先复制片段'),false;
    return pasteRows(clipClipboard.rows,Math.max(0,position));
  }
  function duplicateSelection(){
    const rows=ensureSelection();
    if(!rows.length)return fail('请先选择要再制的片段'),false;
    return pasteRows(rows,Math.max(...rows.map(row=>row.end)));
  }
  function clearSelection(){
    marqueeSelectionActive=false;timelineSelection.clear();videoSelection.clear();trackSelection=null;
    paintSelectionClasses();renderProperties();renderSpeed();paintRange();
    return true;
  }
  function applyZoom(next){
    const slider=$('timeline-zoom');
    if(!slider)return false;
    const value=Math.max(Number(slider.min)||12,Math.min(Number(slider.max)||80,Math.round(next)));
    if(value===Number(slider.value))return true;
    slider.value=String(value);
    window.hubTimelineScale=value;
    renderTimeline();paintSelectionClasses();paint();
    return true;
  }
  /* Ctrl / ⌘ + 滚轮：缩放时间轴，并让鼠标下的时间点在缩放后仍然停在鼠标下。 */
  const LABEL_W=104;
  function zoomAtPointer(event){
    const slider=$('timeline-zoom');
    if(!slider||!project)return;
    const rect=scroll.getBoundingClientRect(),scale=window.hubTimelineScale||32;
    const pointer=event.clientX-rect.left;
    const time=Math.max(0,(pointer+scroll.scrollLeft-LABEL_W)/scale);
    const step=event.deltaY<0?1:-1;
    let next=Math.round(scale*Math.exp(-event.deltaY*0.0015));
    if(next===scale)next=scale+step;
    if(!applyZoom(next))return;
    const applied=window.hubTimelineScale||32;
    scroll.scrollLeft=Math.max(0,LABEL_W+time*applied-pointer);
  }
  scroll.addEventListener('wheel',event=>{
    if(!(event.altKey||event.ctrlKey||event.metaKey))return;
    if(!me||view!=='editor'||!project||document.querySelector('dialog[open]'))return;
    event.preventDefault();
    if(event.altKey&&!event.ctrlKey&&!event.metaKey){
      const factor=event.deltaMode===1?16:event.deltaMode===2?scroll.clientWidth:1;
      scroll.scrollLeft+=(event.deltaY||event.deltaX)*factor;
    }else zoomAtPointer(event);
  },{passive:false});
  function ungroupAll(){
    const rows=timelineEntries(),keys=new Set(expandKeys(selectedKeys())),chosen=rows.filter(row=>keys.has(row.key));
    if(!chosen.length)return fail('请先选择要解除的组'),false;
    const ids=new Set(chosen.flatMap(row=>[row.item.edit_group,row.item.edit_compound]).filter(Boolean));
    if(!ids.size)return fail('所选片段不在任何组里'),false;
    pause();
    editTimeline(()=>{for(const row of rows){if(ids.has(row.item.edit_group))delete row.item.edit_group;if(ids.has(row.item.edit_compound))delete row.item.edit_compound;}});
    mark();render();setTimelineSelection(chosen.map(row=>row.key));
    return true;
  }
  /* 键盘分割按 CapCut 习惯：直接切播放头下的片段，不受成组多选影响。 */
  function splitAtPlayhead(){
    const compound=selectedCompound();if(compound)return splitCompound(compound);
    const stickerRow=selectedRows().find(r=>r.key.startsWith('sticker:'));
    if(stickerRow){
      const c=stickerRow.item,t=HubLayout.q(position);
      if(c.locked||t<=c.start||t>=c.end)return fail('请把播放头移到未锁定贴纸的中间'),false;
      const list=project.body.stickers;if(list.length>=50)return fail('最多 50 个贴纸'),false;
      pause();const i=list.indexOf(c);list.splice(i,1,{...c,end:t},{...c,id:'sticker-'+crypto.randomUUID(),start:t});mark();render();setTimelineSelection(['sticker:'+(i+1)]);seek(position);return true;
    }
    const list=clips();
    let index=clipAtPlayhead();
    if(index<0&&list[selected])index=selected;
    if(index<0)return fail('请先把播放头移到要分割的片段上'),false;
    const clip=list[index];
    if(clip.edit_compound&&!expandedCompounds.has(clip.edit_compound))return fail('请双击展开复合片段，再分割内部片段'),false;
    const rate=clip.speed||1,at=clip.start+(position-offset(index))*rate;
    if((at-clip.start)/rate<.1||(clip.end-at)/rate<.1)return fail('请把播放位置移到当前片段中间，再分割'),false;
    if(list.length>=50)return fail('最多 50 个片段'),false;
    pause();
    list.splice(index,1,{...clip,end:at},{...clip,start:at,at:position});
    mark();render();seek(position);
    return true;
  }
  /* Q / W 波纹裁剪：把片段入点或出点裁到播放头，主轨磁吸开启时其后片段自动前移补位。 */
  function soloSelectedIndex(){
    if(videoSelection.size===1)return clips().indexOf([...videoSelection][0]);
    if(timelineSelection.size===1){
      const key=[...timelineSelection][0];
      if(key.startsWith('video:')){const index=Number(key.slice(6));if(clips()[index])return index;}
    }
    return -1;
  }
  function insideClip(index){
    const clip=clips()[index];
    if(!clip)return false;
    const start=offset(index),finish=start+length(clip);
    return position>start+1e-6&&position<finish-1e-6;
  }
  function rippleIndex(){
    if(!clips().length)return -1;
    const chosen=soloSelectedIndex();
    if(chosen>=0&&insideClip(chosen))return chosen;
    const under=clipAtPlayhead();
    if(under>=0)return under;
    return chosen;
  }
  function rippleTrim(edge){
    if(!clips().length)return fail('请先把视频加入时间轴，再按 Q / W 裁剪'),false;
    const index=rippleIndex();
    const key=edge==='start'?'Q':'W';
    if(index<0)return fail(`按 ${key} 前，请把播放头移到要裁剪的片段上`),false;
    const clip=clips()[index];
    if(clip.edit_compound&&!expandedCompounds.has(clip.edit_compound))return fail('请双击展开复合片段，再裁剪内部片段'),false;
    /* 只有位于片段内部的播放头才能决定新的入点 / 出点。 */
    const rate=clip.speed||1,start=offset(index),finish=start+length(clip);
    if(position<=start+1e-4||position>=finish-1e-4)return fail(`按 ${key} 前，请把播放头移到片段中间`),false;
    const value=clip.start+(position-start)*rate;
    if(value<clip.start+.1*rate||value>clip.end-.1*rate)return fail('裁剪后片段至少要保留 0.1 秒'),false;
    selected=index;videoSelection.clear();videoSelection.add(clip);
    const keep=position;
    trim(edge,value);
    if(Math.abs(clip[edge]-value)>1e-6)return false; // trim 已提示为什么不合法
    seek(Math.min(keep,total()));
    return true;
  }
  const shortcutActions={
    play:()=>{playing?pause():startPlayback();return true;},
    prevFrame:()=>{pause();seek(position-frame);return true;},
    nextFrame:()=>{pause();seek(position+frame);return true;},
    back1s:()=>{pause();seek(position-1);return true;},
    fwd1s:()=>{pause();seek(position+1);return true;},
    prevCut:()=>{const list=cutPoints().filter(value=>value<position-1e-4);pause();seek(list.length?list[list.length-1]:0);return true;},
    nextCut:()=>{const list=cutPoints().filter(value=>value>position+1e-4);pause();seek(list.length?list[0]:total());return true;},
    goStart:()=>{pause();seek(0);return true;},
    goEnd:()=>{pause();seek(total());return true;},
    split:splitAtPlayhead,
    rippleIn:()=>rippleTrim('start'),
    rippleOut:()=>rippleTrim('end'),
    deleteSelection,
    remove:deleteSelection,
    copy:copySelection,
    cut:()=>copySelection()?deleteTimelineSelection():false,
    paste:pasteClipboard,
    duplicate:duplicateSelection,
    nudgeLeft:()=>nudge(-frame),
    nudgeRight:()=>nudge(frame),
    nudgeLeftSecond:()=>nudge(-1),
    nudgeRightSecond:()=>nudge(1),
    mute:toggleMute,
    detach:()=>press('edit-detach'),
    group:()=>{bundle('group',false);return true;},
    compound:()=>{bundle('compound',false);return true;},
    ungroup:ungroupAll,
    speed:()=>{window.hubEditorShell?.openRight?.('speed');return true;},
    addCaption:()=>press('edit-add-caption'),
    zoomIn:()=>applyZoom(Number($('timeline-zoom').value)+8),
    zoomOut:()=>applyZoom(Number($('timeline-zoom').value)-8),
    zoomFit:()=>applyZoom(total()>0?(scroll.clientWidth-140)/total():32),
    snapToggle:()=>{tlToggles.snap.click();return true;},
    magnetToggle:()=>{tlToggles.magnet.click();return true;},
    linkToggle:()=>{tlToggles.link.click();return true;},
    selectAll:()=>{setTimelineSelection([...scroll.querySelectorAll('[data-timeline-key]')].map(node=>node.dataset.timelineKey));return true;},
    deselect:clearSelection,
    undo:()=>press('edit-undo'),
    redo:()=>press('edit-redo'),
    save:()=>press('edit-save'),
    export:()=>press('edit-export'),
    shortcuts:()=>{shortcutApi?.openSettings();return true;}
  };
  if(shortcutApi){
    shortcutApi.register(shortcutActions);
    shortcutApi.onChange(()=>console.info('[shortcuts] updated'));
  }
  // 素材预览优先占用空格：预览期间空格只控制预览台，不触发时间轴播放；Esc 退出预览。
  window.addEventListener('keydown',event=>{
    if(!previewCard||sourcePreview.hidden||event.defaultPrevented||event.isComposing)return;
    if(!$('edit-stage')?.offsetParent)return;
    if(event.key==='Escape'){endSourcePreview();return;}
    if(event.code!=='Space'&&event.key!==' ')return;
    if(event.ctrlKey||event.metaKey||event.altKey||event.shiftKey)return;
    const target=event.target;
    if(target&&target.closest&&target.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="menu"],[role="tablist"]'))return;
    if(document.querySelector('dialog[open]'))return;
    event.preventDefault();event.stopImmediatePropagation();
    if(!event.repeat)toggleSourcePreview();
  },true);
  document.addEventListener('keydown',e=>{
    if(!me||view!=='editor'||!project||busy||trimmingActive||e.defaultPrevented||e.isComposing||document.querySelector('dialog[open]'))return;
    const t=e.target;if(t.closest('input,textarea,select,[contenteditable]:not([contenteditable="false"]),[role="menu"],[role="tablist"]'))return;
    /* 取色器打开时，键盘归取色器所有；但保留 Ctrl/Cmd 组合（保存、撤销等），且不允许左右键拖动播放头 */
    if(t.closest('.cp-panel,.cp')&&!(e.ctrlKey||e.metaKey))return;
    const hit=shortcutApi?.resolve(e);
    if(!hit){
      // 没有对应动作时仍要挡住空格/退格，避免页面滚动或后退。
      if(!e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.code==='Space'||e.key==='Backspace')){e.preventDefault();return;}
      if(!e.ctrlKey&&!e.metaKey&&!e.altKey&&(e.key==='Backspace'||e.key==='Delete')&&marqueeSelectionActive&&!timelineSelection.size)e.preventDefault();
      return;
    }
    e.preventDefault();e.stopImmediatePropagation();
    if(e.repeat&&!repeatable.has(hit.id))return;
    shortcutApi.run(hit.id,e);
  },true);
  setInterval(()=>{if(me&&!document.hidden&&((view==='editor'&&loaded&&exportPending)||hubNotice.has('export:')))refreshExports();},5000);
  window.addEventListener('pagehide',()=>{if(project)saveRecovery();});
  window.addEventListener('beforeunload',event=>{if(dirty&&!saveRecovery()){event.preventDefault();event.returnValue='';}});
  return {drawTracks,seek:time=>seek(time),isPlaying:()=>playing,hasBundle:key=>expandKeys([key]).length>1,bundle,bundleRows,beginSelectionTrim:beginMultiVideoTrim,beginCompoundTrim,beginTimelineMove,beginBundleMove,moveSelectionTo,toggleCompound,setTimelineSelection,timelineSelection:()=>[...timelineSelection],selectTrack,total,open,fromTask,pause,reset,selectProject,save,renderLibrary,ensureFullLibrary,audioTimeline,insertVoice,refreshVoiceProject,
    insertAudioAsset,
    insertAudioAssetAt,
    insertAudioFiles,
    insertDroppedFiles,
    importFootage,
    uploadAudioFiles,
    isDirty:()=>dirty,
    captionSelection:()=>project?.body.captions.flatMap((c,i)=>c._voiceSelected?[i]:[])||[],
    selectCaption,
    captionIndex:()=>captionTarget()?.index??null,
    captionCount:()=>project?.body.captions?.length||0,
    current:()=>project?structuredClone(project):null,
    body:()=>project?.body||null,
    mark:()=>mark(),
    fail:message=>fail(message),
    repaint:()=>{render();},
    setSettings:(title,target,ratio)=>{if(project){project.title=title;project.body.target_duration=target;project.body.ratio=ratio;mark();render();}},
    redrawTimeline:()=>{renderTimeline();announce();paintPlayhead();},
    refreshLibrary:refresh,
    refreshMobileLibrary:async()=>{if($('library-scope'))$('library-scope').value='all';await refresh();},
    refreshExports,    step:delta=>{pause();seek(position+delta);},
    position:()=>position};
})();


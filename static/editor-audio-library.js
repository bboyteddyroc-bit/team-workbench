/* Owner-scoped audio assets, shared by uploaded and generated speech. */
(()=>{
  'use strict';
  const $=id=>document.getElementById(id);
  let mode='uploaded',epoch=0,assets=[],generated=new Set(),mounted=false,notice='';
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text)n.textContent=text;if(cls)n.className=cls;return n;};
  async function json(url,options){const r=await fetch(url,{credentials:'same-origin',...options});const d=await r.json();if(!r.ok)throw Error(d.detail||'读取音频失败');return d;}
  const AUDIO_EXT={mp3:'audio/mpeg',wav:'audio/wav',m4a:'audio/mp4',aac:'audio/aac',ogg:'audio/ogg',oga:'audio/ogg',opus:'audio/ogg',flac:'audio/flac'};
  const extension=name=>(String(name||'').split('.').pop()||'').toLowerCase();
  const audioMime=file=>{const declared=(file.type||'').toLowerCase();if(declared&&declared!=='application/octet-stream')return declared;return AUDIO_EXT[extension(file.name)]||declared;};
  // MP4/MOV 等是视频容器，只是也能装音频：按视频处理，避免把视频当音频上传。
  const VIDEO_EXT=/\.(mp4|mov|m4v|mkv|avi|webm|flv|wmv)$/i;
  const isAudioFile=file=>{const declared=(file.type||'').toLowerCase();if(/^video\//i.test(declared)||VIDEO_EXT.test(file.name||''))return false;return /^audio\//i.test(declared)||!!AUDIO_EXT[extension(file.name)];};
  async function uploadAssets(files){
    const session=sessionEpoch,created=[],errors=[];
    for(const file of files){
      if(session!==sessionEpoch)break;
      try{
        if(!isAudioFile(file))throw Error('请选择 MP3、WAV、M4A、AAC、OGG 或 FLAC 音频');
        if(file.size>64*1024*1024)throw Error('单个音频不能超过 64 MB');
        created.push(await json('/api/assets',{method:'POST',headers:{'X-Hub-Request':'1','Content-Type':audioMime(file),'X-File-Name':encodeURIComponent(file.name)},body:file}));
      }catch(e){errors.push(`${file.name}：${e.message}`);}
    }
    return {created,errors};
  }
  const say=message=>{notice=message;const node=$('editor-audio-note');if(node)node.textContent=message;};
  function reset(){epoch++;assets=[];generated.clear();document.querySelectorAll('#editor-audio-assets audio').forEach(a=>a.pause());$('editor-audio-assets')?.replaceChildren();}
  async function refresh(){
    if(!mounted)return;const token=++epoch,session=sessionEpoch;
    try{
      const [rows,jobs]=await Promise.all([json('/api/workspace/materials'),json('/api/voice/jobs')]);
      if(token!==epoch||session!==sessionEpoch)return;
      assets=rows.filter(a=>a.mime?.startsWith('audio/')).sort((a,b)=>b.created-a.created);
      generated=new Set((jobs.jobs||[]).filter(j=>j.asset_id).map(j=>j.asset_id));
      render();renderMixed();$('editor-audio-note').textContent=notice;
    }catch(e){if(token===epoch&&session===sessionEpoch)say(e.message);}
  }
  function render(host=$('editor-audio-assets'), selectedMode=mode, selectedScope=null){
    if(!host)return;host.querySelectorAll('audio').forEach(a=>a.pause());host.replaceChildren();
    const scope=selectedScope||$('editor-audio-scope')?.value||'today',now=new Date(),current=window.hubEditor?.current();
    const projectIds=new Set([current?.body?.audio?.asset_id,...(current?.body?.audio_clips||[]).map(c=>c.asset_id)].filter(Boolean));
    const rows=assets.filter(a=>{
      if((generated.has(a.id)||a.name.startsWith('AI配音-'))!==(selectedMode==='generated'))return false;
      if(scope==='all')return true;
      if(scope==='project')return projectIds.has(a.id);
      const d=new Date(a.created*1000);return a.created&&d.getFullYear()===now.getFullYear()&&d.getMonth()===now.getMonth()&&d.getDate()===now.getDate();
    });
    if(!rows.length){host.append(el('p','当前范围暂无音频，可切换“全部日期”查看历史素材。','fine'));return;}
    const groups=new Map();for(const a of rows){const d=new Date(a.created*1000),day=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;if(!groups.has(day))groups.set(day,[]);groups.get(day).push(a);}
    for(const [day,items] of groups){
      const section=el('details',null,'edit-day');section.open=host.id==='editor-mixed-audio'||host.children.length===0;
      const summary=el('summary',null,'edit-day-summary');summary.append(el('strong',day),el('span',` · ${items.length} 个`,'fine'));section.append(summary);
      const body=el('div',null,'edit-day-body audio-asset-list');section.append(body);host.append(section);
      const fill=()=>{if(body.children.length)return;for(const a of items){
        const row=el('div',null,'edit-source source-card audio-asset-row'),name=el('strong',a.name),audio=el('audio');audio.preload='metadata';audio.src='/api/assets/'+encodeURIComponent(a.id);audio.setAttribute('aria-label','试听 '+a.name);
        name.draggable=true;name.title='拖到时间轴上的音频轨';name.setAttribute('draggable','true');
        name.addEventListener('dragstart',event=>{event.dataTransfer.effectAllowed='copy';event.dataTransfer.setData('application/x-seedance-audio',a.id);event.dataTransfer.setData('text/plain',a.name);$('editor-audio-note').textContent='拖到时间轴上的音频轨即可放置';});
        name.addEventListener('dragend',()=>{$('editor-audio-note').textContent='';});
        const preview=el('div',null,'source-frame audio-asset-preview');preview.draggable=true;preview.tabIndex=0;preview.setAttribute('role','button');preview.setAttribute('aria-label','播放或暂停 '+a.name);preview.title='点击试听；拖动到音频轨';preview.addEventListener('dragstart',event=>{event.dataTransfer.effectAllowed='copy';event.dataTransfer.setData('application/x-seedance-audio',a.id);event.dataTransfer.setData('text/plain',a.name);});preview.addEventListener('click',()=>{if(audio.paused){const p=audio.play();p?.catch(()=>say('音频无法播放，请检查文件格式'));}else audio.pause();});preview.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();preview.click();}});
        preview.innerHTML='<svg viewBox="0 0 160 80" aria-hidden="true"><path d="M12 34v12m10-20v28m10-36v44m10-25v6m10-18v30m10-45v60m10-40v20m10-28v36m10-45v54m10-39v24m10-33v42m10-28v14m10-20v26m10-17v8" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/></svg>';
        const duration=el('span','--:--','source-duration');audio.addEventListener('loadedmetadata',()=>{if(Number.isFinite(audio.duration))duration.textContent=`${Math.floor(audio.duration/60)}:${String(Math.floor(audio.duration%60)).padStart(2,'0')}`;});preview.append(audio,duration);
        audio.addEventListener('play',()=>{preview.classList.add('is-playing');window.hubEditor?.pause();host.querySelectorAll('audio').forEach(other=>{if(other!==audio)other.pause();});});audio.addEventListener('pause',()=>preview.classList.remove('is-playing'));
        const add=el('button','+','source-add');add.type='button';add.setAttribute('aria-label','加入时间轴：'+a.name);add.title='加入时间轴';add.addEventListener('click',event=>event.stopPropagation());
        add.onclick=async()=>{const project=window.hubEditor?.current(),session=sessionEpoch;add.disabled=true;try{
          if(!Number.isFinite(audio.duration))await new Promise((resolve,reject)=>{const done=()=>{cleanup();resolve();},error=()=>{cleanup();reject(Error('无法读取音频，请重试'));},timer=setTimeout(error,15000),cleanup=()=>{clearTimeout(timer);audio.removeEventListener('loadedmetadata',done);audio.removeEventListener('error',error);};audio.addEventListener('loadedmetadata',done);audio.addEventListener('error',error);audio.load();});
          if(session!==sessionEpoch||project?.id!==window.hubEditor?.current()?.id)throw Error('剪辑项目已切换，请重新添加');
          window.hubEditor.insertAudioAsset(a,audio.duration);say('已加入当前播放头位置');
        }catch(e){say(e.message);}finally{add.disabled=false;}};
        preview.append(add);row.append(preview,name);body.append(row);
        row.title='点击试听，拖动缩略图到时间轴，或点“+”加入';
      }};
      section.addEventListener('toggle',()=>{if(section.open)fill();});if(section.open)fill();
    }
  }
  function renderMixed(){const host=$('editor-mixed-audio'),list=$('edit-library-list');if(!host||!list)return;list.querySelectorAll('.audio-asset-row').forEach(n=>n.remove());render(host,'uploaded',$('library-scope')?.value||'today');for(const section of [...host.querySelectorAll('.edit-day')]){const day=section.querySelector('summary strong')?.textContent;const target=[...list.querySelectorAll('.edit-day')].find(s=>s.querySelector('summary strong')?.textContent===day);if(!target)continue;const body=target.querySelector('.edit-day-body'),source=section.querySelector('.edit-day-body');if(!body.dataset.filled)target.open=true;body.append(...source.children);section.remove();}if(!host.querySelector('.edit-day'))host.replaceChildren();}
  function mount(){
    const panel=$('editor-tool-audio');if(!panel||mounted)return;mounted=true;
    const settings=el('details',null,'audio-track-settings');settings.append(el('summary','时间轴音频设置'));
    [...panel.children].forEach(n=>settings.append(n));settings.hidden=true;panel.append(settings);const mixed=el('div');mixed.id='editor-mixed-audio';$('edit-library-list')?.after(mixed);$('library-scope')?.addEventListener('change',renderMixed);
    const tabs=el('div',null,'editor-panel-tabs');tabs.setAttribute('role','tablist');tabs.setAttribute('aria-label','音频来源');
    const list=el('div');list.id='editor-audio-assets';const note=el('p',null,'fine');note.id='editor-audio-note';note.setAttribute('role','status');
    const scopeLabel=el('label','素材范围'),scope=el('select');scope.id='editor-audio-scope';scope.setAttribute('aria-label','音频素材范围');
    for(const [value,label] of [['today','今日素材'],['all','全部日期'],['project','本项目']])scope.add(new Option(label,value));
    scope.onchange=()=>render();scopeLabel.append(scope);
    const upload=el('label','上传音频','audio-upload-button'),input=el('input');input.type='file';input.accept='audio/*';input.multiple=true;input.setAttribute('aria-label','上传音频');upload.append(input);
    const extras=new Map();
    const showTab=key=>{
      mode=key;const builtin=key==='uploaded'||key==='generated';
      list.hidden=!builtin;scopeLabel.hidden=!builtin;upload.hidden=key!=='uploaded';
      for(const [name,node] of extras)node.hidden=name!==key;
      [...tabs.children].forEach(x=>{if(x.tagName!=='BUTTON')return;const active=x.dataset.tab===key;x.classList.toggle('active',active);x.setAttribute('aria-selected',String(active));x.tabIndex=active?0:-1;});
      if(builtin)render();
    };
    for(const [key,label] of [['generated','AI音频']]){const b=el('button',label);b.type='button';b.setAttribute('role','tab');b.dataset.tab=key;b.onclick=()=>showTab(key);tabs.append(b);}
    const addTab=(key,label,build)=>{
      if(extras.has(key))return extras.get(key);
      const button=el('button',label);button.type='button';button.setAttribute('role','tab');button.dataset.tab=key;button.onclick=()=>showTab(key);tabs.append(button);
      const host=el('div',null,'audio-tab-page');host.dataset.tab=key;host.hidden=true;list.after(host);extras.set(key,host);
      try{build(host,{show:()=>showTab(key),note:say,tabs});}catch(e){host.append(el('p','音效面板加载失败：'+e.message,'fine'));}
      return host;
    };
    panel.prepend(tabs,upload,scopeLabel,note,list);tabs.firstChild.click();
    const receive=async(files,options={})=>{const session=sessionEpoch,input2=input;input2.disabled=true;const picked=options.audioOnly===false?files:files.filter(isAudioFile);let errors=[];
      if(!picked.length){input2.disabled=false;say('请选择 MP3、WAV、M4A、AAC、OGG 或 FLAC 音频文件');return;}
      try{if(picked.length===1)say('正在上传 '+picked[0].name+'…');else say(`正在上传 ${picked.length} 个音频…`);
        const result=await uploadAssets(picked);errors=result.errors;
        if(session!==sessionEpoch)return;
        if(result.created.length){await refresh();say(errors.length?errors.join('；'):`已保存 ${result.created.length} 个音频，可在素材区使用`);}
        else say(errors.join('；')||'没有可用的音频文件');}
      catch(e){say(e.message);}finally{input2.value='';input2.disabled=false;}};
    input.onchange=()=>receive([...input.files]);
    panel.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();e.dataTransfer.dropEffect='copy';}});
    panel.addEventListener('drop',e=>{const files=[...(e.dataTransfer.files||[])];if(!files.length)return;e.preventDefault();e.stopPropagation();const audio=files.filter(f=>isAudioFile(f)),video=files.filter(f=>!isAudioFile(f));if(audio.length)receive(audio);if(video.length){const importer=window.hubEditor?.importFootage;if(!importer){say('视频请拖到时间轴，或用“导入实拍视频”');return;}importer(video).then(items=>say(`已导入 ${items.length} 个视频到素材，拖到时间轴或点“+”使用`)).catch(err=>say(err.message||String(err)));}});
    const materials=$('editor-tool-materials');
    if(materials&&!$('editor-audio-drop-hint')){
      const hint=el('p','可将视频、音频或文件夹拖入素材区。','fine');hint.id='editor-audio-drop-hint';materials.append(hint);
      const dragAudio=e=>[...(e.dataTransfer?.items||[])].some(i=>i.kind==='file'&&/^audio\//i.test(i.type||''));
      materials.addEventListener('dragover',e=>{if(!Array.from(e.dataTransfer.types||[]).includes('Files'))return;if(![...(e.dataTransfer.items||[])].some(i=>i.kind==='file'))return;e.preventDefault();e.dataTransfer.dropEffect='copy';if(dragAudio(e))materials.classList.add('audio-drop-active');});
      materials.addEventListener('dragleave',e=>{if(!materials.contains(e.relatedTarget))materials.classList.remove('audio-drop-active');});
      materials.addEventListener('drop',e=>{const files=[...(e.dataTransfer.files||[])];if(!files.length)return;materials.classList.remove('audio-drop-active');e.preventDefault();e.stopPropagation();const audio=files.filter(f=>isAudioFile(f)),pickVideo=files.filter(f=>!isAudioFile(f));if(audio.length)receive(audio,{audioOnly:false});if(pickVideo.length){const importer=window.hubEditor?.importFootage;if(!importer){say('视频请拖到时间轴，或用“导入实拍视频”');return;}importer(pickVideo).then(items=>say(`已导入 ${items.length} 个视频到素材，拖到时间轴或点“+”使用`)).catch(err=>say(err.message||String(err)));}});
    }
    new MutationObserver(()=>{if(!panel.hidden)refresh();else panel.querySelectorAll('audio').forEach(a=>a.pause());}).observe(panel,{attributes:true,attributeFilter:['hidden']});
    window.addEventListener('hub-project',()=>{if(!panel.hidden)refresh();});window.addEventListener('hub-library-render',renderMixed);
    window.hubAudioLibrary={refresh,reset,upload:uploadAssets,receive,tab:addTab,show:showTab};refresh();
  }
  // Deferred scripts run while readyState is interactive, before the shell's
  // DOMContentLoaded callback has built editor-tool-audio.
  window.addEventListener('hub-editor-shell-ready',mount);
  document.addEventListener('DOMContentLoaded',mount);
  mount();
})();

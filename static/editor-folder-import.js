/* Import mixed folders through the existing video and audio upload paths. */
(()=>{
  'use strict';
  let busy=false;
  const audioExt=/\.(mp3|wav|m4a|aac|ogg|oga|opus|flac)$/i;
  const videoExt=/\.(mp4|mov|m4v)$/i;
  function kind(file){if(videoExt.test(file.name))return 'video';if(audioExt.test(file.name))return 'audio';return 'other';}
  const setBusy=value=>{busy=value;document.querySelectorAll('.editor-folder-import input').forEach(el=>el.disabled=value);};
  async function collectEntries(entries){
    const files=[],errors=[];
    async function visit(entry){
      if(entry.isFile){try{files.push(await new Promise((resolve,reject)=>entry.file(resolve,reject)));}catch(e){errors.push(`${entry.fullPath||entry.name}：${e.message||'读取失败'}`);}return;}
      if(!entry.isDirectory)return;
      try{
        const reader=entry.createReader();
        while(true){const batch=await new Promise((resolve,reject)=>reader.readEntries(resolve,reject));if(!batch.length)break;for(const child of batch)await visit(child);}
      }catch(e){errors.push(`${entry.fullPath||entry.name}：${e.message||'读取文件夹失败'}`);}
    }
    for(const entry of entries)await visit(entry);
    return {files,errors};
  }
  async function importFiles(files,status,readErrors=[]){
    let videos=0,audios=0,skipped=0;const errors=[...readErrors];
    try{
      for(const [i,file] of files.entries()){
        const type=kind(file);if(type==='other'){skipped++;continue;}
        status.textContent=`正在导入 ${i+1}/${files.length}：${file.name}`;
        try{
          if(type==='video'){if(!window.hubEditor?.importFootage)throw Error('视频导入功能尚未就绪');await window.hubEditor.importFootage([file]);videos++;}
          else{if(!window.hubAudioLibrary?.upload)throw Error('音频导入功能尚未就绪');const result=await window.hubAudioLibrary.upload([file]);audios+=result.created.length;if(result.errors.length)errors.push(...result.errors);else if(!result.created.length)errors.push(`${file.name}：未完成导入`);}
        }catch(e){errors.push(`${file.name}：${e.message||String(e)}`);}
      }
      if(audios)await window.hubAudioLibrary?.refresh?.();
      status.textContent=`导入完成：视频 ${videos} 个，音频 ${audios} 个${skipped?`，跳过不支持的文件 ${skipped} 个`:''}${errors.length?`；未完成或结果待确认 ${errors.length} 个（请先检查素材库，避免重复导入）：${errors.join('；')}`:''}${!files.length&&!errors.length?'；文件夹为空':''}`;
    }catch(e){status.textContent=`导入中断：已导入视频 ${videos} 个、音频 ${audios} 个；${e.message||String(e)}`;}
  }
  function mount(){
    const materials=document.getElementById('editor-tool-materials');
    for(const panel of [materials]){
      if(!panel||panel.querySelector('.editor-folder-import'))continue;
      const label=document.createElement('div');label.className='editor-folder-import';const menu=document.createElement('details');menu.innerHTML='<summary>＋ 导入素材</summary><div class="import-choices"><button type="button" data-pick="files">选择视频或音频</button><button type="button" data-pick="folder">导入文件夹</button></div>';label.append(menu);const filesInput=document.createElement('input');filesInput.type='file';filesInput.multiple=true;filesInput.accept='video/*,audio/*';label.append(filesInput);
      const input=document.createElement('input');input.type='file';input.multiple=true;input.setAttribute('webkitdirectory','');input.setAttribute('directory','');input.setAttribute('aria-label','导入视频和音频文件夹');label.append(input);
      const status=document.createElement('p');status.className='editor-folder-status fine';status.setAttribute('role','status');status.textContent='支持视频 MP4 / MOV / M4V；音频 MP3 / WAV / M4A / AAC / OGG / OPUS / FLAC。其他格式暂不支持。';
      const anchor=panel.querySelector('.footage-upload');if(anchor){anchor.hidden=true;anchor.after(label,status);}else panel.prepend(label,status);panel.querySelector('.edit-section-heading h2')?.remove();const oldStatus=document.getElementById('edit-footage-status');if(oldStatus)oldStatus.hidden=true;menu.querySelector('[data-pick=files]').onclick=()=>{menu.open=false;filesInput.click()};menu.querySelector('[data-pick=folder]').onclick=()=>{menu.open=false;input.click()};filesInput.addEventListener('change',async()=>{const files=[...filesInput.files];if(!files.length)return;if(busy){status.textContent='已有导入正在进行';filesInput.value='';return;}setBusy(true);try{await importFiles(files,status);}finally{filesInput.value='';setBusy(false);}});
      window.hubMaterialUpload={async add(files){if(busy){status.textContent='已有导入正在进行，请稍候。';return;}setBusy(true);try{await importFiles(files,status);}finally{setBusy(false);}},folder(){if(!busy)input.click();}};window.dispatchEvent(new Event('hub-material-upload-ready'));
      input.addEventListener('change',async()=>{
        const files=[...input.files];if(!files.length)return;if(busy){status.textContent='已有文件夹正在导入，请稍候。';input.value='';return;}
        setBusy(true);try{await importFiles(files,status);}finally{input.value='';setBusy(false);}
      });
      const hasFiles=e=>Array.from(e.dataTransfer?.types||[]).includes('Files');
      panel.addEventListener('dragover',e=>{if(!hasFiles(e))return;e.preventDefault();e.dataTransfer.dropEffect=busy?'none':'copy';label.classList.add('is-dragover');},true);
      panel.addEventListener('dragleave',e=>{if(!panel.contains(e.relatedTarget))label.classList.remove('is-dragover');},true);
      panel.addEventListener('drop',e=>{
        label.classList.remove('is-dragover');if(!hasFiles(e))return;
        // Read entries synchronously during the drop; the browser clears the drag data afterwards.
        const items=Array.from(e.dataTransfer.items||[]).filter(item=>item.kind==='file');
        const entries=items.map(item=>item.webkitGetAsEntry?.()||null);
        const hasDirectory=entries.some(entry=>entry?.isDirectory);
        const onFolderTarget=label.contains(e.target);
        if(!hasDirectory)return; // The upload component or existing panel handler receives ordinary files.
        e.preventDefault();e.stopImmediatePropagation();panel.classList.remove('audio-drop-active');
        if(busy){status.textContent='已有文件夹正在导入，请稍候。';return;}
        if(!hasDirectory){const files=Array.from(e.dataTransfer.files||[]);if(!files.length){status.textContent='无法读取拖入内容，请点击选择。';return;}setBusy(true);importFiles(files,status).finally(()=>setBusy(false));return;}
        setBusy(true);status.textContent='正在读取文件夹及子文件夹…';
        const missing=entries.some(entry=>!entry);
        collectEntries(entries.filter(Boolean)).then(({files,errors})=>{if(missing)errors.push('部分拖入项目无法读取，请检查后使用点击选择文件夹');return importFiles(files,status,errors);}).catch(e=>{status.textContent='读取文件夹失败：'+(e.message||String(e));}).finally(()=>setBusy(false));
      },true);
    }
  }
  window.addEventListener('hub-editor-shell-ready',mount);document.addEventListener('DOMContentLoaded',mount);mount();
})();

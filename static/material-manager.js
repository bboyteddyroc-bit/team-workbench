'use strict';
// Management-only surface. Upload/reference pickers remain in materials.js.
window.hubMaterialManager=(()=>{
 let stop=()=>{};
 const folders=[['all','全部素材'],['person','人物素材'],['product','产品素材'],['scene','场景素材'],['video','视频素材'],['audio','音频素材'],['other','其他素材'],['unclassified','待归类']];
 const categories=folders.filter(([id])=>['person','product','scene','other'].includes(id));
 const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const day=t=>{const d=new Date(t*1000);return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;};
 function matchesFolder(a,id){return id==='all'||(['video','audio'].includes(id)?a.mime.startsWith(id+'/'):window.hubMaterials.effectiveCategory(a)===id);}
 async function open(root){
  stop();const epoch=sessionEpoch,uploadGuard=new AbortController();let alive=true,assets=[],folder='all',browsing=false,filter={query:'',range:null},checking=false;
  const bar=el('div',undefined,'materials-toolbar'),content=el('div'),status=el('p','正在加载素材…','fine'),head=el('div',undefined,'material-manager-heading'),back=el('button','返回文件夹'),title=el('h2','全部素材'),count=el('span',undefined,'fine');
  root.classList.add('material-manager');status.setAttribute('role','status');back.type='button';head.append(back,title,count);root.replaceChildren(bar,status,head,content);head.hidden=true;
  window.hubMaterialFilters.mount(bar,[],value=>{filter=value;render();});
  const active=()=>alive&&epoch===sessionEpoch&&root.isConnected;
  const setStatus=(text,error=false)=>{status.textContent=text;status.classList.toggle('error',error);status.hidden=!text;};
  function updateControls(reset=false){window.hubMaterialFilters.update(bar,assets.filter(a=>!browsing||matchesFolder(a,folder)),reset);}
  back.onclick=()=>{folder='all';browsing=false;filter={query:'',range:null};updateControls(true);render();};
  async function refresh(){const fresh=await api('/workspace/materials');if(!active())return;assets=fresh;updateControls();render();}
  window.hubMaterials.drop(content,async files=>{
   const notice='upload:'+crypto.randomUUID();hubNotice.begin(notice,`正在上传 ${files.length} 个素材`,'查看素材','materials','#materials');setStatus('正在上传素材…');
   try{
    await window.hubMaterials.upload(files);if(epoch===sessionEpoch)hubNotice.finish(notice,`${files.length} 个素材已上传`,'success');
    if(!active())return;
    folder='all';browsing=false;filter={query:'',range:null};
    await refresh();if(!active())return;
    updateControls(true);setStatus(`成功上传 ${files.length} 个素材，请在「全部素材」或「视频素材」中查看。`);
   }catch(err){if(epoch===sessionEpoch)hubNotice.finish(notice,'上传未全部完成','error','已成功的文件会保留，请核对素材库后再操作。');if(active()){try{await refresh();}catch{}setStatus('上传未全部完成：'+err.message+'；已成功的文件会保留在素材库，请核对后再重试。',true);}throw err;}
  });
  // Prevent the browser from navigating to a file dropped elsewhere on the management page.
  for(const kind of ['dragover','drop'])root.addEventListener(kind,event=>{if(event.dataTransfer?.types?.includes('Files'))event.preventDefault();},{signal:uploadGuard.signal});
  function buildCard(a){
   const card=el('article',undefined,'material-card'),media=window.hubMaterials.preview(a),name=el('textarea',undefined,'material-name'),meta=el('p',`${day(a.created)} · ${Math.max(1,Math.round(a.size/1024)).toLocaleString()} KB`,'fine'),actions=el('div',undefined,'material-actions'),download=el('a','下载到本地','material-download'),details=el('details'),summary=el('summary','管理素材'),form=el('div',undefined,'material-edit');
   card.dataset.assetId=a.id;name.value=a.name;name.rows=2;name.maxLength=200;name.spellcheck=false;name.setAttribute('aria-label','素材名称：'+a.name);name.title='点击修改文件名；回车或移开焦点保存，Esc 取消';download.href='/api/assets/'+a.id+'?download=1';download.download=a.name;actions.append(download,details);details.append(summary,form);
   let savingName=false;
   async function saveName(){
    const next=name.value.trim();if(savingName||!active())return;
    if(next===a.name){name.value=a.name;return;}
    if(!next||/[\/\\\x00-\x1f]/.test(next)){name.value=a.name;toast('文件名不能为空，也不能包含斜杠、换行或控制字符。',true);return;}
    savingName=true;name.readOnly=true;name.setAttribute('aria-busy','true');
    try{await api('/workspace/materials/'+a.id,{name:next});if(active()){a.name=next;name.value=next;name.setAttribute('aria-label','素材名称：'+next);download.download=next;updateControls();setStatus('');toast('文件名已保存');}}
    catch(e){if(active()){name.value=a.name;setStatus(e.message,true);toast(e.message,true);}}
    finally{savingName=false;name.readOnly=false;name.removeAttribute('aria-busy');}
   }
   name.onblur=()=>{void saveName();};name.onkeydown=event=>{if(event.isComposing||event.keyCode===229)return;if(event.key==='Enter'){event.preventDefault();name.blur();}else if(event.key==='Escape'){event.preventDefault();name.value=a.name;name.blur();}};
   const categoryLabel=el('label','手动归类'),select=el('select'),classify=el('button','保存分类');select.setAttribute('aria-label','手动归类');for(const [id,label]of categories)select.append(new Option(label,id));select.value=a.category;categoryLabel.append(select);classify.type='button';
   async function mutate(button,action){button.disabled=true;try{await action();if(active()){setStatus('');await refresh();}}catch(e){if(active()){setStatus(e.message,true);toast(e.message,true);}}finally{button.disabled=false;}}
   classify.onclick=()=>mutate(classify,()=>api('/workspace/materials/'+a.id,{category:select.value}));
   form.append(categoryLabel,classify);
   const remove=el('button','删除素材','material-delete');remove.type='button';remove.onclick=()=>{if(window.confirm(`确认删除“${a.name}”？此操作不可恢复。被项目或任务引用的素材不会删除。`))mutate(remove,()=>api('/workspace/materials/'+a.id+'/delete',{}));};form.append(remove);
   const state=el('div',undefined,'classification-state');if(a.mime.startsWith('image/')){
    const labels={waiting_model:'待配置识别模型',queued:'AI 识别排队中',running:'AI 正在识别',retry_wait:'服务限流 · 稍后自动继续',failed:'AI 识别失败',classified:'已自动归类',manual:'已手动归类'};
    state.append(el('small',labels[a.classification_status]||'待识别','fine'));if(a.classification_error)state.append(el('small',a.classification_error,'fine'));
    const ai=el('button',a.classification_status==='manual'?'改用 AI 识别':'AI 识别');ai.type='button';ai.disabled=['queued','running','retry_wait'].includes(a.classification_status);ai.onclick=()=>{if(a.classification_status==='manual'&&!window.confirm('AI 识别将替换当前手动分类，是否继续？'))return;mutate(ai,()=>api('/workspace/materials/'+a.id+'/classify',{}));};form.append(ai);
   }
   card.append(media,name,meta,state,actions);return card;
  }
  function render(){
   if(!active())return;content.querySelectorAll('video,audio').forEach(m=>m.pause());content.replaceChildren();
   const searching=!!filter.query.trim()||!!filter.range;
   head.hidden=!browsing&&!searching;back.hidden=!browsing;
   title.textContent=browsing?folders.find(([id])=>id===folder)[1]:'搜索结果';
   if(!browsing&&!searching){
    const collection=el('div',undefined,'asset-folders');
    for(const [id,label]of folders){
     const list=assets.filter(a=>matchesFolder(a,id)),button=el('button',undefined,'asset-folder'),art=el('span',undefined,'folder-art'),rear=el('span',undefined,'folder-back'),fan=el('span',undefined,'folder-fan'),front=el('span',undefined,'folder-front');button.type='button';button.dataset.folder=id;art.setAttribute('aria-hidden','true');
     list.slice(0,3).forEach((a,i)=>{const sheet=el('span',undefined,'folder-sheet');sheet.style.setProperty('--offset',String(i-1));sheet.style.setProperty('--order',String(i));if(a.mime.startsWith('image/')){const img=el('img');img.src='/api/assets/'+a.id;img.alt='';img.loading='lazy';sheet.append(img);}else sheet.append(el('span',a.mime.startsWith('audio/')?'AUDIO':'VIDEO','folder-filetype'));fan.append(sheet);});
     if(!list.length)front.append(el('span','暂无素材','folder-empty'));art.append(rear,fan,front);button.append(art,el('strong',label),el('span',`${list.length} 个素材`,'folder-count'));button.onclick=()=>{folder=id;browsing=true;filter={query:'',range:null};updateControls(true);render();back.focus();};collection.append(button);
    }content.append(collection);return;
   }
   const list=assets.filter(a=>(!browsing||matchesFolder(a,folder))&&a.name.toLocaleLowerCase().includes(filter.query.trim().toLocaleLowerCase())&&(!filter.range||(day(a.created)>=filter.range.from&&day(a.created)<=(filter.range.to||filter.range.from))));
   count.textContent=`${list.length} 个素材`;
   if(!list.length){const empty=el('div',undefined,'material-empty');empty.append(el('h3',assets.length?'没有匹配的素材':'素材库为空'),el('p',assets.length?'试试其他名称或日期范围。':'在制作台上传或生成的素材会保存在这里。','fine'));content.append(empty);return;}
   // Folder browsing groups by upload day: newest day open, older days collapsed.
   // Cards are built only when a day opens, so collapsed days cost no media loads.
   if(!searching){
    const groups=new Map();
    for(const a of list){const key=day(a.created);if(!groups.has(key))groups.set(key,[]);groups.get(key).push(a);}
    let first=true;
    for(const [key,items] of groups){
     const section=el('details',undefined,'material-day'),summary=el('summary',undefined,'material-day-summary'),dayGrid=el('div',undefined,'materials-grid');
     summary.append(el('strong',key),el('span',` · ${items.length} 个素材`,'fine'));
     const fill=()=>{if(dayGrid.dataset.filled)return;dayGrid.dataset.filled='1';for(const a of items)dayGrid.append(buildCard(a));};
     section.open=first;first=false;section.append(summary,dayGrid);
     section.addEventListener('toggle',()=>{if(section.open)fill();});
     if(section.open)fill();
     content.append(section);
    }
    return;
   }
   const grid=el('div',undefined,'materials-grid');content.append(grid);
   for(const a of list)grid.append(buildCard(a));
  }
  let timer;stop=()=>{alive=false;uploadGuard.abort();clearInterval(timer);window.hubMaterialFilters.unmount(bar);content.querySelectorAll('video,audio').forEach(m=>m.pause());};
  try{await refresh();if(active())setStatus('');}catch(e){if(active()){setStatus('素材加载失败：'+e.message,true);const retry=el('button','重试');retry.onclick=()=>open(root);content.replaceChildren(retry);}}
  if(active())timer=setInterval(async()=>{if(!active()){stop();return;}if(checking||document.hidden||root.closest('.view')?.hidden||root.querySelector('details[open]:not(.material-day),.material-name:focus,.material-name[aria-busy]')||!assets.some(a=>['waiting_model','queued','running','retry_wait'].includes(a.classification_status)))return;checking=true;try{const fresh=await api('/workspace/materials');if(active()&&!root.querySelector('details[open]:not(.material-day),.material-name:focus,.material-name[aria-busy]')&&JSON.stringify(fresh)!==JSON.stringify(assets)){assets=fresh;updateControls();render();}}catch{}finally{checking=false;}},3000);
 }
 return {open,reset:()=>stop()};
})();

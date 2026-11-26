'use strict';
window.hubMaterials=(()=>{
  let generation=0,dialog=null;
  const categories=[['','全部用途'],['person','人物素材'],['product','产品素材'],['scene','场景素材'],['other','其他素材']];
  const AUDIO_EXT={mp3:'audio/mpeg',wav:'audio/wav',m4a:'audio/mp4',aac:'audio/aac',ogg:'audio/ogg',oga:'audio/ogg',flac:'audio/flac',opus:'audio/ogg'};
  function fileMime(file){
    const declared=(file.type||'').toLowerCase();
    if(declared&&declared!=='application/octet-stream')return declared;
    const ext=(file.name.split('.').pop()||'').toLowerCase();
    return AUDIO_EXT[ext]||declared;
  }
  async function upload(files){
    const result=[],epoch=sessionEpoch;
    for(const file of files){
      if(file.size>64*1024*1024)throw Error('单个素材最大 64 MB');
      const r=await fetch('/api/assets',{method:'POST',credentials:'same-origin',headers:{'Content-Type':fileMime(file),'X-Hub-Request':'1','X-File-Name':encodeURIComponent(file.name)},body:file});
      const a=await r.json();if(!r.ok)throw Error(a.detail||'上传失败');
      if(epoch!==sessionEpoch)throw Error('登录状态已变化');result.push(a);
    }return result;
  }
  function drop(zone,receive,options={}){
    zone.classList.add('drop-zone');let busy=false;
    const box=el('section',undefined,'attachment-upload'),pick=el('button',undefined,'attachment-drop'),icon=el('span',undefined,'attachment-icon'),title=el('strong','拖入文件，或点击选择'),hint=el('span',options.audio?'支持音频文件 · 单文件最大 64 MB':'图片、视频、音频 · 单文件最大 64 MB'),status=el('p',undefined,'attachment-status'),input=el('input');
    icon.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M12 16V3m-4 4 4-4 4 4M4 15v5a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-5"/></svg>';
    pick.type='button';input.type='file';input.hidden=true;input.multiple=options.multiple!==false;input.accept=options.accept||'image/png,image/jpeg,image/webp,video/mp4,audio/mpeg,audio/wav,audio/x-wav,audio/mp4,audio/x-m4a,audio/aac,audio/ogg,audio/flac,.mp3,.wav,.m4a,.aac,.ogg,.flac';status.setAttribute('role','status');status.hidden=true;pick.append(icon,title,hint);box.append(pick,input,status);
    if(zone.parentElement)zone.before(box);else zone.prepend(box);
    async function submit(files){if(busy||!files.length)return;busy=true;pick.disabled=true;box.setAttribute('aria-busy','true');status.hidden=false;status.classList.remove('failed');status.textContent=`正在处理 ${files.length} 个文件…`;try{if(files.some(f=>f.size>64*1024*1024))throw Error('单个素材最大 64 MB');if(options.multiple===false&&files.length!==1)throw Error('请每次选择一个文件');await receive(files);status.textContent='文件已处理，请查看下方素材。';}catch(err){status.classList.add('failed');status.textContent=err.message;toast(err.message,true);}finally{busy=false;pick.disabled=false;input.value='';box.removeAttribute('aria-busy');}}
    pick.onclick=()=>input.click();input.onchange=()=>submit([...input.files]);
    // An optional enclosing card accepts external files anywhere, including nested inputs.
    const card=options.dropTarget;
    if(card){
      const hasFiles=e=>Array.from(e.dataTransfer?.types||[]).includes('Files');
      card.addEventListener('dragover',e=>{if(!hasFiles(e))return;e.preventDefault();e.stopPropagation();e.dataTransfer.dropEffect='copy';card.classList.add('file-drop-active');},true);
      card.addEventListener('dragleave',e=>{if(!card.contains(e.relatedTarget))card.classList.remove('file-drop-active');},true);
      card.addEventListener('drop',e=>{if(!hasFiles(e))return;e.preventDefault();e.stopPropagation();card.classList.remove('file-drop-active');submit(Array.from(e.dataTransfer.files||[]));},true);
    }
    for(const target of [box,zone]){
      target.addEventListener('dragover',e=>{if(e.dataTransfer.types.includes('Files')){e.preventDefault();e.stopPropagation();box.classList.add('drag-over');}});
      target.addEventListener('dragleave',e=>{if(!target.contains(e.relatedTarget))box.classList.remove('drag-over');});
      target.addEventListener('drop',e=>{if(!e.dataTransfer.files.length)return;e.preventDefault();e.stopPropagation();box.classList.remove('drag-over');submit([...e.dataTransfer.files]);});
    }
    return box;
  }
  function pickerButton(callback){const b=el('button',undefined,'secondary library-picker-button'),icon=el('span',undefined,'library-picker-icon'),copy=el('span',undefined,'library-picker-copy');icon.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><path d="M3.5 7.5h17v11a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/><path d="M3.5 7.5V5.8a2 2 0 0 1 2-2h4l2 2h7a2 2 0 0 1 2 2"/></svg>';copy.append(el('strong','从素材库选择'),el('small','调用已保存的图片、视频或声音'));b.type='button';b.append(icon,copy);b.onclick=()=>openPicker(callback);return b;}
  function effectiveCategory(a){
    if(!a.mime.startsWith('image/'))return '';
    if(a.category==='other'&&!['classified','manual'].includes(a.classification_status))return 'unclassified';
    return a.category;
  }
  function classificationControls(a,refresh){
    const box=el('div',undefined,'classification-state');
    if(!a.mime.startsWith('image/'))return box;
    const labels={waiting_model:'待识别 · 管理员可在右下角 AI 助理的连接设置中配置',queued:'自动分类排队中',running:'正在识别图片',retry_wait:'服务限流 · 等待后自动继续',failed:'自动分类失败',classified:'已自动分类',manual:'手动分类'};
    box.append(el('small',labels[a.classification_status]||'待识别','fine'));
    if(a.classification_error)box.append(el('small',a.classification_error,'fine'));
    if(['waiting_model','failed'].includes(a.classification_status)){const retry=el('button','重新识别');retry.type='button';retry.onclick=async()=>{retry.disabled=true;try{const state=await api('/workspace/materials/'+a.id+'/classify',{});a.classification_status=state.status;a.classification_error=state.error;refresh();}catch(e){toast(e.message,true);}finally{retry.disabled=false;}};box.append(retry);}return box;
  }
  function preview(a,light=false){const type=a.mime.split('/')[0],media=el(type==='image'?'img':type==='audio'?'audio':'video');if(type==='image'){media.alt=a.name;media.loading='lazy';media.decoding='async';media.src='/api/assets/'+a.id;}else{media.controls=true;window.hubMediaLazy.watch(media,'/api/assets/'+a.id,light?'none':'metadata');}return media;}
  function morphSearch(bar,search,cat,type,date,refresh){
    const shell=el('div',undefined,'morph-search-shell'),icon=el('span',undefined,'morph-search-icon'),clear=el('button','清除','morph-search-clear'),chips=el('div',undefined,'morph-search-chips'),recent=el('div',undefined,'morph-search-recent');
    icon.innerHTML='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg>';clear.type='button';clear.hidden=true;search.setAttribute('aria-expanded','false');shell.append(icon,search,clear);bar.replaceChildren(shell,chips,recent,cat,type,date);cat.hidden=type.hidden=date.hidden=true;
    const filters=[['type','', '全部'],['type','image','图片'],['type','video','视频'],['type','audio','音频'],['type','generated','生成成片'],['date','today','今天上传']];
    const storageKey='seedance-material-searches';
    const readRecent=()=>{try{return JSON.parse(localStorage.getItem(storageKey)||'[]').filter(v=>typeof v==='string').slice(0,5);}catch{return [];}};
    const saveRecent=value=>{const term=value.trim();if(!term)return;try{localStorage.setItem(storageKey,JSON.stringify([term,...readRecent().filter(v=>v!==term)].slice(0,5)));}catch{}}
    function showRecent(){recent.replaceChildren();const values=readRecent();recent.hidden=!shell.classList.contains('is-open')||!!search.value||!values.length;if(recent.hidden)return;recent.append(el('span','最近搜索','morph-recent-label'));for(const value of values){const b=el('button',value);b.type='button';b.onclick=()=>{search.value=value;sync();refresh();search.focus();};recent.append(b);}}
    function sync(){clear.hidden=!search.value;chips.replaceChildren();if(cat.value){const label=cat.options[cat.selectedIndex]?.text||'当前分类',fixed=el('span',label,'morph-context-chip');fixed.setAttribute('aria-label','当前文件夹：'+label);chips.append(fixed);}
      for(const [kind,value,label]of filters){const control=kind==='type'?type:date;if(kind==='type'&&cat.value&&value==='generated')continue;const active=control.value===value||(kind==='date'&&value==='today'&&date.value==='today');const b=el('button',label,active?'active':'');b.type='button';b.setAttribute('aria-pressed',String(active));b.onclick=()=>{if(kind==='date')date.value=date.value==='today'?'all':'today';else type.value=value;sync();refresh();};chips.append(b);}showRecent();}
    const open=()=>{shell.classList.add('is-open');search.setAttribute('aria-expanded','true');showRecent();};
    const close=()=>{shell.classList.remove('is-open');search.setAttribute('aria-expanded','false');showRecent();};
    search.addEventListener('focus',open);search.addEventListener('keydown',e=>{if(e.isComposing||e.keyCode===229)return;if(e.key==='Enter'){e.preventDefault();saveRecent(search.value);showRecent();}if(e.key==='Escape'){if(search.value){search.value='';sync();refresh();}else{close();search.blur();}}});
    bar.addEventListener('focusout',()=>requestAnimationFrame(()=>{if(!bar.contains(document.activeElement))close();}));
    clear.onclick=()=>{search.value='';sync();refresh();search.focus();};
    sync();return{sync,showRecent};
  }
  async function mount(root,callback,initial={}){
    const stamp=generation,epoch=sessionEpoch;let assets=await api('/workspace/materials');if(stamp!==generation||epoch!==sessionEpoch)return;
    const chosen=new Set(),bar=el('div',undefined,'materials-toolbar'),search=el('input'),cat=el('select'),type=el('select'),date=el('select'),grid=el('div',undefined,'materials-grid');
    search.type='search';search.placeholder='搜索素材名称';search.setAttribute('aria-label','搜索素材');
    for(const [v,t] of categories)cat.append(new Option(t,v));cat.setAttribute('aria-label','素材用途');
    for(const [v,t] of [['','全部类型'],['image','图片'],['video','视频素材'],['audio','音频素材'],['generated','生成成片']])type.append(new Option(t,v));type.setAttribute('aria-label','文件类型');
    date.append(new Option('全部日期','all'),new Option('今天上传','today'));date.setAttribute('aria-label','上传日期');
    cat.value=initial.category||'';type.value=initial.type||'';date.value=initial.date||'all';
    const note=el('p','可拖入图片、视频或音频。素材按当前工作台账号保存，可跨天复用。','fine');
    const apply=el('button',callback?'添加所选参考':'所选素材用于普通生成','primary');apply.type='button';apply.disabled=true;
    apply.onclick=async()=>{try{const selected=assets.filter(a=>chosen.has(a.id));if(callback)await callback(selected);else{navigate('studio');await restoreComposer();await useInComposer(compositions[0],selected);}dialog?.close();root.querySelector('dialog.folder-overlay[open]')?.close();}catch(e){toast(e.message,true);}};
    root.replaceChildren(bar,note,grid,apply);const morph=morphSearch(bar,search,cat,type,date,render);
    const uploadView=drop(grid,files=>receive(files));
    // Folder navigation uses the same live filters and asset cards as the picker.
    let folderRefresh=()=>{};
    if(!callback){
      const folders=el('div',undefined,'asset-folders'),section=el('section',undefined,'folder-browser');
      section.hidden=true;
      const modal=el('dialog',undefined,'folder-overlay'),header=el('div',undefined,'folder-overlay-header'),title=el('h2','素材'),close=el('button','关闭','secondary');
      title.id='folder-overlay-title';modal.setAttribute('aria-labelledby',title.id);close.type='button';header.append(title,close);modal.append(header);root.replaceChildren(folders,section,modal);section.append(bar,note,uploadView,grid,apply);
      let trigger=null;
      const restore=()=>{modal.querySelectorAll('video,audio').forEach(m=>m.pause());section.append(bar,note,uploadView,grid,apply);[...folders.children].find(b=>b.dataset.folder===trigger?.dataset.folder)?.focus();};
      close.onclick=()=>modal.close();modal.addEventListener('close',restore);
      const viewHost=root.closest('.view');
      if(viewHost){const visibilityObserver=new MutationObserver(()=>{if(!modal.isConnected){visibilityObserver.disconnect();return;}if(viewHost.hidden&&modal.open)modal.close();});visibilityObserver.observe(viewHost,{attributes:true,attributeFilter:['hidden']});}
      modal.addEventListener('click',e=>{if(e.target===modal){const r=modal.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)modal.close();}});
      const groups=[['全部素材','',''],['人物素材','person',''],['产品素材','product',''],['场景素材','scene',''],['视频素材','','video'],['音频素材','','audio'],['其他素材','other',''],['待归类','unclassified','']];
      folderRefresh=()=>{folders.replaceChildren();for(const [name,category,mime]of groups){
        const items=assets.filter(a=>(!category||effectiveCategory(a)===category)&&(!mime||a.mime.startsWith(mime+'/')));
        const button=el('button',undefined,'asset-folder');button.type='button';button.dataset.folder=name;button.setAttribute('aria-label',`${name}，${items.length} 个素材`);button.setAttribute('aria-haspopup','dialog');
        const art=el('span',undefined,'folder-art'),back=el('span',undefined,'folder-back'),fan=el('span',undefined,'folder-fan'),front=el('span',undefined,'folder-front');art.setAttribute('aria-hidden','true');
        items.slice(0,5).forEach((a,i)=>{const sheet=el('span',undefined,'folder-sheet');sheet.style.setProperty('--offset',String(i-(Math.min(items.length,5)-1)/2));sheet.style.setProperty('--order',String(i));if(a.mime.startsWith('image/')){const img=el('img');img.src='/api/assets/'+a.id;img.alt='';img.loading='lazy';img.decoding='async';sheet.append(img);}else sheet.append(el('span',a.mime.startsWith('audio/')?'AUDIO':'VIDEO','folder-filetype'));fan.append(sheet);});
        if(!items.length)front.append(el('span','暂无素材','folder-empty'));
        art.append(back,fan,front);button.append(art,el('strong',name),el('span',`${items.length} 个素材`,'folder-count'));
        button.onclick=()=>{trigger=button;cat.value=category;type.value=mime;search.value='';date.value='all';render();title.textContent=name;modal.append(bar,note,uploadView,grid,apply);modal.showModal();close.focus();};folders.append(button);
      }};
    }
    async function receive(files){note.textContent='正在上传素材…';await upload(files);if(stamp!==generation||epoch!==sessionEpoch)return;assets=await api('/workspace/materials');render();note.textContent='素材已保存，可分类或选择复用。';}
    function render(){
      morph.sync();
      folderRefresh();
      grid.replaceChildren();
      if(type.value==='generated'){chosen.clear();
        const ready=tasks.filter(t=>t.state==='ready'&&(!search.value||t.prompt.includes(search.value))&&(date.value!=='today'||new Date(t.created*1000).toDateString()===new Date().toDateString()));
        for(const t of ready){const card=el('article',undefined,'material-card'),video=el('video');video.src='/api/tasks/'+t.id+'/video';video.controls=true;video.preload='metadata';const edit=el('button','加入剪辑'),relay=el('button','接力生成');edit.onclick=()=>window.hubWorkspace.add(t.id).catch(e=>toast(e.message,true));relay.onclick=()=>{dialog?.close();window.hubWorkspace.openRelay(t).catch(e=>toast(e.message,true));};card.append(video,el('strong',t.prompt.slice(0,70)),edit,relay);grid.append(card);}
        if(!ready.length)grid.append(el('p','暂无匹配的生成成片','fine'));apply.disabled=true;return;
      }
      const list=assets.filter(a=>(!search.value||a.name.toLowerCase().includes(search.value.toLowerCase()))&&(!cat.value||effectiveCategory(a)===cat.value)&&(!type.value||a.mime.startsWith(type.value+'/'))&&(date.value!=='today'||new Date(a.created*1000).toDateString()===new Date().toDateString()));
      if(!list.length)grid.append(el('p','暂无匹配素材，可将文件拖到这里上传。','empty'));
      for(const a of list){const card=el('article',undefined,'material-card'),pick=el('button',chosen.has(a.id)?'已选择':'选择参考','material-select');pick.type='button';pick.setAttribute('aria-pressed',String(chosen.has(a.id)));pick.onclick=()=>{if(chosen.has(a.id))chosen.delete(a.id);else{if(initial.maxSelect===1)chosen.clear();chosen.add(a.id);}render();};card.append(preview(a),el('strong',a.name),pick);card.append(classificationControls(a,render));
        if(!callback){const details=el('details'),summary=el('summary','名称与分类'),name=el('input'),select=el('select'),save=el('button','保存');name.value=a.name;name.maxLength=200;name.setAttribute('aria-label','素材名称');select.setAttribute('aria-label','素材分类');for(const [v,t]of categories.slice(1))select.append(new Option(t,v));select.value=a.category||'other';save.onclick=async()=>{save.disabled=true;try{await api('/workspace/materials/'+a.id,{name:name.value,category:select.value});a.name=name.value.trim();a.category=select.value;a.classification_status='manual';a.classification_error='';render();}catch(e){toast(e.message,true);}finally{save.disabled=false;}};details.append(summary,name,select,save);card.append(details);}grid.append(card);
      }apply.disabled=!chosen.size;apply.textContent=(callback?'添加所选参考':'所选素材用于普通生成')+(chosen.size?' · '+chosen.size:'');
    }
    search.oninput=()=>{morph.sync();render();};cat.onchange=render;type.onchange=render;date.onchange=render;render();
    let checking=false;const timer=setInterval(async()=>{if(!root.isConnected||stamp!==generation||epoch!==sessionEpoch){clearInterval(timer);return;}if(checking||document.hidden||root.closest('.view')?.hidden||!assets.some(a=>['waiting_model','queued','running','retry_wait'].includes(a.classification_status)))return;checking=true;try{const fresh=await api('/workspace/materials');if(stamp!==generation||epoch!==sessionEpoch||!root.isConnected)return;if(JSON.stringify(fresh)!==JSON.stringify(assets)){assets=fresh;render();}}catch{}finally{checking=false;}},3000);
  }
  async function folderPicker(callback,options={}){
    dialog?.remove();const modal=el('dialog',undefined,'reference-library-dialog');dialog=modal;
    const header=el('header'),title=el('h2','素材库'),back=el('button','← 返回分类'),search=el('input'),body=el('div',undefined,'reference-library-body'),footer=el('footer'),count=el('span','未选择素材'),cancel=el('button','取消'),confirm=el('button','确认选择','primary');
    back.type=cancel.type=confirm.type='button';search.type='search';search.placeholder='搜索当前分类素材';search.setAttribute('aria-label','搜索当前分类素材');back.hidden=search.hidden=true;confirm.disabled=true;
    header.append(back,title,search);footer.append(count,cancel,confirm);modal.append(header,body,footer);modal.setAttribute('aria-label','从素材库选择参考素材');document.body.append(modal);modal.showModal();
    const selected=new Map(),excluded=new Set(options.excludeIds||[]),epoch=sessionEpoch;let assets=[],active=null,observer=null,pending=false,checking=false,pickerPage=0;
     const timer=setInterval(async()=>{if(!modal.isConnected||epoch!==sessionEpoch){clearInterval(timer);return;}if(checking||pending||document.hidden||!assets.some(a=>['waiting_model','queued','running','retry_wait'].includes(a.classification_status)))return;checking=true;try{const fresh=await api('/workspace/materials');if(!modal.isConnected||epoch!==sessionEpoch)return;if(JSON.stringify(fresh)!==JSON.stringify(assets)){assets=fresh;const byId=new Map(assets.map(a=>[a.id,a]));for(const [id]of selected){const a=byId.get(id);if(a)selected.set(id,a);}if(active){body.querySelectorAll('[data-asset-id]').forEach(card=>{const a=byId.get(card.dataset.assetId);if(!a)return;const signature=JSON.stringify([a.classification_status,a.classification_error]);if(card.dataset.classification!==signature){card.dataset.classification=signature;card.lastElementChild.replaceWith(classificationControls(a,showItems));}});}else folders();}}catch{}finally{checking=false;}},3000);
     modal.addEventListener('close',()=>clearInterval(timer),{once:true});
    const groups=[['人物素材','person',''],['产品素材','product',''],['场景素材','scene',''],['视频素材','','video'],['音频素材','','audio'],['其他素材','other',''],['待归类','unclassified','']];
    const matches=(a,g)=>(!g[1]||effectiveCategory(a)===g[1])&&(!g[2]||a.mime.startsWith(g[2]+'/'))&&(!options.imageOnly||a.mime.startsWith('image/'));
    function sync(){count.textContent=`已选择 ${selected.size} 项`;confirm.disabled=pending||!selected.size;}
    cancel.onclick=()=>{if(!pending)modal.close();};modal.addEventListener('cancel',e=>{if(pending)e.preventDefault();});modal.addEventListener('close',()=>{observer?.disconnect();modal.querySelectorAll('video,audio').forEach(m=>m.pause());modal.remove();});
    confirm.onclick=async()=>{if(pending||!selected.size)return;pending=true;sync();cancel.disabled=true;try{await callback([...selected.values()]);modal.close();}catch(e){toast(e.message,true);}finally{pending=false;cancel.disabled=false;sync();}};
    function folders(){observer?.disconnect();active=null;body.replaceChildren();body.scrollTop=0;title.textContent='素材库';back.hidden=search.hidden=true;const grid=el('div',undefined,'reference-library-folders');
      for(const g of groups){const items=assets.filter(a=>matches(a,g)),b=el('button',undefined,'reference-library-folder'),art=el('span',undefined,'folder-art'),rear=el('span',undefined,'folder-back'),fan=el('span',undefined,'folder-fan'),front=el('span',undefined,'folder-front');b.type='button';b.disabled=!!options.imageOnly&&['video','audio'].includes(g[2]);
        items.filter(a=>a.mime.startsWith('image/')).slice(0,1).forEach((a,i)=>{const sheet=el('span',undefined,'folder-sheet'),img=el('img');sheet.style.setProperty('--offset',String(i-1));sheet.style.setProperty('--order',String(i));img.src='/api/assets/'+a.id;img.alt='';img.loading='lazy';img.decoding='async';sheet.append(img);fan.append(sheet);});art.append(rear,fan,front);b.append(art,el('strong',g[0]),el('small',b.disabled?'首尾帧仅支持图片':`${items.length} 个素材`));b.onclick=()=>{active=g;pickerPage=0;search.value='';showItems();};grid.append(b);}body.append(grid);}
    function showItems(){observer?.disconnect();body.querySelectorAll('video,audio').forEach(m=>{m.pause();m.removeAttribute('src');m.load();});body.replaceChildren();body.scrollTop=0;title.textContent=active[0];back.hidden=search.hidden=false;
      const filtered=assets.filter(a=>matches(a,active)&&a.name.toLowerCase().includes(search.value.trim().toLowerCase())),pages=Math.max(1,Math.ceil(filtered.length/36));pickerPage=Math.min(pickerPage,pages-1);const list=filtered.slice(pickerPage*36,(pickerPage+1)*36),grid=el('div',undefined,'reference-masonry'),tail=el('button','加载更多','reference-masonry-tail');tail.type='button';let shown=0;body.append(grid,tail);
      function append(){const next=list.slice(shown,shown+12);shown+=next.length;for(const a of next){const card=el('article',undefined,'reference-masonry-card'),media=preview(a,true),pick=el('button'),name=el('strong',a.name);card.dataset.assetId=a.id;card.dataset.classification=JSON.stringify([a.classification_status,a.classification_error]);pick.type='button';if(a.mime.startsWith('image/'))media.loading='lazy';
          function mark(){const on=selected.has(a.id);card.classList.toggle('is-selected',on);pick.textContent=excluded.has(a.id)?'已添加':on?'✓ 已选中':'选择素材';pick.disabled=excluded.has(a.id);pick.setAttribute('aria-pressed',String(on));}
          pick.onclick=()=>{if(selected.has(a.id))selected.delete(a.id);else{if(options.maxSelect===1){selected.clear();grid.querySelectorAll('.is-selected').forEach(n=>{n.classList.remove('is-selected');const b=n.querySelector('button');b.textContent='选择素材';b.setAttribute('aria-pressed','false');});}selected.set(a.id,a);}mark();sync();};if(a.mime.startsWith('image/'))media.onclick=()=>pick.click();mark();card.append(media,name,pick,classificationControls(a,showItems));grid.append(card);}
        tail.hidden=shown>=list.length;if(!list.length)grid.append(el('p','该分类暂无匹配素材。','empty'));}
      tail.onclick=append;append();observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&shown<list.length)append();},{root:body,rootMargin:'240px'});observer.observe(tail);
      if(pages>1){const pager=el('div',undefined,'reference-masonry-tail'),prev=el('button','上一页','secondary'),next=el('button','下一页','secondary');prev.type=next.type='button';prev.disabled=pickerPage===0;next.disabled=pickerPage===pages-1;prev.onclick=()=>{pickerPage--;showItems();};next.onclick=()=>{pickerPage++;showItems();};pager.append(prev,el('span',` 第 ${pickerPage+1} / ${pages} 页 · ${filtered.length} 个 `),next);body.append(pager);}
    }
    let searchTimer;back.onclick=()=>{clearTimeout(searchTimer);folders();};search.oninput=()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{if(modal.isConnected&&active){pickerPage=0;showItems();}},180);};modal.addEventListener('close',()=>clearTimeout(searchTimer),{once:true});body.textContent='正在读取素材库…';
    try{assets=await api('/workspace/materials');if(!modal.isConnected||epoch!==sessionEpoch)return;folders();}catch(e){body.textContent=e.message;}
  }
  async function openPicker(callback,options={}){
    dialog?.remove();dialog=el('dialog',undefined,'material-picker');const close=el('button','关闭'),content=el('div');close.onclick=()=>dialog.close();dialog.append(el('h2',options.title||'选择参考素材'),close,content);document.body.append(dialog);dialog.showModal();try{await mount(content,callback,options);}catch(e){content.textContent=e.message;}
  }
  async function useInComposer(c,assets,role='reference'){
    if(c.mode==='frames'&&role==='reference')role=c.assets.some(a=>a.role==='first')?'last':'first';
    if(c.mode==='frames'&&(assets.length!==1||!assets[0].mime.startsWith('image/')))throw Error('首尾帧请每次选择一张图片');
    const next=c.assets.filter(a=>role==='reference'||a.role!==role),unique=assets.filter(a=>!next.some(x=>x.id===a.id));
    const assetIssue=studioReferenceIssue(c,[...next,...unique]);
    if(assetIssue)throw Error(assetIssue);
    for(const a of unique){const item={...a,role};if(window.hubTakeToken)item.token=window.hubTakeToken(c,a.mime,next);next.push(item);}c.assets=next;changed(c);renderCompositions();
  }
  // 素材卡与预览台显示同一段素材，属于同一次预览，不能互相把对方停掉。
  const previewPair=m=>m.id==='edit-source-preview'||!!m.closest?.('#edit-library-list');
  document.addEventListener('play',e=>{if(!e.target.matches('video,audio')||e.target.id==='edit-player'||e.target.id==='edit-audio'||e.target.dataset.timelineAudio)return;const pair=previewPair(e.target);if(!pair)window.hubEditor?.pause();document.querySelectorAll('video,audio').forEach(m=>{if(m!==e.target&&!(pair&&previewPair(m)))m.pause();});},true);
  return {upload,drop,pickerButton,preview,openPicker,folderPicker,useInComposer,effectiveCategory,open:()=>window.hubMaterialManager.open(document.getElementById('materials-content')),reset:()=>{generation++;window.hubMaterialManager?.reset();dialog?.close();dialog?.remove();dialog=null;document.getElementById('materials-content').replaceChildren();}};
})();

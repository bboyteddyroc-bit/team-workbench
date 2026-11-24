'use strict';
let compositions=[], composerEpoch=0, composerLoaded=false, pendingUploads=0, submissionPending=false;
const compositionOptionsOpen=new Set();
function blankComposition(){return {id:crypto.randomUUID(),prompt:'',mode:'omni',model:'auto',duration:5,count:1,assets:[],nextImage:1,request_key:crypto.randomUUID()};}
function referencePattern(token){return new RegExp('@'+token.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')+'(?![0-9])','g');}
// Prompt references cover every reference kind: 图片/视频/音频 + running number, unique per composition.
function compositionToken(c,mime,extra=[]){
  const kind=String(mime||'').startsWith('video/')?'视频':String(mime||'').startsWith('audio/')?'音频':'图片',key=kind==='视频'?'nextVideo':kind==='音频'?'nextAudio':'nextImage';
  const used=new Set([...(c.assets||[]),...extra].map(a=>a&&a.token).filter(Boolean));let n=Number(c[key]||1);while(used.has(kind+n))n++;c[key]=n+1;return kind+n;
}
window.hubTakeToken=compositionToken;
function resetComposer(){composerEpoch++;classificationPoll=null;compositions=[];composerLoaded=false;pendingUploads=0;submissionPending=false;document.querySelector('#composition-list').replaceChildren();}
function changed(item){item.request_key=crypto.randomUUID();requestKey=crypto.randomUUID();updateCompositionSummary();window.hubAutoSave?.schedule();}
async function restoreComposer(){
  if(composerLoaded)return;const epoch=composerEpoch,session=sessionEpoch;
  const saved=await api('/compositions');if(epoch!==composerEpoch||session!==sessionEpoch||!me)return;
  let local=null;try{local=JSON.parse(localStorage.getItem('hub-draft-pending:'+me.id)||'null');}catch{}compositions=Array.isArray(local?.items)&&local.items.length?local.items:(saved.items.length?saved.items:[blankComposition()]);composerLoaded=true;renderCompositions();window.dispatchEvent(new Event('hub-composer-restored'));if(local)window.hubAutoSave.schedule();
}
function unavailableReason(c,libtv){
  const assets=c.assets||[],count=Number(c.count),duration=Number(c.duration),roles=new Set(assets.map(a=>a.role));
  if(!c.prompt.trim())return '请填写提示词';
  if(!Number.isInteger(count)||count<1||count>10)return '生成条数须为 1 至 10 条';
  if(!Number.isInteger(duration)||duration<4||duration>15)return '时长须为 4 至 15 秒';
  if(assets.length>12||new Set(assets.map(a=>a.id)).size!==assets.length)return '每组最多 12 个素材，不能重复';
  if(c.mode==='frames'){
    if(!libtv&&!['auto','5000005'].includes(c.model))return '首尾帧请选择 Seedance 2.0';
    if(!roles.has('first')||roles.size!==assets.length||assets.some(a=>!a.mime.startsWith('image/')||!['first','last'].includes(a.role)))return '请添加一张首帧图片，可选一张尾帧';
  }
  if(libtv)return '';
  if(c.mode!=='frames'&&assets.some(a=>a.role&&a.role!=='reference'))return '全能模式请使用参考素材，不使用首尾帧';
  const images=assets.filter(a=>a.mime.startsWith('image/')).length,videos=assets.filter(a=>a.mime.startsWith('video/')).length,audios=assets.filter(a=>a.mime.startsWith('audio/')).length;
  if(assets.length){
    if(!features.references)return 'TikTok 参考素材上传尚未验证';
    if(images>9||videos>3||audios>3)return '最多 9 张图、3 条视频、3 条音频';
    if(!images&&!videos)return '声音参考需要搭配图片或视频';
    const tokens=new Set(assets.map(a=>a.token));
    if([...c.prompt.matchAll(/@(图片[0-9]+|视频[0-9]+|音频[0-9]+)/g)].some(m=>!tokens.has(m[1])))return '提示词引用了已移除的素材，请重新选择';
  }else if(['mini','fast'].includes(c.model))return 'Mini / Fast 需要至少一张参考图或一条视频';
  return '';
}
function setStudioText(node,text){if(node&&node.textContent!==text)node.textContent=text;}
function studioChannel(){
  const id=$('#generation-channel')?.value,connected=accounts.filter(a=>a.scope==='shared'&&a.enabled&&a.status==='connected').length;
  if(id==='libtv'){
    const profile=window.hubLibTVProfiles?.choice();
    return {id,profile:profile?.id,label:profile?.id?'LibTV · '+profile.name:'LibTV',reason:profile?.id?'':profile?.reason||'正在读取 LibTV 账号…'};
  }
  if(id==='tiktok')return {id,label:'TikTok · 公司账号池',reason:connected?'':'公司账号池没有可用连接，请联系管理员',available:`${connected} 个可用连接，系统按队列分配`};
  return {id:'',label:'尚未选择渠道',reason:'请在「生成渠道」选择 TikTok 或 LibTV'};
}
function submissionCheck(items,route=studioChannel()){
  if(submissionPending)return '正在提交，请稍候';
  if(!items.length)return '请先新建创作窗口';
  if(route.reason)return route.reason;
  if(pendingUploads)return '素材上传中，请稍候';
  if(route.id==='libtv'){
    if(items.length!==1)return 'LibTV 请在单个窗口内提交';
    if(window.hubLibTV?.submitting(items[0].id))return '此窗口的 LibTV 任务尚未返回，请查看任务记录';
  }
  for(const c of items){const reason=unavailableReason(c,route.id==='libtv');if(reason)return items.length>1?`创作 ${compositions.indexOf(c)+1}：${reason}`:reason;}
  return '';
}
function updateCompositionSummary(){
  const route=studioChannel(),total=compositions.reduce((n,c)=>n+Number(c.count||1),0),reason=submissionCheck(compositions,route);
  setStudioText($('#composition-summary'),`${route.label} · ${compositions.length} 组，共 ${total} 条。${reason||route.available||'提交到已选账号'}`);
  const submit=$('#submit-task');setStudioText(submit,`提交 ${total} 条视频`);submit.disabled=!!reason;
  const byId=new Map(compositions.map(c=>[c.id,c]));
  for(const card of $('#composition-list').children){
    const c=byId.get(card.dataset.compositionId),button=card.querySelector('.single-generate');if(!c||!button)continue;
    const issue=submissionCheck([c],route);
    setStudioText(card.querySelector('.submit-route'),`${route.label} · ${c.count||1} 条`);
    setStudioText(card.querySelector('.submit-condition'),issue||route.available||'按当前模型和分辨率提交');
    setStudioText(button,route.id?`提交到 ${route.id==='libtv'?'LibTV':'TikTok'}`:'生成视频');
    button.disabled=!!issue;card.querySelector('.submit-check').classList.toggle('is-blocked',!!issue);
  }
}
function selectControl(labelText,options,value,onchange){const label=el('label',labelText),select=el('select');for(const [v,t] of options){const option=el('option',t);option.value=v;select.append(option);}select.value=String(value);select.onchange=()=>onchange(select.value);label.append(select);return label;}
function renderCompositions(){const list=$('#composition-list');list.replaceChildren();compositions.forEach((c,index)=>list.append(compositionNode(c,index)));updateCompositionSummary();window.hubAutoSave?.schedule();}
function composerReferences(c,dropTarget){
  const area=el('section',undefined,'material-area unified-references'),actions=el('div',undefined,'reference-actions');
  area.append(actions);
  const upload=window.hubMaterials.drop(area,files=>{if(c.mode==='frames'&&(files.length!==1||!files[0].type.startsWith('image/')))throw Error('首尾帧请每次选择一张图片');return addAssets(c,files,c.mode==='omni'?'reference':c.assets.some(a=>a.role==='first')?'last':'first');},{dropTarget,multiple:c.mode!=='frames',accept:c.mode==='frames'?'image/png,image/jpeg,image/webp':undefined});
  actions.append(upload);const uploadButton=upload.querySelector('.attachment-drop');uploadButton.title='上传本地文件';uploadButton.setAttribute('aria-label','上传本地文件');
  const picker=window.hubMaterials.pickerButton(()=>{});picker.title='从素材库选择';picker.setAttribute('aria-label','从素材库选择');picker.onclick=()=>window.hubMaterials.folderPicker(items=>window.hubMaterials.useInComposer(c,items),{imageOnly:c.mode==='frames',maxSelect:c.mode==='frames'?1:undefined,excludeIds:c.assets.map(a=>a.id)});actions.append(picker);
  const gallery=el('div',undefined,'reference-selected-gallery');
  for(const asset of c.assets){const card=el('article',undefined,'reference-selected-card'),remove=el('button','×','reference-remove');const roleLabel=asset.role==='first'?'首帧':asset.role==='last'?'尾帧':'参考素材';const classification=asset.mime.startsWith('image/')?(({waiting_model:'图片待识别',queued:'分类排队中',running:'正在识别',failed:'分类失败 · 可到素材库重试',classified:({person:'人物',product:'产品',scene:'场景',other:'其他'})[asset.category]||'已分类',manual:'已手动分类'})[asset.classification_status]||''):'';const media=asset.mime.startsWith('audio/')?el('span','♪','reference-thumb-audio'):window.hubMaterials.preview(asset);card.title=[asset.name,roleLabel,asset.token?'@'+asset.token:'',classification].filter(Boolean).join(' · ');remove.type='button';remove.setAttribute('aria-label','移除 '+asset.name);remove.onclick=()=>{c.assets=c.assets.filter(a=>a.id!==asset.id);if(asset.token)c.prompt=c.prompt.replace(referencePattern(asset.token),'');changed(c);renderCompositions();};card.append(media,remove);if(asset.role==='first'||asset.role==='last')card.append(el('span',roleLabel,'reference-thumb-role'));gallery.append(card);}
  if(!c.assets.length)gallery.append(el('p','上传本地文件或从素材库选择，已选素材将在这里展示。','reference-empty'));
  area.append(gallery);return area;
}
// Relay references live inside the window: pick any frame, extract the original audio or split vocals locally.
function relaySourcePanel(c){
  const duration=Number(c.relay_duration||c.duration||5),frame=c.assets.find(a=>a.role==='reference'&&a.token==='图片1'),audio=c.assets.find(a=>a.kind==='audio'),vocal=c.assets.find(a=>a.kind==='vocal');
  const box=el('div',undefined,'relay-source');box.dataset.relay='1';
  const head=el('div',undefined,'relay-source-head'),thumb=el('img',undefined,'relay-source-thumb');
  thumb.alt='当前参考帧';thumb.loading='lazy';if(frame)thumb.src='/api/assets/'+frame.id;
  const meta=el('div');meta.append(el('strong','参考来源'),el('small',`${c.relay_label||'接力来源'} · ${duration.toFixed(1)} 秒`,'relay-source-meta'));
  head.append(thumb,meta);box.append(head);
  const current=Math.min(Math.max(0,Number(c.continuation?.frame_time??Math.max(0,duration-.2))),Math.max(0,duration-.04));
  const stamp=el('output',current.toFixed(2)+' 秒','relay-source-time');
  const slider=el('input');slider.type='range';slider.min=0;slider.max=Math.max(.04,duration-.04).toFixed(4);slider.step=.04;slider.value=String(current);
  slider.className='relay-source-slider';slider.setAttribute('aria-label','参考帧位置');slider.dataset.relayAction='frame';
  slider.oninput=()=>{stamp.textContent=Number(slider.value).toFixed(2)+' 秒';};
  const status=el('small',frame?'拖动滑块可改用其他画面；原声与人声会随窗口一起提交':'请先选择参考帧','relay-source-status');status.setAttribute('role','status');
  const actions=el('div',undefined,'relay-source-actions');
  const frameBtn=el('button','提取此帧','secondary');frameBtn.type='button';frameBtn.title='按滑块位置提取参考帧';
  const audioBtn=el('button',audio?'重新提取原声':'提取原声','secondary');audioBtn.type='button';audioBtn.dataset.relayAction='audio';audioBtn.title='提取来源视频原声，含人声、音乐和环境声';
  const vocalBtn=el('button',vocal?'重新分离人声':'分离人声','secondary');vocalBtn.type='button';vocalBtn.dataset.relayAction='vocal';vocalBtn.title='在本机用 Demucs 分离人声，文件不出本机';
  actions.append(frameBtn,audioBtn,vocalBtn);
  const row=el('label',undefined,'relay-source-frame');row.append(el('span','参考帧'),slider,stamp);
  box.append(row,actions,status);
  const run=async(btn,busyText,work)=>{
    btn.disabled=true;const label=btn.textContent;btn.textContent=busyText;
    try{await work();}
    catch(err){btn.disabled=false;btn.textContent=label;status.textContent=err.message||String(err);toast(err.message||String(err),true);}
  };
  const applyFrame=async time=>{
    const asset=await api('/media/extract',{source_id:c.relay_task,kind:'frame',time});
    c.assets=c.assets.filter(a=>!(a.role==='reference'&&a.token==='图片1'));
    c.assets.unshift({...asset,role:'reference',token:'图片1'});
    c.continuation={...(c.continuation||{}),source_id:c.relay_task,frame_id:asset.id,frame_time:Number(asset.start??time),append_timeline:false};
    changed(c);renderCompositions();toast('参考帧已更新：'+asset.name);
  };
  frameBtn.onclick=()=>run(frameBtn,'提取中…',()=>applyFrame(Number(slider.value)));
  slider.onchange=async()=>{
    slider.disabled=true;status.textContent='正在提取所选画面…';
    try{await applyFrame(Number(slider.value));}
    catch(err){status.textContent=err.message||String(err);toast(err.message||String(err),true);}
    finally{slider.disabled=false;}
  };
  audioBtn.onclick=()=>run(audioBtn,'提取中…',async()=>{
    const asset=await api('/media/extract',{source_id:c.relay_task,kind:'audio',start:0,end:Math.min(15,Math.max(2,duration))});
    c.assets=c.assets.filter(a=>a.kind!=='audio');
    c.assets.push({...asset,role:'reference'});
    c.continuation={...(c.continuation||{}),source_id:c.relay_task,audio_id:asset.id,append_timeline:false};
    changed(c);renderCompositions();toast('已加入原声参考：'+asset.name);
  });
  vocalBtn.onclick=()=>run(vocalBtn,'分离中…',async()=>{
    const asset=await api('/media/vocals',{source_id:c.relay_task,start:0,end:Math.min(15,Math.max(2,Math.round(duration)||5))});
    c.assets=c.assets.filter(a=>a.kind!=='vocal'&&a.id!==asset.id);
    c.assets.push({...asset,role:'reference'});
    c.continuation={...(c.continuation||{}),source_id:c.relay_task,audio_id:asset.id,append_timeline:false};
    changed(c);renderCompositions();toast('已分离人声并加入声音参考：'+asset.name);
  });
  return box;
}
function taskCompositionId(t){
  if(t.libtv)return t.composition_id||'';
  if(t.owner_name&&t.owner_name!==me?.username)return '';
  try{return JSON.parse(t.config||'{}')?.id||'';}catch{return '';}
}
function taskPreviewKey(t){return (t.libtv?'libtv:':'task:')+t.id;}
function originalWindowAction(task){
  const id=taskCompositionId(task),button=el('button','回到原窗口');button.type='button';
  button.dataset.compositionTarget=id;
  button.onclick=()=>window.hubStudioHistory?.locate(id,taskPreviewKey(task));
  return button;
}
function compositionTaskGroups(c){return tasks.filter(t=>taskCompositionId(t)===c.id);}
// LibTV results are stored as jobs outside the task queue; they carry the window id so results return to the card.
function compositionLibTVJobs(c){
  const rows=window.hubLibTV?.jobs?.()||[];
  return rows.filter(j=>j&&j.composition_id===c.id);
}
const waitStates=new Set(['queued','submitting','running','importing','waiting']);
function previewItems(c){
  const items=[];
  for(const t of compositionTaskGroups(c))items.push({key:'task:'+t.id,created:Number(t.created||0),state:t.state,error:t.error,detail:t.queue_reason||'',videoUrl:t.state==='ready'?'/api/tasks/'+encodeURIComponent(t.id)+'/video':null,relay:t,libtv:null});
  for(const j of compositionLibTVJobs(c))items.push({key:'libtv:'+j.id,created:Number(j.created||0),state:j.feedback_state==='waiting'?'waiting':j.state,error:j.error,detail:j.stage||'',videoUrl:j.state==='ready'&&j.asset_id?'/api/assets/'+encodeURIComponent(j.asset_id):null,relay:null,libtv:j});
  return items.sort((a,b)=>b.created-a.created);
}
function previewWaiting(item){
  const box=el('div',undefined,'gen-wait');box.dataset.state=item.state;
  const ring=el('span',undefined,'gen-wait-ring'),bars=el('div',undefined,'gen-wait-bars');
  for(let i=0;i<5;i++)bars.append(el('span'));
  const detail=String(item.detail||'').trim(),prefix=detail&&!/^libtv/i.test(detail)?'LibTV · ':'';
  const title=item.libtv&&detail?`${prefix}${detail}`:(labels[item.state]||'正在生成视频');
  const synced=item.libtv?.updated||item.relay?.updated;
  const timing='已等待 '+Math.max(0,Math.floor((Date.now()/1000-item.created)/60))+' 分钟'+(synced?' · 最近更新 '+new Date(synced*1000).toLocaleTimeString('zh-CN'):'');
  const hint=item.libtv?'完成后自动保存并回到这个窗口':'后台排队或生成中，中台持续同步；无需停留在本页面';
  box.append(ring,bars,el('strong',title),el('small',timing),el('small',hint));return box;
}
function resultSignature(item){
  if(item.videoUrl)return JSON.stringify(['video',item.videoUrl]);
  const waiting=waitStates.has(item.state);
  return JSON.stringify([item.state,(item.libtv||item.relay)?.feedback_state,item.error,item.detail,waiting?Math.floor(Date.now()/60000):0,waiting?(item.libtv||item.relay)?.updated:0]);
}
function resultCard(item,c){
    const box=el('div',undefined,'window-result');box.dataset.state=item.state;box.dataset.resultKey=item.key;
    if(item.state==='ready'&&item.videoUrl){
      const video=el('video');video.controls=true;video.dataset.studioSrc=item.videoUrl;video.preload='none';video.width=640;video.height=360;video.setAttribute('aria-label',item.libtv?'LibTV 生成的视频':'生成的视频');box.append(video);
      const source=item.libtv?{...item.libtv,libtv:true}:item.relay;
      const actions=el('div',undefined,'window-result-actions');
      actions.setAttribute('role','group');actions.setAttribute('aria-label','生成结果操作');
      actions.append(window.hubRelay.button(source,c),window.hubRelay.editButton(source));box.append(actions);
    }else if(waitStates.has(item.state)){box.append(previewWaiting(item));}
    else{
      const problem=attentionStates.includes(item.state),feedbackState=(item.libtv||item.relay)?.feedback_state||item.state;
      box.append(el('strong',problem&&window.hubTaskFeedback?window.hubTaskFeedback.state(feedbackState):labels[item.state]||item.state||'待处理'));
      if(problem){
        box.append(el('small',feedbackState==='unknown'?'请先核对原平台记录，不要重复提交。':'请在任务记录中查看具体原因。'));
        const more=el('button','打开任务记录','text-button');more.type='button';more.onclick=e=>{e.stopPropagation();window.hubStudioHistory?.open('failed');};box.append(more);
      }else box.append(el('small',item.error||item.detail||'状态将自动更新'));
    }
    return box;
}
const previewStates=new WeakMap();
function previewState(preview){
  if(previewStates.has(preview))return previewStates.get(preview);
  const results=el('div',undefined,'window-results'),controls=el('div',undefined,'depth-controls'),prev=el('button','‹'),next=el('button','›'),dots=el('div',undefined,'depth-dots');
  const empty=el('div',undefined,'composition-preview-empty');empty.append(el('span','▶'),el('strong','生成结果将在这里显示'),el('small','填写提示词后开始创作'));
  const state={results,controls,dots,empty,entries:new Map(),order:[],active:null};let startX=null;
  state.select=key=>{if(!state.entries.has(key))return false;state.active=key;layoutPreview(state);return true;};
  const shift=step=>{const {order,active}=state;if(order.length>1)state.select(order[(order.indexOf(active)+step+order.length)%order.length]);};
  prev.type=next.type='button';prev.setAttribute('aria-label','上一个视频');next.setAttribute('aria-label','下一个视频');
  prev.onclick=e=>{e.stopPropagation();shift(-1);};next.onclick=e=>{e.stopPropagation();shift(1);};
  results.addEventListener('click',e=>{const key=e.target.closest('.window-result')?.dataset.resultKey;if(key&&key!==state.active){e.preventDefault();e.stopPropagation();state.select(key);}},true);
  results.addEventListener('pointerdown',e=>{startX=e.target.closest('button,video')?null:e.clientX;});
  results.addEventListener('pointerup',e=>{if(startX!==null&&Math.abs(e.clientX-startX)>35)shift(e.clientX<startX?1:-1);startX=null;});
  results.addEventListener('pointercancel',()=>{startX=null;});
  controls.append(prev,dots,next);preview.append(empty,results,controls);previewStates.set(preview,state);return state;
}
function layoutPreview({results,controls,dots,empty,entries,order,active}){
  const carousel=order.length>1,index=order.indexOf(active);
  // Keep the media element attached even when the surrounding carousel gains a new result.
  results.hidden=!order.length;empty.hidden=!!order.length;controls.hidden=!carousel;
  results.classList.toggle('depth-carousel',carousel);
  order.forEach((key,i)=>{
    const card=entries.get(key).node,video=card.querySelector('video'),selected=key===active;
    let d=i-index;if(d>order.length/2)d-=order.length;if(d< -order.length/2)d+=order.length;const back=Math.abs(d);
    card.setAttribute('aria-hidden',String(!selected));
    card.style.transform=carousel?`translate(-50%,-50%) translateX(${d*56}px) translateZ(${-back*95}px) rotateY(${-d*15}deg)`:'';
    card.style.zIndex=carousel?String(100-back):'';card.style.opacity=carousel?(back>2?'0':String(Math.max(.3,1-back*.28))):'';
    card.style.filter=carousel?`brightness(${Math.max(.5,1-back*.16)}) blur(${back*1.2}px)`:'';
    card.style.pointerEvents=back>2?'none':'';
    if(!selected){if(video&&!video.paused)video.pause();}
    else if(video?.dataset.studioSrc){window.hubMediaLazy.watch(video,video.dataset.studioSrc);delete video.dataset.studioSrc;}
    dots.children[i]?.setAttribute('aria-current',String(selected));
  });
}
function renderCompositionPreview(c,preview,items=previewItems(c)){
  if($('#studio').hidden)return;
  const state=previewState(preview),order=items.map(i=>i.key),sigs=items.map(resultSignature),signature=JSON.stringify([order,sigs]);
  if(state.signature===signature)return;
  state.signature=signature;preview.classList.toggle('is-generating',items.some(i=>waitStates.has(i.state)));
  const keep=new Set(order),previous=state.entries.get(state.active),layoutChanged=order.length!==state.order.length||order.some((key,i)=>key!==state.order[i]);
  for(const [key,entry] of state.entries)if(!keep.has(key)){entry.node.querySelector('video')?.pause();entry.node.remove();state.entries.delete(key);}
  items.forEach((item,index)=>{
    const old=state.entries.get(item.key),sig=sigs[index];if(old?.sig===sig)return;
    const node=resultCard(item,c);if(old){old.node.querySelector('video')?.pause();old.node.replaceWith(node);}else state.results.append(node);
    state.entries.set(item.key,{node,sig,request:item.libtv?.request_key});
  });
  if(!keep.has(state.active))state.active=(previous?.request&&items.find(i=>i.libtv?.request_key===previous.request)?.key)||order[0]||null;
  if(layoutChanged){
    state.order=order;state.dots.replaceChildren(...(order.length>1?order.map((key,i)=>{const dot=el('button');dot.type='button';dot.setAttribute('aria-label',`查看第 ${i+1} 条视频`);dot.onclick=e=>{e.stopPropagation();state.select(key);};return dot;}):[]));
  }
  layoutPreview(state);
}
function refreshCompositionPreviews(){
  if($('#studio').hidden)return;
  const byId=new Map(compositions.map(c=>[c.id,c]));
  for(const node of $('#composition-list').children){const c=byId.get(node.dataset.compositionId),preview=node.querySelector('.simple-preview');if(c&&preview)renderCompositionPreview(c,preview);}
  window.hubMediaLazy?.sweep();
}
window.hubCompositionPreview={refresh:refreshCompositionPreviews,select:(card,key)=>previewStates.get(card.querySelector('.simple-preview'))?.select(key)};
window.addEventListener('hub-tasks',refreshCompositionPreviews);
function compositionNode(c,index){
  const node=el('section',undefined,'composition'),head=el('div',undefined,'composition-heading');node.dataset.compositionId=c.id;
  head.append(el('h3',`创作 ${index+1}`));if(c.relay_source){const from=compositions.findIndex(x=>x.id===c.relay_source);const badge=el('span',from>=0?`接力自 创作 ${from+1}`:(c.relay_label||'接力窗口'),'relay-badge');badge.title='继承来源视频尾帧作为参考；生成后自动接在来源右侧';head.append(badge);}if(compositions.length>1){const remove=el('button','移除','text-button');remove.type='button';remove.onclick=()=>{compositions=compositions.filter(x=>x!==c);requestKey=crypto.randomUUID();renderCompositions();};head.append(remove);}node.append(head);
  const preview=el('div',undefined,'simple-preview');preview.setAttribute('aria-live','polite');node.append(preview);renderCompositionPreview(c,preview);
  const options=el('details',undefined,'simple-options parameter-popover'),optionsTitle=el('summary',`参数 · ${c.mode==='frames'?'首尾帧':'全能'} · ${c.duration} 秒 · ${c.count} 条`);options.open=compositionOptionsOpen.has(c.id);const placeParameterPanel=()=>requestAnimationFrame(()=>{const panel=options.querySelector('.parameter-body');if(!panel)return;panel.style.maxHeight='';panel.classList.remove('flip-down');const rect=options.getBoundingClientRect(),box=document.querySelector('.canvas-viewport')?.getBoundingClientRect(),top=Math.max(box?box.top:0,0),bottom=Math.min(box?box.bottom:window.innerHeight,window.innerHeight),need=Math.min(panel.scrollHeight,420),above=rect.top-top-20,below=bottom-rect.bottom-20;if(above<300&&below>above)panel.classList.add('flip-down');const room=panel.classList.contains('flip-down')?below:above;panel.style.maxHeight=Math.max(200,Math.min(420,room))+'px';});options.reposition=placeParameterPanel;options.addEventListener('toggle',()=>{if(!options.isConnected)return;if(options.open){compositionOptionsOpen.add(c.id);placeParameterPanel();}else compositionOptionsOpen.delete(c.id);});options.append(optionsTitle);const parameterBody=el('div',undefined,'parameter-body');options.append(parameterBody);const refreshParameterSummary=()=>{optionsTitle.textContent=`参数 · ${c.mode==='frames'?'首尾帧':'全能'} · ${c.duration} 秒 · ${c.count} 条`;};
  const modes=el('div',undefined,'mode-switch');modes.setAttribute('role','group');modes.setAttribute('aria-label',`创作 ${index+1} 生成模式`);
  for(const [v,title] of [['omni','全能模式'],['frames','首尾帧模式']]){const b=el('button',undefined,c.mode===v?'selected':'');b.append(el('strong',title),el('small',v==='omni'?'文字、图片、视频和声音参考':'使用首帧与尾帧控制画面起止')); b.type='button';b.setAttribute('aria-pressed',String(c.mode===v));b.onclick=()=>{c.mode=v;changed(c);renderCompositions();};modes.append(b);}parameterBody.append(modes);
  const references=composerReferences(c,node);
  const promptLabel=el('label',`提示词 ${index+1}`),textarea=el('textarea');textarea.rows=5;textarea.required=true;textarea.value=c.prompt;textarea.placeholder='描述主体、动作、镜头和声音。输入 @ 引用已上传的图片、视频或声音。';textarea.setAttribute('aria-label',`第 ${index+1} 组提示词`);if(Number(c.promptHeight)>0)textarea.style.height=Math.round(Number(c.promptHeight))+'px';promptLabel.className='compact-prompt';promptLabel.append(textarea);node.append(promptLabel);
  const suggestions=el('div',undefined,'mention-menu');suggestions.hidden=true;suggestions.setAttribute('aria-label','选择参考素材');promptLabel.append(suggestions);
  const expand=el('span',undefined,'prompt-popover-host');promptLabel.append(expand);
  const chips=el('div',undefined,'reference-chips');node.append(chips);
  const mediaKind=mime=>String(mime||'').startsWith('video/')?'video':String(mime||'').startsWith('audio/')?'audio':'image';
  const kindGlyph=kind=>kind==='video'?'▶':kind==='audio'?'♪':'';
  function renderChips(){chips.replaceChildren();for(const a of c.assets.filter(a=>a.token&&referencePattern(a.token).test(c.prompt))){const chip=el('span',undefined,'reference-chip'),kind=mediaKind(a.mime);if(kind==='image'){const img=el('img');window.hubMediaLazy.watchImage(img,'/api/assets/'+a.id);img.alt='';chip.append(img);}else chip.append(el('span',kindGlyph(kind),'reference-chip-kind '+kind));chip.append(el('span','@'+a.token));chips.append(chip);}}
  function attachMentions(field,menu,sync){
    const render=()=>{
      menu.replaceChildren();
      const before=field.value.slice(0,field.selectionStart??field.value.length),match=before.match(/@([^\s@]*)$/);
      if(!match){menu.hidden=true;return;}
      const query=match[1].toLowerCase(),available=c.assets.filter(a=>a.token&&(!query||String(a.token).toLowerCase().includes(query)||String(a.name||'').toLowerCase().includes(query)));
      menu.hidden=false;
      if(!available.length){menu.append(el('p',c.assets.length?'没有匹配的素材，可输入 @图片1、@视频1 或 @音频1。':'先添加图片、视频或声音素材，再输入 @ 引用。','fine'));return;}
      for(const a of available){const b=el('button'),kind=mediaKind(a.mime);b.type='button';if(kind==='image'){const img=el('img');window.hubMediaLazy.watchImage(img,'/api/assets/'+a.id);img.alt='';b.append(img);}else b.append(el('span',kindGlyph(kind),'mention-kind '+kind));b.append(el('span',a.token+' · '+a.name));b.onmousedown=e=>e.preventDefault();b.onclick=()=>{const pos=field.selectionStart??field.value.length,start=Math.max(0,pos-match[0].length);field.setRangeText('@'+a.token+' ',start,pos,'end');menu.hidden=true;sync();field.focus();};b.onkeydown=e=>{if(e.key==='Escape'){menu.hidden=true;field.focus();}};menu.append(b);}
    };
    field.addEventListener('input',render);field.addEventListener('click',render);
    field.addEventListener('keyup',e=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(e.key))render();});
    field.addEventListener('keydown',e=>{if(e.key==='Escape')menu.hidden=true;else if(e.key==='ArrowDown'&&!menu.hidden){e.preventDefault();menu.querySelector('button')?.focus();}});
    field.addEventListener('blur',()=>setTimeout(()=>{if(!menu.contains(document.activeElement))menu.hidden=true;},150));
    return {render,hide:()=>{menu.hidden=true;}};
  }
  const mentions=attachMentions(textarea,suggestions,()=>{c.prompt=textarea.value;changed(c);renderChips();});
  textarea.oninput=()=>{c.prompt=textarea.value;changed(c);renderChips();};renderChips();
  const promptPanel=el('div',undefined,'studio-prompt-panel'),title=el('strong',`编辑提示词 ${index+1}`),field=el('div',undefined,'prompt-editor-field'),large=el('textarea'),menu=el('div',undefined,'mention-menu');
  large.value=textarea.value;large.placeholder=textarea.placeholder;large.setAttribute('aria-label',`展开编辑第 ${index+1} 组提示词`);menu.hidden=true;
  const sync=()=>{textarea.value=large.value;c.prompt=large.value;changed(c);renderChips();mentions.hide();};
  attachMentions(large,menu,sync);large.addEventListener('input',sync);textarea.addEventListener('input',()=>{large.value=textarea.value;});field.append(large,menu);promptPanel.append(title,field);promptPanel.hidden=true;window.hubPopover.mount(expand,promptPanel,'⤢','prompt');

  const settings=el('div',undefined,'composition-settings');settings.append(selectControl('时长',Array.from({length:12},(_,i)=>[i+4,`${i+4} 秒`]),c.duration,v=>{c.duration=Number(v);changed(c);refreshParameterSummary();}),selectControl('同提示词生成条数',Array.from({length:10},(_,i)=>[i+1,`${i+1} 条`]),c.count,v=>{c.count=Number(v);changed(c);refreshParameterSummary();}));parameterBody.append(settings);
  if(!window.hubLibTV?.selected())settings.append(selectControl('模型优先顺序',[['auto','2.0 优先 · 额度不足切换 Mini / Fast'],['5000005','仅 Seedance 2.0'],['mini',features.references?'Seedance 2.0 Mini · 全能参考':'Seedance 2.0 Mini（上传待验证）'],['fast','Seedance 2.0 Fast · 全能参考']],c.model,v=>{c.model=v;changed(c);}));
  if(window.hubLibTV?.selected()){
    c.libtv_model=c.libtv_model||'star-video2';c.libtv_resolution=c.libtv_resolution||'720p';
    const resolutions=c.libtv_model==='star-video2'?['480p','720p','1080p','4k']:['480p','720p'];
    if(!resolutions.includes(c.libtv_resolution))c.libtv_resolution='720p';
    const libtvSettings=el('div',undefined,'libtv-generation-settings');libtvSettings.setAttribute('aria-label','LibTV 生成参数');
    libtvSettings.append(selectControl('LibTV 模型',[['star-video2','2.0 VIP'],['star-video2-fast','2.0 Fast'],['star-video2-mini','2.0 Mini']],c.libtv_model,v=>{c.libtv_model=v;changed(c);renderCompositions();}),selectControl('分辨率',resolutions.map(v=>[v,v.toUpperCase()]),c.libtv_resolution,v=>{c.libtv_resolution=v;changed(c);}));
    parameterBody.append(libtvSettings);
  }
  if(c.relay_source&&c.relay_task){parameterBody.prepend(relaySourcePanel(c));}
  const toolbar=el('div',undefined,'composer-compact-toolbar');toolbar.append(options,references.querySelector('.reference-actions'));node.append(toolbar,references);
  const check=el('div',undefined,'submit-check'),route=el('strong',undefined,'submit-route'),condition=el('small',undefined,'submit-condition');
  condition.id='submit-condition-'+c.id;check.append(route,condition);node.append(check);
  const single=el('button','生成视频','primary single-generate');single.type='button';single.setAttribute('aria-describedby',condition.id);single.onclick=()=>submitCompositions([c],single);node.append(single);return node;
}
async function addAssets(c,files,role){
  if(!files.length)return;const epoch=composerEpoch,session=sessionEpoch;
  const images=files.filter(f=>f.type.startsWith('image/')).length,remaining=c.assets.filter(a=>a.role!==role||role==='reference');
  if(remaining.filter(a=>a.mime.startsWith('image/')).length+images>9){toast('每组最多 9 张图片',true);return;}
  if(remaining.length+files.length>12){toast('每组最多 12 个素材',true);return;}
  if(files.some(f=>f.size>64*1024*1024)){toast('当前中台单文件最大 64 MB，请先压缩文件',true);return;}
  pendingUploads++;updateCompositionSummary();
  try{for(const file of files){const r=await fetch('/api/assets',{method:'POST',credentials:'same-origin',headers:{'Content-Type':file.type,'X-Hub-Request':'1','X-File-Name':encodeURIComponent(file.name)},body:file});const asset=await r.json();if(!r.ok)throw new Error(asset.detail||'素材上传失败');if(epoch!==composerEpoch||session!==sessionEpoch||!me)return;asset.role=role;asset.token=compositionToken(c,asset.mime);if(role!=='reference')c.assets=c.assets.filter(a=>a.role!==role);c.assets.push(asset);changed(c);}renderCompositions();toast('素材已保存到中台，尚未上传 TikTok');}catch(e){if(epoch===composerEpoch)toast(e.message,true);}finally{if(epoch===composerEpoch){pendingUploads--;renderCompositions();}}
}
async function saveCompositions(){const epoch=composerEpoch;await api('/compositions',{items:compositions});if(epoch===composerEpoch)toast('草稿已保存，下次登录可继续编辑');}
async function submitCompositions(items,button,context={}){
  if(submissionPending)return;
  const route=studioChannel(),reason=submissionCheck(items,route);
  if(reason){toast(reason,true);return;}
  button?.classList.add('is-busy');
  if(route.id==='libtv'){
    try{return await window.hubLibTV.submit(items,route.profile);}
    finally{button?.classList.remove('is-busy');}
  }
  const epoch=composerEpoch,session=sessionEpoch;submissionPending=true;updateCompositionSummary();
  try{
    const key=items.length===1?items[0].request_key:requestKey;
    const result=await api('/tasks',{account_id:'pool',request_key:key,items,project_id:Object.hasOwn(context,'project_id')?context.project_id:(window.hubWorkspace?.projectId()||null)});
    if(epoch!==composerEpoch||session!==sessionEpoch||!me)return;
    items.forEach(changed);result.ids.forEach(id=>hubNotice.begin('task:'+id,'视频已加入队列','查看任务','studio','#task-list'));saveDraftQuietly();
    await load(true).catch(()=>{});await window.hubWorkspace?.refresh().catch(()=>{});return result;
  }catch(e){if(epoch===composerEpoch)toast(e.message,true);}
  finally{if(epoch===composerEpoch){submissionPending=false;button?.classList.remove('is-busy');updateCompositionSummary();}}
}
// Keep window ids on the server so results still find their window after a reload.
const autoSaveState={timer:null,busy:false,version:0,failed:false};
window.hubAutoSave={schedule(){if(!composerLoaded||!me?.id)return;const key='hub-draft-pending:'+me.id;autoSaveState.version++;try{localStorage.setItem(key,JSON.stringify({items:compositions}));}catch(e){if(!autoSaveState.failed){autoSaveState.failed=true;toast('本地自动保存失败，请检查浏览器存储空间',true);}}clearTimeout(autoSaveState.timer);autoSaveState.timer=setTimeout(flushAutoSave,600);}};
async function flushAutoSave(){if(autoSaveState.busy||!composerLoaded||!me?.id)return;const version=autoSaveState.version,epoch=composerEpoch,user=me.id,key='hub-draft-pending:'+user;let items;try{items=JSON.parse(JSON.stringify(compositions));}catch{return;}autoSaveState.busy=true;try{await api('/compositions',{items});if(epoch===composerEpoch&&me?.id===user){autoSaveState.failed=false;if(version===autoSaveState.version)localStorage.removeItem(key);}}catch(e){if(epoch===composerEpoch&&!autoSaveState.failed){autoSaveState.failed=true;toast('自动保存到服务器失败，本机暂存仍保留：'+e.message,true);}}finally{autoSaveState.busy=false;if(composerLoaded&&me?.id&&version!==autoSaveState.version)flushAutoSave();}}
function saveDraftQuietly(){window.hubAutoSave.schedule();}

document.addEventListener('DOMContentLoaded',()=>{
  $('#add-composition').onclick=()=>{if(compositions.length>=100){toast('单个编辑工作区最多 100 组，可先提交或保存当前内容',true);return;}compositions.push(blankComposition());requestKey=crypto.randomUUID();renderCompositions();$('#composition-list').lastElementChild.querySelector('textarea').focus();};
  $('#save-compositions').onclick=()=>busy($('#create-form'),saveCompositions).finally(updateCompositionSummary);
  $('#create-form').onsubmit=e=>{e.preventDefault();submitCompositions(compositions,$('#submit-task'));};
});
// Relay uses a locally available result from either generation channel, never a remote canvas ID.
const relayInFlight=new Set();
const relayJobReady=job=>job?.state==='ready'&&(!job.libtv||Boolean(job.asset_id));
window.hubRelay={
  resolve(taskId,provider){
    return provider==='libtv'?window.hubLibTV?.jobs().find(j=>j.id===taskId&&relayJobReady(j)):tasks.find(t=>t.id===taskId&&relayJobReady(t));
  },
  button(task,source=null){
    const b=el('button',source?'接力':'接力生成',source?'relay-start':undefined);
    b.type='button';b.draggable=true;b.title='提取尾帧并创建接力草稿；也可拖到制作台画布';
    b.addEventListener('dragstart',e=>{e.dataTransfer.effectAllowed='copy';e.dataTransfer.setData('application/x-hub-relay',JSON.stringify({task:task.id,provider:task.libtv?'libtv':'tiktok',composition:source?.id}));});
    b.onclick=async e=>{e.stopPropagation();b.disabled=true;try{if(source)await window.hubRelay.createFrom(source,task);else await window.hubRelay.fromTask(task);}catch(err){toast(err.message||String(err),true);}finally{b.disabled=false;}};
    return b;
  },
  editButton(task,onPreview=true){
    const b=el('button','加入剪辑',onPreview?'relay-start adopt':undefined);b.type='button';b.title='把这条视频加入剪辑台时间轴';
    b.onclick=async e=>{e.stopPropagation();b.disabled=true;try{if(task.libtv)await window.hubEditor.fromTask(task.id);else await window.hubWorkspace.add(task.id);}catch(err){toast(err.message||String(err),true);}finally{b.disabled=false;}};
    return b;
  },
  async createFrom(source,task,point){
  if(!source||!relayJobReady(task))throw Error('来源视频尚未完成或未入库');
  if(compositions.length>=100)throw Error('单个工作区最多 100 张创作卡片');
  const epoch=composerEpoch,session=sessionEpoch,key=JSON.stringify([epoch,task.libtv?'libtv':'tiktok',task.id]);
  if(relayInFlight.has(key))return;
  relayInFlight.add(key);
  try{
  const info=await api('/media/source/'+task.id);
  if(epoch!==composerEpoch||session!==sessionEpoch||!me)throw Error('登录状态已变化');
  const duration=Number(info.duration||0);
  const frame=await api('/media/extract',{source_id:task.id,kind:'frame',time:Math.max(0,duration-.2)});
  if(epoch!==composerEpoch||session!==sessionEpoch||!me)throw Error('登录状态已变化');
  if(compositions.length>=100)throw Error('单个工作区最多 100 张创作卡片');
  const c=blankComposition();
  c.mode='omni';c.model=source.model||'auto';c.duration=Math.min(15,Math.max(4,Math.round(duration)||5));c.count=1;
  c.assets=[{...frame,role:'reference',token:'图片1'}];c.nextImage=2;
  const inherited=(source.assets||[]).filter(a=>(a.mime||'').startsWith('image/')&&a.role==='reference'&&a.id!==frame.id).slice(0,8);
  for(const a of inherited){if(c.assets.some(x=>x.id===a.id))continue;c.assets.push({...a,token:'图片'+(c.nextImage++)});}
  c.relay_source=source.id;c.relay_task=task.id;c.relay_label=source.relay_label||null;c.relay_duration=Math.round(duration*100)/100;
  c.continuation={source_id:task.id,frame_id:frame.id,frame_time:Number(frame.start??Math.max(0,duration-.2)),audio_id:null,append_timeline:false};
  const base=source.canvas_position||{x:0,y:0};
  let spot=point?{x:Math.round(point.x),y:Math.round(point.y)}:{x:Math.round(base.x+520),y:Math.round(base.y)};
  if(!point)while(compositions.some(o=>o.canvas_position&&Math.abs(o.canvas_position.x-spot.x)<420&&Math.abs(o.canvas_position.y-spot.y)<180))spot={x:spot.x,y:spot.y+220};
  c.canvas_position=spot;
  compositions.push(c);renderCompositions();
  toast('已创建接力窗口：继承来源尾帧'+(inherited.length?`和 ${inherited.length} 个参考素材`:'')+'，填写提示词后再生成');
  return c;
  }finally{relayInFlight.delete(key);}
}};

// One relay entry for the whole app: queue rows, project clips and the window button all land here.
window.hubRelay.fromTask=async (task,point,focus)=>{
  if(!task)throw Error('接力来源不可用');
  if(task.state!=='ready')throw Error('只有已完成的视频可以接力，当前状态：'+(task.state||'未知'));
  if(typeof navigate==='function')navigate('studio');
  const right=compositions.reduce((m,c)=>Math.max(m,(Number(c.canvas_position?.x)||0)+480),0);
  const label=(task.prompt||'').trim().slice(0,10);
  const stub={id:'task:'+task.id,model:['auto','5000005','mini','fast'].includes(task.model)?task.model:'auto',assets:[],
    relay_label:`接力自${label?`「${label}」`:'已完成任务'}`};
  const c=await window.hubRelay.createFrom(stub,task,point||{x:compositions.length?right+40:0,y:0});
  if(c&&focus){
    const settle=tries=>setTimeout(()=>{
      const card=document.querySelector(`#composition-list .composition[data-composition-id="${c.id}"]`);
      if(!card)return;
      window.hubCanvas?.reveal?.(c.id);
      const pop=card.querySelector('.parameter-popover');
      if(pop&&!pop.open){pop.open=true;compositionOptionsOpen.add(c.id);}
      pop?.reposition?.();
      const target=card.querySelector(`[data-relay-action="${focus}"]`);
      if(target&&document.activeElement!==target)target.focus({preventScroll:true});
      if(pop&&!pop.open&&(tries||0)<5)settle((tries||0)+1);
    },tries?200:80);
    settle(0);
  }
  return c;
};

// Refresh classification badges without replacing a focused prompt or its selection.
let classificationPoll=null;
setInterval(async()=>{
  if(classificationPoll||!me||document.hidden||view!=='studio'||document.activeElement?.matches('textarea,input')||!compositions.some(c=>c.assets.some(a=>['queued','running'].includes(a.classification_status))))return;
  const epoch=composerEpoch,session=sessionEpoch,poll={epoch,session};classificationPoll=poll;
  try{const ids=[...new Set(compositions.flatMap(c=>c.assets.map(a=>a.id)).filter(Boolean))],items=[];for(let i=0;i<ids.length;i+=500){const r=await fetch('/api/workspace/material-status',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:JSON.stringify({ids:ids.slice(i,i+500)})});if(r.status===404||r.status===405){items.splice(0,items.length,...await api('/workspace/materials'));break;}if(!r.ok)throw Error('状态读取失败');items.push(...await r.json());}if(epoch!==composerEpoch||session!==sessionEpoch||!me||document.hidden||view!=='studio'||document.activeElement?.matches('textarea,input'))return;let dirty=false;const byId=new Map(items.map(a=>[a.id,a]));for(const c of compositions)for(const a of c.assets){const fresh=byId.get(a.id);if(fresh&&(fresh.classification_status!==a.classification_status||fresh.category!==a.category)){a.classification_status=fresh.classification_status;a.category=fresh.category;dirty=true;}}if(dirty)renderCompositions();}catch{}finally{if(classificationPoll===poll)classificationPoll=null;}
},4000);

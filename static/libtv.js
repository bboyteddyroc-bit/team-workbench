 'use strict';
window.hubLibTV=(()=>{
 let channel,connection,channelStatus,libtvConfigured=null,rows=[],pending=new Map(),activeCompositions=new Set(),fetching=false;
 function renderChannelStatus(){
  if(!channelStatus)return;
  const libtv=selected(),pool=document.getElementById('pool-summary');
  if(pool)pool.hidden=libtv;
  connection.hidden=me?.role!=='admin';
  setStudioText(channelStatus,libtv?'选择一个已授权的 LibTV 账号；实际可用性以提交时校验为准。':'TikTok 由公司账号池按队列分配。');
 }
 const selected=()=>channel?.value==='libtv';
 const jobs=()=>[...[...pending.values()].filter(p=>!rows.some(r=>r.request_key===p.request_key)),...rows].map(r=>({...r,libtv:true}));
 async function refresh(reportError=false){if(!me||me.must_change||fetching)return;fetching=true;const epoch=sessionEpoch;try{const [state,data]=await Promise.all([api('/libtv/status'),api('/libtv/jobs')]);if(epoch!==sessionEpoch)return;libtvConfigured=state.connected;setStudioText(connection,state.connected?'重新核验 LibTV 连接':'连接共享 LibTV');renderChannelStatus();rows=data;hubNotice.observe('libtv:',data);renderTasks();window.hubCompositionPreview?.refresh?.();updateCompositionSummary();}catch(e){if(epoch===sessionEpoch&&reportError===true)toast(e.message,true);}finally{fetching=false;}}
 function node(job){
  const row=el('article',undefined,'task');row.dataset.libtvJob=job.id;
  const top=el('div',undefined,'task-top');
  const identity=['LibTV · 共享账号',job.created?new Date(job.created*1000).toLocaleString('zh-CN'):null].filter(Boolean).join(' · ');
  const issue=['failed','attention','unknown'].includes(job.state),feedbackUI=window.hubTaskFeedback;
  const state=issue&&feedbackUI?feedbackUI.state(job.feedback_state||job.state):job.state==='running'?(job.stage||'生成中'):({failed:'生成失败',ready:'已完成',attention:'同步待恢复',importing:'正在取回原任务结果'})[job.state]||job.state;
  top.append(el('span',identity,'task-meta'),el('span',state,'status '+job.state));row.append(top);
  row.append(el('p',[job.model,job.duration?job.duration+' 秒':null,(job.resolution||'').toUpperCase()].filter(Boolean).join(' · '),'fine'));
  if(job.prompt.length>180){const details=el('details'),summary=el('summary',job.prompt.slice(0,90)+'…');details.append(summary,el('p',job.prompt,'task-prompt'));row.append(details);}else row.append(el('p',job.prompt,'task-prompt'));
  if(issue&&feedbackUI)row.append(feedbackUI.studio(job,'libtv'));else if(job.error){const d=el('details');d.append(el('summary','同步详情'),el('p',job.error,'fine'));row.append(d);}
  const actions=el('div',undefined,'task-actions');actions.append(originalWindowAction(job));
  if(job.asset_id){
   const video=el('video');video.controls=true;window.hubMediaLazy.watch(video,'/api/assets/'+job.asset_id);video.setAttribute('aria-label','LibTV 生成的视频');row.append(video);
   if(job.state==='ready'){const source={...job,libtv:true};actions.append(window.hubRelay.button(source),window.hubRelay.editButton(source,false));}
   const download=el('a','下载 MP4');download.href='/api/assets/'+job.asset_id+'?download=1';actions.append(download);
  }
  if(job.state==='attention'&&job.project){
   row.append(el('p','只取回原任务视频，不重新生成或重复扣费。','fine'));
   const b=el('button','取回已生成视频');b.onclick=async()=>{const epoch=sessionEpoch;b.disabled=true;b.textContent='正在取回…';try{await api('/libtv/jobs/'+job.id+'/recover',{});if(epoch!==sessionEpoch)return;await refresh();toast('视频已取回并保存到素材库');window.dispatchEvent(new Event('hub-tasks'));}catch(e){if(epoch===sessionEpoch){toast(e.message,true);await refresh();}}finally{if(epoch===sessionEpoch){b.disabled=false;b.textContent='取回已生成视频';}}};actions.append(b);
  }
  if(job.project){
   const link=el('a','查看 LibTV 画布');link.href='https://www.liblib.tv/canvas?projectId='+encodeURIComponent(job.project);link.target='_blank';link.rel='noopener noreferrer';
   if(job.state==='ready'){
    const more=el('div',undefined,'task-overflow-extra');more.hidden=true;more.id='task-extra-libtv-'+job.id;more.append(link);
    window.hubWorkspace.overflowActions(job.id,actions,more);
   }else actions.append(link);
   actions.append(el('span','画布 '+job.project,'task-meta'));
  }
  if(actions.childElementCount)row.append(actions);return row;
 }
  function submit(items,profile){
   if(pendingUploads)return;
   if(items.length!==1){toast('LibTV 请在单个窗口内提交',true);return;}
   const c=items[0],count=Number(c.count);
   if(!Number.isInteger(count)||count<1||count>10){toast('生成条数须为 1 至 10 条',true);return;}
   if(activeCompositions.has(c.id))return;
   if(!c.prompt.trim()){toast('请填写提示词',true);return;}
   const reason=profile?submissionCheck(items,{id:'libtv'}):'请选择已授权的 LibTV 账号';if(reason){toast(reason,true);return;}
   const epoch=sessionEpoch,baseKey=crypto.randomUUID();
   const payload={prompt:c.prompt,assets:JSON.parse(JSON.stringify(c.assets)),duration:c.duration,mode:c.mode,model:c.libtv_model||'star-video2',resolution:c.libtv_resolution||'720p',libtv_profile:profile,composition_id:c.id};
   const keys=Array.from({length:count},(_,i)=>count===1?baseKey:baseKey+'-'+(i+1));
   activeCompositions.add(c.id);
   for(const key of keys)pending.set(key,{id:'pending-'+key,request_key:key,composition_id:c.id,state:'running',stage:'正在提交到 LibTV',created:Date.now()/1000,prompt:payload.prompt,model:({'star-video2':'Seedance 2.0 VIP','star-video2-fast':'Seedance 2.0 Fast VIP','star-video2-mini':'Seedance 2.0 Mini'})[payload.model],resolution:payload.resolution});
   renderTasks();window.hubCompositionPreview?.refresh?.();updateCompositionSummary();
   // Each clip has its own idempotency key and request. Never retry a failed or uncertain POST.
   let needsReview=false;
   const requests=keys.map(key=>{
    hubNotice.begin('libtv:'+key,'正在提交到 LibTV','查看任务','studio','#task-list');
    return api('/libtv/jobs',{...payload,request_key:key})
     .then(result=>{if(epoch!==sessionEpoch)return;if(result?.state!=='ready'){needsReview=true;const item=pending.get(key);if(item){item.state='attention';item.error='任务状态需要核对；请查看任务记录和原画布。';}}if(epoch===sessionEpoch&&result?.state==='ready')hubNotice.finish('libtv:'+key,'LibTV 视频已保存到素材库','success',undefined,{label:'查看素材',view:'materials',target:'#materials'});})
     .catch(e=>{needsReview=true;if(epoch===sessionEpoch){const item=pending.get(key);if(item){item.state='attention';item.error='提交结果需要核对：'+e.message+'；请查看任务记录和原画布，避免重复生成。';}hubNotice.finish('libtv:'+key,'LibTV 任务需要核对','error',e.message+'；请查看原任务，避免重复提交');}})
     .finally(()=>{if(epoch!==sessionEpoch)return;const item=pending.get(key);if(item&&item.state!=='attention')pending.delete(key);renderTasks();window.hubCompositionPreview?.refresh?.();updateCompositionSummary();window.dispatchEvent(new Event('hub-tasks'));});
   });
   
   return Promise.allSettled(requests).then(()=>{
     if(epoch!==sessionEpoch)return;
     activeCompositions.delete(c.id);updateCompositionSummary();
     if(needsReview)toast('部分 LibTV 任务结果需要核对；请查看任务记录，避免重复生成',true);
    });
  }

 function restoreChannel(){if(!channel)return;let saved='';try{saved=localStorage.getItem('hub-generation-channel:'+me?.id)||'';}catch{}channel.value=['tiktok','libtv'].includes(saved)?saved:'';renderChannelStatus();}
 function reset(){rows=[];pending.clear();activeCompositions.clear();libtvConfigured=null;if(channel){restoreChannel();channel.disabled=false;}}
 document.addEventListener('DOMContentLoaded',()=>{const head=document.querySelector('.composer-title');const label=el('label','生成渠道');channel=el('select');channel.id='generation-channel';channel.setAttribute('aria-label','生成渠道');channel.append(new Option('TikTok · 公司账号池','tiktok'),new Option('LibTV · 共享账号','libtv'));channel.onchange=()=>{renderChannelStatus();renderCompositions();refresh();};label.append(channel);head.after(label);connection=el('button','连接共享 LibTV');connection.type='button';connection.hidden=true;connection.onclick=async()=>{connection.disabled=true;try{await api('/libtv/connect',{});toast('共享 LibTV 已连接（不属于 TikTok 公司账号池）');await refresh();}catch(e){toast(e.message,true);}finally{connection.disabled=false;}};document.getElementById('libtv-account-management')?.append(connection);connection.className='libtv-shared-connect';channelStatus=el('small',undefined,'fine');channelStatus.hidden=true;label.append(channelStatus);renderChannelStatus();if(compositions.length)renderCompositions();refresh();});

 document.addEventListener('DOMContentLoaded',()=>{channel.prepend(new Option('请选择：公司账号池 / LibTV',''));restoreChannel();channel.addEventListener('change',()=>{try{if(me?.id)localStorage.setItem('hub-generation-channel:'+me.id,channel.value);}catch{}});renderCompositions();});
 window.addEventListener('hub-tasks',refresh);setInterval(()=>{if(me&&(view==='studio'||hubNotice.has('libtv:'))&&!document.hidden)refresh();},2000);
 return {selected,submit,reset,jobs,node};
})();

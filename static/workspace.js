'use strict';
window.hubWorkspace=(()=>{
  const by=id=>document.getElementById(id);
  let projects=[],links=[],current=null,epoch=0;
  window.hubTimelineScale=32;
  const error=e=>toast(e.message||String(e),true);
  const selectedId=()=>current?.id||null;
  function visibility(next){by('workspace-bar').hidden=next!=='editor';}
  function reset(){
    epoch++;projects=[];links=[];current=null;
    for(const id of ['project-dialog','task-details-dialog'])by(id).close();
    paintBar();
  }
  function paintBar(){
    const select=by('workspace-project');select.replaceChildren(new Option('独立生成 · 不关联项目',''));
    const groups=new Map();for(const p of projects){const d=p.created?new Date(p.created*1000):null;const key=d&&!isNaN(d)?`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`:'未知日期';if(!groups.has(key))groups.set(key,[]);groups.get(key).push(p);}
    for(const [key,items] of groups){const group=document.createElement('optgroup');group.label=key;for(const p of items)group.append(new Option(p.title,p.id));select.append(group);}
    select.value=selectedId()||'';
    for(const [id,value] of [['workspace-target',current?.body.target_duration||30],['workspace-ratio',current?.body.ratio||'9:16']]){
      if(document.activeElement!==by(id))by(id).value=value;
      by(id).disabled=!current;
    }
    by('workspace-save').disabled=!current;
    by('workspace-reload').disabled=!current?.id;
    by('workspace-state').textContent=current?.id?'已关联项目':current?'未保存剪辑':'独立生成';
  }
  async function refresh(){
    if(!me||me.must_change)return;
    const token=epoch,session=sessionEpoch;
    const result=await Promise.all([api('/editor/projects?summary=true'),api('/workspace/links')]);
    if(token!==epoch||session!==sessionEpoch||!me)return;
    [projects,links]=result;paintBar();window.hubEditor?.renderLibrary();
  }
  async function add(id){
    if(selectedId())await api('/workspace/link',{project_id:selectedId(),task_id:id});
    await window.hubEditor.fromTask(id);await refresh();
    toast('已加入时间轴，请保存项目');
  }
  function taskActions(task,actions){
    if(task.state!=='ready')return;
    const relay=el('button','接力生成');relay.type='button';relay.draggable=true;relay.title='点击在制作台开接力窗口，或拖到画布任意位置';relay.onclick=()=>window.hubRelay.fromTask(task).catch(err=>toast(err.message||String(err),true));
    relay.addEventListener('dragstart',e=>{e.dataTransfer.effectAllowed='copy';const raw=JSON.stringify({task:String(task.id)});e.dataTransfer.setData('application/x-hub-relay',raw);e.dataTransfer.setData('application/x-seedance-relay',raw);});actions.prepend(relay);
    const more=el('div',undefined,'task-overflow-extra');more.hidden=true;more.id='task-extra-'+task.id;
    const details=el('button','查看参数 / 关联项目');
    details.onclick=async()=>{try{
      await refresh();
      const detail=await api('/tasks/'+encodeURIComponent(task.id)+'/config');
       const config=JSON.parse(detail.config||'{}');
      by('task-details-content').textContent=JSON.stringify({task_id:task.remote_id||task.id,prompt:task.prompt,model:config.model,duration:task.duration,input_assets:config.assets||[],projects:links.filter(l=>l.task_id===task.id).map(l=>l.title),versions:'版本历史尚未启用'},null,2);
      by('task-details-dialog').showModal();
    }catch(e){error(e);}};
    more.append(details);
    for(const [text,focus] of [['提取尾帧 / 指定帧','frame'],['提取原声','audio']]){
      const b=el('button',text);b.onclick=async()=>{try{await window.hubRelay.fromTask(task,null,focus);}catch(e){error(e);}};more.append(b);
    }
    overflowActions(task.id,actions,more);
  }
  // Shared action rail for all generation providers; callers supply supported actions only.
  function overflowActions(id,actions,more){
    const track=el('div',undefined,'task-overflow-track'),primary=el('div',undefined,'task-overflow-primary'),toggle=el('button','…','task-overflow-toggle');
    toggle.type='button';toggle.setAttribute('aria-controls',more.id);
    for(const node of [...actions.children])if(node.matches('button,a'))primary.append(node);
    function expanded(on){more.hidden=!on;toggle.textContent=on?'×':'…';toggle.setAttribute('aria-expanded',String(on));toggle.setAttribute('aria-label',on?'收起其他操作':'展开其他操作');toggle.title=on?'收起其他操作':'展开其他操作';}
    toggle.onclick=()=>expanded(more.hidden);
    track.addEventListener('keydown',e=>{if(e.key==='Escape'&&!more.hidden){expanded(false);toggle.focus();e.stopPropagation();}});
    expanded(false);track.append(primary,more,toggle);actions.prepend(track);

  }
  by('workspace-project').onchange=async e=>{
    const id=e.target.value;
    try{if(!await window.hubEditor.selectProject(id)){paintBar();return;}await refresh();}catch(e){paintBar();error(e);}
  };
  by('workspace-editor').onclick=()=>navigate('editor');
  by('workspace-reload').onclick=async()=>{
    const id=selectedId();if(!id)return;
    try{if(await window.hubEditor.selectProject(id)){await refresh();toast('已重新载入项目');}}catch(e){error(e);}
  };
  by('workspace-save').onclick=async()=>{
    by('workspace-save').disabled=true;
    try{await window.hubEditor.save();await refresh();toast('项目已保存');}catch(e){error(e);}finally{paintBar();}
  };
  function settings(){
    const target=Number(by('workspace-target').value);
    if(!Number.isFinite(target)||target<1||target>3600){error(Error('项目目标时长为 1–3600 秒'));paintBar();return;}
    window.hubEditor.setSettings(current.title,target,by('workspace-ratio').value);
  }
  by('workspace-target').onchange=settings;by('workspace-ratio').onchange=settings;
  by('workspace-new').onclick=()=>by('project-dialog').showModal();
  by('project-cancel').onclick=()=>by('project-dialog').close();
  by('project-create').onsubmit=async e=>{
    e.preventDefault();const button=e.target.querySelector('button.primary');button.disabled=true;
    try{
      const data=new FormData(e.target),p=await api('/editor/projects',{title:data.get('title'),body:{clips:[],captions:[],ratio:'9:16',target_duration:Number(data.get('target'))}});
      await refresh();await window.hubEditor.selectProject(p.id);by('project-dialog').close();
    }catch(e){error(e);}finally{button.disabled=false;}
  };
  function tracks(project){
    if(!project)return;
    window.hubEditor?.drawTracks();
  }

  window.addEventListener('hub-project',e=>{
    current=e.detail;if(current?.id){projects=projects.filter(p=>p.id!==current.id);projects.unshift(current);}
    paintBar();tracks(current);window.hubEditor?.renderLibrary();
  });
  by('timeline-zoom').oninput=e=>{window.hubTimelineScale=Number(e.target.value);window.hubEditor.redrawTimeline();};
  by('edit-prev-frame').onclick=()=>window.hubEditor.step(-1/24);
  by('edit-next-frame').onclick=()=>window.hubEditor.step(1/24);
  by('library-scope').onchange=async()=>{try{if(by('library-scope').value!=='today')await window.hubEditor.ensureFullLibrary();window.hubEditor.renderLibrary();}catch(e){toast('素材加载失败：'+(e.message||String(e)),true);}};
  function filterLibrary(items){
    if(by('library-scope').value==='all')return items;
    if(by('library-scope').value==='today'){const now=new Date();return items.filter(i=>{if(!i.created)return false;const d=new Date(i.created*1000);return d.getFullYear()===now.getFullYear()&&d.getMonth()===now.getMonth()&&d.getDate()===now.getDate();});}
    const ids=new Set([...links.filter(l=>l.project_id===selectedId()).map(l=>l.task_id),...(current?.body.clips||[]).map(c=>c.task_id)]);
    return items.filter(i=>ids.has(i.id));
  }
  return {projectId:selectedId,refresh,reset,visibility,add,taskActions,overflowActions,filterLibrary,
    select:async id=>{const accepted=await window.hubEditor.selectProject(id);if(accepted)await refresh();return accepted;}};
})();

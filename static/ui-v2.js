'use strict';
window.hubUI=(()=>{
  const by=id=>document.getElementById(id);
  let overview=[],selectedOverview=null,refreshing=null,session=-1,browseAll=false,page=0,hasNext=false;
  const pageSize=20;
  const paths={
    overview:'M3 3h7v7H3z M14 3h7v7h-7z M3 14h7v7H3z M14 14h7v7h-7z',
    studio:'M4 6h16v15H4z M4 6l3-4 M10 6l3-4 M16 6l3-4 M10 11l6 3-6 3z',
    editor:'M9 9l12 12 M9 15L21 3 M3 3a4 4 0 1 0 6 6 4 4 0 0 0-6-6 M3 15a4 4 0 1 0 6 6 4 4 0 0 0-6-6',
    accounts:'M5 21v-3a4 4 0 0 1 4-4h6a4 4 0 0 1 4 4v3 M8 6a4 4 0 1 0 8 0 4 4 0 0 0-8 0',
    members:'M2 21v-3a4 4 0 0 1 4-4h5a4 4 0 0 1 4 4v3 M5 6a4 4 0 1 0 8 0 4 4 0 0 0-8 0 M17 3a4 4 0 0 1 0 8 M18 14a4 4 0 0 1 4 4v3',
    audit:'M12 8v5l4 2 M22 12a10 10 0 1 0-20 0 10 10 0 0 0 20 0',
    play:'M8 5l12 7-12 7z',
    project:'M3 6h7l2 3h9v12H3z M3 6V3h7l2 3',
  };
  function icon(name){
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    for(const [k,v]of Object.entries({viewBox:'0 0 24 24',fill:'none',stroke:'currentColor','stroke-width':'1.7','stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))svg.setAttribute(k,v);
    const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d',paths[name]||paths.project);svg.append(path);return svg;
  }
  for(const button of document.querySelectorAll('.sidebar [data-view]'))button.prepend(icon(button.dataset.view));
  for(const mark of document.querySelectorAll('.brand-mark')){mark.replaceChildren(icon('play'));}
  const breadcrumb=by('view-label');breadcrumb.classList.add('breadcrumb');
  function date(n){return n?new Date(n*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}):'—';}
  function model(name){return name==='mini'?'Seedance 2.0 Mini':name==='fast'?'Seedance 2.0 Fast':'Seedance 2.0';}
  function btn(text,fn,cls='secondary'){const b=el('button',text,cls);b.onclick=async()=>{b.disabled=true;try{await fn();}catch(e){toast(e.message,true);}finally{b.disabled=false;}};return b;}
  function preview(task,controls=true){
    const video=el('video');video.muted=true;video.playsInline=true;video.controls=controls;video.setAttribute('aria-label',task.prompt.slice(0,80));
    return window.hubMediaLazy.watch(video,'/api/tasks/'+task.id+'/video#t=0.1');
  }
  async function refresh(){
    if(!me||me.must_change)return;
    if(refreshing)return refreshing;
    const token=sessionEpoch;
    refreshing=(async()=>{
      const selectedId=window.hubWorkspace.projectId();
      let data=await api('/workspace/overview?limit='+(pageSize+1)+'&offset='+(page*pageSize));
      if(token!==sessionEpoch||!me)return;
      if(!data.length&&page>0){page--;data=await api('/workspace/overview?limit='+(pageSize+1)+'&offset='+(page*pageSize));}
      let selected=data.find(p=>p.id===selectedId)||null;
      if(selectedId&&!selected){const match=await api('/workspace/overview?project_id='+encodeURIComponent(selectedId));selected=match[0]||null;}
      if(token!==sessionEpoch||!me||selectedId!==window.hubWorkspace.projectId())return;
      hasNext=data.length>pageSize;overview=data.slice(0,pageSize);selectedOverview=selected;session=token;renderOverview();
    })().finally(()=>refreshing=null);
    return refreshing;
  }
  function state(p){
    if(p.tasks.some(t=>['queued','submitting','running'].includes(t.state)))return '生成中';
    if(p.exports.some(e=>e.state==='ready'))return '已有导出';
    if(p.clip_count)return '剪辑中';
    if(p.tasks.some(t=>t.state==='ready'))return '待剪辑';
    return '尚未加入片段';
  }
  async function openProject(id,next){
    if(await window.hubWorkspace.select(id)){browseAll=false;selectedOverview=overview.find(p=>p.id===id)||null;navigate(next);await refresh();}
  }
  function renderOverview(){
    if(session!==sessionEpoch)return;
    const root=by('overview-content');root.replaceChildren();
    const current=browseAll?null:(overview.find(p=>p.id===window.hubWorkspace.projectId())||(selectedOverview?.id===window.hubWorkspace.projectId()?selectedOverview:null));
    if(!current){
      if(!overview.length){root.append(empty('建立你的第一个视频项目','创建项目后，生成片段、参考素材和剪辑成品会关联在这里。'));return;}
      const grid=el('div',undefined,'project-grid');
      for(const p of overview){
        const card=el('article',undefined,'project-card'),cover=el('div',undefined,'project-cover'),first=p.tasks.find(t=>t.state==='ready');
        if(first)cover.append(preview(first));else cover.append(icon('project'),el('span','等待第一段视频'));
        const content=el('div',undefined,'project-card-content');content.append(el('span',state(p),'status'),el('h2',p.title),el('p',`${p.target_duration} 秒目标 · ${p.ratio} · ${p.tasks.length} 个任务`,'fine'),el('p','更新于 '+date(p.updated),'fine'));
        const actions=el('div',undefined,'workspace-actions');actions.append(btn('打开项目',()=>openProject(p.id,'overview'),'primary'),btn('进入剪辑台',()=>openProject(p.id,'editor')));
        content.append(actions);card.append(cover,content);grid.append(card);
      }
      root.append(grid);
      const pager=el('div',undefined,'workspace-actions');
      if(page>0)pager.append(btn('上一页',async()=>{page--;await refresh();}));
      pager.append(el('span','第 '+(page+1)+' 页','fine'));
      if(hasNext)pager.append(btn('下一页',async()=>{page++;await refresh();}));
      root.append(pager);return;
    }
    const p=current,hero=el('section',undefined,'project-hero'),cover=el('div',undefined,'project-cover'),first=p.tasks.find(t=>t.state==='ready');
    root.append(btn('返回全部项目',()=>{browseAll=true;renderOverview();},'text-button'));
    if(first)cover.append(preview(first));else cover.append(icon('project'));
    const heading=el('div',undefined,'project-hero-info');heading.append(el('span',state(p),'status'),el('h2',p.title));
    const facts=el('dl',undefined,'project-facts');
    for(const [label,value]of [['目标时长',p.target_duration+' 秒'],['视频比例',p.ratio],['时间轴',p.timeline_duration.toFixed(2)+' 秒'],['最近保存',date(p.updated)]]){
      const group=el('div');group.append(el('dt',label),el('dd',value));facts.append(group);
    }
    heading.append(facts);hero.append(cover,heading);root.append(hero);
    const layout=el('div',undefined,'overview-layout'),main=el('div'),side=el('aside');
    const metrics=el('div',undefined,'project-metrics');
    for(const [label,value]of [['关联任务',p.tasks.length],['可用片段',p.tasks.filter(t=>t.state==='ready').length],['待处理',p.tasks.filter(t=>['failed','attention','unknown'].includes(t.state)).length]]){
      const item=el('div');item.append(el('span',label),el('strong',String(value)));metrics.append(item);
    }
    main.append(metrics);
    const section=el('section',undefined,'overview-panel');section.append(el('h2','项目片段'));
    if(!p.tasks.length)section.append(el('p','项目尚无生成任务。进入制作台，提交时会自动关联当前项目。','fine'));
    for(const t of p.tasks){
      const row=el('article',undefined,'project-task-row');
      if(t.state==='ready')row.append(preview(t));else{const placeholder=el('div',undefined,'task-placeholder');placeholder.append(icon('play'));row.append(placeholder);}
      const info=el('div');info.append(el('strong',t.prompt.slice(0,55)),el('p',`${t.duration} 秒 · ${model(t.model)} · ${labels[t.state]||t.state}`,'fine'));
      row.append(info);
      if(t.state==='ready'){
        const actions=el('div',undefined,'workspace-actions');
        actions.append(btn('接力生成',()=>window.hubRelay.fromTask(t).catch(e=>toast(e.message||String(e),true))),btn('加入剪辑',()=>window.hubWorkspace.add(t.id)));
        row.append(actions);
      }
      section.append(row);
    }
    main.append(section);
    const quick=el('section',undefined,'overview-panel');quick.append(el('h2','继续创作'));
    quick.append(btn('新增生成片段',()=>navigate('studio'),'primary'),btn('进入剪辑台',()=>navigate('editor')));
    quick.append(el('p','剪辑台可保存工程并导出 MP4。生成与导出状态均以实际任务为准。','fine'));side.append(quick);
    const history=el('section',undefined,'overview-panel');history.append(el('h2','保存与导出'));
    history.append(el('p',`当前工程版本 ${p.version} · ${date(p.updated)}`,'fine'),el('p','在剪辑台“版本”中查看和恢复工程。生成版本对比尚未接入。','fine'));
    if(!p.exports.length)history.append(el('p','还没有导出记录。','fine'));
    for(const job of p.exports){
      const item=el('div',undefined,'overview-export');item.append(el('span',date(job.created)),el('span',({ready:'导出完成',queued:'等待导出',rendering:'正在导出',failed:'导出失败'})[job.state],'status'));
      if(job.state==='ready'){const a=el('a','下载 MP4');a.href='/api/editor/exports/'+job.id+'/video?download=true';item.append(a);}
      if(job.error)item.append(el('p',job.error,'error'));history.append(item);
    }
    side.append(history);layout.append(main,side);root.append(layout);
  }
  for(const b of document.querySelectorAll('[data-property]'))b.onclick=()=>{
    document.querySelectorAll('[data-property]').forEach(n=>n.classList.toggle('active',n===b));
    for(const name of ['base','repair','versions'])by('editor-'+name+'-panel').hidden=name!==b.dataset.property;
    const p=window.hubEditor.current();by('editor-version-info').textContent=p?.id?`当前工程第 ${p.version} 次保存。`:'项目尚未保存。';
    if(b.dataset.property==='versions')loadVersions().catch(e=>toast(e.message,true));
  };
  async function loadVersions(){
    const p=window.hubEditor.current(),list=by('editor-version-list');list.replaceChildren();
    if(!p?.id)return;
    const token=sessionEpoch,versions=await api('/editor/projects/'+p.id+'/versions');
    if(token!==sessionEpoch||window.hubEditor.current()?.id!==p.id)return;
    for(const version of versions){
      const row=el('div',undefined,'engineering-version');
      row.append(el('strong','版本 '+version.version),el('p',`${date(version.created)} · ${version.clips} 段 · ${version.duration.toFixed(2)} 秒`,'fine'));
      if(version.version===p.version)row.append(el('span','当前版本','status'));
      else row.append(btn('恢复为新版本',async()=>{
        let latest=window.hubEditor.current();
        if(window.hubEditor.isDirty())latest=await window.hubEditor.save();
        if(latest?.id!==p.id)throw Error('当前项目已改变，请重新选择版本');
        await api('/editor/projects/'+p.id+'/restore',{version:version.version,expected_version:latest.version});
        await window.hubWorkspace.select(p.id);await loadVersions();toast('已恢复为新的工程版本，旧版本仍然保留');
      }));
      list.append(row);
    }
  }
  by('overview-new').onclick=()=>by('workspace-new').click();
  window.addEventListener('hub-project',()=>{renderOverview();if(view==='overview')Promise.resolve(refreshing).then(()=>refresh()).catch(()=>{});});
  window.addEventListener('hub-tasks',()=>{if(view==='overview')refresh().catch(()=>{});});
  function reset(){overview=[];selectedOverview=null;session=-1;browseAll=false;page=0;hasNext=false;by('overview-content').replaceChildren();by('editor-version-list').replaceChildren();}
  return {refresh,reset};
})();

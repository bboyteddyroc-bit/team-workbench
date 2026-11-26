'use strict';
window.hubPromptTemplates=(()=>{
  let dialog;
  const button=(label,action)=>{
    const node=el('button',label);
    node.type='button';
    node.onclick=async()=>{
      const epoch=sessionEpoch;
      node.disabled=true;
      try{await action();}catch(e){if(epoch===sessionEpoch)toast(e.message,true);}
      finally{node.disabled=false;}
    };
    return node;
  };
  function reset(){
    const current=dialog;
    dialog=null;
    current?.close();
    current?.remove();
  }
  function shell(title){
    reset();
    const current=dialog=el('dialog',undefined,'material-picker prompt-library');
    const body=el('section',undefined,'prompt-library-body');
    const head=el('header',undefined,'prompt-library-head');
    head.append(el('h2',title),button('关闭',reset));
    current.append(head,body);
    current.addEventListener('close',()=>{if(dialog===current)reset();},{once:true});
    document.body.append(current);current.showModal();
    return body;
  }
  function field(label,control){
    const wrapper=el('label',label);
    wrapper.append(control);
    return wrapper;
  }
  function editor(data={},done=detail){
    const body=shell(data.id?'编辑提示词模板':'保存提示词模板');
    const title=el('input'),kind=el('select'),prompt=el('textarea'),shared=el('input');
    title.maxLength=80;title.value=data.title||'';title.required=true;
    kind.append(new Option('视频提示词','video'),new Option('生图提示词','image'));
    kind.value=data.kind||'video';
    prompt.value=data.prompt||'';prompt.rows=9;prompt.maxLength=20000;prompt.required=true;
    shared.type='checkbox';shared.checked=Boolean(data.shared);
    const form=el('form');
    form.append(field('模板名称',title));
    if(!data.source&&!data.id&&!data.copy)form.append(field('模板类型',kind));
    if(!data.source&&!data.copy)form.append(field('提示词',prompt));
    const sharing=field('共享给团队',shared);
    sharing.className='prompt-share';
    form.append(sharing,el('p','团队共享提示词和参数。素材与结果仍按成员权限查看。','fine'));
    const save=el('button','保存','primary');
    save.type='submit';form.append(save);
    form.onsubmit=async event=>{
      event.preventDefault();
      const epoch=sessionEpoch;
      save.disabled=true;
      try{
        const request={title:title.value,shared:shared.checked};
        if(data.source)Object.assign(request,{source:data.source,job:data.job});
        else if(data.copy)request.copy=data.copy;
        else Object.assign(request,{kind:kind.value,prompt:prompt.value});
        const result=await api('/prompt-templates'+(data.id?'/'+data.id+'/update':''),request);
        if(epoch!==sessionEpoch||!body.isConnected)return;
        toast('提示词模板已保存');
        await done(data.id||result.id);
      }catch(e){if(epoch===sessionEpoch)toast(e.message,true);}
      finally{save.disabled=false;}
    };
    body.append(form);title.focus();
  }
  function sourceButton(source,job){return button('保存为模板',()=>editor({source,job}));}
  function pinButton(source,job,pinned){
    let keep=Boolean(pinned);
    const control=button(keep?'取消长期保留':'长期保留',async()=>{
      const result=await api('/video-retention',{source,job,pin:!keep});
      keep=result.pinned;
      control.textContent=keep?'取消长期保留':'长期保留';
      control.setAttribute('aria-pressed',String(keep));
      toast(keep?'已长期保留':'已恢复自动清理规则');
      window.dispatchEvent(new Event('hub-tasks'));
    });
    control.setAttribute('aria-pressed',String(keep));
    return control;
  }
  function videoActions(task){
    const source=task.libtv?'libtv':'tiktok';
    return [sourceButton(source,task.id),...(task.state==='ready'?[pinButton(source,task.id,task.retained)]:[])];
  }
  const timeText=value=>value?new Date(value*1000).toLocaleString('zh-CN'):'';
  const summarize=s=>[s.channel,s.libtv_model||s.model,s.libtv_resolution||s.size,s.ratio,s.duration?s.duration+' 秒':''].filter(Boolean).join(' · ');
  function references(refs){
    const list=el('ul',undefined,'prompt-ref-list');
    for(const ref of refs){
      const item=el('li');
      if(ref.available!==false&&(ref.url||ref.id&&ref.mime?.startsWith('image/'))){
        const img=el('img');
        img.src=ref.url||'/api/assets/'+encodeURIComponent(ref.id);img.loading='lazy';img.alt='';
        item.append(img);
      }
      item.append(el('span',[ref.token?'@'+ref.token:'',ref.name,ref.available===false?'素材已不可用':''].filter(Boolean).join(' · ')));
      list.append(item);
    }
    return list;
  }
  async function detail(id,offset=0){
    const body=shell('提示词详情'),data=await api('/prompt-templates/'+id+'?offset='+offset);
    if(!body.isConnected)return;
    const actions=el('div',undefined,'task-actions');
    actions.append(button('返回提示词库',library),button('用此模板',async()=>{
      const apply=data.kind==='image'?window.hubAssistant?.usePromptTemplate:window.hubApplyVideoTemplate;
      if(!apply)throw Error('生成界面尚未就绪');
      reset();
      await apply(data);
    }),button('复制为新模板',()=>editor({copy:data.id,title:(data.title+' 副本').slice(0,80)})));
    if(data.mine)actions.append(button('编辑',()=>editor(data)));
    body.append(el('h3',data.title),actions);
    if(summarize(data.settings))body.append(el('p',summarize(data.settings),'fine'));
    body.append(el('pre',data.prompt,'prompt-template-text'));
    if(data.refs.length)body.append(el('h3','参考素材'),references(data.refs));
    body.append(el('h3','历史结果'));
    if(!data.history.length)body.append(el('p','当前账号暂无关联结果','fine'));
    for(const item of data.history){
      const row=el('article',undefined,'task prompt-history-result');
      const state=({ready:'已完成',complete:'已完成',expired:'成片已过期',pending:'进行中',running:'进行中',queued:'已排队',failed:'失败',attention:'需要核对'})[item.state]||item.state;
      row.append(el('strong',state),el('p',[timeText(item.created),summarize(item.settings)].filter(Boolean).join(' · '),'fine'));
      if(item.prompt!==data.prompt){const d=el('details');d.append(el('summary','当次提示词'),el('pre',item.prompt,'prompt-template-text'));row.append(d);}
      if(item.refs.length){const d=el('details');d.append(el('summary','当次参考素材'),references(item.refs));row.append(d);}
      if(item.urls.length){
        const d=el('details');
        d.append(el('summary',item.source==='image'?'预览图片':'预览成片'));
        d.addEventListener('toggle',()=>{
          if(!d.open){d.querySelector('video')?.pause();return;}
          if(d.children.length>1)return;
          for(const url of item.urls){
            const media=el(item.source==='image'?'img':'video');media.src=url;
            if(item.source==='image')media.alt='生成图片';else{media.controls=true;media.preload='metadata';}
            d.append(media);
          }
        });
        row.append(d);
      }
      if(item.state==='ready'&&item.source!=='image')row.append(pinButton(item.source,item.id,item.pinned));
      body.append(row);
    }
    const pages=el('div',undefined,'task-actions');
    if(offset)pages.append(button('上一页',()=>detail(id,offset-16)));
    if(offset+16<data.total)pages.append(button('下一页',()=>detail(id,offset+16)));
    body.append(pages);
  }
  async function library(){
    const body=shell('提示词库'),bar=el('div',undefined,'prompt-library-head');
    const kind=el('select'),query=el('input'),list=el('div'),status=el('p',undefined,'fine');
    kind.append(new Option('全部模板',''),new Option('视频提示词','video'),new Option('生图提示词','image'));
    kind.setAttribute('aria-label','模板类型');
    query.type='search';query.placeholder='搜索模板名称或提示词';query.maxLength=100;query.setAttribute('aria-label','搜索模板');
    let revision=0;
    const refresh=async()=>{
      const edition=++revision;
      status.textContent='正在读取模板…';
      try{
        const rows=await api('/prompt-templates?'+new URLSearchParams({kind:kind.value,q:query.value}));
        if(!body.isConnected||edition!==revision)return;
        status.textContent=rows.length?'':'暂无提示词模板';
        list.replaceChildren(...rows.map(row=>{
          const entry=el('article',undefined,'task prompt-library-head');
          entry.append(button(row.title,()=>detail(row.id)),el('span',[
            row.kind==='image'?'生图':'视频',row.shared?'团队共享':'个人','复用 '+row.uses+' 次',
            row.last_used?'最近 '+timeText(row.last_used):''
          ].filter(Boolean).join(' · '),'fine'));
          return entry;
        }));
      }catch(e){if(body.isConnected&&edition===revision)status.textContent=e.message;}
    };
    bar.append(query,kind,button('搜索',refresh),button('新建模板',()=>editor()));
    kind.onchange=refresh;query.onsearch=refresh;
    query.onkeydown=e=>{if(e.key==='Enter'&&!e.isComposing)refresh();};
    body.append(bar,status,list);await refresh();
  }
  return {library,reset,sourceButton,videoActions};
})();

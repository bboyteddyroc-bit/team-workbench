(() => {
  'use strict';
  const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const pageSize=24;
  const stateOf=x=>x.feedback_state||(x.state==='failed'?'failed':x.state==='unknown'||/结果(?:可能)?未知/.test(x.error||'')?'unknown':'attention');
  const label=s=>window.hubTaskFeedback.state(s);
  const date=t=>window.hubTaskFeedback.stamp(t)||'时间未留存';
  const typeOf=x=>x.type||x.kind;
  const title=x=>x.title&&x.title!==x.id?x.title:x.case_id?'视频案例':'任务 '+x.id;
  function row(x,i){
    const state=stateOf(x),detail=x.feedback||{},stage=detail.stage||x.saved_stage;
    const facts=[window.hubTaskFeedback.facts(detail),x.saved_code&&!detail.provider_code?`接口码 ${x.saved_code}`:''].filter(Boolean).join(' · ');
    const retry=x.kind==='文案口播提取'&&state!=='unknown';
    return `<article class="ex-row" data-row="${i}">
      <div class="ex-row-head"><strong class="ex-kind">${esc(x.kind)}</strong>${x.provider?`<span>${esc(x.provider)}</span>`:''}<span class="ex-state" data-state="${esc(state)}">${esc(label(state))}</span><time>${esc(date(x.updated))}</time></div>
      <div class="ex-id">${esc(title(x))}${x.shared?' · 团队案例':''} · 编号 ${esc(x.id)}</div>
      <p class="ex-error">${esc(x.error)}</p>
      ${stage||facts?`<p class="ex-meta">${esc([stage,facts].filter(Boolean).join(' · '))}</p>`:''}
      ${state==='unknown'?'<p class="ex-meta">请先核对原平台记录，不要重复提交。</p>':''}
      ${x.state==='partial'?'<p class="ex-meta">已取得的样本仍保留。</p>':''}
      <div class="ex-actions">
        ${x.type?'<button type="button" class="ex-refresh" data-record>查看处理记录</button>':''}
        ${x.case_id?'<button type="button" class="ex-refresh" data-case>打开案例</button>':''}
        ${retry?'<button type="button" class="ex-refresh" data-retry>重新排队</button>':''}
      </div></article>`;
  }
  window.hubExceptionCenter={async open(body){
    body.innerHTML=`<section class="ex-page" aria-label="异常任务">
      <div class="ex-filter">
        <input type="search" aria-label="搜索异常" placeholder="搜索账号、任务编号或报错">
        <select aria-label="筛选异常类型"><option value="">全部类型</option></select>
        <select aria-label="筛选处理状态"><option value="">全部状态</option>${['attention','unknown','failed','blocked'].map(s=>`<option value="${s}">${esc(label(s))}</option>`).join('')}</select>
        <span class="ex-count" role="status"></span><button type="button" class="ex-refresh" data-refresh>刷新</button>
      </div>
      <p class="ex-scope">显示本人采集、补数和脚本异常，以及团队可见案例的采集与分析异常。</p>
      <div class="ex-list" role="region" aria-label="当前异常" aria-busy="true"><p class="ex-empty" role="status">正在读取异常任务…</p></div>
      <nav class="vc-pagination ex-pages" aria-label="异常任务分页" hidden><button type="button" data-prev>上一页</button><span data-page></span><button type="button" data-next>下一页</button></nav>
      <p class="ex-foot">每种类型最多显示最近 200 条。历史任务没有逐步记录时，只显示已留存的状态和报错。</p>
    </section>`;
    const section=body.querySelector('.ex-page'),list=section.querySelector('.ex-list'),input=section.querySelector('input');
    const [type,status]=section.querySelectorAll('select'),count=section.querySelector('.ex-count');
    const refresh=section.querySelector('[data-refresh]'),paging=section.querySelector('.ex-pages');
    const prev=paging.querySelector('[data-prev]'),next=paging.querySelector('[data-next]');
    let ready=false,rows=[],visible=[],page=0;
    function render(reset=false){
      if(!ready)return;
      if(reset)page=0;
      const q=input.value.trim().toLocaleLowerCase();
      visible=rows.filter(x=>(!type.value||typeOf(x)===type.value)&&(!status.value||stateOf(x)===status.value)&&
        (!q||[x.kind,x.provider,x.id,x.title,x.error,x.feedback?.reference,x.feedback?.stage,x.saved_stage].join(' ').toLocaleLowerCase().includes(q)));
      const pages=Math.max(1,Math.ceil(visible.length/pageSize));page=Math.min(page,pages-1);
      count.textContent=`${visible.length} 条异常`;
      list.innerHTML=visible.length?visible.slice(page*pageSize,(page+1)*pageSize).map((x,i)=>row(x,page*pageSize+i)).join(''):
        (rows.length?'<p class="ex-empty">暂无匹配的异常任务，试试更换筛选条件。</p>':'<p class="ex-empty">暂无异常任务。</p>');
      paging.hidden=pages<2;paging.querySelector('[data-page]').textContent=`第 ${page+1} / ${pages} 页`;
      prev.disabled=page===0;next.disabled=page+1>=pages;
    }
    async function load(){
      if(refresh.disabled)return;
      refresh.disabled=true;list.setAttribute('aria-busy','true');
      try{
        const r=await fetch('/api/intelligence/exceptions',{credentials:'same-origin'});
        if(r.status===401)throw Error('登录已失效，请重新登录。');
        if(!r.ok)throw Error('请稍后刷新。');
        const data=await r.json();if(!section.isConnected)return;
        rows=Array.isArray(data.items)?data.items:[];
        const updated=data.scope==='current_user_and_team_cases';
        section.querySelector('.ex-scope').textContent=updated?'显示本人采集、补数和脚本异常，以及团队可见案例的采集与分析异常。':'显示当前服务已提供的异常任务。';
        if(Number.isInteger(data.limit_per_type))section.querySelector('.ex-foot').textContent=`每种类型最多显示最近 ${data.limit_per_type} 条。历史任务没有逐步记录时，只显示已留存的状态和报错。`;
        else section.querySelector('.ex-foot').textContent='当前服务未提供逐步处理记录。';
        const types=data.types||[...new Set(rows.map(x=>x.kind))].sort().map(kind=>({type:kind,kind}));
        const selected=type.value;type.replaceChildren(new Option('全部类型',''),...types.map(x=>new Option(x.kind,x.type)));
        type.value=types.some(x=>x.type===selected)?selected:'';
        ready=true;render();
      }catch(e){if(section.isConnected){count.textContent='';const message=document.createElement('p');message.className='ex-empty';message.setAttribute('role','alert');message.textContent='读取失败：'+e.message;list.replaceChildren(message);paging.hidden=true;ready=false;}}
      finally{refresh.disabled=false;list.setAttribute('aria-busy','false');}
    }
    refresh.onclick=()=>void load();input.oninput=type.onchange=status.onchange=()=>render(true);
    prev.onclick=()=>{page--;render();};next.onclick=()=>{page++;render();};
    list.onclick=async event=>{
      const button=event.target.closest('button'),article=button?.closest('[data-row]');
      if(!article||!list.contains(article))return;
      const x=visible[Number(article.dataset.row)];if(!x)return;
      if(button.hasAttribute('data-record')){
        void window.hubTaskFeedback.open('/api/intelligence/exceptions/'+encodeURIComponent(x.type)+'/'+encodeURIComponent(x.id)+'/feedback',{...x,feedback_state:stateOf(x)});return;
      }
      if(button.hasAttribute('data-case')){
        window.dispatchEvent(new CustomEvent('hub-view-video-case',{detail:{id:x.case_id}}));return;
      }
      if(!button.hasAttribute('data-retry')||!window.confirm('确认将这条口播提取任务重新排队？仅在自动处理已开启且账号仍被勾选时可执行。'))return;
      button.disabled=true;
      try{
        const response=await fetch('/api/intelligence/scripts/automation/retry/'+encodeURIComponent(x.id),{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:'{}'});
        if(!response.ok){let detail='重新排队失败';try{detail=(await response.json()).detail||detail;}catch{}throw Error(detail);}
        if(section.isConnected)await load();
      }catch(e){if(section.isConnected)window.alert(e.message);}
      finally{button.disabled=false;}
    };
    await load();
  }};
})();

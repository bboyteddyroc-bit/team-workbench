/* Video case gallery. Personal is a team-visible collection, never a privacy boundary. */
(()=>{'use strict';
const base='/api/intelligence/cases',esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={title:'详情标题',summary:'一句话看点',event:'节点',category:'适配品类 / 一级品类',content_type:'内容玩法',replicability:'可复制性',replication_actions:'复刻动作',hook_example:'Hook 示例（真实原句）',hook_template:'Hook 模板（改写建议）',suitable_products:'适合商品',production_threshold:'制作门槛',prerequisites:'适用前提',publisher:'发布账号',published_at:'发布时间',manual_views:'播放量（人工核实，注明口径）',manual_likes:'点赞（人工核实）',manual_comments:'评论（人工核实）',manual_collects:'收藏（人工核实）',manual_shares:'分享（人工核实）',merchant_visible:'商家可见（须有依据）',opening:'实际开场',audience_scenario:'人群与场景',expression:'内容 / 卖点递进',ending:'实际结尾',notes:'备注 / 待核实',transcript:'人工校对逐字稿',transcript_en:'英文版本',transcript_zh:'中文版本'};
Object.assign(labels,{manual_views:'播放量',manual_likes:'点赞',manual_shares:'分享',manual_collects:'收藏',manual_comments:'评论',manual_gmv:'GMV',manual_gmv_currency:'GMV币种',manual_metric_basis:'指标统计口径'});
const weeklyQuestions = [
  ['一、上周案例实操展示', [['imitation','1.案例模仿思路'],['feedback','2.案例数据反馈与分析'],['optimize','3.案例是否进一步优化']]],
  ['二、本周案例分享', [['video_analysis','1.视频分析'],['speech_analysis','2.口播分析']]],
  ['三、如何搬', [['product_fit','1.案例和我们产品有什么关联性'],['execution','2.如何落地']]],
  ['', [['suggestions','四、视频案列修改意见及补充']]]
];
const ideaLabels={reason:'我为什么收藏它',borrow:'我想借鉴哪一点',adaptation:'换成我们的产品怎么做',conditions:'需要什么条件 / 哪些不能照搬',hypothesis:'本次准备验证什么',result:'实际使用结果 / 复盘'};
const kindNames={metadata:'Apify 视频资料（历史）',kalodata:'Kalodata 视频资料',analysis:'AI 视频分析初填',transcript:'口播提取',ai:'AI 文字整理'},stateNames={queued:'排队中',submitting:'提交中',running:'处理中',ready:'已完成',waiting:'等待检查',attention:'需核对'};
const tagCategories=[['product','商品品类'],['format','内容玩法'],['appeal','核心吸引点'],['scene','场景与节点'],['production','制作特征'],['other','其他标签']];
let host=null,scope='team',query='',offset=0,total=0,pageSize=48,rows=[],current=null,pane='source',epoch=0,detailSerial=0,timer=null,request=null,listSerial=0,loading=false,returnFocus=null;
function tagList(r){const groups=r.tagging?.groups||{other:r.human.tags??r.ai?.fields?.tags??[]};return tagCategories.flatMap(([kind,label])=>(groups[kind]||[]).map(text=>({kind,label,text})));}
function tagHtml(t){return `<span class="vc-tag" data-tag-kind="${esc(t.kind)}" title="${esc(t.label)} · ${esc(t.text)}">${esc(t.text)}</span>`;}
function metricDisplay(m){if(!m||m.missing)return '未提供';const v=m.text||fmt(m.value);return (m.key==='gmv'?(m.currency?m.currency+' ':'币种未注明 · '):'')+v;}
function metricsOf(r){return r.metrics||[];}
function autoHeight(area){area.style.height='auto';area.style.height=Math.max(32,Math.min(260,area.scrollHeight+2))+'px';}
const fmt=n=>typeof n==='number'?new Intl.NumberFormat('zh-CN').format(n):'—',date=n=>n?new Date(n*1000).toLocaleString('zh-CN',{hour12:false}):'未提供';
async function api(path='',data,root=base){const r=await fetch(root+path,{credentials:'same-origin',...(data!==undefined?{method:'POST',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:JSON.stringify(data)}:{})});let v;try{v=await r.json()}catch{throw Error('服务暂不可用（HTTP '+r.status+'），提交结果不明确时请先刷新核查。')}if(!r.ok)throw Error(typeof v.detail==='string'?v.detail:'请求失败 '+r.status);return v;}
function note(s,error=false){if(host?.isConnected){const n=host.querySelector('[data-case-message]');if(n){n.textContent=s;n.setAttribute('role',error?'alert':'status')}}}
function empty(title,text){return `<div class="intel-empty"><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`}
Object.assign(stateNames,{waiting:'等待供应商缓存',cancelled:'已停止等待'});
function val(row,key){if(row.fields?.[key])return row.fields[key].value??'';const a=row.ai?.fields||{},h=row.human||{};return Object.hasOwn(h,key)?h[key]:(key==='category'?a.product_category:a[key])||''}
function displayTitle(r){return (Object.hasOwn(r.human||{},'title')?r.human.title:(val(r,'title')||r.source.title))||String(val(r,'summary')||'').slice(0,90)||r.handle||'待整理视频'}
function active(){return rows.some(r=>r.latest_jobs?.some(j=>['queued','submitting','running','waiting'].includes(j.state)))||current?.jobs?.some(j=>['queued','submitting','running','waiting'].includes(j.state))}
function stop(){clearTimeout(timer);timer=null;request?.abort();epoch++;detailSerial++;host?.querySelector('dialog')?.remove();host=null;current=null;loading=false}
async function load(unchangedSkip=false){if(!host?.isConnected)return;const e=epoch,serial=++listSerial;loading=true;host.querySelector('[data-case-refresh]').disabled=true;try{const data=await api(`?scope=${scope}&q=${encodeURIComponent(query)}&offset=${offset}&limit=${pageSize}`);if(e!==epoch||serial!==listSerial||!host?.isConnected)return;const unchanged=unchangedSkip&&total===data.total&&JSON.stringify(rows)===JSON.stringify(data.items);rows=data.items;total=data.total;if(!unchanged)gallery();note(`${total} 条案例 · 个人内容也对团队可见`)}catch(err){if(e===epoch&&serial===listSerial)note(err.message,true)}finally{if(e===epoch&&serial===listSerial&&host?.isConnected){loading=false;host.querySelector('[data-case-refresh]').disabled=false;clearTimeout(timer);if(active())timer=setTimeout(()=>void refreshJobs(),pollDelay())}}}
function pollDelay(){const js=[...rows.flatMap(r=>r.latest_jobs||[]),...(current?.jobs||[])];return js.some(j=>j.kind==='kalodata'&&['queued','submitting','running'].includes(j.state))?2000:8000}
async function refreshJobs(){if(!host?.isConnected||document.hidden)return;await load(true);if(current&&host?.isConnected){try{const r=await api('/'+current.id);if(current?.id===r.id){const dirty=host.querySelector('form[data-dirty=true]');if(dirty||host.querySelector('[data-clip-editor][open], [data-research-tags][open]')||document.activeElement?.closest('[data-case-comment-evidence]')||host.querySelector('[data-shot-load]:disabled')||host.querySelector('[data-pane-body] video')?.currentTime>0){current.jobs=r.jobs;current.data_status=r.data_status;current.commercial=r.commercial;current.metrics=r.metrics;const banner=host.querySelector('[data-case-data-status]');if(banner)banner.outerHTML=dataBanner(r);const facts=host.querySelector('[data-provider-facts]');if(facts){facts.querySelectorAll('[data-provider-output]').forEach(n=>{const replacement=document.createElement('div');replacement.innerHTML=providerOutputs(r);n.replaceWith(...replacement.childNodes)});const extra=facts.querySelector('[data-commercial-output]');if(extra)extra.innerHTML=commercialRows(r);const sources=facts.querySelector('[data-metric-sources]');if(sources)sources.innerHTML=metricSources(r)}const box=host.querySelector('[data-case-jobs]');if(box){box.innerHTML=jobs(r);bindWait()}}else{const scroll=host.querySelector('.vc-detail-scroll')?.scrollTop||0,expanded=[...host.querySelectorAll('.vc-detail details')].map(d=>d.open);current=r;renderDetail();host.querySelectorAll('.vc-detail details').forEach((d,i)=>d.open=!!expanded[i]);host.querySelector('.vc-detail-scroll').scrollTop=scroll}}}catch{}}}
function caseLanes(r){
 const history=r.jobs||r.latest_jobs||[];
 return [['平台数据',['metadata','kalodata'],metricsOf(r).some(m=>!m.missing)],['AI 拆解',['analysis','ai'],!!r.ai?.generated_at]].map(([label,kinds,saved])=>{
  const job=history.find(j=>kinds.includes(j.kind));
  const state=job?.state;
  const status=state==='attention'?(saved?'已有结果 · 更新失败':'待处理'):state==='ready'||(!state&&saved)?'已获取':stateNames[state]||'待获取';
  return {label,job,status};
 });
}
function bindShotReview(out,r){
 const toggle=out.querySelector('[data-shot-load]');
 if(!toggle)return;
 const player=out.querySelector('video');
 let stopAt=null;
 player.addEventListener('timeupdate',()=>{
  if(stopAt!==null && player.currentTime>=stopAt){player.pause();stopAt=null;}
 });
 for(const key of ['summary','opening','replication_actions','expression','ending']){
  const input=out.querySelector('textarea[name="'+key+'"]');
  const reason=r.ai?.evidence?.[key];
  if(!input?.value)continue;
  const saved=r.clip_reviews?.[key];
  const interval=input.value===r.ai?.fields?.[key] && !Object.hasOwn(r.human||{},key) && /^\[(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\]/.exec(reason||'');
  let start=saved?.start??Number(interval?.[1]),end=saved?.end??Number(interval?.[2]);
  const tools=document.createElement('details'),heading=document.createElement('summary');tools.dataset.clipEditor='';
  heading.textContent=saved?'调整已确认区间':'标记或确认区间';tools.append(heading);
  const times=['起点（秒）','终点（秒）'].map((label,i)=>{
   const field=document.createElement('input');field.type='number';field.step='0.01';field.min='0';
   const value=i?end:start;if(Number.isFinite(value))field.value=value;
   const wrap=document.createElement('label');wrap.append(label,field);tools.append(wrap);return field;
  });
  const confirm=document.createElement('button'),status=document.createElement('output');
  confirm.type='button';confirm.textContent='确认区间';tools.append(confirm,status);
  confirm.onclick=async()=>{
   confirm.disabled=true;
   try{
    const [a,b]=times.map(t=>t.valueAsNumber);
    const result=await api('/'+r.id+'/clip-review',{field:key,claim:input.value,start:a,end:b,revision:r.revision});
    r.revision=result.revision;start=a;end=b;button.hidden=false;
    button.textContent='播放已确认片段 · '+a+'–'+b+' 秒';heading.textContent='调整已确认区间';tools.open=false;
   }catch(err){status.textContent=err.message;}finally{confirm.disabled=false;}
  };
  const button=document.createElement('button');
  button.type='button';
  button.hidden=!Number.isFinite(end)||end<=start;
  button.textContent=(saved?'播放已确认片段 · ':'核对片段 · ')+start+'–'+end+' 秒'+(saved?'':'（待核对）');
  input.closest('label').after(button,tools);
  input.addEventListener('input',()=>{button.hidden=true;tools.hidden=true;});
  button.onclick=async()=>{
   try{
    if(player.readyState<1){await new Promise((resolve,reject)=>{
     const controller=new AbortController(),options={once:true,signal:controller.signal};
     player.addEventListener('loadedmetadata',()=>{controller.abort();resolve();},options);
     player.addEventListener('error',()=>{controller.abort();reject();},options);
     player.load();
    });}
    if(end>player.duration)throw new Error();
    stopAt=end;player.currentTime=start;player.scrollIntoView({block:'nearest'});await player.play();
   }catch{stopAt=null;button.textContent='片段无法定位，请查看原片';}
  };
 }
 toggle.onclick=async()=>{
  const dialog=document.createElement('dialog');
  dialog.className='vc-shot-viewer';
  dialog.setAttribute('aria-label','镜头回看');
  dialog.innerHTML=`<header><strong>镜头回看</strong><button type="button" data-close autofocus>关闭</button></header>
   <div class="vc-shot-workspace"><section><video controls playsinline preload="metadata" aria-label="镜头原片"></video>
   <footer><button data-prev disabled>上一镜</button><output aria-live="polite">正在读取镜头…</output><button data-next disabled>下一镜</button></footer></section>
   <aside aria-label="镜头列表"></aside></div>`;
  host.append(dialog);dialog.showModal();toggle.disabled=true;player.pause();
  const video=dialog.querySelector('video'),grid=dialog.querySelector('aside'),status=dialog.querySelector('output');
  const prev=dialog.querySelector('[data-prev]'),next=dialog.querySelector('[data-next]');
  video.src=player.currentSrc||player.src;
  dialog.querySelector('[data-close]').onclick=()=>dialog.close();
  dialog.onclose=()=>{video.pause();if(video.readyState>=1&&player.isConnected)player.currentTime=video.currentTime;dialog.remove();toggle.disabled=false;toggle.focus()};
  try{
   const {shots}=await api('/'+encodeURIComponent(r.id)+'/shots');
   if(!dialog.open||!shots.length)return;
   let selected=-1;
   const time=t=>Math.floor(t/60)+':'+(t%60).toFixed(2).padStart(5,'0');
   function highlight(index){
    if(index===selected)return;
    grid.children[selected]?.removeAttribute('aria-current');selected=index;
    grid.children[index].setAttribute('aria-current','true');
    grid.children[index].scrollIntoView({block:'nearest',inline:'nearest'});
    status.textContent='镜头 '+(index+1)+' / '+shots.length+' · '+time(shots[index].start);
    prev.disabled=index===0;next.disabled=index===shots.length-1;
   }
   function seek(index){
    if(index<0||index>=shots.length)return;
    video.pause();video.currentTime=shots[index].start;highlight(index);
   }
   shots.forEach((shot,i)=>{
    const button=document.createElement('button'),img=document.createElement('img');
    img.src='data:image/jpeg;base64,'+shot.thumbnail;img.alt='';
    button.append(img,document.createTextNode(time(shot.start)));
    button.setAttribute('aria-label','镜头 '+(i+1)+'，'+time(shot.start));
    button.onclick=()=>seek(i);grid.append(button);
   });
   prev.onclick=()=>seek(selected-1);next.onclick=()=>seek(selected+1);
   dialog.onkeydown=e=>{if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();seek(selected+(e.key==='ArrowRight'?1:-1))}};
   function indexAt(t){return Math.max(0,shots.findLastIndex(s=>s.start<=t+0.001))}
   seek(indexAt(player.currentTime));
   video.ontimeupdate=()=>{if(!video.seeking)highlight(indexAt(video.currentTime))};
  }catch(e){status.textContent=e.message}
 };
}
function gallery(){const out=host.querySelector('[data-case-grid]');out.innerHTML=rows.length?rows.map(r=>{const title=displayTitle(r),tags=tagList(r);const overview=metricsOf(r).filter(m=>['views','gmv'].includes(m.key));return `<article class="vc-card ${current?.id===r.id?'is-selected':''}"><button type="button" class="vc-cover" data-case-open="${r.id}" aria-label="查看详情：${esc(title)}">${r.cover_url?`<img src="${esc(r.cover_url)}" loading="lazy" alt="" referrerpolicy="no-referrer">`:'<span>封面未提供</span>'}<span class="vc-platform">${esc(r.platform)}</span></button><button type="button" class="vc-card-info" data-case-open="${r.id}"><strong>${esc(title)}</strong><span class="vc-tags">${tags.slice(0,2).map(tagHtml).join('')}${tags.length>2?`<span class="vc-tag">+${tags.length-2}</span>`:''}</span><span class="vc-card-metrics">${overview.map(m=>`<span title="${esc(m.source+' · '+m.scope)}">${m.label} ${esc(metricDisplay(m))}</span>`).join('')}</span><span class="vc-meta">${esc(r.handle?'@'+r.handle:r.collectors[0]?.username||'团队成员')} · ${esc(r.review_status||'待分析')}</span></button></article>`}).join(''):empty(query?'没有匹配案例':'把值得研究的视频留下来',query?'换一个关键词，或清空筛选。':'添加完整视频链接，新案例自动取数与AI初填，可能收费。');out.querySelectorAll('img').forEach(img=>img.onerror=()=>img.replaceWith(Object.assign(document.createElement('span'),{textContent:'封面暂不可用'})));out.querySelectorAll('[data-case-open]').forEach(b=>b.onclick=()=>{returnFocus=b;void openDetail(b.dataset.caseOpen)});const pager=host.querySelector('[data-case-pages]'),page=Math.floor(offset/pageSize)+1,pages=Math.max(1,Math.ceil(total/pageSize));const numbers=[...new Set([1,page-1,page,page+1,pages])].filter(x=>x>0&&x<=pages).sort((a,b)=>a-b);pager.innerHTML=`<span class="vc-page-total">共 ${total} 条</span><button type="button" data-page="${page-1}" ${page===1?'disabled':''}>上一页</button>${numbers.map((n,i)=>`${i&&n>numbers[i-1]+1?'<span>…</span>':''}<button type="button" data-page="${n}" aria-label="第${n}页" ${n===page?'aria-current="page"':''}>${n}</button>`).join('')}<button type="button" data-page="${page+1}" ${page>=pages?'disabled':''}>下一页</button><label><span class="login-sr-only">每页条数</span><select data-page-size aria-label="每页条数">${[24,48,96].map(n=>`<option value="${n}" ${n===pageSize?'selected':''}>${n} 条/页</option>`).join('')}</select></label>`;pager.querySelectorAll('[data-page]').forEach(b=>b.onclick=()=>{offset=(Number(b.dataset.page)-1)*pageSize;void load().then(()=>host?.querySelector('.vc-gallery')?.scrollIntoView({block:'start'}))});pager.querySelector('[data-page-size]').onchange=e=>{pageSize=Number(e.target.value);offset=0;void load()};}
function bindWait(){host?.querySelectorAll('[data-cancel-wait]').forEach(b=>b.onclick=async()=>{b.disabled=true;try{await api('/'+current.id+'/jobs/'+b.dataset.cancelWait+'/cancel-wait',{});await refreshJobs()}catch(e){note(e.message,true)}finally{b.disabled=false}})}
function jobs(r){return r.jobs?.length?r.jobs.slice(0,6).map(j=>`<div class="vc-job"><span>${esc(kindNames[j.kind])} · ${esc(stateNames[j.state])}${j.stage&&['queued','submitting','running','waiting'].includes(j.state)?' · '+esc(j.stage):''}</span><small>${esc(date(j.updated))}</small>${j.error?`<p role="${j.state==='waiting'?'status':'alert'}">${esc(j.error)}</p>`:''}${j.state==='waiting'?`<p>下次检查 ${esc(date(j.next_attempt))} · 已等待 ${j.wait_count}/6 轮 · 截止 ${esc(date(j.wait_deadline))}</p>${j.is_owner?`<button type="button" data-cancel-wait="${j.id}">停止自动检查</button>`:''}`:''}</div>`).join(''):'<p class="vc-muted">暂无处理记录。新 TikTok 案例通过「保存并自动分析」自动排队，可能收费；重复案例不重跑。</p>'}
async function openDetail(id,focus=true){if(current?.id!==id&&host?.querySelector('form[data-dirty=true]')&&!confirm('有未保存内容，切换案例会放弃本次修改。继续吗？'))return;const e=epoch,serial=++detailSerial;try{const r=await api('/'+id);if(e!==epoch||serial!==detailSerial||!host)return;current=r;renderDetail();gallery();if(focus)host.querySelector('[data-case-close]')?.focus({preventScroll:true})}catch(err){if(e===epoch&&serial===detailSerial)note(err.message,true)}}
function renderDetail(){const r=current,drawer=host.querySelector('[data-case-detail]');host.querySelector('.vc-layout').classList.add('has-detail');drawer.hidden=false;drawer.innerHTML=`<div class="vc-detail-top"><header class="vc-detail-head"><div><small>${esc(r.platform)} · 案例详情</small><h3>${esc(displayTitle(r))}</h3></div><button type="button" data-case-close aria-label="关闭案例详情">关闭</button></header><div class="vc-detail-actions"><a href="${esc(r.url)}" target="_blank" rel="noopener noreferrer">原视频 ↗</a>${r.platform==='TikTok'?'<button type="button" data-case-goods>关联商品</button>':''}<button type="button" data-collect>${r.mine?'移除我的收藏':'收藏到个人'}</button><details class="vc-more"><summary>更多操作</summary><div><button type="button" data-library>关联文案档案</button>${r.can_remove?'<button type="button" data-remove-case>移除视频</button>':''}</div></details></div><nav class="vc-detail-tabs" aria-label="案例详情分组">${[['source','详情'],['ideas','个人意见']].map(([id,t])=>`<button type="button" data-pane="${id}" aria-pressed="${pane===id}">${t}</button>`).join('')}</nav></div><div class="vc-detail-scroll"><div data-pane-body></div><details class="vc-processing" ${pane==='ideas'?'hidden':''}><summary>处理记录与关联脚本</summary><div data-case-jobs>${jobs(r)}</div>${r.tasks.map(t=>`<p>脚本 ${esc(String(t.number||'').padStart(3,'0'))} · ${esc(t.state)}</p>`).join('')}</details></div>`;
 if(r.platform==='TikTok'&&pane==='source'){
  const slot=document.createElement('section');slot.className='vc-section';drawer.querySelector('[data-pane-body]').before(slot);
  import('/static/comment-samples.js?v=evidence-tags1').then(m=>{if(slot.isConnected)m.mountCaseEvidence(slot,r.video);}).catch(()=>{if(slot.isConnected)slot.textContent='评论样本组件暂不可用';});
 }
 const goods=drawer.querySelector('[data-case-goods]');if(goods)goods.onclick=()=>window.dispatchEvent(new CustomEvent('hub-view-goods',{detail:{video:r.video}}));
 drawer.querySelector('[data-case-close]').onclick=closeDetail;drawer.querySelector('[data-collect]').onclick=async e=>{e.target.disabled=true;try{if(r.mine&&!confirm('只移除你的收藏，不删除团队资料及任何人的想法。继续吗？'))return;await api('/'+r.id+'/collect',{saved:!r.mine});if(!r.mine)await openDetail(r.id,false);else closeDetail();await load()}catch(err){note(err.message,true)}finally{e.target.disabled=false}};
 const removeButton=drawer.querySelector('[data-remove-case]');if(removeButton)removeButton.onclick=async()=>{if(!confirm('从团队案例库移除这个视频？其他成员将不再看到；未执行的案例任务会取消，历史资料保留。'))return;removeButton.disabled=true;try{await api('/'+r.id+'/remove',{confirm:true});const f=drawer.querySelector('form');if(f)delete f.dataset.dirty;closeDetail();await load();note('视频已从团队案例库移除')}catch(err){note(err.message,true)}finally{removeButton.disabled=false}};
 drawer.querySelector('[data-library]').onclick=async e=>{e.target.disabled=true;try{const v=await api('/'+r.id+'/library',{});note(v.existing?'已关联现有文案档案，未覆盖原内容':'文案档案已建立；不代表达到爆款标准');await openDetail(r.id,false)}catch(err){note(err.message,true)}finally{e.target.disabled=false}};
 drawer.querySelectorAll('[data-pane]').forEach(b=>b.onclick=()=>{if(drawer.querySelector('form[data-dirty=true]')&&!confirm('当前有未保存内容，切换会丢弃这些修改。继续吗？'))return;pane=b.dataset.pane;renderDetail()});renderPane();bindWait();}
function closeDetail(){if(host?.querySelector('form[data-dirty=true]')&&!confirm('有未保存内容，确认放弃本次修改？'))return;const previous=current?.id;current=null;const d=host?.querySelector('[data-case-detail]');if(d){d.hidden=true;d.replaceChildren();host.querySelector('.vc-layout').classList.remove('has-detail');gallery()}const back=previous?host?.querySelector(`[data-case-open="${previous}"]`):returnFocus;back?.isConnected&&back.focus({preventScroll:true})}
function dataBanner(r){const d=r.data_status||{state:'empty',label:'尚无平台指标',message:'未返回的指标不补零。'};return `<section class="vc-data-status" data-case-data-status data-state="${esc(d.state)}" role="status"><strong>${esc(d.label)}</strong><p>${esc(d.message)}${d.has_data&&d.state!=='ready'?' · 下方仍保留上次已取得的数据。':''}</p></section>`}
function providerOutputs(r){const job=(r.jobs||[]).find(j=>j.kind==="metadata");const failure=job?.state==="attention"?job.error:"";return `<div data-provider-output>${failure?`<p role="status">Apify 采集：${esc(failure)}</p>`:""}${metricsOf(r).map(m=>`<div class="vc-row" data-metric="${m.key}"><span class="vc-row-label">${m.label}${m.key==='gmv'?'（估算）':''}</span><div class="vc-row-content"><div class="vc-row-value">${esc(metricDisplay(m))}</div></div></div>`).join('')}<div class="vc-row"><span class="vc-row-label">数据采集时间</span><div class="vc-row-content"><div class="vc-row-value">${esc(date(r.data_status?.collected||r.source.kalodata?.collected||r.source.collected))}</div></div></div></div>`}
function commercialRows(r){return (r.commercial||[]).map(m=>{const value=m.missing?'未提供':m.kind==='ratio'?new Intl.NumberFormat('zh-CN',{style:'percent',maximumFractionDigits:2}).format(m.value):m.kind==='text'?m.value:fmt(m.value);return `<div class="vc-row" data-commercial="${esc(m.key)}"><span class="vc-row-label">${esc(m.label)}</span><div class="vc-row-content"><div class="vc-row-value">${esc(value)}</div><small>${esc(m.source)}${!m.missing?' · '+esc(m.endpoint)+' · '+esc(m.scope):''}${m.note?' · '+esc(m.note):''}</small></div></div>`}).join('')}
function metricSources(r){return metricsOf(r).map(m=>`<div class="vc-row"><span class="vc-row-label">${esc(m.label)}</span><div class="vc-row-content">${esc(m.source)}${m.scope?' · '+esc(m.scope):''}${m.collected?' · '+esc(date(m.collected)):''}</div></div>`).join('')}
function kalodataFacts(r){const k=r.source.kalodata;return `<section class="vc-section" data-provider-facts><h4>平台指标</h4><div class="vc-actions">${metricsOf(r).filter(m=>!m.missing).map(m=>`<span>${esc(m.label)} ${esc(metricDisplay(m))}</span>`).join('')}</div><details><summary>全部指标与采集时间</summary>${providerOutputs(r)}</details><details class="vc-commercial"><summary>商业与投放详情 · 接口实际字段</summary><p class="vc-muted">仅显示该视频实际返回的字段。category_ids 是排行榜筛选参数，不是视频商品类目；未返回的品类由有证据的AI建议补缺。</p><div data-commercial-output>${commercialRows(r)}</div></details><details class="vc-platform-data"><summary>更新指标与来源说明</summary><p class="vc-muted">${k?esc(k.period_start+' — '+k.period_end+'（UTC）'):'当前没有Kalodata详情结果。'}美国市场 · USD · 第三方估算，不是结算订单；不与累计快照混算。收藏数需已有公开快照或人工补充。按视频ID精确查询 /video/detail；/video/rank 是榜单筛选，不能保证查到任意链接。</p><div data-metric-sources>${metricSources(r)}</div><div class="vc-actions"><select data-kalodata-days aria-label="Kalodata 查询区间"><option value="30">近30天</option><option value="7">近7天</option></select><button type="button" data-process="kalodata">${k?'更新':'调取'}资料 · 约0.1 credits</button></div></details></section>`}
function fieldRow(r,k){const projected=r.fields?.[k];const facts={title:r.source.title,publisher:r.source.kalodata?.handle||r.handle,published_at:r.source.published?date(r.source.published):'',transcript:r.transcript};const value=projected?projected.value:(Object.hasOwn(r.human,k)?r.human[k]:(facts[k]??val(r,k)));const evidence=projected?projected.evidence:(r.ai?.evidence?.[k]||(k==='category'?r.ai?.evidence?.product_category:''));const origin=projected?.source||(Object.hasOwn(r.human,k)?'人工修订':facts[k]!==undefined&&facts[k]!==''?'来源资料':value?'AI建议 · 待审核':'未提供');const max=k.startsWith('transcript')?30000:({title:300,publisher:300,expression:6000,replication_actions:4000,event:300,category:300,content_type:300,suitable_products:2000,production_threshold:500,published_at:100,merchant_visible:100,manual_views:100,manual_likes:100,manual_comments:100,manual_collects:100,manual_shares:100,manual_gmv:100,manual_gmv_currency:10,manual_metric_basis:300}[k]||3000);return `<label class="vc-row"><span class="vc-row-label">${esc(labels[k]||k)}</span><span class="vc-row-content"><textarea name="${k}" rows="1" maxlength="${max}" placeholder="未提供">${esc(value)}</textarea></span></label>`;}
function renderUnified(r,out){const groups=r.tagging?.groups||{},main=['summary','opening','replication_actions'];out.innerHTML=`<section class="vc-overview"><div><h4>${esc(r.case_number)}<span class="vc-status">${esc(r.review_status)}</span></h4></div><div class="vc-actions">${r.platform==='TikTok'&&r.jobs?.find(j=>j.kind==='analysis')?.state==='attention'?'<button type="button" data-process="analysis">重新分析视频</button>':''}<button data-review ${!r.ai?.generated_at||r.review_status==='数据不足'?'disabled':''}>审核通过</button></div></section>${r.has_preview?`<video controls preload="none" aria-label="案例视频" style="display:block;width:100%;max-height:240px;object-fit:contain" src="${base}/${encodeURIComponent(r.id)}/preview" poster="${esc(r.cover_url||'')}"></video><button type="button" data-shot-load>查看镜头</button>`:''}<details class="vc-source"><summary>采集与分析状态</summary>${dataBanner(r)}<div class="vc-actions">${caseLanes(r).map(l=>`<span>${esc(l.label)} · ${esc(l.status)}</span>${l.job?.state==='attention'?`<details><summary>查看原因</summary><p>${esc(l.job.error)}</p>${l.job.kind==='analysis'?'':`<button data-process="${esc(l.job.kind)}">重新处理</button>`}</details>`:''}`).join('')}</div></details><details class="vc-source" data-research-tags><summary>标签依据与核对</summary><div data-tag-rows></div><p role="status"></p></details><form data-case-edit class="intel-form"><fieldset class="vc-section"><legend>内容详情</legend><div class="vc-fields">${main.map(k=>fieldRow(r,k)).join('')}<div class="vc-row"><span class="vc-row-label">分类标签</span><div class="vc-row-content"><div class="vc-tags vc-tag-preview">${tagList(r).map(tagHtml).join('')||'<span class="vc-muted">待分类</span>'}</div></div></div></div></fieldset><details class="vc-source"><summary>编辑分类标签</summary>${tagCategories.map(([id,t])=>`<label class="vc-row"><span class="vc-row-label"><span class="vc-tag" data-tag-kind="${id}">${t}</span></span><span class="vc-row-content"><input name="tag_${id}" value="${esc((groups[id]||[]).join('，'))}" maxlength="248" placeholder="逗号分隔，最多8个"></span></label>`).join('')}</details>${kalodataFacts(r)}<details class="vc-section"><summary>更多复用拆解</summary><div class="vc-fields">${['event','category','content_type','replicability','hook_example','hook_template','suitable_products','production_threshold','prerequisites','audience_scenario','expression','ending','notes'].map(k=>fieldRow(r,k)).join('')}</div></details><details class="vc-section"><summary>来源与状态</summary><div class="vc-fields">${['title','publisher','published_at','merchant_visible'].map(k=>fieldRow(r,k)).join('')}<div class="vc-row"><span class="vc-row-label">平台</span><div class="vc-row-value">${esc(r.platform)}</div></div></div></details><details class="vc-source"><summary>逐字稿与翻译</summary>${['transcript','transcript_en','transcript_zh'].map(k=>fieldRow(r,k)).join('')}</details>${r.ai?.uncertainties?.length?`<details class="vc-warning"><summary>证据与待确认 · ${r.ai.uncertainties.length} 项</summary><p class="vc-muted">${esc(r.ai.basis)}</p><ul>${r.ai.uncertainties.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></details>`:''}<div class="vc-save-bar"><button type="submit" class="primary">保存修改</button><p role="status">人工修改优先，团队可见</p></div></form>`;
 bindShotReview(out,r);const f=out.querySelector('form'),baseline=Object.fromEntries(new FormData(f));f.querySelectorAll('textarea').forEach(autoHeight);f.querySelectorAll('details').forEach(d=>d.addEventListener('toggle',()=>{if(d.open)d.querySelectorAll('textarea').forEach(autoHeight)}));f.oninput=e=>{f.dataset.dirty='true';if(e.target.tagName==='TEXTAREA')autoHeight(e.target)};f.onsubmit=e=>{e.preventDefault();const fields=Object.fromEntries(new FormData(f)),changed={};let tagsChanged=false;for(const [k,v] of Object.entries(fields)){if(k.startsWith('tag_')){if(v!==baseline[k])tagsChanged=true;}else if(v!==baseline[k])changed[k]=v;}if(tagsChanged)changed.tag_groups=Object.fromEntries(tagCategories.map(([id])=>[id,fields['tag_'+id].split(/[,，]/).map(t=>t.trim()).filter(Boolean)]));if(!Object.keys(changed).length){f.querySelector('[role=status]').textContent='没有修改';return}void submitForm(f,()=>api('/'+r.id,{revision:r.revision,fields:changed}));};out.querySelector('[data-review]').onclick=async b=>{if(f.dataset.dirty==='true'){f.querySelector('[role=status]').textContent='请先保存修改再审核';return}b.target.disabled=true;try{await api('/'+r.id+'/review',{revision:r.revision,ai_generated:r.ai.generated_at||0});await openDetail(r.id,false)}catch(e){f.querySelector('[role=status]').textContent=e.message}finally{b.target.disabled=false}};}
function bindTagReviews(box, id){
 if(!box)return;
 const list=box.querySelector('[data-tag-rows]'),status=box.querySelector('[role=status]');
 const path='/tag-review/case/'+encodeURIComponent(id),root='/api/intelligence/own-goods';
 const choices={pending:'待核对',confirmed:'已确认',rejected:'已驳回'};
 function paint(data){
  list.innerHTML=data.tags.map((t,i)=>`<div class="vc-row"><span class="vc-row-label">${esc(t.kind)}</span><div class="vc-row-content"><strong>${esc(t.label)}</strong><p class="vc-muted">${esc(t.source)}</p><select aria-label="${esc(t.label)}审核状态" data-i="${i}" ${data.can_edit?'':'disabled'}>${Object.entries(choices).map(([key,text])=>`<option value="${key}" ${t.decision===key?'selected':''}>${text}</option>`).join('')}</select></div></div>`).join('')||'<p class="vc-muted">暂无可核对的标签</p>';
  list.onchange=async e=>{
   const control=e.target.closest('select[data-i]');if(!control)return;
   const t=data.tags[Number(control.dataset.i)];list.inert=true;
   try{const updated=await api(path,{kind:t.kind,label:t.label,decision:control.value},root);paint(updated);status.textContent='已保存';}
   catch(err){control.value=t.decision;status.textContent=err.message}
   finally{list.inert=false}
  };
 }
 box.ontoggle=async()=>{if(!box.open||list.childElementCount)return;status.textContent='正在读取…';try{paint(await api(path,undefined,root));status.textContent='';}catch(err){status.textContent=err.message}};
}
function renderPane(){const r=current,out=host.querySelector('[data-pane-body]');if(pane!=='ideas'){renderUnified(r,out);bindTagReviews(out.querySelector('[data-research-tags]'),r.id);out.querySelectorAll('[data-process]').forEach(b=>b.onclick=()=>void process(r,b.dataset.process,b));return;}
{
 out.innerHTML=`<button type="button" data-add-idea>写一条复用想法</button><div data-idea-form></div>${r.ideas.map(i=>{
   const fields = {...ideaLabels,...Object.fromEntries(weeklyQuestions.flatMap(([,items])=>items))};
   return `<details class="vc-idea"><summary>${esc(i.username)} · ${esc(date(i.updated))}</summary><dl>${Object.entries(fields).filter(([key])=>i.content[key]).map(([key,label])=>`<dt>${label}：</dt><dd class="vc-pre">${esc(i.content[key])}</dd>`).join('')}</dl>${i.is_owner?`<button type="button" data-edit-idea="${i.id}">编辑我的想法</button>`:''}</details>`;
 }).join('')}`;
 out.querySelector('[data-add-idea]').onclick=()=>ideaForm(null);
 out.querySelectorAll('[data-edit-idea]').forEach(b=>b.onclick=()=>ideaForm(r.ideas.find(i=>i.id===b.dataset.editIdea)));
 }
 out.querySelectorAll('[data-process]').forEach(b=>b.onclick=()=>void process(r,b.dataset.process,b));}
async function submitForm(f,fn){const b=f.querySelector('[type=submit]');b.disabled=true;try{await fn();await openDetail(current.id,false);await load();note('已保存，团队可见')}catch(err){f.querySelector('[role=status]').textContent=err.message}finally{b.disabled=false}}
function ideaForm(i){const area=host.querySelector('[data-idea-form]');area.innerHTML=`<form class="intel-form"><h4>${i?'编辑我的想法':'新增复用想法'}</h4>${weeklyQuestions.map(([heading,items])=>`<fieldset class="vc-section">${heading?`<legend>${heading}</legend>`:''}${items.map(([key,label])=>`<label>${label}：<textarea name="${key}" rows="2" maxlength="6000">${esc(i?.content[key]||'')}</textarea></label>`).join('')}</fieldset>`).join('')}<div class="vc-actions"><button type="submit" class="primary">保存想法</button><button type="button" data-cancel>取消</button></div><p role="status"></p></form>`;const f=area.querySelector('form');f.oninput=()=>f.dataset.dirty='true';f.querySelector('[data-cancel]').onclick=()=>area.replaceChildren();f.onsubmit=e=>{e.preventDefault();void submitForm(f,()=>api('/'+current.id+'/ideas',{...(i?{id:i.id,revision:i.revision}:{}),fields:{...i?.content,...Object.fromEntries(new FormData(f))}}))};f.querySelector('textarea').focus()}
async function createScript(iid,b){b.disabled=true;try{const v=await api('/'+current.id+'/library',{});window.dispatchEvent(new CustomEvent('hub-create-script',{detail:{id:v.id,video:current.video||current.platform,case_id:current.id,idea_id:iid}}))}catch(err){note(err.message,true)}finally{b.disabled=false}}
async function process(r,kind,b){const days=Number(host.querySelector('[data-kalodata-days]')?.value||30);const text={analysis:'获取此视频的Kalodata视频地址（可能另计credits），把完整视频画面和声音、逐字稿和资料发送至 A6API Gemini 分析（单条最大50 MB），可能收费。人工修改保持优先，结果需审核。1054等待缓存最多追加6次检查（1/2/5/10/20/30分钟，24小时内截止），每次可能计费，可在处理记录停止。其他失败或结果未知不重提。继续吗？',kalodata:`将此视频 ID 发给 Kalodata，查询美国市场近${days}个完整自然日（UTC昨日截止）。预计0.1 credits，实际以供应商为准。本次新结果在案例库向团队共享，不读取私人查询历史。不自动获取封面、口播或调用AI。继续吗？`,metadata:'将此视频完整链接发送至 Apify 采集公开资料，单次费用熔断最高 $2（不是预估费用）。不采集整个作者，不启用额外视频下载或 AI 分析。实际费用以供应商为准。继续吗？',transcript:'下载此 TikTok 视频的公开音频并使用本地已就绪模型识别，产生下载流量。不自动下载模型；平台限制可能导致失败。继续吗？',ai:'将已有逐字稿 / 发布文案发送到 A6API Gemini 做文字整理，可能收费。不发送视频画面，不覆盖人工内容。继续吗？'};if(!confirm(text[kind]))return;const unknown=r.jobs.some(j=>j.kind===kind&&j.state==='attention');if(unknown&&!confirm('此类处理曾有需核对记录。请先核对原服务记录；新请求可能重复计费。确认仍要提交新的请求？'))return;b.disabled=true;const key=crypto.randomUUID();try{await api('/'+r.id+'/process',{kind,request_key:key,confirm:true,acknowledge_unknown:unknown,...(kind==='analysis'?{native_video_consent:true,native_video_policy:'a6-native-video-audio-v1'}:{}),...(kind==='kalodata'?{days,share_with_team:true}:{})});await openDetail(r.id,false);await load();note('已排队，处理完成前可继续浏览；不会自动重复提交')}catch(err){note(err.message,true)}finally{b.disabled=false}}
function addDialog(initial=''){const dialog=document.createElement('dialog');dialog.className='vc-add-dialog';dialog.innerHTML=`<form class="intel-form"><h3>添加视频案例</h3><p>每行一条链接，最多100条。保存新TikTok案例后自动：Apify单视频采集（可能收费，单次最高2美元熔断）→ 获取视频地址（另按供应商收费）→ 本地语音识别 → 发送完整视频画面和声音至 A6API Gemini 分析初填（可能收费；单条最大50 MB）。若管理员已启用 ScrapeCreators，新案例还会并行补采公开评论和部分回复（可能收费）；单独启用评论 AI 后，会把这些文本发送给 A6API 提炼。每周五北京时间08:00，对本周新增案例按视频ID查询一次Kalodata（约0.1 credits/条）；未找到不在以后各周重查，结果未知不自动重试。发送完整视频画面、声音、转写和资料给 A6API；结果向团队共享，待人工审核。重复案例不重跑。1054等待缓存会按1/2/5/10/20/30分钟最多追加6次检查，24小时内截止，每次可能计费，可停止等待；其他失败或结果未知不自动重试。TikTok需完整视频链接；其他平台仅保存链接。</p><label>视频链接<textarea name="urls" rows="5" required placeholder="https://www.tiktok.com/@账号/video/视频ID">${esc(initial)}</textarea></label><label>为什么值得留下（选填）<textarea name="reason" rows="2" maxlength="3000" placeholder="这一点会保存为你的团队可见想法"></textarea></label><p class="vc-muted">个人是归属筛选，不是私密空间。团队成员可见。</p><div class="vc-actions"><button type="submit" class="primary">保存并自动分析</button><button type="button" data-cancel>取消</button></div><p role="alert"></p></form>`;host.append(dialog);dialog.querySelector('[data-cancel]').onclick=()=>dialog.close();dialog.onclose=()=>dialog.remove();dialog.showModal();dialog.querySelector('textarea').focus();dialog.querySelector('form').onsubmit=async e=>{e.preventDefault();const f=e.target,b=f.querySelector('[type=submit]');b.disabled=true;try{const result=await api('',{urls:f.elements.urls.value.split(/\r?\n/).map(v=>v.trim()).filter(Boolean),reason:f.elements.reason.value,auto_process:true,confirm_automation:true,share_with_team:true,native_video_consent:true,native_video_policy:'a6-native-video-audio-v1'});dialog.close();offset=0;await load();if(result.items[0])await openDetail(result.items[0].id);note(result.notice)}catch(err){f.querySelector('[role=alert]').textContent=err.message}finally{b.disabled=false}}}
window.hubVideoCases={close:stop,reset(){stop();rows=[];query='';scope='team';offset=0},async open(body){stop();host=body;const e=++epoch;body.innerHTML=`<section class="vc" aria-label="视频案例库"><div class="vc-toolbar"><div class="vc-scope" aria-label="案例归属"><button type="button" data-scope="team" aria-pressed="${scope==='team'}">团队</button><button type="button" data-scope="mine" aria-pressed="${scope==='mine'}">个人</button></div><label class="vc-search"><span class="login-sr-only">搜索案例</span><input type="search" value="${esc(query)}" placeholder="搜索标题、账号、标签或个人意见" aria-label="搜索视频案例"></label><div class="vc-actions"><button type="button" data-case-refresh>刷新</button><button type="button" class="primary" data-case-add>添加视频链接</button></div></div><div class="vc-legend" aria-label="标签颜色类别">${tagCategories.slice(0,5).map(([id,t])=>`<span data-tag-kind="${id}"><i aria-hidden="true"></i>${t}</span>`).join('')}</div><p data-case-message role="status">正在读取案例…</p><div class="vc-layout"><div class="vc-gallery"><div class="vc-grid" data-case-grid></div><div class="vc-pagination" data-case-pages></div></div><aside class="vc-detail" data-case-detail role="dialog" aria-modal="false" aria-label="视频案例详情" hidden></aside></div></section>`;body.querySelector('[data-case-add]').onclick=()=>addDialog();body.querySelector('[data-case-refresh]').onclick=()=>void refreshJobs();body.querySelectorAll('[data-scope]').forEach(b=>b.onclick=()=>{scope=b.dataset.scope;offset=0;body.querySelectorAll('[data-scope]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));void load()});const input=body.querySelector('input[type=search]');input.onkeydown=ev=>{if(ev.isComposing)return;if(ev.key==='Enter'){ev.preventDefault();query=input.value.trim();offset=0;void load()}if(ev.key==='Escape'){input.value='';query='';offset=0;void load()}};input.onsearch=()=>{query=input.value.trim();offset=0;void load()};body.onkeydown=ev=>{if(ev.key==='Escape'&&!ev.isComposing&&current&&!ev.target.closest('input,textarea,dialog')){ev.stopPropagation();closeDetail()}};await load();if(e!==epoch)return;}};
window.addEventListener('resize',()=>{if(host?.isConnected)host.querySelectorAll('.vc-detail textarea').forEach(autoHeight)});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&host?.isConnected&&active()&&!loading)void refreshJobs()});
window.addEventListener('hub-view-video-case',e=>{
  document.querySelector('[data-intel-tab="reuse"]')?.click();
  if(host?.isConnected && e.detail?.id) void openDetail(e.detail.id);
});
window.addEventListener('hub-collect-video-case',async e=>{if(!confirm('保存新案例后将调用Apify单视频采集（最高2美元熔断）、获取视频并发送完整视频画面和声音至 A6API Gemini 初填（单条最大50 MB）；每周五北京时间08:00对新增案例查询一次Kalodata（约0.1 credits/条），未找到不继续重查。若管理员已启用 ScrapeCreators，将并行补采公开评论和部分回复；若另启用评论 AI，会发送这些文本给 A6API。均可能收费，结果团队可见；重复案例不重跑。继续吗？'))return;try{const data=await api('',{urls:[e.detail.url],auto_process:true,confirm_automation:true,share_with_team:true,native_video_consent:true,native_video_policy:'a6-native-video-audio-v1'});window.hubToast?window.hubToast.show(data.notice):alert(data.notice)}catch(err){alert(err.message)}});
})();

import {dashboard,disposeReport} from './own-goods-dashboard.js?v=scroll-report1';
// Evidence ledger: derived, read-only on open. User corrections are separate from the original cases.
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=v=>Number.isFinite(v)?v.toLocaleString('zh-CN',{maximumFractionDigits:2}):'—';
const stamp=v=>v?new Date(v*1000).toLocaleString('zh-CN',{hour12:false}):'未提供时间';
const fraction=d=>d?.total?`${num(d.pct)}%（${num(d.hits)}/${num(d.total)}）`:'无可计算样本';
const counts=d=>`<span>评论 ${fraction(d.comments)}</span><span>回复 ${fraction(d.replies)}</span>`;
const cite=(id,label='在内容复用查看案例')=>`<button type="button" data-research-open="${esc(id)}">${esc(label)}</button>`;
const inlineCase=id=>`<button type="button" data-research-jump="${esc(id)}">看关联证据</button>`;
const external=url=>/^https:\/\//i.test(url||'')?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">TikTok 原视频 ↗</a>`:'';
const labels={summary:'视频内容',content_type:'内容形式',audience_scenario:'视频呈现的人群 / 场景',category:'案例商品品类',opening:'开场',ending:'收尾',expression:'表现方式',replication_actions:'复用动作'};
const stateText={not_sampled:'尚未补采',queued:'待补采',running:'处理中',ready:'已取样本',partial:'仅取到部分样本',empty:'本次没有可用文本',attention:'待核对',pending:'待 AI 标注'};
const marksText={ready:'多维标注可用',queued:'旧样本补标已排队',running:'旧样本补标处理中',legacy:'仅有旧版主题，未纳入多维比例',stale:'样本与标注版本不一致，不计算比例',attention:'多维标注待核对，不自动重跑'};

export function tags(profile,max=7){
 const items=(profile?.tags||[]).filter(t=>t.decision!=='rejected');
 const chip=(label,kind,source)=>`<span class="vc-tag" data-tag-kind="${kind}" title="${esc(source)}">${esc(label)}</span>`;
 return `<div class="vc-tags" aria-label="商品标签">${items.some(t=>t.kind==='细品类')?'':chip('品类待确认','other',profile?.reason||'')}${items.slice(0,max).map(t=>chip(t.label,t.kind==='细品类'?'product':'other',t.source)).join('')}</div>`;
}

function quote(q,caseId,inside=false){
 return `<blockquote><p dir="auto">${esc(q.text)}</p><footer>${q.parent?'回复':'主评论'} · ID ${esc(q.cid)}${q.parent?'（回复 '+esc(q.parent)+'）':''}${q.published?' · '+esc(stamp(q.published)):''}${inside?'':` · ${inlineCase(caseId)}`}</footer></blockquote>`;
}
function signal(d,caseId=''){
 return `<div class="og-signal"><div class="og-line"><strong>${esc(d.label)}</strong><span class="og-counts">${counts(d)}</span></div>${d.groups.length?d.groups.map(g=>`<details class="og-sub"><summary>${esc(g.label)} · <span class="og-counts">${counts(g)}</span></summary>${g.quotes.map(q=>quote(q,caseId||q.case_id,!!caseId)).join('')}${g.comments.hits+g.replies.hits>g.quotes.length?'<p class="og-note">这里展示代表原话；案例下可核对标注及该批文本。</p>':''}</details>`).join(''):''}${d.group_count>d.groups.length?`<p class="og-note">另外 ${d.group_count-d.groups.length} 组已计入上方去重总数，逐案例可查看。</p>`:''}</div>`;
}
const allHits=d=>d.comments.hits+d.replies.hits;
function caseCard(v,d){
 const c=v.comments;
 const canSupplement=d.is_admin&&c.research_state==='legacy'&&d.queues.ai&&!d.queues.ai_error;
 const observations=Object.entries(v.video_content);
 const k=v.estimate;
 return `<details class="og-case" data-research-case="${esc(v.id)}"><summary><strong>${esc(v.title)}</strong><small>@${esc(v.handle)} · ${esc(v.match.label)} · ${c.comments||c.replies?`${c.comments} 评论 / ${c.replies} 回复`:esc(stateText[c.state])}</small></summary><div class="og-dim-body">
 <p>${esc(v.match.reason)}</p>${!v.included?`<p class="og-note">不纳入同类汇总${v.market_conflict?'：已知 Kalodata 市场 '+esc(k.region)+' 与自营档案市场不同':'；仅作人工参考'}。</p>`:''}
 <div class="vc-actions">${cite(v.id)}${external(v.url)}${d.can_edit&&v.match.kind!=='manual'?`<button type="button" data-research-exclude="${esc(v.id)}">排除此关联</button>`:''}</div>
 ${observations.length?`<dl class="og-facts">${observations.map(([key,value])=>`<div><dt>${labels[key]}</dt><dd>${esc(value.value)} <small>${esc(value.source)}</small>${value.evidence?`<p>${esc(value.evidence)}</p>`:''}</dd></div>`).join('')}</dl>`:'<p class="og-note">案例还没有可用的内容拆解。</p>'}
 <details class="og-sub"><summary>查看数据与来源</summary><p>发布时间：${v.published?esc(v.published)+' · '+esc(v.published_source):'未提供'}</p>${v.public.length?`<p>${esc(v.snap_scope)} · ${esc(stamp(v.snap_time))} · 累计</p><div class="og-counts">${v.public.map(m=>`<span>${esc(m.label)} ${num(m.value)}</span>`).join('')}</div>${v.performance_flags.length?`<p>达标：${esc(v.performance_flags.join('、'))}${v.snap_age_band?' · 观察时已发布 '+esc(v.snap_age_band):''}</p>`:''}`:'<p>没有可用的累计公开快照。</p>'}${k?`<p>Kalodata · ${esc(k.region||'市场未提供')} · ${esc(k.start||'—')} 至 ${esc(k.end||'—')}（UTC）<br>视频级区间销量估算 ${num(k.units)} · GMV 估算 ${num(k.gmv)} ${esc(k.currency)} · 关联商品数 ${num(k.product_count)}。不是自家订单。</p>`:''}${v.metrics.some(m=>!m.missing)?`<details><summary>案例字段口径（含人工修订）</summary>${v.metrics.filter(m=>!m.missing).map(m=>`<p>${esc(m.label)} ${esc(m.value??m.text)} ${esc(m.currency||'')} · ${esc(m.source)}<br>${esc(m.scope)}${m.collected?' · '+esc(stamp(m.collected)):''}</p>`).join('')}</details>`:''}${v.shops.length?`<p>视频关联店铺：${esc(v.shops.map(s=>s.name||s.id).join('、'))}</p>`:''}</details>
 <details class="og-sub"><summary>查看评论与反例</summary><p>ScrapeCreators · ${esc(stateText[c.state]||c.state)} · ${c.comments} 主评论、${c.replies} 回复${c.observed?' · 采集于 '+esc(stamp(c.observed)):''}。${esc(marksText[c.research_state]||stateText[c.ai_state]||'暂无标注')}。</p>
 ${[c.error,c.ai_error,c.research_error].filter(Boolean).map(s=>`<p class="og-note">${esc(s)}</p>`).join('')}
 ${v.signals?Object.values(v.signals).filter(x=>allHits(x)).map(s=>signal(s,v.id)).join('')||'<p>已标注文本中未识别到这些信号。</p>':''}${c.topics.length?`<details><summary>主题与反例（${c.topics.length} 组）</summary>${c.topics.map(t=>`<div class="og-sub"><strong>${esc(t.label)}</strong>${[['支持',t.support],['反例',t.counter]].map(([name,s])=>`<p>${name} · ${counts(s)}</p>${s.quotes.map(q=>quote(q,v.id,true)).join('')}`).join('')}</div>`).join('')}</details>`:''}
 ${canSupplement?`<button type="button" data-research-supplement="${esc(v.video)}">补标这条旧样本</button>`:''}${cite(v.id,'到案例查看本批文本')}</details></div></details>`;
}

function render(d){
 const reviews=d.profile.tags||[];
 return `<div data-board></div><details class="og-appendix"><summary>商品标签与来源 · ${reviews.length}</summary>${reviews.map((t,i)=>`<div class="og-tag-review"><div><b>${esc(t.label)}</b> · ${esc(t.kind)}<p>${esc(t.source)}</p></div><small>${esc(({confirmed:'已确认',rejected:'已驳回'})[t.decision]||'待核对')}</small>${d.can_edit&&t.key?`<button type="button" data-tag-index="${i}" data-decision="confirmed">确认</button><button type="button" data-tag-index="${i}" data-decision="rejected">驳回</button><button type="button" data-tag-index="${i}" data-decision="pending">撤销判断</button>`:''}</div>`).join('')||'<p>尚未取得标签</p>'}</details><details class="og-appendix"><summary>全部关联案例与管理 · ${d.cases.length}</summary><div class="og-sources"><h4>关联案例与原始证据 <span class="og-note">${d.cases.length}</span></h4>${d.cases.length?d.cases.map(v=>caseCard(v,d)).join(''):'<p>有可匹配的视频分析或商品 ID 记录后，这里会自动出现。也可修正商品品类，或在下方手动关联参考。</p>'}
 ${d.excluded.length?`<details class="og-sub"><summary>已排除的关联（${d.excluded.length}）</summary>${d.excluded.map(v=>`<div class="vc-actions"><span>视频 ${esc(v.video)}</span>${cite(v.id,'查看案例')}${d.can_edit?`<button type="button" data-research-restore="${esc(v.id)}">恢复自动关联</button>`:''}</div>`).join('')}</details>`:''}</div></details>`;
}

async function mutate(url,payload){
 const r=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:JSON.stringify(payload)});
 const data=await r.json();if(!r.ok){const e=Error(typeof data.detail==='string'?data.detail:'操作未完成');e.observed=r.status<500;throw e;}return data;
}

export function mount(host,gid,api,tools,abortSignal){
 const heading=host.querySelector('[data-research-title]'),out=host.querySelector('[data-research-body]'),notice=host.querySelector('[data-research-status]'),refresh=host.querySelector('[data-research-refresh]');
 const state={card:window.matchMedia('(min-width:1001px)').matches?'demand':'',row:0,method:''};
 let loaded=false,busy=false,saving=false,report,needsEvidence=false;
 const path=`/${encodeURIComponent(gid)}/research`;
 async function load(){
  if(busy||!host.isConnected||abortSignal?.aborted)return;busy=true;refresh.disabled=true;
  needsEvidence=false;
  notice.setAttribute('role','status');notice.textContent=loaded?'正在刷新已有证据…':'正在读取已有证据…';
  try{
   const d=await api(path);if(!host.isConnected)return;
   const dims=new Set([...out.querySelectorAll('[data-research-dimension][open]')].map(n=>n.dataset.researchDimension));
   const cases=new Set([...out.querySelectorAll('[data-research-case][open]')].map(n=>n.dataset.researchCase));
   const openDetails=[...out.querySelectorAll('.og-appendix')].map(el=>el.open);
   disposeReport(out.querySelector('[data-board]'));report=d;out.innerHTML=render(d);dashboard(out.querySelector('[data-board]'),tools,d,state,abortSignal);
    const reason=d.profile.notice||(!d.profile.tags.some(t=>t.kind==='细品类'&&t.decision!=='rejected')&&(d.profile.category?'该细品类已被驳回，不参与同品类匹配。':d.profile.reason));
    if(reason){const note=document.createElement('p');note.className='og-note';note.textContent=reason;out.prepend(note);}
   out.querySelectorAll('.og-appendix').forEach((el,i)=>el.open=!!openDetails[i]);loaded=true;notice.textContent='';
   out.querySelectorAll('[data-research-dimension]').forEach(n=>n.open=dims.has(n.dataset.researchDimension));
   out.querySelectorAll('[data-research-case]').forEach(n=>n.open=cases.has(n.dataset.researchCase));
   return true;
  }catch(e){if(host.isConnected){notice.setAttribute('role','alert');notice.textContent=`报告读取失败：${e.message}${loaded?'。保留上次结果。':''}`;}return false;}
  finally{busy=false;refresh.disabled=false;if(needsEvidence&&!saving)void load();}
 }
 refresh.onclick=()=>{if(!saving)void load();};
 host.onclick=async e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.dataset.decision){
   if(saving||busy)return;const tag=report?.profile.tags[Number(b.dataset.tagIndex)];if(!tag)return;
   saving=true;b.disabled=true;
   try{await api('/tag-review/goods/'+encodeURIComponent(gid),{kind:tag.kind,label:tag.label,decision:b.dataset.decision});await load();}catch(err){notice.textContent=err.message;notice.setAttribute('role','alert');}finally{saving=false;b.disabled=false;}
   return;
  }
  if(b.dataset.researchOpen){window.dispatchEvent(new CustomEvent('hub-view-video-case',{detail:{id:b.dataset.researchOpen}}));return;}
  if(b.dataset.researchJump){const v=out.querySelector(`[data-research-case="${CSS.escape(b.dataset.researchJump)}"]`);if(v){v.open=true;v.querySelector('summary')?.focus();v.scrollIntoView({block:'start'});}return;}
  const id=b.dataset.researchExclude||b.dataset.researchRestore,supply=b.dataset.researchSupplement;
  if((!id&&!supply)||saving||busy||!report)return;
  const excluded=!!b.dataset.researchExclude;
  if(supply&&!confirm('仅为此视频的旧样本安排一次额外 A6API 标注，使用现有每日预算，可能收费。只传公开文本及序号，不重新采集，不外发商品档案。未知结果不重提。确认排队？'))return;
  if(excluded&&!confirm('从此款商品的自动报告中排除该案例？内容复用原案例、旧样本与人工证据仍保留。'))return;
  saving=true;b.disabled=true;notice.setAttribute('role','status');notice.textContent='正在保存…';
  try{
   const result=supply?await mutate(`/api/intelligence/comment-samples/${encodeURIComponent(supply)}/research`,{confirm_ai:true}):await api(path+'/exclusion',{case_id:id,excluded});
   if(!host.isConnected)return;
   if(await load())notice.textContent=supply?(result.queued_now?'已排队，稍后可刷新报告。':'已有补标记录，未重复提交。'):(excluded?'已排除，原始案例保留。':'已恢复自动关联。');
   refresh.focus();
  }catch(err){
   if(host.isConnected){notice.setAttribute('role','alert');notice.textContent=err.observed?err.message:'保存结果待核对，请先刷新报告，勿重复提交。';if(!err.observed)refresh.focus();else b.disabled=false;}
  }finally{saving=false;}
 };
 let lastStamp=null,checking=false;
 async function check(initial=false){
  if(checking||!host.isConnected||host.hidden||document.hidden||saving||(!initial&&busy))return;
  checking=true;
  try{const {stamp}=await api(path+'/stamp');
   if(!initial&&stamp!==lastStamp){if(await load())lastStamp=stamp;}else lastStamp=stamp;
  }catch{}finally{checking=false;}
 }
 void check(true);const timer=setInterval(()=>{if(!host.isConnected)clearInterval(timer);else void check();},30000);
 abortSignal?.addEventListener('abort',()=>clearInterval(timer),{once:true});
 heading.title='基于已有案例与样本，不发起外部取数';void load();
 return ()=>{if(busy||saving)needsEvidence=true;else void load();};
}

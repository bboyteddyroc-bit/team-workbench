const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const imageOK=s=>typeof s==='string'&&(/^https:\/\//i.test(s)||/^\/(api|static)\//.test(s));
const pct=r=>Number.isFinite(r?.hits)&&r.total>0?Math.max(0,Math.min(100,r.hits/r.total*100)):null;
const clock=t=>Number.isFinite(t)?Math.floor(t/60)+':'+String(Math.floor(t%60)).padStart(2,'0'):'待定位';
const image=e=>imageOK(e.thumb)?`<img loading="lazy" decoding="async" src="${esc(e.thumb)}" alt="来源视频画面">`:'<span class="ogr-no-image">暂无画面</span>';
const names={fit:'商品适配',demand:'用户需求',scene:'使用场景',barrier:'购买阻力',performance:'拍法表现',shots:'可复用镜头'};
export function evidenceItems(cards){
 const seen=new Map(),items=[];
 for(const card of cards)for(const row of card.rows||[])for(const e of row.evidence||[]){
  const key=e.cid?`${e.video||e.case_id}:${e.cid}`:JSON.stringify([e.case_id,e.source,e.text,e.time,e.description]);
  if(seen.has(key)){const old=seen.get(key);if(!old.dimensions.includes(card.id))old.dimensions.push(card.id);continue;}
  const item={key,dimensions:[card.id],row,e};seen.set(key,item);items.push(item);
 }
 return items;
}
function source(item){
 const {e,row,dimensions}=item;
 const chinese=e.translation||e.meaning;
 const jump=e.case_id?`<button type="button" data-research-open="${esc(e.case_id)}">查看原案例 ↗</button>`:'';
 const link=/^https:\/\//i.test(e.url||'')?`<a href="${esc(e.url)}" target="_blank" rel="noopener noreferrer">原视频 ↗</a>`:'';
 return `<article class="ogr-evidence"><div class="ogr-tags">${dimensions.map(id=>`<span>${esc(names[id])}</span>`).join('')}<small>${esc(e.source||row.label)}</small></div><div class="ogr-quote">${image(e)}<div><h4>${esc(chinese||e.description||e.text||row.label)}</h4>${chinese?`<small>${e.translation?'中文译文':'中文要点 · 尚无逐句译文'}</small><p class="ogr-original" dir="auto">${esc(e.text)}</p>`:''}<small>${esc(e.handle||e.title||'商品档案')}</small></div></div><footer>${jump}${link}</footer></article>`;
}
function metric(r){const p=pct(r);return `<div class="ogr-metric"><div><span>${esc(r.label)}${(r.detail||'').startsWith('回复')?' · 回复':''}</span><b>${p===null?esc(r.value):Math.round(p)+'% · '+esc(r.value)}</b></div>${p===null?'':`<span class="ogr-track"><i style="--fill:${p}%"></i></span>`}<small>${esc(r.detail)}</small></div>`;}
function gauge(r){const p=pct(r);if(p===null)return '<p class="ogr-empty">暂无可计算的评论样本</p>';return `<div class="ogr-gauge"><svg viewBox="0 0 240 145" role="img" aria-label="${esc(r.label)} ${Math.round(p)}%"><path class="ogr-gauge-track" d="M 20 120 A 100 100 0 0 1 220 120" pathLength="100"/><path class="ogr-gauge-fill" d="M 20 120 A 100 100 0 0 1 220 120" pathLength="100" stroke-dasharray="${p} 100"/><text x="120" y="99" text-anchor="middle">${Math.round(p)}%</text></svg><strong>${esc(r.label)}</strong><small>${esc(r.value)} 条主评论 · 非购买概率</small><small>${esc(r.detail)}</small></div>`;}
function visual(card,cases){
 const rows=card.rows||[],numeric=rows.filter(r=>pct(r)!==null),main=numeric.find(r=>(r.detail||'').startsWith('主评论'));
 if(card.id==='demand'||card.id==='barrier')return `<div class="ogr-summary">${gauge(main)}<div class="ogr-metrics">${rows.filter(r=>r!==main).map(metric).join('')||'<p class="ogr-empty">等待更多可核实的信号</p>'}</div></div>`;
 if(card.id==='fit')return `<div class="ogr-fit"><strong>商品档案</strong><div>${rows.map(r=>`<div><span>${esc(r.label)}</span><small>${esc(r.value)} · ${esc(r.detail)}</small></div>`).join('')||'<p>尚无可核实的商品特征</p>'}</div></div>`;
 if(card.id==='shots')return `<div class="ogr-shots">${rows.map(r=>{const e=r.evidence?.[0];return e?`<article><div class="ogr-shot-image">${image(e)}</div><h4>${esc(r.label)} <small>${clock(e.frame_time)}</small></h4><small>${esc(e.frame_kind||'待定位')} · ${esc(r.value)}</small>${e.case_id?`<button type="button" data-play="${esc(e.case_id)}" data-seconds="${Number.isFinite(e.time)?e.time:0}" data-end="${Number.isFinite(e.end)?e.end:''}">定位原视频 ↗</button>`:''}</article>`:'';}).join('')||'<p class="ogr-empty">尚无可定位的镜头证据</p>'}</div>`;
 if(card.id==='performance'){
  const valid=cases.filter(v=>v.included&&Number.isFinite(v.views_snapshot)&&Number.isFinite(v.baseline?.median)&&v.baseline.median>0);
  return `${valid.length?`<div class="ogr-baselines">${valid.map(v=>`<div><span>@${esc(v.handle)}</span><b>${(v.views_snapshot/v.baseline.median).toFixed(2)}×</b><small>相对同账号播放中位数 · ${esc(v.baseline.count)} 条对照视频</small></div>`).join('')}</div>`:'<p class="ogr-callout">缺少可比基线，暂不判断拍法优劣</p>'}<div class="ogr-metrics">${rows.map(metric).join('')}</div>`;
 }
 return `<div class="ogr-metrics">${rows.map(metric).join('')||'<p class="ogr-empty">暂无可核实的场景样本</p>'}</div>`;
}
const cleanups=new WeakMap();
export function disposeReport(out){cleanups.get(out)?.();cleanups.delete(out);}
export function renderReport(out,tools,cards,cases,coverage,signal){
 disposeReport(out);
 const items=evidenceItems(cards),shown=new Set();
 tools.innerHTML=`<div class="og-methods"><strong>商品综合证据报告</strong><span>${cases.length} 条关联视频 · ${coverage.accounts||0} 位达人 · ${coverage.analysed_videos||0} 条视频已分析评论</span><small>高赞优先抽样 · 主评论与回复分别统计</small></div>`;
 const sections=cards.map((card,index)=>{
  const examples=items.filter(x=>x.dimensions.includes(card.id)&&!shown.has(x.key)).slice(0,2);examples.forEach(x=>shown.add(x.key));
  return `<section class="ogr-section" data-dimension="${esc(card.id)}"><h3><span>${String(index+1).padStart(2,'0')}</span>${esc(card.title)}</h3>${visual(card,cases)}<div class="ogr-evidence-grid">${examples.map(source).join('')}</div></section>`;
 }).join('');
 const remaining=items.filter(x=>!shown.has(x.key));let cursor=0;
 out.innerHTML=`<div class="ogr-report"><nav class="ogr-progress" aria-label="报告阅读进度">${cards.map(c=>`<span data-progress="${esc(c.id)}">${esc(names[c.id]||c.title)}</span>`).join('')}</nav><p class="ogr-intro">综合结果来自全部有效关联样本；向下阅读判断依据与原始来源。</p>${sections}<section class="ogr-more"><h3>继续浏览全部证据</h3><p>按维度标记 · 去重展示 · 滚动自动加载</p><div class="ogr-evidence-grid" data-feed></div><p class="ogr-sentinel" data-sentinel role="status"></p></section></div>`;
 const feed=out.querySelector('[data-feed]'),sentinel=out.querySelector('[data-sentinel]');
 let stopped=false,raf=0;
 const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
 const reveal=!reduce&&typeof IntersectionObserver!=='undefined'?new IntersectionObserver(entries=>{for(const e of entries)if(e.isIntersecting){e.target.classList.add('ogr-visible');reveal.unobserve(e.target);}},{threshold:0.03}):null;
 function observe(node){if(!reveal)return;node.classList.add('ogr-reveal');reveal.observe(node);}
 out.querySelectorAll('.ogr-section > :not(h3)').forEach((node,i)=>{node.style.setProperty('--reveal-delay',(i%3)*60+'ms');observe(node);});
 function images(){out.querySelectorAll('img:not([data-error-bound])').forEach(img=>{img.dataset.errorBound='1';const fail=()=>{const p=document.createElement('span');p.className='ogr-no-image';p.textContent='截图暂不可用';img.replaceWith(p);};img.addEventListener('error',fail,{once:true});if(img.complete&&!img.naturalWidth)fail();});}
 function append(){if(stopped||!out.isConnected)return;const batch=remaining.slice(cursor,cursor+12);cursor+=batch.length;feed.insertAdjacentHTML('beforeend',batch.map(source).join(''));sentinel.textContent=cursor<remaining.length?`已展示 ${shown.size+cursor} / ${items.length} 条可追溯证据，继续下拉加载`:'已展示本次报告返回的全部证据';images();}
 append();
 // A near-viewport sentinel loads only saved evidence; it never schedules paid work.
 const loader=typeof IntersectionObserver!=='undefined'?new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)&&cursor<remaining.length){append();loader.unobserve(sentinel);requestAnimationFrame(()=>{if(!stopped)loader.observe(sentinel);});}},{rootMargin:'300px'}):null;
 if(loader)loader.observe(sentinel);else if(out.isConnected)while(cursor<remaining.length)append();
 function progress(){raf=0;if(stopped)return;const sections=[...out.querySelectorAll('[data-dimension]')];const y=out.querySelector('.ogr-progress').getBoundingClientRect().bottom+80;const active=sections.filter(el=>el.getBoundingClientRect().top<=y).at(-1)||sections[0];out.querySelectorAll('[data-progress]').forEach(el=>{const yes=el.dataset.progress===active?.dataset.dimension;el.classList.toggle('is-current',yes);if(yes)el.setAttribute('aria-current','step');else el.removeAttribute('aria-current');});}
 function scroll(){if(!out.isConnected){cleanup();return;}if(!raf)raf=requestAnimationFrame(progress);}
 document.addEventListener('scroll',scroll,true);progress();images();
 function cleanup(){stopped=true;reveal?.disconnect();loader?.disconnect();document.removeEventListener('scroll',scroll,true);cancelAnimationFrame(raf);signal?.removeEventListener('abort',cleanup);out.querySelectorAll('video').forEach(v=>v.pause());}
 cleanups.set(out,cleanup);signal?.addEventListener('abort',cleanup,{once:true});
 out.onclick=ev=>{const b=ev.target.closest('[data-play]');if(!b)return;out.querySelectorAll('video').forEach(v=>{v.pause();v.remove();});const v=document.createElement('video');v.controls=true;v.playsInline=true;v.src='/api/intelligence/cases/'+encodeURIComponent(b.dataset.play)+'/preview#t='+encodeURIComponent(b.dataset.seconds)+(b.dataset.end?','+encodeURIComponent(b.dataset.end):'');v.onerror=()=>{const p=document.createElement('p');p.textContent='原片暂不可用，请到内容复用查看来源。';v.replaceWith(p);};b.closest('article').append(v);v.play().catch(()=>{});};out.onkeydown=null;
}

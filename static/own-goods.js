import {mount as mountResearch,tags as researchTags} from './own-goods-research.js?v=scroll-report1';
import {mountLookup} from './own-goods-lookup.js?v=auto-cover1';
const base='/api/intelligence/own-goods';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kinds={comment:'视频评论',review:'商品评价',search:'搜索线索',video:'视频内容核查',own:'自家商品核实'};
const relations={same:'同款',similar:'相似款',analogy:'场景或痛点类比'};
const evidenceRelations={...relations,self:'自家规格或实测'};
const sides={support:'支持',counter:'反例',context:'背景'};
const options=(items,selected='')=>Object.entries(items).map(([k,v])=>`<option value="${esc(k)}" ${selected===k?'selected':''}>${esc(v)}</option>`).join('');
const link=(url,text)=>/^https:\/\//i.test(url||'')?`<a href="${esc(url)}" target="_blank" rel="noopener noreferrer">${esc(text)}</a>`:'';
const plain=v=>`<p class="intel-pre" dir="auto">${esc(v)}</p>`;
const values=f=>Object.fromEntries(new FormData(f));
const coverPlaceholder='<span aria-hidden="true">▧</span>';
function coverVisual(g,thumb=false){
 const path=`${base}/${encodeURIComponent(g.id)}/cover`;
 const url=typeof g.cover_url==='string'&&g.cover_url.startsWith(path+'?v=')&&/^[a-f\d]{16}$/.test(g.cover_url.slice(path.length+3))?g.cover_url:'';
 return url?`<img src="${esc(url)}" alt="${thumb?'':esc(g.name+'主图')}" ${thumb?'loading="lazy"':''} decoding="async">`:coverPlaceholder;
}
const fillLabel={queued:'主图待补',running:'正在补主图',retry:'主图将重试',blocked:'主图待核对'};
const productCard=g=>`<button type="button" class="vc-card og-product-card" data-cover-row="${esc(g.id)}" data-id="${esc(g.id)}" aria-label="查看 ${esc(g.name)}">
 <span class="og-product-card-head">
  <span class="og-list-thumb" aria-hidden="true">${coverVisual(g,true)}</span>
  <small data-image-fill ${fillLabel[g.cover_fill]?'':'hidden'}>${fillLabel[g.cover_fill]||''}</small>
 </span>
 <strong class="og-product-card-name">${esc(g.name)}</strong>
 <small>${esc(g.shop)} · ${esc(g.market)}${g.sku?' · SKU '+esc(g.sku):''}</small>
 ${researchTags(g.tag_profile,3)}
 <span class="og-product-card-metric"><small>人工关联参考</small><strong>${esc(g.links)} 条</strong></span>
 <small>${esc(g.topics)} 项判断</small>
</button>`;
async function api(path='',payload,signal){
 const post=payload!==undefined;
 const r=await fetch(base+path,{signal,method:post?'POST':'GET',headers:post?{'Content-Type':'application/json','X-Hub-Request':'1'}:{},body:post?JSON.stringify(payload):undefined});
 const data=await r.json();if(!r.ok){const e=Error(typeof data.detail==='string'?data.detail:'读取失败，请核对登录和服务状态');e.observed=r.status<500;e.status=r.status;throw e;}return data;
}
export function open(host){
 const screen=document.createElement('section');screen.className='vc own-goods';screen.setAttribute('aria-label','自营商品');host.replaceChildren(screen);
 screen.innerHTML=`<div class="intel-direct-tools"><form class="intel-direct-fields" data-search><input type="search" name="q" maxlength="160" placeholder="搜索商品、店铺、市场或 SKU" aria-label="搜索商品、店铺、市场或 SKU"><button type="submit">搜索</button></form><button type="button" class="primary intel-direct-action" data-add>添加自营商品</button></div><p role="status" data-status></p><div data-list></div><div class="vc-pagination" data-pages></div><aside class="vc-detail" role="region" aria-label="自营商品详情" hidden></aside>`;
 const $=q=>screen.querySelector(q), list=$('[data-list]'),pages=$('[data-pages]'),drawer=$('aside');
 const sourceButton=document.createElement('button');sourceButton.type='button';sourceButton.textContent='主图图源';sourceButton.hidden=true;
 const add=$('[data-add]'),tools=document.createElement('div');tools.className='intel-direct-actions';add.before(tools);add.classList.remove('intel-direct-action');tools.append(sourceButton,add);
 let offset=0,query='',row=null,detailId='',req=0,serial=0,previousFocus=null,listAbort,detailAbort,listTimer,sourceOpening=false;
 let visibleGoods=new Map();
 const active=()=>screen.isConnected;
 const listPath=()=>`?q=${encodeURIComponent(query)}&offset=${offset}`;
 function message(text,error=false){const el=$('[data-status]');el.setAttribute('role',error?'alert':'status');el.textContent=text;}
 function patchCover(g){
  const old=visibleGoods.get(g.id);if(!old)return;
  const card=list.querySelector(`[data-cover-row="${CSS.escape(g.id)}"]`);if(!card)return;
  if(g.cover_url!==old.cover_url)card.querySelector('.og-list-thumb').innerHTML=coverVisual(g,true);
  const hint=card.querySelector('[data-image-fill]'),label=fillLabel[g.cover_fill]||'';
  if(hint.textContent!==label){hint.textContent=label;hint.hidden=!label;}
  visibleGoods.set(g.id,g);
 }
 function pollSoon(){
  clearTimeout(listTimer);
  const states=[...visibleGoods.values()].map(g=>g.cover_fill);
  const delay=states.some(s=>s==='queued'||s==='running'||s==='retry')?4500:states.includes('blocked')?30000:0;
  if(active()&&delay)listTimer=setTimeout(()=>void pollCovers(),delay);
 }
 async function pollCovers(){
  if(!active())return;
  if(!drawer.hidden||document.hidden){pollSoon();return;}
  const token=req;
  try{const d=await api(listPath()+'&covers=true',undefined,listAbort.signal);if(token===req&&active())d.items.forEach(patchCover);}
  catch{/* Only a read, never a resubmission. */}
  finally{if(token===req)pollSoon();}
 }
 async function load(){
  clearTimeout(listTimer);
  const token=++req;listAbort?.abort();listAbort=new AbortController();message('正在读取商品…');
  try{const d=await api(listPath(),undefined,listAbort.signal);if(token!==req||!active())return;
   sourceButton.hidden=d.can_configure_cover_source!==true;
   visibleGoods=new Map(d.items.map(g=>[g.id,g]));
   if(offset&&offset>=d.total){offset=Math.max(0,Math.floor((d.total-1)/d.page_size)*d.page_size);return load();}
   message(`${d.total} 款自营商品 · 团队共享`);
   list.innerHTML=d.items.length?`<div class="vc-grid og-product-grid">${d.items.map(productCard).join('')}</div>`:`<div class="intel-empty"><h3>${query?'没有匹配商品':'还没有自营商品'}</h3><p>${query?'换一个关键词再查。':'先登记一款真实商品。不连接店铺、不付费取数也能开始。'}</p></div>`;
   pages.innerHTML=d.total>d.page_size?`<button type="button" data-page="${offset-d.page_size}" ${offset===0?'disabled':''}>上一页</button><span>第 ${Math.floor(offset/d.page_size)+1} / ${Math.ceil(d.total/d.page_size)} 页</span><button type="button" data-page="${offset+d.page_size}" ${offset+d.page_size>=d.total?'disabled':''}>下一页</button>`:'';
   pollSoon();
  }catch(e){if(e.name!=='AbortError'&&token===req&&active())message(e.message,true);}
 }
 function closeDetail(){const id=detailId;serial++;detailAbort?.abort();detailId='';row=null;drawer.hidden=true;drawer.replaceChildren();(previousFocus?.isConnected?previousFocus:list.querySelector(`button[data-id="${CSS.escape(id)}"]`)||$('[data-add]'))?.focus();pollSoon();}
 async function detail(id,topic='',focus=true){
  const token=++serial; detailId=id;detailAbort?.abort();detailAbort=new AbortController();
  if(!row||row.id!==id){drawer.hidden=false;drawer.innerHTML=`<div class="vc-detail-top"><div class="vc-detail-head"><h3>正在读取商品…</h3><button type="button" data-close>关闭</button></div></div>`;if(focus)drawer.querySelector('[data-close]').focus();}
  try{const d=await api('/'+encodeURIComponent(id),undefined,detailAbort.signal);if(token!==serial||!active())return;row=d;renderDetail(topic);if(focus&&topic)drawer.querySelector(`[data-topic="${CSS.escape(topic)}"] summary`)?.focus();else if(focus)drawer.querySelector('[data-close]')?.focus();}
  catch(e){if(e.name!=='AbortError'&&token===serial&&active()){message(e.message,true);drawer.innerHTML=`<div class="vc-detail-top"><div class="vc-detail-head"><h3>${esc(e.message)}</h3><button type="button" data-close>关闭</button></div></div>`;drawer.querySelector('[data-close]').focus();}}
 }
 function renderDetail(expand){
  drawer.hidden=false;
  const coverImg=`<span class="og-cover-visual">${coverVisual(row)}</span>`;
  const cover=row.can_edit?`<label class="og-product-image" title="更换商品主图">${coverImg}<input type="file" accept="image/png,image/jpeg,image/webp" aria-label="更换商品主图"></label>`:`<div class="og-product-image">${coverImg}</div>`;
  drawer.innerHTML=`<div class="vc-detail-top og-product-head">${cover}<div class="og-product-name"><small>${esc(row.shop)} · ${esc(row.market)}</small><h3>${esc(row.name)}</h3><div data-method-tools></div></div><div class="og-head-actions"><button type="button" data-archive-toggle aria-expanded="false">商品档案</button><button type="button" data-close>返回列表</button></div></div><p class="og-cover-status" role="status"></p><div class="vc-detail-scroll"><div data-manual-panel hidden><div class="vc-actions"><button type="button" class="primary" data-new-topic>添加待验证判断</button><button type="button" data-add-ref>关联已有参考</button>${row.can_edit?'<button type="button" data-edit>编辑档案</button>':''}</div><section aria-label="证据结论"><h3>证据结论</h3>${row.topics.length?row.topics.map(t=>`<article class="intel-form"><p><strong>${esc(t.status)}</strong> · ${t.counts.support} 条支持 / ${t.counts.counter} 条反例</p>${t.counts.support&&t.status!=='证据有分歧'?`<h3>${esc(t.claim)}</h3>`:`<h3>待核对：${esc(t.claim)}</h3>`}<p>${esc(t.result)} 外部支持覆盖 ${t.external_angles} 类证据、${t.external_groups} 个录入来源组，不代表市场占比。</p><details data-topic="${esc(t.id)}" ${expand===t.id?'open':''}><summary>查看原始证据（${t.evidence_count} 条）</summary><div data-originals role="region" aria-label="原始证据"></div></details><button type="button" data-evidence="${esc(t.id)}">补充证据</button></article>`).join(''):'<div class="intel-empty"><h3>暂无结论</h3><p>先添加一项可验证的判断，例如「用户反复询问安装尺寸」，再补支持证据和反例。</p></div>'}</section><section data-own-references><h3>人工关联的参考样本</h3>${row.links.length?row.links.map(r=>`<div class="vc-row"><span class="vc-row-label">${r.kind==='case'?'视频案例':'竞品'}<br>${esc(relations[r.relation])}</span><div class="vc-row-content"><strong>${esc(r.title)}</strong>${r.detail?plain(r.detail):''}${link(r.url,'查看原视频')}${r.metrics?.some(m=>!m.missing)?`<details><summary>已有案例指标及口径</summary>${r.metrics.filter(m=>!m.missing).map(m=>`<p>${esc(m.label)} ${esc(m.value??m.text)} ${esc(m.currency||'')} · ${esc(m.source)} · ${esc(m.scope)}</p>`).join('')}</details>`:''}${r.can_edit?`<button type="button" data-unlink="${esc(r.ref)}" data-kind="${esc(r.kind)}">解除关联</button>`:''}</div></div>`).join(''):'<p>暂无关联样本。可以用场景或痛点类比，不必强行找同款。</p>'}</section><section><h3>自营商品档案</h3><div class="vc-row"><span class="vc-row-label">商品链接</span><div>${link(row.url,'查看商品页面')}</div></div><div class="vc-row"><span class="vc-row-label">SKU</span>${plain(row.sku||'未提供')}</div><div class="vc-row"><span class="vc-row-label">规格与事实</span>${plain(row.facts||'尚未核实')}</div></section></div>`;
  const manual=drawer.querySelector('[data-manual-panel]'),toggle=drawer.querySelector('[data-archive-toggle]');
  const showManual=show=>{manual.hidden=!show;research.hidden=show;toggle.setAttribute('aria-expanded',String(show));toggle.textContent=show?'返回证据报告':'商品档案';};
  toggle.onclick=()=>showManual(manual.hidden);
  const gid=row.id,file=drawer.querySelector('input[type=file]'),visual=drawer.querySelector('.og-cover-visual');
   function showCover(next){
    Object.assign(row,{cover_url:next.cover_url,cover_source:next.cover_source,cover_observed:next.cover_observed,cover_basis:next.cover_basis});
    visual.innerHTML=coverVisual(row);
    if(visibleGoods.has(gid))patchCover({...visibleGoods.get(gid),...row,cover_fill:next.cover_fill?.state});
   }
  if(file)file.onchange=async()=>{
   const selected=file.files[0];if(!selected)return;
   const status=drawer.querySelector('.og-cover-status');file.disabled=true;status.textContent='正在保存商品主图…';
   try{const res=await fetch(base+'/'+encodeURIComponent(gid)+'/cover',{method:'POST',headers:{'Content-Type':selected.type,'X-Hub-Request':'1'},body:selected});
    if(!res.ok){let data={};try{data=await res.json();}catch{}throw Error(data.detail||'主图上传失败');}
    if(detailId===gid&&file.isConnected){await detail(gid,'',false);void load();}
   }catch(err){if(file.isConnected){status.textContent=err.message;file.disabled=false;file.value='';}}
  };
  const scroll=drawer.querySelector('.vc-detail-scroll');
  // Identify the retained manual references before inserting the derived evidence ledger.
  const refs=scroll.querySelectorAll('[data-own-references] .vc-row-content');
  const research=document.createElement('section');research.className='og-research';research.setAttribute('aria-label','自动证据报告');
  research.innerHTML=`<div class="og-heading"><h3 data-research-title>自动证据报告</h3><button type="button" data-research-refresh>刷新报告</button></div><p role="status" data-research-status></p><div data-research-body>${researchTags(row.tag_profile)}</div>`;
  scroll.prepend(research);
  if(expand)showManual(true);
  const signal=detailAbort.signal;
  const reloadReport=mountResearch(research,row.id,(path,data)=>api(path,data,signal),drawer.querySelector('[data-method-tools]'),signal);
  if(row.lookup){
   const lookup=document.createElement('section');lookup.className='og-lookup';lookup.setAttribute('aria-label','商品链接与资料');
   scroll.prepend(lookup);
   const check=mountLookup(lookup,row,api,signal,()=>{void reloadReport();void load();},showCover);
   research.querySelector('[data-research-refresh]').addEventListener('click',()=>void check(),{signal});
  }
  const slots=[];
  row.links.forEach((r,i)=>{
   const id=r.available&&r.kind==='case'&&/^https:\/\/www\.tiktok\.com\/@[\w.]+\/video\/(\d{5,25})(?:[/?#]|$)/.exec(r.url)?.[1];
   if(!id||!refs[i])return;
   const details=document.createElement('details');details.dataset.commentSample=id;
   details.innerHTML='<summary>评论样本与 AI 提炼</summary><div data-sample-body>正在加载组件…</div>';
   refs[i].append(details);slots.push(details);
  });
  if(slots.length)import('/static/comment-samples.js?v=1').then(m=>slots.filter(s=>s.isConnected).forEach(m.attachEvidence)).catch(()=>slots.filter(s=>s.isConnected).forEach(s=>s.querySelector('[data-sample-body]').textContent='评论样本组件未加载，请刷新后查看。'));
 }
 drawer.addEventListener('toggle',async ev=>{
  const d=ev.target,tid=d.dataset?.topic;if(!tid||!d.open||d.dataset.loaded)return;
  const area=d.querySelector('[data-originals]');d.dataset.loaded='pending';area.innerHTML='<p role="status">正在读取证据…</p>';
  try{const {items}=await api(`/${row.id}/topics/${tid}/evidence`);if(!d.isConnected)return;
   area.innerHTML=items.length?items.map(e=>`<div class="vc-row"><span class="vc-row-label">${esc(kinds[e.kind])}<br>${esc(sides[e.side])}<br>${esc(evidenceRelations[e.relation])}</span><div class="vc-row-content">${plain(e.quote)}<p>${esc(e.observed)} · ${esc(e.source_group)}</p><p>采样口径：${esc(e.sample)}</p><p>${e.sample_total===null?'未提供可计算分母':`该批样本命中 ${e.sample_hits} / ${e.sample_total}（${(e.sample_hits/e.sample_total*100).toLocaleString('zh-CN',{maximumFractionDigits:2})}%），不跨样本合并`}</p>${link(e.source_url,'打开证据来源')}${e.can_edit?` <button type="button" data-remove="${esc(e.id)}" data-tid="${esc(tid)}">移除证据</button>`:''}</div></div>`).join(''):'<p>还没有证据。可录入原话、出处和采样范围。</p>';
   d.dataset.loaded='true';
  }catch(e){delete d.dataset.loaded;area.innerHTML=`<p role="alert">${esc(e.message)}。请折叠后重新展开。</p>`;}
 },true);
 function modal(title,fields,onSave,setup){
  const opener=document.activeElement;
  const d=document.createElement('dialog');d.className='vc-add-dialog';d.setAttribute('aria-label',title);
  d.innerHTML=`<form class="intel-form"><h3>${esc(title)}</h3>${fields}<div class="vc-actions"><button type="submit" class="primary">保存</button><button type="button" data-cancel>取消</button></div><p role="alert"></p></form>`;
  screen.append(d);const f=d.querySelector('form'),b=f.querySelector('[type=submit]');
  d.querySelector('[data-cancel]').onclick=()=>d.close();d.addEventListener('close',()=>d.remove(),{once:true});
  f.onsubmit=async ev=>{ev.preventDefault();if(b.disabled)return;b.disabled=true;const alert=f.querySelector('[role=alert]');alert.textContent='';
   try{await onSave(values(f),f);if(d.open){d.close();if(!drawer.hidden)(drawer.querySelector('details[open] summary')||drawer.querySelector('[data-close]'))?.focus();else if(opener?.isConnected)opener.focus();}}
   catch(e){alert.textContent=e.message;}finally{b.disabled=b.dataset.locked==='1';}
  };
  d.showModal();setup?.(d,f,b);
 }
 sourceButton.onclick=async()=>{
  if(sourceOpening||sourceButton.hidden||$('dialog[open]'))return;
  sourceOpening=true;sourceButton.setAttribute('aria-busy','true');
  try{
   const original=await api('/cover-source');if(!active()||$('dialog[open]')||!drawer.hidden)return;
   const label=c=>c.configured?(c.enabled?'已启用（未验证连接）':'已暂停'):'未配置';
   modal('主图图源',`<p>领星 MCP · 美国站（US）</p><p data-source-status role="status">${label(original)}</p><p>开启后会按准确商品 ID 补齐缺图档案，不发起 Kalodata 查询。请使用有对应商品分析读取权限的独立领星密钥。</p><label>自动读取<select name="enabled"><option value="on" ${!original.configured||original.enabled?'selected':''}>启用</option><option value="off" ${original.configured&&!original.enabled?'selected':''}>暂停</option></select></label><label>领星 MCP 密钥${original.configured?'（留空保留）':''}<input name="key" type="password" autocomplete="new-password" maxlength="512" spellcheck="false" ${original.configured?'':'required'}></label><p>密钥加密保存，不回显。暂停不删除已保存图片。<a href="https://www.lingxing.com/help/article/mcp" target="_blank" rel="noopener noreferrer">查看领星授权说明 ↗</a></p>`,async (data,form)=>{
    try{
     const saved=await api('/cover-source',{enabled:data.enabled==='on',key:data.key||'',expected_updated:original.updated});
     message(`领星主图图源：${label(saved)}。`);void pollCovers();
    }catch(e){
     if(e.observed&&e.status!==409)throw e;
     form.elements.key.value='';form.querySelector('[type=submit]').dataset.locked='1';
     const fresh=await api('/cover-source').catch(()=>null);
     if(fresh)form.querySelector('[data-source-status]').textContent=`当前：${label(fresh)}`;
     throw Error(e.status===409?e.message:'本次保存结果未确认，未再次提交。请关闭后查看当前配置。');
    }
   },(_d,form)=>{const select=form.elements.enabled,key=form.elements.key;select.onchange=()=>{const enabled=select.value==='on';key.disabled=!enabled;key.required=enabled&&!original.configured;};select.onchange();});
  }catch(e){if(active())message(e.message,true);}
  finally{sourceOpening=false;sourceButton.removeAttribute('aria-busy');}
 };
 const field=(name,label,max,value='',other='required')=>`<label>${label}<input name="${name}" maxlength="${max}" value="${esc(value)}" ${other}></label>`;
 function edit(r){modal(r?'编辑自营商品':'添加自营商品',`<p>仅登记自家运营的商品。建议填完整的 TikTok Shop 商品页链接。新版支持在保存后自动补齐主图，不发起 Kalodata 查询。</p>${field('name','商品名称',140,r?.name)}${field('shop','店铺名称',120,r?.shop)}${field('market','市场（两位国家代码）',2,r?.market||'US')}${field('url','商品 HTTPS 链接',1800,r?.url,'required type="url"')}${field('sku','SKU 或规格版本（选填）',140,r?.sku,'')}${field('category','细品类（选填，留空自动识别）',36,r?.tag_profile?.override,`placeholder="${esc(r?.tag_profile?.category||'例如：脏衣篮')}"`)}<p>细品类用于匹配案例，例如「脏衣篮」，不要填「家居」等大类。已保存的人工标签优先。</p><label>已核实规格和适用条件（选填）<textarea name="facts" rows="3" maxlength="3000">${esc(r?.facts)}</textarea></label>`,async d=>{const out=await api('',r?{...d,id:r.id,revision:r.revision}:d);if(!active())return;if(!r){query='';offset=0;$('[data-search]').elements.q.value='';}await Promise.all([load(),detail(out.id)]);});}
 function reference(){
  const gid=row.id;
  modal('关联已有参考',`<label>来源<select name="kind"><option value="case">视频案例</option><option value="competitor">竞品商品</option></select></label><label>名称、账号或编号<input name="keywords" type="search" maxlength="160"></label><button type="button" data-find>查找</button><p data-find-status role="status"></p><label>匹配结果<select required name="ref"><option value="">先查找</option></select></label><label>与自家商品的关系<select name="relation">${options(relations,'analogy')}</select></label>`,async ({kind,ref,relation})=>{
   await api(`/${gid}/links`,{kind,ref,relation});await refresh(gid);
  },(d,f,save)=>{
   let token=0;const ref=f.elements.ref,kind=f.elements.kind,q=f.elements.keywords,status=f.querySelector('[data-find-status]');
   function clear(){token++;ref.replaceChildren(new Option('先查找',''));save.disabled=true;status.textContent='';}
   kind.onchange=clear;q.oninput=clear;clear();
   f.querySelector('[data-find]').onclick=async()=>{clear();if(!q.value.trim()){status.textContent='请输入关键词';q.focus();return;}const n=token;status.textContent='正在查找…';try{const data=await api(`/references?kind=${kind.value}&q=${encodeURIComponent(q.value)}`);if(token!==n||!d.open)return;for(const x of data.items)ref.add(new Option(`${x.title}${x.detail?' · '+x.detail:''}`,x.id));status.textContent=data.more?'仅显示前 20 条，请缩小范围以查看更多':'找到 '+data.items.length+' 条';save.disabled=!data.items.length;ref.focus();}catch(e){if(token===n&&d.open)status.textContent=e.message;}};
  });
 }
 async function refresh(id,topic=''){if(active())await Promise.all([load(),detail(id,topic)]);}
 function newTopic(){const id=row.id;modal('添加待验证判断',`${field('claim','一句话判断',200)}<p>例如「用户反复询问窄水槽能否安装」。没有证据前不会标成已验证。</p>`,async d=>{const t=await api(`/${id}/topics`,d);await refresh(id,t.id);});}
 function evidence(tid){
  const id=row.id;
  modal('补充证据',`<label>证据类型<select name="kind">${options(kinds)}</select></label><label>倾向<select name="side">${options(sides)}</select></label><label>与自家商品的关系<select name="relation">${options(relations,'analogy')}</select></label>${field('source_group','来源组（同一账号或商品请保持一致）',160)}${field('source_url','原始来源 HTTPS 链接',1800,'','type="url"')}${field('observed','观察日期',10,'','required type="date"')}<label>原话或可核实的观察<textarea name="quote" rows="3" required maxlength="1000"></textarea></label><label>采样口径与局限（市场、时间、抽取范围，例如「US，评论前两页，非全量」）<textarea name="sample" rows="2" required maxlength="300"></textarea></label><details data-sample><summary>填写已逐条查验的样本计数（选填）</summary><p>没有完整查过这一批样本，就留空。不要用总评论数替代已查样本。</p><label>实查样本总数<input name="sample_total" type="number" min="1" max="1000000" step="1"></label><label>命中条数<input name="sample_hits" type="number" min="0" max="1000000" step="1"></label></details>`,async d=>{
   for(const key of ['sample_total','sample_hits'])d[key]=d[key]===''||d[key]===undefined?null:Number(d[key]);
   await api(`/${id}/topics/${tid}/evidence`,d);await refresh(id,tid);
  },(_d,f)=>{const el=f.elements;
   function sync(){const own=el.kind.value==='own',counts=['comment','review'].includes(el.kind.value);el.side.innerHTML=options(own?{context:sides.context}:sides);el.relation.innerHTML=options(own?{self:evidenceRelations.self}:relations,own?'self':'analogy');el.source_url.required=!own;f.querySelector('[data-sample]').hidden=!counts;el.sample_hits.disabled=el.sample_total.disabled=!counts;}
   el.kind.onchange=sync;sync();
  });
 }
 screen.onclick=async e=>{
  const b=e.target.closest('button');if(!b)return;
  if(b.hasAttribute('data-add'))return edit(null);
  if(b.dataset.id){previousFocus=b;return detail(b.dataset.id);}
  if(b.dataset.page!==undefined){offset=Number(b.dataset.page);return load();}
  if(b.hasAttribute('data-close'))return closeDetail();
  if(!row)return;
  if(b.hasAttribute('data-edit'))return edit(row);
  if(b.hasAttribute('data-add-ref'))return reference();
  if(b.hasAttribute('data-new-topic'))return newTopic();
  if(b.dataset.evidence)return evidence(b.dataset.evidence);
  const id=row.id;
  if(b.dataset.remove||b.dataset.unlink){
   if(!confirm(b.dataset.remove?'移除这条证据？结论状态会重新计算。':'解除关联？不会删除原样本。'))return;
   b.disabled=true;try{if(b.dataset.remove)await api(`/${id}/topics/${b.dataset.tid}/evidence`,{id:b.dataset.remove,remove:true});else await api(`/${id}/links`,{kind:b.dataset.kind,ref:b.dataset.unlink,remove:true});await refresh(id,b.dataset.tid);}catch(err){if(active())message(err.message,true);}finally{b.disabled=false;}
  }
 };
 drawer.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();closeDetail();}});
 $('[data-search]').onsubmit=e=>{e.preventDefault();query=values(e.target).q.trim();offset=0;void load();};
 void load();
}

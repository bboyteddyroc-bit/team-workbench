const root='/api/intelligence/comment-samples';
const esc=v=>String(v??'').replace(/[&<>"']/g,s=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s]));
const labels={queued:'待采集',running:'处理中',ready:'已完成',partial:'部分样本',empty:'本次无可用文本',attention:'需核对',pending:'待提炼'};
const sources={backfill:'历史案例回填',case:'新增视频案例',monitor:'历史监测样本 · 已收录为案例'};
const stamp=n=>n?new Date(n*1000).toLocaleString('zh-CN'):'—';
async function api(path='',payload){
 const r=await fetch(root+path,payload?{method:'POST',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:JSON.stringify(payload)}:{});
 const data=await r.json();if(!r.ok){const e=Error(typeof data.detail==='string'?data.detail:'请求失败');e.status=r.status;throw e;}return data;
}
const status=s=>labels[s]||'未知';
function samples(node,d){
 const map=new Map(d.samples.map(x=>[x.cid,x]));
 const entry=x=>`<div class="vc-row"><span class="vc-row-label">${x.parent?'回复':'评论'}<br>${esc(stamp(x.published))}</span><div class="vc-row-content"><p class="intel-pre" dir="auto">${esc(x.text)}</p><small>评论 ID ${esc(x.cid)}${x.parent?' · 主评论 '+esc(x.parent):''} · 采集 ${esc(stamp(x.observed))}</small></div></div>`;
 const fraction=d=>d.total?`${d.pct}%（${d.hits}/${d.total}）`:'无可计算样本';
 const research=d.research&&Object.values(d.research).filter(s=>s.groups.length);
 const marked=research?`<details><summary>多维标注：核对命中原话</summary><p>AI 仅标注这批文本，评论和回复单独计算；标签可重叠，比例并非人数或市场占比。</p>${research.length?research.map(s=>`<div class="vc-row"><span class="vc-row-label">${esc(s.description)}</span><div class="vc-row-content"><p>评论 ${fraction(s.comments)} · 回复 ${fraction(s.replies)}</p>${s.groups.map(g=>`<details><summary>${esc(g.label)} · 评论 ${fraction(g.comments)} · 回复 ${fraction(g.replies)}</summary>${g.ids.map(id=>map.has(id)?entry(map.get(id)):'').join('')}</details>`).join('')}</div></div>`).join(''):'<p>已标注文本未识别到这些信号。</p>'}</details>`:'';
 const citations=(title,group)=>group.ids.length?`<details><summary>${title}：${d.comments?`${group.comments}/${d.comments} 条评论`:'无评论样本'} · ${d.replies?`${group.replies}/${d.replies} 条回复`:'无回复样本'}</summary>${group.ids.map(id=>map.has(id)?entry(map.get(id)):'').join('')}</details>`:`<p>${title}：未标注命中；不能推断样本之外的情况。</p>`;
 node.innerHTML=`<p><strong>ScrapeCreators · ${esc(status(d.state))}</strong> · ${esc(sources[d.origin])} · 采集于 ${esc(stamp(d.finished||d.started))}</p><p>有效样本 ${d.comments} 条评论、${d.replies} 条回复（独立分母），读取 ${d.pages} 页评论、${d.reply_pages} 页回复。${esc(d.stop_reason)}</p>${d.error?`<p role="alert">${esc(d.error)}</p>`:''}<p>AI：${esc(status(d.ai_state))}${d.model?' · '+esc(d.model):''}。主题为 AI 建议，编号和计数由程序核对；同一视频的评论与回复不是独立来源。</p>${d.ai_error?`<p role="alert">${esc(d.ai_error)}</p>`:''}${d.topics.map(t=>`<div class="intel-form"><strong>${esc(t.label)}</strong>${citations('支持',t.support)}${citations('反例',t.counter)}</div>`).join('')}${d.ai_state==='ready'&&!d.topics.length?'<p>AI 本次未给出可引用的主题。</p>':''}${marked}<details><summary>查看本批文本（${d.samples.length} 条，每条至多保留 420 字符）</summary>${d.samples.length?d.samples.map(entry).join(''):'<p>本次没有可用文本。</p>'}</details><p><a href="${esc(d.url)}" target="_blank" rel="noopener noreferrer">打开 TikTok 原视频</a></p>`;
}
export function mountEvidence(host,video){
 if(!/^\d{5,25}$/.test(String(video)))return;
 const details=document.createElement('details');details.dataset.commentSample=video;
 details.innerHTML='<summary>评论样本与 AI 提炼</summary><div data-sample-body></div>';
 host.append(details);attachEvidence(details);
}
export function mountCaseEvidence(host,video){
 if(!/^\d{5,25}$/.test(String(video)))return;
 host.className='vc-section';host.dataset.caseCommentEvidence='';
 host.innerHTML='<h4>评论样本与 AI 提炼</h4><p role="status" data-sample-state>正在读取评论样本…</p><div class="vc-actions"><button type="button" data-sample-refresh>刷新评论与 AI 结果</button></div><div data-sample-body></div>';
 const notice=host.querySelector('[data-sample-state]'),button=host.querySelector('[data-sample-refresh]'),node=host.querySelector('[data-sample-body]');
 const load=async()=>{
   if(button.disabled)return;button.disabled=true;notice.textContent='正在读取评论样本…';
   try{const d=await api('/'+video);if(host.isConnected){samples(node,d);notice.textContent='';}}
   catch(e){if(host.isConnected){node.replaceChildren();notice.textContent=e.status===404?'此案例暂无评论样本。可在「数据接入」查看采集是否启用，或将未采样案例加入回填。':e.message;}}
   finally{button.disabled=false;}
 };
 button.onclick=()=>void load();void load();
}
export function attachEvidence(section){
 const video=section.dataset.commentSample;
 if(!/^\d{5,25}$/.test(video))return;
 let busy=false;
 const load=async()=>{
  if(!section.open||busy||section.dataset.loaded)return;
  const node=section.querySelector('[data-sample-body]');busy=true;node.textContent='正在读取评论样本…';
  try{const d=await api('/'+video);if(!section.isConnected)return;samples(node,d);if(!['queued','running'].includes(d.state)&&!['pending','running'].includes(d.ai_state))section.dataset.loaded='1';}
  catch(e){if(section.isConnected)node.textContent=e.status===404?'尚未补采此视频。请在「数据接入」配置采集与回填。':e.message;}
  finally{busy=false;}
 };
 section.addEventListener('toggle',load);if(section.open)void load();
}
export function config(host){
 host.innerHTML=`<section class="intel-form"><h3>ScrapeCreators · TikTok 评论与回复</h3><p>只补采「内容复用」中已收录的 TikTok 视频评论和部分回复。竞对账号监测不触发补采，Apify 基础数据采集不变。按视频 ID 去重，非全量。</p><p role="status" data-cs-state>正在读取设置…</p><div data-cs-fields></div><p role="status" data-cs-message></p></section><section class="intel-form"><h3>评论样本与 AI 提炼</h3><p>样本分视频查看。AI 只建议议题及引用，程序分别计算评论和回复命中数，不把建议写成自营结论。</p><div class="vc-actions"><button type="button" data-cs-refresh>刷新状态和样本</button></div><div data-cs-list></div><div class="vc-pagination" data-cs-pages></div></section>`;
 const $=q=>host.querySelector(q),state=$('[data-cs-state]'),fields=$('[data-cs-fields]'),notice=$('[data-cs-message]'),list=$('[data-cs-list]'),pages=$('[data-cs-pages]');
 let cfg,offset=0,loading=false,busy=false;
 const n=(name,label,value,min,max)=>`<label>${label}<input type="number" name="${name}" min="${min}" max="${max}" step="1" value="${value}" required></label>`;
 function show(c){
  cfg=c;const u=c.usage,job=c.counts,ai=c.ai_counts;
  state.textContent=`${c.configured?'Key 已保存（未验证额度）':'未配置 ScrapeCreators Key'} · 采集${c.collect_error?'已暂停待核对':c.collect?'已启用':'已停用'} · AI ${c.ai_error?'已暂停待核对':c.ai?'已启用':'已停用'}。今日预留 ${u.requests||0}/${c.daily||'不限'} 次采集请求、${u.ai_calls||0}/${c.ai_daily||'不限'} 次 AI；已报告 ${u.reported_credits||0} credits${u.unreported?'，另有 '+u.unreported+' 次费用未获报告':''}。待采 ${job.queued||0}，处理中 ${job.running||0}，已取样本 ${(job.ready||0)+(job.partial||0)}，待 AI ${ai.pending||0}。`;
  if(!c.admin){fields.innerHTML='<p>管理员可配置 Key、预算和自动化；成员可以查阅团队样本。</p>';return;}
  fields.innerHTML=`${c.collect_error?`<p role="alert">${esc(c.collect_error)}</p>`:''}${c.ai_error?`<p role="alert">${esc(c.ai_error)}</p>`:''}<form data-cs-save><div class="intel-fields"><label>ScrapeCreators API Key<input type="password" name="key" autocomplete="new-password" spellcheck="false" minlength="10" maxlength="500" ${c.configured?'placeholder="留空保留原 Key"':'required'}></label>${n('daily','每日采集请求上限（0 为不限）',c.daily,0,100)}${n('pages','每条视频最多评论页数',c.pages,1,3)}${n('replies','最多抽取几个回复线程（各取第一页）',c.replies,0,3)}${n('ai_daily','每日 AI 请求上限（0 为不限）',c.ai_daily,0,30)}</div><p>保存只加密写入，不调用供应商；保存后采集与 AI 都需重新启用。已有样本保留。</p><div class="intel-form-actions"><button class="primary" type="submit">保存 ScrapeCreators 设置</button></div></form><div class="vc-actions"><button type="button" data-action="${c.collect&&!c.collect_error?'disable':'enable'}" ${c.configured?'':'disabled'}>${c.collect_error?'核对后恢复采集':c.collect?'暂停采集':'确认费用并启用采集'}</button>${c.collect&&!c.collect_error&&c.backfill_remaining?'<button type="button" data-action="backfill">将未采样案例加入回填</button>':''}<button type="button" data-action="${c.ai&&!c.ai_error?'disable_ai':'enable_ai'}" ${c.ai_configured?'':'disabled'}>${c.ai_error?'核对后恢复 AI':c.ai?'暂停 AI 提炼':'确认并启用 AI 提炼'}</button>${c.collect_error?'<button type="button" data-action="disable">停用采集</button>':''}${c.ai_error?'<button type="button" data-action="disable_ai">停用 AI</button>':''}</div>${c.ai_configured?'':'<p>A6API 尚未配置，请先在现有 A6API 设置中保存密钥。采集不受影响。</p>'}`;
  const form=fields.querySelector('form');form.onsubmit=e=>{e.preventDefault();const payload=Object.fromEntries(new FormData(form));for(const k of ['daily','ai_daily','pages','replies'])payload[k]=Number(payload[k]);void change({...payload,action:'save'});};
  fields.querySelectorAll('[data-action]').forEach(b=>b.onclick=()=>{
   const action=b.dataset.action;
   const paid=action==='enable'||action==='backfill',ai=action==='enable_ai';
   if(paid&&!confirm(`确认按${cfg.daily?'每天最多 '+cfg.daily+' 次请求':'每日不限次数'}启用 ScrapeCreators？将优先回填「内容复用」中已有的 TikTok 案例，之后仅补采新增案例。不会从竞对账号自动补采。请求可能消耗 credits；结果未知的任务不会自动重跑。`))return;
   if(ai&&!confirm(`确认把公开样本文本发送给 A6API 进行收费提炼（${cfg.ai_daily?'每天最多 '+cfg.ai_daily+' 次':'每日不限次数'}，已有样本也会进入队列）？不会发送视频、账号资料或凭据。`))return;
   void change({action,confirm_paid:paid,confirm_ai:ai});
  });
 }
 async function change(payload){
  if(busy||loading)return;busy=true;notice.textContent='正在保存…';
  fields.querySelectorAll('button').forEach(x=>x.disabled=true);
  try{const d=await api('/config',payload);if(!host.isConnected)return;show(d);notice.textContent=payload.action==='save'?'已加密保存，尚未启用。':`已保存${d.queued_now?`，本次新增 ${d.queued_now} 条回填任务`:''}。`;await refresh(false);}
  catch(e){if(host.isConnected){if(cfg)show(cfg);notice.textContent=e.status?e.message:'保存结果待核对，请先刷新状态，勿重复提交。';}}
  finally{busy=false;}
 }
 async function refresh(withConfig=true){
  if(loading)return;loading=true;
  try{
   if(withConfig){const c=await api('/config');if(!host.isConnected)return;show(c);}
   const r=await api('?offset='+offset);if(!host.isConnected)return;
   list.innerHTML=r.items.map(row=>`<details data-comment-sample="${esc(row.video)}"><summary>${esc(row.video)} · ${esc(sources[row.origin])} · ${esc(status(row.state))} · ${row.samples} 条样本</summary><div data-sample-body></div></details>`).join('')||'<p>暂无样本任务。启用后会回填库内已有 TikTok 案例。</p>';
   list.querySelectorAll('[data-comment-sample]').forEach(attachEvidence);
   pages.innerHTML=r.total>20?`<button type="button" data-prev ${offset===0?'disabled':''}>上一页</button><span>${offset+1}–${Math.min(offset+20,r.total)} / ${r.total}</span><button type="button" data-next ${offset+20>=r.total?'disabled':''}>下一页</button>`:'';
   pages.querySelector('[data-prev]')?.addEventListener('click',()=>{offset=Math.max(0,offset-20);void refresh(false);});pages.querySelector('[data-next]')?.addEventListener('click',()=>{offset+=20;void refresh(false);});
  }catch(e){if(host.isConnected)(cfg?list:state).textContent=e.status===404?'当前服务尚未加载 ScrapeCreators 接口。':e.message;}
  finally{loading=false;}
 }
 $('[data-cs-refresh]').onclick=()=>{if(!busy)void refresh();};void refresh();
}

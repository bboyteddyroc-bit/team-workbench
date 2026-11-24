(() => {
'use strict';
let epoch=0,timer;
const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const date=x=>x?new Date(x*1000).toLocaleString('zh-CN'):'—';
const num=x=>x==null?'—':Number(x).toLocaleString('zh-CN');
const states={queued:'待补数',running:'补数中',waiting:'等待收录',ready:'已补齐',attention:'需核对',unavailable:'暂未收录'};
async function api(path,data){const r=await fetch('/api/intelligence/apify/'+path,{credentials:'same-origin',...(data?{method:'POST',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:JSON.stringify(data)}:{})});const d=await r.json();if(!r.ok)throw Error(typeof d.detail==='string'?d.detail:'请求失败');return d;}
function close(){epoch++;clearTimeout(timer);}
function open(node){
close();const token=epoch,selected=new Set();let viewed=null,busy=false;
node.innerHTML=`<div class="intel-toolbar"><div><h2>竞对账号</h2><p>Apify 先抓公开视频；Kalodata 后补 GMV、销量与历史趋势。数据仅当前成员可见。</p></div></div>
<form class="intel-form" id="ap-add"><label>账号或 TikTok 主页链接<input name="handle" required maxlength="500" placeholder="@tooltime93"></label><button class="primary">保存监测账号</button></form>
<form class="intel-form" id="ap-options"><div class="intel-fields"><label>视频发布日期范围<select name="mode"><option value="today">当天</option><option value="seven" selected>近 7 天（含今天）</option><option value="custom">自定义日期</option></select></label><label>日期时区<select name="timezone"><option value="America/New_York">美国东部时间</option><option value="Asia/Shanghai">北京时间</option><option value="UTC">UTC</option></select></label><label>开始日期<input type="date" name="start" disabled></label><label>结束日期<input type="date" name="end" disabled></label><label>每账号数量上限<select name="limit"><option>30</option><option>100</option><option>300</option></select></label></div><p>单次采集及新定时任务使用以上范围；滚动日期随执行日期更新。</p><button type="button" id="ap-batch">采集勾选账号（Apify 付费）</button><p id="ap-budget" role="status"></p></form>
<p>Apify 每账号每次向平台设置 $0.50 费用上限，日期筛选可能额外收费，实际以供应商为准。数量上限不保证采全。自动任务需中台服务持续运行。</p>
<p>Kalodata 默认关闭，按账号单独开启。只补已抓取视频，按视频 ID 关联；美国市场、USD、UTC 前两日截止（保守等待，不是实时水位）。新视频等待成熟；第三方估算不等于结算订单，不覆盖 Apify 播放快照。飞书提醒未接入。</p>
<p id="ap-message" role="status"></p><div id="ap-accounts"></div><div id="ap-videos"></div>`;
const message=t=>{if(token===epoch)node.querySelector('#ap-message').textContent=t;};
const settings=node.querySelector('#ap-options');settings.onsubmit=e=>e.preventDefault();
settings.elements.mode.onchange=()=>{for(const key of ['start','end']){settings.elements[key].disabled=settings.elements.mode.value!=='custom';settings.elements[key].required=!settings.elements[key].disabled;}};
const readOptions=()=>{if(!settings.reportValidity())throw Error('请填写完整日期');const d=Object.fromEntries(new FormData(settings));d.limit=Number(d.limit);return d;};
const budget=()=>node.querySelector('#ap-budget').textContent=`已选 ${selected.size} 个账号，Apify 本批上限 $${(selected.size*0.5).toFixed(2)}；最多 10 个账号。Kalodata 额度另计。`;budget();
async function act(button,fn){busy=true;button.disabled=true;try{await fn();}catch(e){message(e.message);}finally{busy=false;if(token===epoch){button.disabled=false;await refresh();}}}
node.querySelector('#ap-batch').onclick=e=>act(e.target,async()=>{if(!selected.size)throw Error('请先勾选账号');await api('batch',{accounts:[...selected],options:readOptions(),allow_paid:true});message('Apify 已排队；开启补数的账号后续由 Kalodata 自动处理。');});
node.querySelector('#ap-add').onsubmit=e=>{e.preventDefault();act(e.target.querySelector('button'),async()=>{await api('accounts',{handle:e.target.elements.handle.value});if(token!==epoch)return;e.target.reset();message('账号已保存，点击采集一次。');});};
function enrichmentCell(a){const c=a.enrichment||{},counts=c.counts||{};return `<small>${c.enabled?(c.paused?'已暂停，需核对':'已开启'):'未开启'} · 今日 ${c.calls_today||0}/${c.daily_limit||30} 次</small><small>${esc(Object.entries(counts).map(([k,n])=>(states[k]||k)+' '+n).join(' · '))}</small><small>${esc(c.error||'')}</small>${c.enabled?`<button data-stop-enrich="${a.id}">关闭自动补数</button>`:''}<details data-config><summary>${c.enabled?'修改设置 / 核对后恢复':'开启自动补数（Kalodata 付费）'}</summary><form data-enrich-form="${a.id}"><label>统计区间<select name="days"><option value="7" ${c.days===7?'selected':''}>7 日</option><option value="30" ${c.days!==7?'selected':''}>30 日</option></select></label><label>每日请求上限<input name="daily_limit" type="number" min="1" max="300" required value="${c.daily_limit||30}"></label><p>处理已有及后续抓取视频；近 30 天视频每日刷新。空成功响应每 24 小时复查，最多共 3 次后停止。实际按供应商计费，不保证收录。</p><label><input name="allow_paid" type="checkbox" required>我确认开启持续付费补数（未知结果不重试）</label><button type="submit">保存并开启</button></form></details>`;}
async function configure(a,enabled,form){
const c=a.enrichment||{},days=form?Number(form.elements.days.value):c.days||30,limit=form?Number(form.elements.daily_limit.value):c.daily_limit||30;
await api('accounts/'+a.id+'/enrichment',{enabled,days,daily_limit:limit,allow_paid:enabled&&!!form?.elements.allow_paid.checked});message(enabled?'自动补数已开启；已抓取视频会自动排队，较新视频等待成熟。异常任务不会自动重试。':'已关闭后续补数；已在途调用可能仍完成，已有数据保留。');
}
async function showVideos(){if(!viewed)return;const videos=await api('accounts/'+viewed+'/videos');if(token!==epoch)return;
node.querySelector('#ap-videos').innerHTML=`<section class="intel-form"><h3>已采集视频</h3><p>最多显示最近 100 条；Apify 为采集时累计值，Kalodata 为所示日期区间的估算。缺失不是零，旧成功结果保留。</p><div class="intel-table-wrap"><table><thead><tr><th>视频 / 发布时间</th><th>Apify 播放 / 增量</th><th>赞 / 评 / 享</th><th>采集时间</th><th>Kalodata GMV / 销量 / GPM</th><th>补数进度 / 统计区间</th><th>每日 GMV</th></tr></thead><tbody>${videos.map(v=>{const k=v.kalodata||{},d=k.data,s=k.status;return `<tr><td><a href="${esc(v.url)}" target="_blank" rel="noopener noreferrer">${esc(v.title||v.video)}</a><small>${date(v.published)}</small></td><td>${num(v.views)} / ${num(v.growth)}</td><td>${num(v.likes)} / ${num(v.comments)} / ${num(v.shares)}</td><td>${v.previous_at?date(v.previous_at)+' → ':''}${date(v.collected)}</td><td>${d?'$'+num(d.gmv)+' / '+num(d.units)+' / '+num(d.gpm):'—'}${d?`<small>期间播放 ${num(d.period_views)} · USD · 第三方估算</small>`:''}</td><td>${esc(states[s?.state]||'未排队 / 等待数据成熟')}<small>${esc(s?.error||'')}</small>${d?`<small>${esc(d.period_start)} 至 ${esc(d.period_end)} · 更新 ${date(d.fetched_at)}</small>`:''}</td><td>${d?.daily_gmv?.length?`<details><summary>${d.daily_gmv.length} 日趋势</summary>${d.daily_gmv.map(x=>`${esc(x.date)}：$${num(x.gmv)}`).join('<br>')}</details>`:'未提供或日期未对齐'}</td></tr>`;}).join('')}</tbody></table></div>${videos.length?'':'<p>暂无视频，请先采集；空结果不能认定零发片。</p>'}</section>`;
}
async function refresh(){if(token!==epoch)return;clearTimeout(timer);if(busy||node.querySelector('details[data-config][open]')){timer=setTimeout(refresh,5000);return;}
try{const accounts=await api('accounts');if(token!==epoch)return;
node.querySelector('#ap-accounts').innerHTML=`<div class="intel-table-wrap"><table><thead><tr><th>选择</th><th>账号 / 达人资料</th><th>最近采集 / 状态</th><th>Apify 定时</th><th>Kalodata 自动补数</th><th>操作</th></tr></thead><tbody>${accounts.map(a=>`<tr><td><input type="checkbox" aria-label="选择 ${esc(a.handle)}" data-pick="${a.id}" ${selected.has(a.id)?'checked':''}></td><td>@${esc(a.handle)}${a.profile?`<small>${esc(a.profile.nickName||'')} · 粉丝 ${num(a.profile.fans)}</small><small>${esc(a.profile.signature||'')}</small>`:''}</td><td>${date(a.last_success)}<small>${esc(a.run?.error||({queued:'排队中',submitting:'提交中',running:'采集中',ready:'采集完成',attention:'需核对'}[a.run?.state])||'待首次采集')}</small><small>${esc(a.run?.warning||'')}</small></td><td><select aria-label="${esc(a.handle)}的采集频率" data-schedule="${a.id}">${[0,6,12,24].map(h=>`<option value="${h}" ${a.interval_hours===h?'selected':''}>${h?'每 '+h+' 小时':'暂停'}</option>`).join('')}</select></td><td>${enrichmentCell(a)}</td><td><button data-collect="${a.id}" ${['queued','submitting','running'].includes(a.run?.state)?'disabled':''}>采集一次（付费）</button><button data-videos="${a.id}">查看视频</button></td></tr>`).join('')}</tbody></table></div>${accounts.length?'':'<p>还没有监测账号，请先添加。</p>'}`;
node.querySelectorAll('[data-pick]').forEach(c=>c.onchange=()=>{if(c.checked&&selected.size>=10){c.checked=false;message('一次最多选择 10 个账号');return;}if(c.checked)selected.add(c.dataset.pick);else selected.delete(c.dataset.pick);budget();});
node.querySelectorAll('[data-collect]').forEach(b=>b.onclick=()=>act(b,async()=>{await api('accounts/'+b.dataset.collect+'/collect',{allow_paid:true,options:readOptions()});viewed=b.dataset.collect;message('Apify 已排队，视频会自动刷新。');}));
node.querySelectorAll('[data-schedule]').forEach(s=>s.onchange=()=>act(s,async()=>{await api('accounts/'+s.dataset.schedule+'/schedule',{hours:Number(s.value),allow_paid:true,options:readOptions()});message(s.value==='0'?'已暂停定时采集。':'频率已保存，首次在一个周期后执行。');}));
node.querySelectorAll('[data-stop-enrich]').forEach(b=>b.onclick=()=>act(b,()=>configure(accounts.find(a=>a.id===b.dataset.stopEnrich),false)));
node.querySelectorAll('[data-enrich-form]').forEach(f=>f.onsubmit=e=>{e.preventDefault();act(f.querySelector('button'),async()=>{await configure(accounts.find(a=>a.id===f.dataset.enrichForm),true,f);f.closest('details').open=false;});});
node.querySelectorAll('[data-videos]').forEach(b=>b.onclick=()=>act(b,async()=>{viewed=b.dataset.videos;await showVideos();}));
await showVideos();
}catch(e){message(e.message);}finally{if(token===epoch)timer=setTimeout(refresh,5000);}}
refresh();
}
window.hubApifyMonitor={open,close};
})();

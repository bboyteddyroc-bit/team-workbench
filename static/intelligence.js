(() => {
'use strict';
const root=document.getElementById('intelligence'); if(!root)return;
const tabs=[['accounts','竞对账号'],['products','商品与店铺'],['reuse','内容复用'],['attribution','GMV 贡献'],['copy','爆款文案库'],['risk','风险表达库'],['tasks','脚本任务'],['exceptions','异常任务'],['kalodata','Kalodata 查询'],['connections','数据接入']];
const spec={
 accounts:{title:'竞对账号',desc:'跟踪发布频次、播放增长和爆款视频。',columns:['账号 / 市场','今日发片','爆款视频','近 7 日 GMV','监测状态'],fields:[['name','账号名称'],['url','账号链接','url'],['market','市场（如 US）']],empty:'添加第一个竞对账号',hint:'可到「Kalodata 查询」查看账号经营数据；每日发片与爆款提醒待实现。'},
 products:{title:'竞品商品',desc:'观察销量展示值的变化、新增短视频与直播线索。',columns:['商品 / 市场','销量展示值','日增量','新增视频','监测状态'],fields:[['name','商品名称'],['url','商品链接','url'],['market','市场（如 US）']],empty:'添加需要跟踪的商品',hint:'销量跳变将保留采集时间和来源；直播数据待接入。'},
 copy:{title:'爆款文案库',desc:'把值得复用的表达，整理成可检索的创作素材。',columns:['文案内容','标签','来源','操作'],fields:[['name','文案内容','textarea'],['tags','标签（逗号分隔）'],['url','来源视频链接','url']],empty:'收集第一条表达',hint:'建议标签：产品卖点、爆款开头、俚语、Demo、CTA。'},
 risk:{title:'风险表达库',desc:'保留风险原因和替代表达，为脚本审核提供依据。',columns:['风险表达','原因 / 场景','替代表达','状态'],fields:[['name','风险表达'],['reason','风险原因与适用场景'],['replacement','替代表达'],['source','规则来源与版本']],empty:'等待接入现有表达库',hint:'可以先试填一条；匹配提示不代表完整合规审核。'},
 tasks:{title:'脚本任务',desc:'用唯一编号串起脚本、制作、发布与出单表现。',columns:['脚本编号 / 标题','负责人','截止日期','状态','操作'],fields:[['name','脚本标题'],['content','脚本正文','textarea'],['owner','负责人'],['due','截止日期','date'],['product','关联商品'],['video','发布视频链接（选填）','url']],empty:'创建第一个脚本任务',hint:'一个脚本可对应多条成片；订单和 GMV 待数据接入后回流。'}
};
let goodsVideo='';
window.addEventListener('hub-view-goods',e=>{
 goodsVideo=String(e.detail?.video||'');
 root.querySelector('[data-intel-tab="products"]').click();
});
let active='accounts', rows={}, query='';
const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const states=['待分配','待制作','制作中','待发布','已发布'];
root.innerHTML=`<header class="intel-heading"><h1>竞对情报与脚本运营</h1></header><nav class="intel-tabs" aria-label="情报模块">${tabs.map(([id,label])=>`<button type="button" data-intel-tab="${id}">${label}</button>`).join('')}</nav><div id="intel-body"></div><p id="intel-status" role="status"></p>`;
const body=root.querySelector('#intel-body');
function clearBody(keep){const host=body.querySelector('[data-competitor-island]');[...body.children].forEach(n=>{if(!keep||n!==host)n.remove();});}
function render(){window.hubVideoCases?.close();root.querySelectorAll('[data-intel-tab]').forEach(b=>{b.classList.toggle('selected',b.dataset.intelTab===active);b.setAttribute('aria-current',b.dataset.intelTab===active?'page':'false');});
 // 切标签页必须先清掉上一页的 DOM：竞对账号是 React 岛，只 close() 不清 #intel-body 的话，商品/文案等静态页会留在上方
 if(active==='accounts'){window.hubScriptLibrary?.close();window.hubKalodata?.close();window.hubApifyMonitor?.open(body);clearBody(true);return;}
 window.hubApifyMonitor?.close();window.hubKalodata?.close();window.hubScriptLibrary?.close();clearBody(false);
 if(active==='products'){window.openProductIntel(body,goodsVideo);goodsVideo='';return;}
 if(active==='reuse' && window.hubVideoCases){window.hubVideoCases.open(body);return;}
 if(active==='own'){
  const pane=document.createElement('div');pane.innerHTML='<p role="status">正在打开自营商品…</p>';body.append(pane);
  import('/static/own-goods.js?v=listing-cover1').then(m=>{if(pane.parentElement===body)m.open(pane);}).catch(()=>{if(pane.parentElement===body){const p=pane.firstElementChild;p.textContent='自营商品加载失败，请刷新页面后再试。';p.setAttribute('role','alert');}});return;
 }
 if(active==='copy' && window.hubScriptLibrary){window.hubScriptLibrary.open(body);return;}
 if(active==='tasks' && window.hubCreativeTasks){window.hubCreativeTasks.open(body);return;}
 if(active==='exceptions' && window.hubExceptionCenter){window.hubExceptionCenter.open(body);return;}
 if(active==='connections'){window.hubKalodata?.openConfig(body);return;}
 if(active==='kalodata'){window.hubKalodata?.open(body);return;}
 const s=spec[active];
 if(!s){renderPending();return;}
 body.innerHTML=`<div class="intel-direct-tools"><input id="intel-search" type="search" aria-label="搜索当前列表" placeholder="输入名称、标签或负责人" value="${escape(query)}"><div class="intel-direct-actions">${Object.values(rows).some(list=>list.length)?'<button type="button" id="intel-export">导出试填内容</button>':''}<button type="button" id="intel-add" class="primary">${active==='tasks'?'新建脚本任务':active==='copy'||active==='risk'?'新增条目':'添加监测对象'}</button></div></div><div id="intel-form"></div><div id="intel-table"></div>`;
 body.querySelector('#intel-add').onclick=()=>form(s);
 const exportButton=body.querySelector('#intel-export');
 if(exportButton)exportButton.onclick=exportDrafts;
 body.querySelector('#intel-search').oninput=e=>{query=e.target.value;table(s);};table(s);
}
function table(s){const list=(rows[active]||[]).filter(r=>Object.values(r).join(' ').toLowerCase().includes(query.toLowerCase()));
 body.querySelector('#intel-table').innerHTML=`<div class="intel-table-wrap"><table><thead><tr>${s.columns.map(c=>`<th scope="col">${c}</th>`).join('')}</tr></thead><tbody>${list.map(r=>{let cells;
 if(active==='accounts'||active==='products')cells=[escape(r.name)+'<small>'+escape(r.market)+'</small>','—','—','—','待接入'];
 if(active==='copy')cells=[escape(r.name),escape(r.tags),r.url?`<a href="${escape(r.url)}" target="_blank" rel="noopener noreferrer">来源视频</a>`:'未填写',`<button data-convert="${r.id}">转为脚本任务</button>`];
 if(active==='risk')cells=[escape(r.name),escape(r.reason),escape(r.replacement),'待人工核验'];
 if(active==='tasks')cells=[`<small>${escape(r.id)} · v1</small>${escape(r.name)}`,escape(r.owner)||'未分配',escape(r.due)||'未设置',`<select aria-label="${escape(r.name)}的状态" data-state="${r.id}">${states.map(x=>`<option ${x===r.status?'selected':''}>${x}</option>`).join('')}</select>`,`<button data-detail="${r.id}">查看详情</button>`];
 return `<tr>${cells.map(c=>`<td>${c}</td>`).join('')}</tr>`;}).join('')}</tbody></table></div>${list.length?'':`<div class="intel-empty"><h3>${query?'没有匹配条目':s.empty}</h3><p>${query?'换一个关键词，或清空搜索。':s.hint}</p></div>`}`;
 body.querySelectorAll('[data-state]').forEach(n=>n.onchange=()=>{rows.tasks.find(r=>r.id===n.dataset.state).status=n.value;});
 body.querySelectorAll('[data-convert]').forEach(n=>n.onclick=()=>{const r=rows.copy.find(r=>r.id===n.dataset.convert);active='tasks';query='';render();form(spec.tasks,{name:r.name.slice(0,40),content:r.name});});
 body.querySelectorAll('[data-detail]').forEach(n=>n.onclick=()=>{const r=rows.tasks.find(r=>r.id===n.dataset.detail);body.querySelector('#intel-form').innerHTML=`<section class="intel-form"><h3>${escape(r.id)} · ${escape(r.name)}</h3><p class="intel-pre">${escape(r.content)||'尚未填写正文'}</p><p>关联商品：${escape(r.product)||'未关联'}</p><p>发布视频：${escape(r.video)||'未关联'}</p><p>订单 / GMV：待接入 · 飞书：待同步</p><button id="intel-close">收起详情</button></section>`;body.querySelector('#intel-close').onclick=()=>body.querySelector('#intel-form').replaceChildren();});
}
function form(s,initial={}){const area=body.querySelector('#intel-form');area.innerHTML=`<form class="intel-form"><h3>${active==='tasks'?'填写脚本任务':'新增'+s.title+'条目'}</h3><div class="intel-fields">${s.fields.map(([key,label,type])=>`<label>${label}${type==='textarea'?`<textarea name="${key}" maxlength="10000" ${key==='name'?'required':''}>${escape(initial[key]||'')}</textarea>`:`<input name="${key}" type="${type||'text'}" maxlength="1000" value="${escape(initial[key]||'')}" ${key==='name'?'required':''}>`}</label>`).join('')}</div><div class="intel-form-actions"><button class="primary" type="submit">添加到预览</button><button type="button" id="intel-cancel">取消</button></div></form>`;
 area.querySelector('#intel-cancel').onclick=()=>area.replaceChildren();area.querySelector('input,textarea').focus();
 area.querySelector('form').onsubmit=e=>{e.preventDefault();const data=Object.fromEntries(new FormData(e.target));if(!data.name.trim())return;for(const key of ['url','video'])if(data[key]&&!/^https?:\/\//i.test(data[key])){e.target.elements[key].setCustomValidity('请输入 http 或 https 链接');e.target.elements[key].reportValidity();e.target.elements[key].oninput=()=>e.target.elements[key].setCustomValidity('');return;}
 data.id=(active==='tasks'?'SC-':'DRAFT-')+crypto.randomUUID();data.status='待分配';(rows[active]??=[]).push(data);query='';render();root.querySelector('#intel-status').textContent='已添加到本页预览，可导出保留。';};
}
function renderPending(){const content={reuse:['内容复用分析','按文案结构和画面形式分别比较，再查看相似证据。',['文案结构：开头 → 痛点 → 卖点 → Demo → CTA','画面形式：展示顺序、镜头类型、产品演示方式','结果：相似账号、对应片段、首次发现时间、人工确认'],'添加监测账号并接入视频数据后，开始建立复用关系。'],attribution:['近 7 日 GMV 贡献','最近 7 个完整自然日，对比前 7 日；统一市场时区和币种。',['视频贡献：视频 → 商品 → GMV → 贡献占比 → 周环比','商品贡献：商品 → 关联视频 → GMV → 周环比','未归因部分单列；缺失值不作为 0 计算'],'等待可用的销量与 GMV 来源，暂无可计算数据。'],connections:['数据接入','连接信息确认后，再启用自动采集和同步。',['Kalodata · 已接入手动查询：美国市场账号、商品与视频详情（需有效密钥）','飞书脚本库 · 待接入：脚本编号、版本与任务状态','飞书爆款提醒 · 待配置：接收位置、爆款条件、去重规则','风险表达库 · 待接入：规则来源、适用场景、版本'],'当前框架不会自动采集数据或发送飞书消息。']}[active];body.innerHTML=`<div class="intel-inline-state"><span class="intel-badge">待接入</span></div><ul class="intel-plan" aria-label="${content[0]}">${content[2].map(x=>`<li>${x}</li>`).join('')}</ul><div class="intel-empty"><h3>数据接通后启用</h3><p>${content[3]}</p><button id="intel-back">${active==='connections'?'查看脚本任务':'添加监测对象'}</button></div>`;body.querySelector('#intel-back').onclick=()=>{active=active==='connections'?'tasks':'accounts';query='';render();};}
window.addEventListener('hub-open-exceptions',()=>{active='exceptions';query='';render();});
window.addEventListener('hub-create-script',e=>{window.hubCreativeTasks?.setReference(e.detail);active='tasks';query='';render();});
root.querySelectorAll('[data-intel-tab]').forEach(n=>n.onclick=()=>{active=n.dataset.intelTab;query='';render();});
function exportDrafts(){const url=URL.createObjectURL(new Blob([JSON.stringify({schema_version:1,mode:'framework_preview',data:rows},null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='intelligence-drafts.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
window.hubIntelligence={reset(){window.hubVideoCases?.reset();window.hubKalodata?.reset();rows={};query='';active='accounts';render();root.querySelector('#intel-status').textContent='';}};
render();
// Do not show the entry until this server has the matching API (rolling upgrades).
fetch('/api/intelligence/own-goods/available').then(r=>r.ok?r.json():null).then(d=>{
 if(d?.available!==true)return;
 const next=root.querySelector('[data-intel-tab="attribution"]');
 const button=document.createElement('button');button.type='button';button.dataset.intelTab='own';button.textContent='自营商品';button.setAttribute('aria-current','false');
 button.onclick=()=>{active='own';query='';render();};next.before(button);
}).catch(()=>{});
})();

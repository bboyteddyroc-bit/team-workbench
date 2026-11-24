(() => {
  'use strict';
  let epoch = 0, timer, container, records = [], requestKey, signature;
  const esc = x => String(x ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const fmt = x => x === null || x === undefined ? '未提供' : Number(x).toLocaleString('zh-CN', {maximumFractionDigits:2});
  const states = {queued:'排队中',running:'查询中',ready:'已完成',attention:'需核对'};
  const panel=document.getElementById('intelligence');
  if(panel)new MutationObserver(()=>{
    if(panel.hidden){panel.querySelectorAll('input[name="secret_key"]').forEach(input=>input.value='');}
  }).observe(panel,{attributes:true,attributeFilter:['hidden']});
  async function call(path, data, provider='kalodata') {
    const options = {credentials:'same-origin'};
    if (data) Object.assign(options, {method:'POST',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:JSON.stringify(data)});
    const controller = new AbortController(); options.signal = controller.signal;
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const r = await fetch('/api/intelligence/' + provider + '/' + path, options);
      const result = await r.json();
      if (!r.ok) throw new Error(typeof result.detail === 'string' ? result.detail : '请求失败');
      return result;
    } catch (e) { if (e.name === 'AbortError') throw new Error(path==='config'?'保存请求超时，请重新打开数据接入查看更新时间后再决定是否重填。':'请求超时，请刷新查询记录；再次提交同一表单会复用请求编号。'); throw e; }
    finally {clearTimeout(timeout);}
  }
  function table() {
    const slot = container?.querySelector('#k-results'); if (!slot) return;
    slot.innerHTML = `<div class="intel-table-wrap"><table><thead><tr><th>查询对象 / 区间</th><th>预估 GMV · USD</th><th>预估销量 · 件</th><th>状态</th><th>结果</th></tr></thead><tbody>${records.map(j=>`<tr><td>${esc(j.target)}<small>近 ${j.days} 日 · 截至 ${esc(j.end_date)}</small></td><td>${fmt(j.result?.gmv)}</td><td>${fmt(j.result?.units)}</td><td>${states[j.state] || '未知'}</td><td>${j.state==='ready'?`<button data-k-detail="${esc(j.id)}">查看数据</button>`:esc(j.error || '等待后台查询')}</td></tr>`).join('')}</tbody></table></div>${records.length?'':'<div class="intel-empty"><h3>还没有查询记录</h3><p>填写准确账号、商品 ID 或视频 ID，获取对应期间的数据。</p></div>'}`;
    slot.querySelectorAll('[data-k-detail]').forEach(b=>b.onclick=()=>detail(records.find(j=>j.id===b.dataset.kDetail)));
  }
  function detail(job) {
    const d=job.result, slot=container.querySelector('#k-detail');
    slot.innerHTML=`<section class="intel-form"><h3>${esc(d.name)}</h3><p>Kalodata 第三方估算 · ${esc(d.period_start)} 至 ${esc(d.period_end)} · US / USD</p><p>查询时间：${esc(d.fetched_at)}</p><div class="intel-table-wrap"><table><tbody>${[['GMV（USD）',d.gmv],['销量（件）',d.units],['播放量',d.views],['期间视频数',d.video_count],['视频 GMV（USD）',d.video_gmv],['直播 GMV（USD）',d.live_gmv]].map(([label,v])=>`<tr><th>${label}</th><td>${fmt(v)}</td></tr>`).join('')}</tbody></table></div><details><summary>每日 GMV</summary>${d.daily_gmv.length?`<div class="intel-table-wrap"><table><thead><tr><th>日期</th><th>预估 GMV · USD</th></tr></thead><tbody>${d.daily_gmv.map(r=>`<tr><td>${esc(r.date)}</td><td>${fmt(r.gmv)}</td></tr>`).join('')}</tbody></table></div>`:'<p>未返回可与完整查询区间对齐的每日数据。</p>'}</details><p>${d.limitations.map(esc).join('；')}。</p><button id="k-download">导出查询结果</button><button id="k-close">收起详情</button></section>`;
    slot.querySelector('#k-close').onclick=()=>slot.replaceChildren();
    slot.querySelector('#k-download').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(d,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download=`kalodata-${job.id}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
  }
  async function refresh(token) {
    try {
      const items = await call('jobs');
      if(token!==epoch || !container?.querySelector('#k-results')) return;
      records=items;table();
      if (items.some(j=>['queued','running'].includes(j.state))) timer=setTimeout(()=>refresh(token),3000);
    } catch(e) {if(token===epoch && container?.querySelector('#k-message')) container.querySelector('#k-message').textContent=e.message;}
  }
  async function open(node) {
    clearTimeout(timer);const token=++epoch;container=node;records=[];
    node.innerHTML=`<form class="intel-form" id="k-form" aria-label="Kalodata 查询条件"><div class="intel-fields"><label>查询类型<select name="kind"><option value="creator">竞对账号</option><option value="product">商品</option><option value="video">视频</option></select></label><label>统计区间（美国市场 · 截止 UTC 昨日）<select name="days"><option value="7">近 7 个完整自然日</option><option value="30">近 30 个完整自然日</option></select></label><label>账号 / 编号 / 完整链接<input name="target" required maxlength="500" placeholder="@账号，或商品 / 视频 ID"></label></div><p id="k-cost">预计最多 0.2 credits；实际扣费以 Kalodata 为准。15 分钟内相同成功查询优先复用。</p><div class="intel-form-actions"><button class="primary" id="k-submit" disabled>查询（消耗 Kalodata 额度）</button><button type="button" id="k-refresh">刷新查询记录</button><span class="intel-badge" id="k-status" role="status">检查配置…</span></div></form><p id="k-message" role="status"></p><div id="k-detail"></div><div id="k-results"></div><p>结果按当前中台成员保存，仅本人可查看。飞书同步和每日自动监测尚未启用。</p>`;
    const form=node.querySelector('#k-form'), submit=node.querySelector('#k-submit');
    form.elements.kind.onchange=()=>node.querySelector('#k-cost').textContent=`预计最多 ${form.elements.kind.value==='creator'?'0.2':'0.1'} credits；实际扣费以 Kalodata 为准。15 分钟内相同成功查询优先复用。`;
    node.querySelector('#k-refresh').onclick=()=>{clearTimeout(timer);refresh(token);};
    form.onsubmit=async e=>{
      e.preventDefault();const data=Object.fromEntries(new FormData(form));data.days=Number(data.days);
      const next=JSON.stringify(data);if(next!==signature){signature=next;requestKey=crypto.randomUUID();}
      submit.disabled=true;node.querySelector('#k-message').textContent='正在提交查询…';
      try {await call('jobs',{...data,request_key:requestKey,allow_paid_api:true});if(token!==epoch)return;requestKey=crypto.randomUUID();node.querySelector('#k-message').textContent='已提交，可在下方查看结果。';clearTimeout(timer);await refresh(token);}
      catch(e){if(token===epoch)node.querySelector('#k-message').textContent=e.message;}
      finally{if(token===epoch)submit.disabled=false;}
    };
    try {const config=await call('status');if(token!==epoch)return;node.querySelector('#k-status').textContent=config.configured?'密钥已配置 · 查询时验证':'未配置密钥';submit.disabled=!config.configured;await refresh(token);}
    catch(e){if(token===epoch){node.querySelector('#k-status').textContent='连接不可用';node.querySelector('#k-message').textContent=e.message;}}
  }
  async function openConfig(node) {
    clearTimeout(timer);const token=++epoch;container=node;
    node.innerHTML=`<section class="intel-form" aria-labelledby="k-config-heading"><h3 id="k-config-heading">Kalodata API 密钥</h3><p id="k-config-state" role="status">正在检查配置…</p><div id="k-config-fields"></div></section><ul class="intel-plan"><li>飞书脚本库 · 待接入</li><li>飞书爆款提醒 · 待配置</li><li>风险表达库 · 待接入</li></ul>`;
    const apifySlot=document.createElement('div');node.append(apifySlot);openApifyConfig(apifySlot, token);
    const samplesSlot=document.createElement('div');node.append(samplesSlot);
    import('/static/comment-samples.js?v=1').then(m=>{if(token===epoch&&samplesSlot.isConnected)m.config(samplesSlot);}).catch(()=>{if(token===epoch)samplesSlot.textContent='ScrapeCreators 配置组件暂不可用';});
    const describe = config => {
      if(config.error)return config.error;
      const label=config.source==='saved'?'已保存中台密钥':config.source==='environment'?'正在使用服务环境中的密钥':config.configured?'密钥已配置':'尚未配置密钥';
      return label+(config.updated?` · 更新于 ${new Date(config.updated*1000).toLocaleString('zh-CN')}`:'')+'。配置状态不代表余额或权限验证成功。';
    };
    try {
      const config=await call('status');if(token!==epoch)return;
      node.querySelector('#k-config-state').textContent=describe(config);
      if(!config.admin){node.querySelector('#k-config-fields').innerHTML='<p>只有管理员可以设置或更换密钥。</p>';return;}
      node.querySelector('#k-config-fields').innerHTML=`<form id="k-config-form"><label>新的 API 密钥<input type="password" name="secret_key" required minlength="8" maxlength="4096" autocomplete="new-password" spellcheck="false" autocapitalize="none" placeholder="粘贴 Kalodata Secret Key"></label><p>保存后用于团队后续查询，覆盖环境中的旧密钥，无需重启。密钥加密保存，不回显；正在执行的查询继续使用原密钥。</p><div class="intel-form-actions"><button type="submit" class="primary">保存并启用</button><button type="button" id="k-config-clear">清空输入</button></div><p id="k-config-message" role="status">保存不消耗 API 额度。可到「Kalodata 查询」验证新密钥。</p></form>`;
      const form=node.querySelector('#k-config-form'),input=form.elements.secret_key,message=node.querySelector('#k-config-message');
      node.querySelector('#k-config-clear').onclick=()=>{input.value='';input.focus();};
      form.onsubmit=async e=>{
        e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;
        message.textContent='正在保存…';
        try {
          const saved=await call('config',{secret_key:input.value});
          input.value='';if(token!==epoch)return;
          node.querySelector('#k-config-state').textContent=describe(saved);
          message.textContent='已加密保存，后续查询将使用新密钥。';
        } catch(e) {input.value='';if(token===epoch)message.textContent=e.name==='AbortError'?'保存结果待核对，请重新打开本页查看配置时间。':e.message;}
        finally {if(token===epoch)button.disabled=false;}
      };
    } catch(e){if(token===epoch)node.querySelector('#k-config-state').textContent=e.message;}
  }
  async function openApifyConfig(node, token) {
    if(window.hubApifyPool){await window.hubApifyPool.open(node);return;}
    node.innerHTML=`<section class="intel-form"><h3>Apify API 密钥</h3><p id="a-config-state" role="status">正在检查配置…</p><div id="a-config-fields"></div></section>`;
    const describe = config => {
      if(config.error)return config.error;
      const label=config.source==='saved'?'已保存中台密钥':config.source==='environment'?'正在使用服务环境中的密钥':config.configured?'密钥已配置':'尚未配置密钥';
      return label+(config.updated?` · 更新于 ${new Date(config.updated*1000).toLocaleString('zh-CN')}`:'')+'。配置状态不代表余额或权限验证成功。';
    };
    try {
      const config=await call('status', undefined, 'apify');if(token!==epoch)return;
      node.querySelector('#a-config-state').textContent=describe(config);
      if(!config.admin){node.querySelector('#a-config-fields').innerHTML='<p>只有管理员可以设置或更换密钥。</p>';return;}
      node.querySelector('#a-config-fields').innerHTML=`<form id="a-config-form"><label>新的 API 密钥<input type="password" name="secret_key" required minlength="8" maxlength="4096" autocomplete="new-password" spellcheck="false" autocapitalize="none" placeholder="粘贴 Apify API Token"></label><p>密钥加密保存，不回显；留空不会修改已有配置。可到「竞对账号」手动采集或设置定时频率。</p><div class="intel-form-actions"><button type="submit" class="primary">保存密钥</button><button type="button" id="a-config-clear">清空输入</button></div><p id="a-config-message" role="status">保存不发起采集、不消耗 Apify 额度；可到「竞对账号」采集一次验证连接。</p></form>`;
      const form=node.querySelector('#a-config-form'),input=form.elements.secret_key,message=node.querySelector('#a-config-message');
      node.querySelector('#a-config-clear').onclick=()=>{input.value='';input.focus();};
      form.onsubmit=async e=>{
        e.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;
        message.textContent='正在保存…';
        try {
          const saved=await call('config',{secret_key:input.value}, 'apify');
          input.value='';if(token!==epoch)return;
          node.querySelector('#a-config-state').textContent=describe(saved);
          message.textContent='已加密保存。可到「竞对账号」手动采集或设置定时频率。';
        } catch(e) {input.value='';if(token===epoch)message.textContent=e.name==='AbortError'?'保存结果待核对，请重新打开本页查看配置时间。':e.message;}
        finally {if(token===epoch)button.disabled=false;}
      };
    } catch(e){if(token===epoch)node.querySelector('#a-config-state').textContent=e.message;}
  }
  window.hubKalodata={open,openConfig,close(){epoch++;clearTimeout(timer);container=null;records=[];},reset(){epoch++;clearTimeout(timer);records=[];signature=null;requestKey=null;container=null;}};
})();

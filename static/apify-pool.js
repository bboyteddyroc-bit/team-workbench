'use strict';
window.hubApifyPool={async open(node){
 const el=(tag,text)=>{const n=document.createElement(tag);if(text)n.textContent=text;return n;};
 const section=el('section');section.className='intel-form apify-key-pool';
 const header=el('header'),heading=el('div'),message=el('p','正在读取密钥池…'),refresh=el('button','刷新余额');
 heading.append(el('h3','Apify API 密钥池'),el('p','管理员统一维护，全中台共享；新采集按密钥轮流分配，已提交任务固定使用原密钥。'));header.append(heading,refresh);
 const wrap=el('div'),table=el('table'),thead=el('thead'),tr=el('tr'),tbody=el('tbody');wrap.className='apify-pool-table';
 for(const title of ['密钥名称','连接状态','剩余额度（USD）','用量 / 月限额','更新时间','操作'])tr.append(el('th',title));thead.append(tr);table.append(thead,tbody);wrap.append(table);
 const form=el('form'),name=el('input'),secret=el('input'),add=el('button','新增密钥并保存');
 name.placeholder='密钥名称';name.required=true;name.maxLength=80;name.setAttribute('aria-label','密钥名称');secret.type='password';secret.placeholder='粘贴 Apify API Token';secret.autocomplete='new-password';secret.required=true;secret.setAttribute('aria-label','Apify API Token');add.type='submit';form.append(name,secret,add);
 section.append(header,wrap,form,message,el('p','余额为官方月使用上限减本月用量的估算，不等同现金余额；显示更新时间。保存不启动采集，余额查询不运行 Actor。同一 Apify 账号的多个密钥共享额度，请勿相加。'));node.replaceChildren(section);
 const api=async(path='',data)=>{const r=await fetch('/api/intelligence/apify/pool'+path,{credentials:'same-origin',...(data!==undefined?{method:'POST',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:JSON.stringify(data)}:{})});const d=await r.json();if(!r.ok)throw Error(d.detail||'请求失败');return d;};
 let items=[],busy=false;
 const money=x=>typeof x==='number'?'$'+x.toFixed(2):'—';
 const labels={unchecked:'待核验',ready:'正常',invalid:'授权失效',forbidden:'权限不足',exhausted:'额度不足',rate_limited:'限流待核验',error:'核验失败'};
 function render(data){items=data.items;tbody.replaceChildren();for(const item of items){const row=el('tr'),actions=el('td'),check=el('button','核验 / 余额'),toggle=el('button',item.enabled?'暂停使用':'启用');
 row.append(el('td',item.name),el('td',item.enabled?(labels[item.state]||item.state):'已暂停'),el('td',item.limit_usd!==null&&item.usage!==null?money(Math.max(0,item.limit_usd-item.usage)):'未知'),el('td',money(item.usage)+' / '+money(item.limit_usd)),el('td',item.checked?new Date(item.checked*1000).toLocaleString():'未查询'));
 if(item.error)row.children[1].title=item.error;
 check.onclick=()=>action('/'+item.id+'/refresh',{});toggle.onclick=()=>action('/'+item.id+'/toggle',{enabled:!item.enabled});actions.append(check,toggle);row.append(actions);tbody.append(row);}
 if(!items.length){const row=el('tr'),cell=el('td','暂无密钥，请管理员新增。');cell.colSpan=6;row.append(cell);tbody.append(row);}}
 async function action(path,data){if(busy)return;busy=true;try{render(await api(path,data));message.textContent='状态已更新，未启动采集。';}catch(e){message.textContent=e.message;}finally{busy=false;}}
 form.onsubmit=async e=>{e.preventDefault();if(busy)return;busy=true;add.disabled=true;try{render(await api('',{name:name.value,secret_key:secret.value}));name.value='';message.textContent='已加密保存，新任务将轮流使用；点击刷新余额核验。';}catch(e){message.textContent=e.message;}finally{secret.value='';busy=false;add.disabled=false;}};
 refresh.onclick=async()=>{if(busy)return;busy=true;refresh.disabled=true;try{for(const item of items)render(await api('/'+item.id+'/refresh',{}));message.textContent='余额已查询；本页可见时每60秒刷新，未知表示官方未返回对应字段。';}catch(e){message.textContent=e.message;}finally{busy=false;refresh.disabled=false;}};
 const interval=setInterval(()=>{if(!node.isConnected||!section.isConnected){clearInterval(interval);return;}if(!document.hidden&&section.getClientRects().length)refresh.click();},60000);
 try{render(await api());message.textContent='密钥加密保存、不回显；暂停不影响已提交任务读取。';}catch(e){message.textContent=e.message;form.hidden=true;refresh.hidden=true;}
}};

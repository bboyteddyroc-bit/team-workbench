'use strict';
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
let features={references:false};
let me, setup=false, accounts=[], tasks=[], filter='all', view='studio', loading=false;
let requestKey=crypto.randomUUID(), toastTimer, cachedTasks=new Map(), sessionEpoch=0, taskLimit=100;
const labels={queued:'已排队',submitting:'正在提交',running:'生成中',ready:'已完成',failed:'生成失败',unknown:'正在确认任务',attention:'同步待恢复',cancelled:'已取消',closed:'已关闭追踪'};
const activeStates=['queued','submitting','running','importing'];
const attentionStates=['failed','unknown','attention'];
function el(tag, text, cls){const n=document.createElement(tag); if(text!==undefined)n.textContent=text; if(cls)n.className=cls; return n;}
function toast(text,error=false){if(window.hubToast){window.hubToast.show(text,error);return;}clearTimeout(toastTimer);const t=$('#toast');t.textContent=text;t.className=error?'error-toast':'';t.hidden=false;toastTimer=setTimeout(()=>t.hidden=true,6500);}
const hubNotice=(()=>{
  const watches=new Map();
  const action=(label,view,target)=>({label,onClick:()=>{navigate(view);if(view==='studio'&&target==='#task-list')window.hubStudioHistory?.open();else requestAnimationFrame(()=>document.querySelector(target)?.scrollIntoView({behavior:'smooth',block:'start'}));}});
  function begin(key,title,label,view,target){watches.set(key,{title,label,view,target});window.hubToast?.begin({id:key,title,action:action(label,view,target)});}
  function finish(key,title,status,description,destination){const item=watches.get(key);if(!item)return;watches.delete(key);const dest=destination||item;if(window.hubToast)window.hubToast.update(key,{title,status,description,duration:status==='error'?12000:8000,action:action(dest.label,dest.view,dest.target)});else toast(title,status==='error');}
  function observe(prefix,rows){for(const row of rows){const key=prefix+(prefix==='libtv:'?row.request_key:row.id);if(!watches.has(key))continue;if(row.state==='ready')finish(key,prefix==='export:'?'导出完成':'视频生成完成','success',undefined,prefix==='libtv:'?{label:'查看素材',view:'materials',target:'#materials'}:undefined);else if(row.state==='failed')finish(key,prefix==='export:'?'导出失败':'视频生成失败','error',row.error||'请查看任务详情');else if(['unknown','attention'].includes(row.state))continue;else if(['cancelled','closed'].includes(row.state))finish(key,'任务已取消或关闭追踪','info');}}
  return {begin,finish,observe,has:prefix=>[...watches.keys()].some(key=>key.startsWith(prefix)),clear:()=>{watches.clear();window.hubToast?.clear();}};
})();
async function api(path,data){
  const epoch=sessionEpoch;
  const options={credentials:'same-origin'};
  if(data!==undefined){options.method='POST';options.headers={'Content-Type':'application/json','X-Hub-Request':'1'};options.body=JSON.stringify(data);}
  const r=await fetch('/api'+path,options);const result=await r.json();
  if(epoch!==sessionEpoch)throw new Error('SESSION_CHANGED');
  if(!r.ok){if(r.status===401&&path!='/login')showAuth();throw new Error(typeof result.detail==='string'?result.detail:'请求失败，请稍后重试');}
  return result;
}
function formData(form){return Object.fromEntries(new FormData(form));}
async function busy(form,fn){const buttons=[...form.querySelectorAll('button')];buttons.forEach(b=>b.disabled=true);try{await fn();}catch(e){toast(e.message,true);}finally{buttons.forEach(b=>b.disabled=false);}}
function showAuth(){window.hubTaskFeedback?.close();window.hubStudioHistory?.close();window.hubAIEdit?.reset();hubNotice.clear();window.hubIntelligence?.reset();window.hubFeishu?.reset();window.hubMobileTransfer?.reset();window.hubAudioLibrary?.reset();window.hubLibTV?.reset();window.hubAssistant?.reset();window.voicePanel?.reset();window.hubMaterials?.reset();window.hubUI?.reset();window.hubWorkspace?.reset();window.hubEditor?.reset();sessionEpoch++;me=null;features={references:false};accounts=[];tasks=[];taskLimit=100;loading=false;cachedTasks.clear();$$('form').forEach(f=>f.reset());resetConnect();$('#task-list').replaceChildren();window.hubAccountTable?.reset();window.hubAdminTables?.reset();$('#account-list').replaceChildren();$('#member-list').replaceChildren();$('#audit-list').replaceChildren();resetComposer();$('#shell').hidden=true;$('#auth').hidden=false;$('#auth-title').textContent=setup?'首次设置':'登录工作台';$('#auth-description').textContent=setup?'在本机创建管理员账号，密码至少 12 字符。':'使用管理员为你创建的工作台账号。';$('#auth-submit').textContent=setup?'创建管理员并登录':'登录';}
async function start(){try{const status=await api('/status');setup=status.needs_setup;$('#environment').textContent=status.local_only?'本机预览':'内网工作空间';if(setup)return showAuth();try{me=await api('/me');await enter();}catch{showAuth();}}catch(e){$('#auth').hidden=false;$('#auth-error').textContent=e.message;}}
async function enter(){
  await window.hubLoginPass?.complete();
  window.hubAssistant?.enter();
  $('#auth').hidden=true;$('#shell').hidden=false;$('#username').textContent=me.username;
  $$('.admin-only').forEach(n=>n.hidden=me.role!=='admin');
  $('#limit-note').textContent='不设中台每日提交上限，实际消耗公司平台额度。';
  if(me.must_change){navigate('password');return;}
  navigate('home');await load();await restoreComposer();await window.hubWorkspace?.refresh();
}
function navigate(next){
  if(me?.must_change&&next!=='password'){toast('请先修改初始密码',true);return;}
  if(view==='editor'&&next!=='editor')window.hubEditor?.pause();
  view=next;$$('.view').forEach(n=>n.hidden=n.id!==next);$$('[data-view]').forEach(n=>n.classList.toggle('active',n.dataset.view===next));
  $('#view-label').textContent={home:'工作台首页','ai-edit':'AI 剪辑',intelligence:'竞对情报与脚本运营',materials:'素材管理',overview:'剪辑历史',studio:'创作空间',editor:'剪辑空间',accounts:'连接管理',members:'团队管理',audit:'操作记录',storage:'存储管理',password:'账号设置'}[next];
  window.hubWorkspace?.visibility(next);
  window.hubMediaLazy?.visibility();
  if(next==='studio'){renderTasks();window.hubCompositionPreview?.refresh();}
  if(next==='editor'){window.hubEditor?.open().then(()=>window.voicePanel?.init()).catch(e=>toast(e.message,true));}
  if(next==='editor')window.hubUI?.refresh().catch(e=>toast(e.message,true));
  window.hubAIEdit?.visibility(next);
  if(next==='ai-edit')window.hubAIEdit?.open().catch(e=>toast(e.message,true));
  if(next==='materials')window.hubMaterials?.open().catch(e=>toast(e.message,true));
  if(next==='overview')window.hubUI?.refresh().catch(e=>toast(e.message,true));
  if(next==='accounts'){window.hubLibTVProfiles?.visibility();window.hubLibTVProfiles?.refresh();}
  if(next==='members')loadMembers().catch(e=>toast(e.message,true));
  if(next==='audit')loadAudit().catch(e=>toast(e.message,true));
  if(next==='storage'&&me?.role==='admin')window.storageReport?.refresh();
}
$$('[data-view]').forEach(n=>n.onclick=()=>navigate(n.dataset.view));
$('#login-form').onsubmit=e=>{e.preventDefault();busy(e.target,async()=>{const d=formData(e.target);$('#auth-error').textContent='';try{if(setup){await api('/setup',d);setup=false;}me=await api('/login',d);e.target.reset();await enter();}catch(err){$('#auth-error').textContent=err.message;}});};
$('#logout').onclick=async()=>{try{await api('/logout',{});showAuth();}catch(e){toast(e.message,true);}};
$('#password-open').onclick=()=>navigate('password');
$('#password-form').onsubmit=e=>{e.preventDefault();busy(e.target,async()=>{await api('/password',formData(e.target));e.target.reset();me=await api('/me');toast('密码已更新');await enter();});};
$('#refresh').onclick=()=>load().catch(e=>toast(e.message,true));
$$('[data-filter]').forEach(n=>n.onclick=()=>{filter=n.dataset.filter;$$('[data-filter]').forEach(b=>b.classList.toggle('active',b===n));renderTasks();});
async function load(skipUnchangedAccounts=false){if(!me||me.must_change||loading)return;loading=true;const epoch=sessionEpoch;try{const[newAccounts,first,newFeatures]=await Promise.all([api('/accounts'),api('/tasks?compact=true'),api('/capabilities')]);let all=first;for(let offset=100;offset<taskLimit&&all.length===offset;offset+=100)all=all.concat(await api('/tasks?compact=true&offset='+offset));if(epoch!==sessionEpoch||!me)return;const accountsChanged=!skipUnchangedAccounts||JSON.stringify(accounts)!==JSON.stringify(newAccounts);accounts=newAccounts;tasks=all;hubNotice.observe('task:',all);features=newFeatures;$('#integration-note').textContent=features.references?'已接入 2.0 / Mini / Fast 全能参考及 2.0 首尾帧；新模式待实际生成验证。全能参考可在额度耗尽后切换 Mini / Fast。':'文生视频已接通；参考图上传待验证，其余模式可先保存草稿。';$('#load-more').hidden=all.length<taskLimit;if(accountsChanged)renderAccounts();renderTasks();window.dispatchEvent(new Event('hub-tasks'));}finally{if(epoch===sessionEpoch)loading=false;}}
$('#load-more').onclick=()=>{taskLimit+=100;load().catch(e=>toast(e.message,true));};
function empty(title,description,action){const wrap=el('div',undefined,'empty');const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 48 48');svg.setAttribute('fill','none');svg.setAttribute('stroke-width','1.5');svg.setAttribute('aria-hidden','true');const rect=document.createElementNS(svg.namespaceURI,'rect');for(const[k,v]of Object.entries({x:7,y:10,width:34,height:28,rx:4}))rect.setAttribute(k,v);const path=document.createElementNS(svg.namespaceURI,'path');path.setAttribute('d','M21 19l9 5-9 5z');svg.append(rect,path);wrap.append(svg,el('h3',title),el('p',description));if(action){const b=el('button','连接第一个账号','secondary');b.onclick=()=>navigate('accounts');wrap.append(b);}return wrap;}
function renderAccounts(){
  const enabled=accounts.filter(a=>a.enabled&&a.status==='connected');
  $('#pool-summary').textContent=`公司账号池 · ${enabled.length} 个连接可用 · 系统按队列分配`;
  updateCompositionSummary();
  if(window.hubAccountTable){window.hubAccountTable.render(accounts,{edit:a=>{const f=$('#connect-form');for(const k of ['id','name','scope'])f.elements[k].value=a[k];f.elements.scope.disabled=true;$('#connect-title').textContent='更新账号连接';$('#pool-manual-connect').open=true;f.scrollIntoView({block:'nearest'});f.elements.curl.focus();},toggle:async a=>{try{await api('/accounts/'+a.id+'/toggle',{});await load();}catch(e){toast(e.message,true);}},sync:async a=>{try{const r=await api('/accounts/'+a.id+'/sync-subaccounts',{});toast('已同步 '+r.count+' 个子账号');await load();}catch(e){toast(e.message,true);await load();}}});return;}
  const list=$('#account-list');list.replaceChildren();if(!accounts.length){list.append(empty('还没有连接账号','请管理员连接公司 TikTok 账号。'));return;}
  for(const a of accounts){const row=el('article',undefined,'account-row'),top=el('div',undefined,'task-top');top.append(el('h3',a.name),el('span',!a.enabled?'已暂停':a.status==='connected'?'连接正常':'需要更新','status'));row.append(top,el('p','公司共享 · 不设中台提交上限'));if(a.error)row.append(el('p',a.error,'error'));if(a.can_manage){const controls=el('div',undefined,'account-controls'),edit=el('button','更新连接'),toggle=el('button',a.enabled?'暂停使用':'恢复使用');edit.onclick=()=>{const f=$('#connect-form');for(const k of ['id','name','scope'])f.elements[k].value=a[k];f.elements.scope.disabled=true;$('#connect-title').textContent='更新账号连接';$('#pool-manual-connect').open=true;f.scrollIntoView({block:'nearest'});f.elements.curl.focus();};toggle.onclick=async()=>{try{await api('/accounts/'+a.id+'/toggle',{});await load();}catch(e){toast(e.message,true);}};const sync=el('button','同步子账号');sync.onclick=async()=>{sync.disabled=true;try{const r=await api('/accounts/'+a.id+'/sync-subaccounts',{});toast('已同步 '+r.count+' 个子账号');await load();}catch(e){toast(e.message,true);await load();}finally{sync.disabled=false;}};controls.append(edit,toggle,sync);row.append(controls);}list.append(row);}
}
window.addEventListener('hub-account-table-ready',()=>{if(me&&!me.must_change)renderAccounts();});
function resetConnect(){const f=$('#connect-form');f.reset();f.elements.id.value='';f.elements.scope.disabled=false;$('#connect-title').textContent='连接 TikTok 账号';}
$('#connect-reset').onclick=resetConnect;
$('#connect-form').onsubmit=e=>{e.preventDefault();busy(e.target,async()=>{const d=formData(e.target);d.scope=e.target.elements.scope.value;await api('/accounts',d);resetConnect();toast('查询验证成功，账号已连接');await load();});};
function renderTasks(){
  if($('#studio').hidden)return; // Poll data in the background, build cards only on entry.
  const combined=[...tasks,...(window.hubLibTV?.jobs()||[])].sort((a,b)=>b.created-a.created);$('#task-count').textContent=combined.length;const visible=combined.filter(t=>filter==='all'||filter==='active'&&activeStates.includes(t.state)||filter==='ready'&&t.state==='ready'||filter==='failed'&&attentionStates.includes(t.state)&&t.feedback_state!=='waiting');
  const list=$('#task-list');if(!visible.length){cachedTasks.clear();list.replaceChildren(filter==='failed'?empty('暂无需处理的任务','这里显示当前已加载的 TikTok 和 LibTV 生成异常。'):empty(combined.length?'没有符合条件的任务':'从第一段视频开始',combined.length?'切换筛选查看其他任务。':'在左侧填写提示词。提交后，进度和结果会出现在这里。',!accounts.length));return;}
  list.querySelector('.empty')?.remove();
  const ids=new Set(visible.map(t=>t.id));for(const [id,entry]of cachedTasks)if(!ids.has(id)){entry.node.remove();cachedTasks.delete(id);}
  visible.forEach((t,index)=>{const signature=JSON.stringify(t);let entry=cachedTasks.get(t.id);if(!entry||entry.signature!==signature){const node=t.libtv?window.hubLibTV.node(t):taskNode(t);if(entry)entry.node.replaceWith(node);entry={node,signature};cachedTasks.set(t.id,entry);}if(list.children[index]!==entry.node)list.insertBefore(entry.node,list.children[index]||null);});
}
function taskNode(t){
  const issue=attentionStates.includes(t.state),feedbackUI=window.hubTaskFeedback;
  const row=el('article',undefined,'task');const top=el('div',undefined,'task-top');top.append(el('span',`TikTok · ${t.account_name} · ${t.owner_name} · ${new Date(t.created*1000).toLocaleString('zh-CN')}`,'task-meta'),el('span',issue&&feedbackUI?feedbackUI.state(t.feedback_state||t.state):labels[t.state]||t.state,'status '+t.state));row.append(top);row.append(el('p',`${JSON.parse(t.config||'{}').model==='mini'?'Seedance 2.0 Mini':JSON.parse(t.config||'{}').model==='fast'?'Seedance 2.0 Fast':'Seedance 2.0'} · ${t.duration||5} 秒`,'fine'));
  if(t.prompt.length>180){const details=el('details'),summary=el('summary',t.prompt.slice(0,90)+'…');details.append(summary,el('p',t.prompt,'task-prompt'));row.append(details);}else row.append(el('p',t.prompt,'task-prompt'));
  if(t.append_error)row.append(el('p',t.append_error,'task-error'));
  if(t.append_state==='applied')row.append(el('p','接力片段已追加到项目；重新载入项目可查看。','fine'));
  const parent=JSON.parse(t.config||'{}').continuation?.source_id;if(parent)row.append(el('p','接力来源 · '+parent,'task-meta'));
  if(t.queue_reason)row.append(el('p',t.queue_reason+(t.queue_position?' · 此账号队列第 '+t.queue_position+' 位（实时变化）':''),'fine'));
  if(issue&&feedbackUI){row.append(feedbackUI.studio(t,'tiktok'));}
  else if(t.error)row.append(el('p',t.error,'task-error'));
  if(t.state==='attention'&&t.remote_id)row.append(el('p','“同步状态”只查询已有任务，不会重新提交生成。','fine'));
  if(t.state==='ready'){const video=el('video');video.controls=true;window.hubMediaLazy.watch(video,'/api/tasks/'+t.id+'/video');video.setAttribute('aria-label','生成的视频');row.append(video);}
  const actions=el('div',undefined,'task-actions');
  if(t.state==='ready'){const edit=el('button','加入剪辑');edit.onclick=()=>window.hubWorkspace?.add(t.id).catch(e=>toast(e.message,true));actions.append(edit);const a=el('a','下载 MP4');a.href='/api/tasks/'+t.id+'/video?download=true';a.download='video.mp4';actions.append(a);}
  if(t.state==='queued')actions.append(taskAction('取消排队',t,'cancel'));
  if(t.state==='running'||t.state==='attention')actions.append(taskAction('同步状态',t,'sync'));
  if(t.state==='unknown'){const details=el('details'),summary=el('summary','关联网页任务');const input=el('input');input.placeholder='网页中核实的任务 ID';input.setAttribute('aria-label','网页任务 ID');const button=el('button','保存关联');button.onclick=async()=>{try{await api('/tasks/'+t.id+'/action',{action:'reconcile',remote_id:input.value});await load();}catch(e){toast(e.message,true);}};details.append(summary,input,button);row.append(details);}
  if((me.role==='admin'||t.account_scope==='personal')&&['unknown','attention'].includes(t.state)){const b=taskAction('已核对，关闭追踪',t,'close');actions.append(b);}
  if(t.remote_id){const id=el('span','任务 '+t.remote_id,'task-meta');actions.append(id);}
  window.hubWorkspace?.taskActions(t,actions);row.append(actions);return row;
}
function taskAction(text,t,action){const b=el('button',text);b.onclick=async()=>{b.disabled=true;try{await api('/tasks/'+t.id+'/action',{action});await load();}catch(e){toast(e.message,true);}finally{b.disabled=false;}};return b;}
$('#member-form').onsubmit=e=>{e.preventDefault();busy(e.target,async()=>{const d=formData(e.target);await api('/users',d);e.target.reset();toast('成员已创建，请安全交付初始密码');await loadMembers();});};
async function loadMembers(){const epoch=sessionEpoch,users=await api('/users');if(epoch!==sessionEpoch||!me)return;if(window.hubAdminTables){window.hubAdminTables.members(users,me.id,{toggle:async u=>{try{await api('/users/'+u.id,{enabled:!u.enabled});await loadMembers();}catch(e){toast(e.message,true);}},reset:openPasswordReset});return;}const list=$('#member-list');list.replaceChildren();for(const u of users){const row=el('div',undefined,'member-row');row.append(el('h3',u.username),el('p',`${u.role==='admin'?'管理员':'成员'} · ${u.enabled?'可使用':'已停用'} · 公司共享额度`));if(u.id!==me.id&&u.role!=='admin'){const controls=el('div',undefined,'account-controls'),toggle=el('button',u.enabled?'停用':'启用');toggle.onclick=async()=>{try{await api('/users/'+u.id,{enabled:!u.enabled});await loadMembers();}catch(e){toast(e.message,true);}};const reset=el('button','重置密码');reset.type='button';reset.onclick=()=>openPasswordReset(u);controls.append(toggle,reset);row.append(controls);}list.append(row);}}
async function loadAudit(){const epoch=sessionEpoch,rows=await api('/audit');if(epoch!==sessionEpoch||!me)return;if(window.hubAdminTables){window.hubAdminTables.audit(rows);return;}const list=$('#audit-list');list.replaceChildren();if(!rows.length){list.append(empty('还没有操作记录','连接账号或提交任务后，这里会显示操作记录。'));return;}const words={account_connected:'连接账号',account_toggle:'切换账号状态',user_created:'创建成员',user_updated:'更新成员',task_queued:'提交任务',task_cancel:'取消排队',task_sync:'同步任务',task_close:'关闭追踪',task_reconcile:'关联任务'};for(const r of rows){const line=el('div',undefined,'audit-row');line.append(el('span',new Date(r.at*1000).toLocaleString('zh-CN')),el('span',r.username||'系统'),el('span',(words[r.action]||r.action)+' · '+r.target));list.append(line);}}
window.addEventListener('hub-admin-tables-ready',()=>{if(!me||me.must_change)return;if(!$('#members').hidden)loadMembers().catch(e=>toast(e.message,true));if(!$('#audit').hidden)loadAudit().catch(e=>toast(e.message,true));});
let studioStream=null, studioStreamUser=null;
function updateStudioStream(){
  const uid=typeof me!=='undefined' && me && !me.must_change && !document.hidden && view==='studio' ? me.id : null;
  if(uid===studioStreamUser)return;
  studioStream?.close();studioStream=null;studioStreamUser=uid;
  if(!uid||!window.EventSource)return;
  studioStream=new EventSource('/api/studio/events');
  studioStream.onmessage=()=>{if(me?.id===uid)load(true).catch(()=>{});};
}
setInterval(updateStudioStream,2000);
document.addEventListener('visibilitychange',updateStudioStream);
setInterval(()=>{if(me&&!document.hidden&&!me.must_change)load(true).catch(()=>{});},10000);
start();

function openPasswordReset(member){
 const dialog=el('dialog'),form=el('form'),title=el('h2','重置 '+member.username+' 的密码');
 dialog.className='panel';dialog.setAttribute('aria-label','重置成员密码');
 const note=el('p','重置后该成员将退出登录，下次登录必须修改临时密码。');
 const label=el('label','临时密码'),input=el('input');input.type='password';input.required=true;input.minLength=12;input.maxLength=200;input.autocomplete='new-password';label.append(input);
 const confirmLabel=el('label','再次输入'),confirm=el('input');confirm.type='password';confirm.required=true;confirm.autocomplete='new-password';confirmLabel.append(confirm);
 const error=el('p','','error');error.setAttribute('role','alert');
 const actions=el('div',undefined,'account-controls'),cancel=el('button','取消'),save=el('button','确认重置','primary');cancel.type='button';save.type='submit';cancel.onclick=()=>dialog.close();actions.append(cancel,save);
 form.append(title,note,label,confirmLabel,error,actions);dialog.append(form);document.body.append(dialog);
 dialog.addEventListener('close',()=>{input.value=confirm.value='';dialog.remove();});
 const epoch=sessionEpoch;
 form.onsubmit=async e=>{e.preventDefault();if(input.value!==confirm.value){error.textContent='两次密码不一致';return;}save.disabled=true;try{await api('/users/'+member.id+'/reset-password',{password:input.value});dialog.close();if(epoch===sessionEpoch){toast('密码已重置，请将临时密码告知该成员');await loadMembers();}}catch(e){error.textContent=e.message;}finally{save.disabled=false;}};
 dialog.showModal();input.focus();
}

$('#pool-login-sync').onsubmit=e=>{e.preventDefault();const f=e.target,status=$('#pool-login-status');busy(f,async()=>{status.textContent='正在核验子账号，请稍候…';try{const r=await api('/accounts/sync-login',{curl:f.elements.curl.value});f.reset();status.textContent=`已核验并更新 ${r.count} 个子账号`;await load();}catch(err){status.textContent=err.message;throw err;}});};

$('#pool-browser-login').onclick=async()=>{const b=$('#pool-browser-login'),s=$('#pool-browser-status');b.disabled=true;try{let r=await api('/accounts/browser-login',{});s.textContent=r.message;for(let i=0;i<330;i++){await new Promise(resolve=>setTimeout(resolve,2000));r=await api('/accounts/browser-login');s.textContent=r.message||'';if(!['waiting','verifying'].includes(r.state)){if(r.state==='ready')await load();return;}}s.textContent='等待超时，请检查服务器登录窗口';}catch(e){s.textContent=e.message;}finally{b.disabled=false;}};

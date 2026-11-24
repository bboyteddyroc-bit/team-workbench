'use strict';
(()=>{
 const make=(t,text)=>{const n=document.createElement(t);if(text)n.textContent=text;return n};
 async function open(){
  let state;try{const r=await fetch('/api/assistant/a6-settings',{credentials:'same-origin'});if(!r.ok)throw Error('仅管理员可管理 A6API 密钥');state=await r.json()}catch(e){alert(e.message);return}
  const d=make('dialog'),title=make('h2','A6API 模型密钥'),desc=make('p','模型：gemini-3.8-flash。密钥仅供管理员配置，加密保存，不会回显。保存不会发送模型请求、上传视频或切换现有服务。'),status=make('p',state.configured?'已配置 A6API；连接状态尚未测试。':'尚未保存密钥。'),form=make('form'),label=make('label','A6API 密钥'),input=make('input'),actions=make('div'),save=make('button','保存密钥'),close=make('button','取消');
  d.className='a6-config-dialog';input.type='password';input.required=true;input.minLength=10;input.maxLength=4096;input.autocomplete='new-password';input.spellcheck=false;label.append(input);save.type='submit';save.className='primary';close.type='button';close.onclick=()=>d.close();status.setAttribute('role','status');actions.className='a6-config-actions';actions.append(save,close);form.append(label,actions);d.append(title,desc,status,form);document.body.append(d);
  d.addEventListener('close',()=>{input.value='';d.remove()});form.onsubmit=async e=>{e.preventDefault();save.disabled=true;try{const r=await fetch('/api/assistant/a6-settings',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:JSON.stringify({key:input.value})});const result=await r.json();input.value='';if(!r.ok)throw Error(result.detail||'保存失败');status.textContent='已加密保存。后续模型调用使用此密钥；本次保存不会发起请求，连接状态尚未测试。';save.hidden=true;close.textContent='关闭';}catch(err){input.value='';status.textContent=err.message||'保存结果待核对，请关闭后重新查看状态。'}finally{save.disabled=false}};d.showModal();input.focus();
 }
 window.openA6Settings=open;
})();

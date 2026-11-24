'use strict';
document.addEventListener('DOMContentLoaded',()=>{
 const bar=document.querySelector('#editor .editor-commandbar');if(!bar)return;
 const make=(t,text)=>{const n=document.createElement(t);if(text)n.textContent=text;return n;};
 const button=make('button','手机传输');button.type='button';
 const archive=[...bar.querySelectorAll('button')].find(n=>n.textContent==='飞书归档设置');if(archive)archive.after(button);else bar.append(button);
 const dialog=make('dialog');dialog.id='mobile-transfer-dialog';dialog.setAttribute('aria-label','手机传输');
 const title=make('h2','手机传输'),close=make('button','关闭'),note=make('p'),choices=make('div'),create=make('button','更新手机列表'),revoke=make('button','撤销链接'),result=make('div');close.type=create.type=revoke.type='button';revoke.hidden=true;
 const header=make('header'),content=make('div'),left=make('section'),right=make('section'),actions=make('footer'),count=make('span','未选择成品（仅上传）'),selectAll=make('button','全选');selectAll.type='button';
 header.className='mobile-dialog-header';content.className='mobile-dialog-content';choices.className='mobile-export-list';actions.className='mobile-dialog-actions';result.className='mobile-qr-result';note.className='mobile-dialog-note';note.setAttribute('role','status');
 header.append(title,close);
 left.append(make('h3','选择传到手机的成品'),make('p','可多选；选好点「更新手机列表」，手机页自动同步，无需重扫。'),selectAll,count,choices);
 right.append(make('h3','手机扫码传输'),make('p','服务已随中台运行，无需打开 EXE。手机选好视频即上传，成功后进入剪辑台素材区。'),result);
 const uploads=make('div'),uploadStatus=make('p','等待手机上传；相册准备阶段无法读取进度。');uploads.className='mobile-upload-list';uploadStatus.setAttribute('role','status');right.append(make('h3','手机上传进度'),uploadStatus,uploads);
 let progressTimer=null,progressBusy=false;
 async function pollProgress(){
  if(progressBusy||!dialog.open||document.hidden)return;progressBusy=true;const epoch=authEpoch;
  try{const d=await api('mobile/progress');if(epoch!==authEpoch||!dialog.open)return;
   uploads.replaceChildren();let active=0;
   const states={uploading:'上传中',verifying:'校验入库中',done:'已入库',failed:'失败',unknown:'结果未知，请核对素材库',stalled:'长时间无更新，请核对手机连接'};
   for(const item of d.items){
    if(['uploading','verifying'].includes(item.state))active++;
    const row=make('div'),label=make('p'),p=make('progress');p.max=100;
    const percent=item.total>0?Math.min(100,Math.floor(item.received/item.total*100)):null;
    if(percent!==null)p.value=percent;if(item.state==='done')p.value=100;
    p.setAttribute('aria-label',item.name+' 上传进度');
    label.textContent=item.name+' · '+(states[item.state]||item.state)+' · '+(item.received/1024/1024).toFixed(1)+' MB'+(item.total>0?' / '+(item.total/1024/1024).toFixed(1)+' MB（'+percent+'%）':'（总大小未知）');
    row.append(label,p);uploads.append(row);
   }
   uploadStatus.textContent=d.items.length?'最近一小时 '+d.items.length+' 条记录，'+active+' 条传输或校验中；显示电脑实际接收进度。':'等待手机上传；相册准备阶段无法读取进度。';
  }catch(e){if(epoch===authEpoch)uploadStatus.textContent='进度暂不可用：'+e.message;}finally{progressBusy=false;}
 }
 content.append(left,right);actions.append(create,revoke);dialog.append(header,content,note,actions);document.body.append(dialog);
 let current=null,timer=null,serial=0,authEpoch=0,applied=[],updating=false,available=[];
 const selected=()=>[...choices.querySelectorAll('input:checked')].map(c=>c.value);
 const selectionChanged=()=>{const n=selected().length;count.textContent=n?'已选择 '+n+' 条成品':'未选择成品（仅上传）';create.textContent=current?'更新手机列表':'生成二维码';if(current)note.textContent='选择后点「更新手机列表」生效；二维码不变，有效期内手机不需重扫。';};
 choices.addEventListener('change',selectionChanged);
 selectAll.onclick=()=>{const inputs=[...choices.querySelectorAll('input')],on=inputs.some(c=>!c.checked);inputs.forEach(c=>c.checked=on);selectionChanged();};
 const api=async(path,data)=>{
  const r=await fetch('/api/'+path,{credentials:'same-origin',...(data!==undefined?{method:'POST',headers:{'X-Hub-Request':'1','Content-Type':'application/json'},body:JSON.stringify(data)}:{})});
  const d=await r.json();if(!r.ok){const e=Error(d.detail||'请求失败');e.status=r.status;throw e;}return d;
 };
 let revision=null,refreshing=false;
 async function refresh(){if(refreshing||document.hidden)return;refreshing=true;const a=authEpoch;try{const d=await api('mobile/received');if(a!==authEpoch)return;if(d.revision!==revision)await window.hubEditor?.refreshMobileLibrary?.();if(a===authEpoch)revision=d.revision;}catch{}finally{refreshing=false;}}
 function showConnection(){
  if(!current)return;
  result.replaceChildren();const img=make('img'),a=make('a',current.url);img.alt='手机传输二维码';img.src=current.qr;a.href=current.url;a.target='_blank';a.rel='noopener';result.append(img,a);revoke.hidden=false;create.textContent='更新手机列表';
  note.textContent='已开启：扫码选视频自动上传；已分享 '+applied.length+' 条成品。有效至 '+new Date(current.expires*1000).toLocaleTimeString()+(current.url.startsWith('http:')?'。局域网 HTTP，无需装证书；传输不加密，仅在可信公司 Wi-Fi 使用，请勿转发二维码。':'。手机须信任 HTTPS 证书，请勿转发二维码。');
  clearInterval(timer);timer=setInterval(()=>{if(current&&Date.now()<current.expires*1000)refresh();else{clearInterval(timer);if(dialog.open)note.textContent='临时链接已到期，点击「生成二维码」重新连接。';create.textContent='生成二维码';}},6000);
 }
 async function updateTransfer(){
  if(updating)return;updating=true;create.disabled=true;const s=serial,a=authEpoch,ids=selected();
  try{
   let legacy=false;
   if(current&&Date.now()<current.expires*1000){
    let d;
    try{d=await api('mobile/transfers/'+current.id+'/selection',{exports:ids});}
    catch(e){
     if(e.status!==404&&e.status!==405)throw e;
     // An older running server may still be finishing jobs. Keep it usable until a safe restart.
     const old=current;
     d=await api('mobile/transfers',{exports:ids});
     if(a!==authEpoch){await api('mobile/transfers/'+d.id+'/revoke',{});return;}
     current=d;legacy=true;
     try{await api('mobile/transfers/'+old.id+'/revoke',{});}catch{}
    }
    if(a!==authEpoch)return;current.expires=d.expires;applied=ids;
   }else{
    const d=await api('mobile/transfers',{exports:ids});
    if(a!==authEpoch){await api('mobile/transfers/'+d.id+'/revoke',{});return;}
    current=d;applied=ids;
   }
   if(dialog.open){showConnection();if(legacy)note.textContent+=' 当前服务仍是旧版：二维码已换新，请手机重扫一次；后台任务结束并安全重启后才支持同码更新。';}await refresh();
  }catch(e){if(s===serial)note.textContent=e.message;if(a===authEpoch&&e.status===410){current=null;result.replaceChildren();revoke.hidden=true;create.textContent='生成二维码';}}
  finally{updating=false;create.disabled=false;}
 }
 create.onclick=updateTransfer;
 button.onclick=async()=>{
  if(dialog.open)return;serial++;const s=serial;choices.replaceChildren();result.replaceChildren();revoke.hidden=true;note.textContent='正在连接中台传输服务…';dialog.showModal();pollProgress();clearInterval(progressTimer);progressTimer=setInterval(pollProgress,1000);
  try{
   available=(await api('editor/exports')).filter(j=>j.state==='ready');if(s!==serial||!dialog.open)return;
   for(const j of available){
    const row=make('label'),c=make('input'),thumb=make('img');row.className='mobile-export-choice';c.type='checkbox';c.value=j.id;c.checked=applied.includes(j.id);
    thumb.className='mobile-export-thumb';thumb.alt='成品缩略图';thumb.loading='lazy';thumb.decoding='async';thumb.src='/api/editor/exports/'+encodeURIComponent(j.id)+'/thumbnail';thumb.onerror=()=>{thumb.hidden=true;};
    row.append(c,thumb,make('span',j.name||'未命名成品'));choices.append(row);
   }
   if(!available.length)choices.append(make('p','暂无已完成成品，可先扫码上传素材。'));
   selectionChanged();
   if(current&&Date.now()<current.expires*1000){showConnection();await refresh();}else await updateTransfer();
  }catch(e){if(s===serial)note.textContent=e.message;}
 };
 revoke.onclick=async()=>{if(!current||updating)return;try{await api('mobile/transfers/'+current.id+'/revoke',{});current=null;applied=[];result.replaceChildren();revoke.hidden=true;clearInterval(timer);selectionChanged();note.textContent='链接已撤销。中台服务仍运行，点击「生成二维码」可重新连接。';}catch(e){note.textContent=e.message;}};
 close.onclick=()=>dialog.close();dialog.addEventListener('close',()=>{serial++;clearInterval(progressTimer);refresh();});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
 window.hubMobileTransfer={reset(){serial++;authEpoch++;clearInterval(timer);current=null;applied=[];revision=null;result.replaceChildren();choices.replaceChildren();revoke.hidden=true;dialog.close();}};
});

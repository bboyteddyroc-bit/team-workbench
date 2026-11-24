'use strict';
(()=>{
  const $=id=>document.getElementById(id);
  // Keep a refreshed phone tab usable without putting the credential in server paths.
  let token=location.hash.slice(1);
  try{if(token)sessionStorage.setItem('hub-mobile-token',token);else token=sessionStorage.getItem('hub-mobile-token')||'';}catch{}
  history.replaceState(null,'',location.pathname);
  const headers={'X-Transfer-Token':token,'X-Hub-Request':'1'};
  if($('transport-note'))$('transport-note').textContent=location.protocol==='http:'?'公司局域网 HTTP：无需安装证书，视频与授权码不加密，仅在可信公司 Wi-Fi 使用。':'HTTPS 加密传输：手机需信任当前服务证书。';
  let valid=false,busy=false,checking=false,expires=0,signature='',timer=0;
  const selected=()=>[...document.querySelectorAll('[name=video]:checked')].map(c=>c.value);
  function downloadState(){const n=selected().length;$('download').disabled=!valid||!n;$('download').textContent=n===1?'下载所选 MP4':n?'显示所选 '+n+' 条 MP4 下载链接':'请选择要下载的成品';}
  function showFiles(files){
    const next=JSON.stringify(files);if(next===signature)return;signature=next;
    const picked=new Set(selected());$('list').replaceChildren();$('all').checked=false;
    for(const f of files){
      const row=document.createElement('label'),c=document.createElement('input'),a=document.createElement('a');
      c.type='checkbox';c.value=f.id;c.name='video';c.checked=picked.has(f.id);c.onchange=downloadState;
      a.textContent=f.name+' · '+(f.size/1024/1024).toFixed(1)+' MB · 下载原文件';
      a.href='/api/mobile/file/'+encodeURIComponent(f.id)+'?token='+encodeURIComponent(token);
      row.append(c,a);$('list').append(row);
    }
    if(!files.length)$('list').textContent='暂无分享成品。电脑导出后在「手机传输」中选择成品并更新，此页会自动显示，无需重新扫码。';
    downloadState();
  }
  async function req(path){
    const r=await fetch('/api/mobile/'+path,{headers});
    if(!r.ok){let text='请求失败';try{text=(await r.json()).detail||text;}catch{}const error=Error(text);error.status=r.status;throw error;}
    return r.json();
  }
  async function load(){
    if(checking)return;checking=true;
    try{
      const d=await req('session');expires=d.expires;valid=true;
      $('status').textContent='已连接中台 · 有效至 '+new Date(expires*1000).toLocaleTimeString();
      $('files').disabled=busy;$('upload').disabled=busy;showFiles(d.files);downloadState();
    }catch(e){
      if(e.status===410){valid=false;clearInterval(timer);$('files').disabled=true;$('upload').disabled=true;}
      $('status').textContent=e.status?e.message:'连接中断，请检查公司 Wi-Fi、局域网访问权限及中台服务；不要重复上传，可点击「刷新连接」。';downloadState();
    }finally{checking=false;}
  }
  function sendFile(file,bar,state){return new Promise((resolve,reject)=>{
    const x=new XMLHttpRequest();x.open('POST','/api/mobile/upload');
    for(const [k,v]of Object.entries(headers))x.setRequestHeader(k,v);
    x.setRequestHeader('X-File-Name',encodeURIComponent(file.name));
    x.upload.onprogress=e=>{if(e.lengthComputable){bar.value=e.loaded/e.total*100;state.textContent='上传中 '+Math.round(bar.value)+'%';}};
    x.upload.onload=()=>{state.textContent='已传完，服务器校验并入库中…';};
    x.onload=()=>{
      let d={};try{d=JSON.parse(x.responseText);}catch{}
      if(x.status>=200&&x.status<300&&typeof d.id==='string')resolve(d);
      else{if(x.status===410)valid=false;reject(Error(d.detail||'未取得入库确认，请先在电脑核对，不要重复上传'));}
    };
    x.onerror=()=>reject(Error('网络中断，结果未知；请先在电脑检查素材再重试'));
    x.onabort=()=>reject(Error('上传已中断，请先核对素材库'));
    x.send(file);
  });}
  async function uploadSelected(){
    if(!valid||busy)return;
    const files=[...$('files').files];if(!files.length)return;
    busy=true;$('files').disabled=true;$('upload').disabled=true;$('upload').textContent='正在上传，请保持页面打开';
    let success=0,failed=0;
    try{
      for(const f of files){
        const line=document.createElement('div'),name=document.createElement('p'),state=document.createElement('p'),bar=document.createElement('progress');
        name.textContent=f.name;bar.max=100;state.textContent='准备上传';line.append(name,state,bar);$('progress').append(line);
        try{
          if(!valid||Date.now()>=expires*1000)throw Error('链接已失效，请在电脑重新生成二维码；本条未提交');
          if(!/\.(mp4|mov|m4v)$/i.test(f.name)||f.size>1024**3)throw Error('格式不支持或超过 1 GB；本条未提交');
          await sendFile(f,bar,state);bar.value=100;state.textContent='已入库 · 电脑剪辑台 → 视频素材 → 上传日期';success++;
        }catch(e){state.textContent=e.message;failed++;}
      }
      $('upload-summary').textContent='本次：'+success+' 条已入库，'+failed+' 条未确认或失败。'+(failed?'失败项不会自动重传，请核对后再选择。':'电脑素材区会自动刷新，不需要打开接收器 EXE。');
    }finally{
      busy=false;$('files').value='';$('files').disabled=!valid;$('upload').disabled=!valid;$('upload').textContent='上传已选视频（备用）';
      load();
    }
  }
  $('files').onchange=uploadSelected;
  $('upload').onclick=uploadSelected;
  $('all').onchange=()=>{document.querySelectorAll('[name=video]').forEach(c=>c.checked=$('all').checked);downloadState();};
  $('download').onclick=()=>{
    const ids=selected();if(!valid||!ids.length)return;
    const status=$('download-status');status.replaceChildren();
    if(ids.length===1){
      const a=document.createElement('a');a.href='/api/mobile/file/'+encodeURIComponent(ids[0])+'?token='+encodeURIComponent(token);a.download='';document.body.append(a);a.click();a.remove();
      status.textContent='已请求下载 MP4，请查看浏览器下载列表；保存到相册需按手机系统操作。';
    }else{
      status.append(document.createTextNode('手机浏览器可能拦截连续下载，请逐条点击下方链接下载 MP4：'));
      const rows=[...document.querySelectorAll('[name=video]:checked')];
      rows.forEach(c=>{const source=c.parentElement.querySelector('a'),link=document.createElement('a');link.href=source.href;link.textContent=source.textContent;link.download='';link.style.display='block';status.append(link);});
    }
  };
  $('refresh').onclick=load;
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)load();});
  load();timer=setInterval(()=>{if(!document.hidden&&!busy)load();},6000);
})();

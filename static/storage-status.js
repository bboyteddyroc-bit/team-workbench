'use strict';
(() => {
  const badge=document.getElementById('storage-status');
  const shell=document.getElementById('shell');
  let running=false;
  async function refresh(){
    if(running || shell.hidden) return;
    running=true;
    try{
      const response=await fetch('/api/storage-status',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok) throw new Error('unavailable');
      const data=await response.json();
      const drive=data.drive.replace(/[\\/]+$/,'');
      const gib=(data.free/1024**3).toFixed(1);
      const prefix=data.level==='critical'?'空间严重不足':data.level==='warning'?'空间不足提醒':'存储空间';
      badge.className='storage-status '+data.level;
      badge.textContent=`${prefix} · ${drive} 剩余 ${gib} GB`;
      badge.title='视频存储磁盘剩余空间；低于 20 GB 提醒，低于 5 GB 严重提醒。不会自动删除文件。';
    }catch(e){badge.className='storage-status unavailable';badge.textContent='存储空间：暂时无法读取';badge.title='请检查服务和存储磁盘是否可用。';}
    finally{running=false;}
  }
  new MutationObserver(()=>{if(!shell.hidden)refresh();}).observe(shell,{attributes:true,attributeFilter:['hidden']});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
  setInterval(refresh,60000);
  refresh();
})();

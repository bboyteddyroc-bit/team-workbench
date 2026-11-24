/* Deferred intelligence pages: one loading/error/race contract. */
(()=>{
 'use strict';
 function register(name,url,message,withReference=false){
  let pending=null,reference=null,hasReference=false,serial=0;
  const proxy={async open(body){
   const request=++serial;body.textContent=message;
   if(!pending)pending=new Promise((resolve,reject)=>{
    const script=document.createElement('script');script.src=url;
    script.onload=()=>{if(window[name]===proxy){pending=null;script.remove();reject(new Error('界面初始化失败，请切换标签重试'));}else resolve();};
    script.onerror=()=>{pending=null;script.remove();reject(new Error('界面加载失败，请切换标签重试'));};
    document.head.append(script);
   });
   try{await pending;if(request!==serial||!body.isConnected||body.textContent!==message)return;
    const page=window[name];if(withReference&&hasReference){page.setReference(reference);reference=null;hasReference=false;}
    await page.open(body);
   }catch(error){if(request===serial&&body.isConnected&&body.textContent===message)body.textContent=error.message;}
  }};
  if(withReference)proxy.setReference=value=>{reference=value;hasReference=true;};
  window[name]=proxy;
 }
 register('hubCreativeTasks','/static/creative-tasks.js?v=direct-content1','正在加载脚本任务界面…',true);
 register('hubExceptionCenter','/static/exception-center.js?v=section-feedback1','正在加载异常任务界面…');
})();

/* Load the read-only exception UI only when its tab is opened. */
(()=>{
 let pending=null;
 const proxy={async open(body){
   body.textContent='正在加载异常任务界面…';
   if(!pending)pending=new Promise((resolve,reject)=>{
     const script=document.createElement('script');script.src='/static/exception-center.js?v=2';
     script.onload=resolve;script.onerror=()=>{script.remove();pending=null;reject(new Error('界面加载失败，请切换标签后重试'));};
     document.head.append(script);
   });
   try{await pending;if(window.hubExceptionCenter!==proxy&&body.isConnected&&body.textContent==='正在加载异常任务界面…')await window.hubExceptionCenter.open(body);}
   catch(e){if(body.isConnected&&body.textContent==='正在加载异常任务界面…')body.textContent=e.message;}
 }};
 window.hubExceptionCenter=proxy;
})();

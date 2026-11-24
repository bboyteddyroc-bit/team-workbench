/* Defer the script-task UI, preserving references received before loading. */
(()=>{
 let pending=null,reference=null;
 const proxy={setReference(value){reference=value;},async open(body){
   body.textContent='正在加载脚本任务界面…';
   if(!pending)pending=new Promise((resolve,reject)=>{const script=document.createElement('script');script.src='/static/creative-tasks.js?v=2';script.onload=resolve;script.onerror=()=>{pending=null;script.remove();reject(new Error('界面加载失败，请切换标签重试'));};document.head.append(script);});
   try{await pending;if(window.hubCreativeTasks!==proxy&&body.isConnected&&body.textContent==='正在加载脚本任务界面…'){if(reference!==null){window.hubCreativeTasks.setReference(reference);reference=null;}await window.hubCreativeTasks.open(body);}}
   catch(e){if(body.isConnected&&body.textContent==='正在加载脚本任务界面…')body.textContent=e.message;}
 }};window.hubCreativeTasks=proxy;
})();

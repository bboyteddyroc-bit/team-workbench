const {app,BrowserWindow}=require('electron');
const path=require('path');
app.disableHardwareAcceleration();
process.on('uncaughtException',()=>finish({error:'登录工具异常退出，请查看诊断信息'}));
app.setPath('userData',path.resolve(process.argv[2]));
if(!app.requestSingleInstanceLock()){process.exit(3);}
let win,done=false;
function finish(value){if(done)return;done=true;process.stdout.write('HUB_LOGIN:'+JSON.stringify(value)+'\n',()=>app.quit());}
app.whenReady().then(()=>{
 win=new BrowserWindow({width:1100,height:820,title:'登录 TikTok · 成功后自动同步中台',webPreferences:{nodeIntegration:false,contextIsolation:true,sandbox:true}});
 win.setMenu(null);
 win.webContents.on('render-process-gone',(_e,details)=>finish({error:'登录页面进程退出：'+details.reason}));
 const session=win.webContents.session;
 let pending=null;
 session.webRequest.onBeforeSendHeaders({urls:['https://ads.tiktok.com/creative_bff_i18n/api/cue/generating-task-count*']},(d,cb)=>{
  if(d.webContentsId===win.webContents.id){const h={};for(const [k,v] of Object.entries(d.requestHeaders))if(['cookie','x-csrftoken','x-fp-id','user-agent','referer','origin','accept','accept-language','agw-js-conv','x-creative-source'].includes(k.toLowerCase()))h[k.toLowerCase()]=v;if(h.cookie&&h['x-csrftoken']&&h['x-fp-id'])pending={id:d.id,headers:h};}
  cb({requestHeaders:d.requestHeaders});
 });
 session.webRequest.onCompleted({urls:['https://ads.tiktok.com/creative_bff_i18n/api/cue/generating-task-count*']},d=>{if(pending?.id===d.id&&d.statusCode===200)finish({headers:pending.headers});});
 win.webContents.setWindowOpenHandler(()=>({action:'deny'}));
 win.on('closed',()=>{if(!done)finish({error:'登录窗口已关闭，未同步'});});
 win.loadURL('https://ads.tiktok.com/creative/creativestudio/create').catch(()=>finish({error:'官网打开失败，请检查服务器网络'}));
 setTimeout(()=>finish({error:'登录等待超时，请重新连接'}),600000).unref();
});

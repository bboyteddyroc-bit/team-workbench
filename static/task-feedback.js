/* Shared, read-only feedback disclosure for the two existing task views. */
(() => {
  'use strict';
  const states={ok:'步骤完成',waiting:'等待结果',failed:'失败',unknown:'结果未知',attention:'需核对',blocked:'处理受阻',partial:'保留部分样本'};
  const node=(tag,value,cls)=>{const n=document.createElement(tag);if(value!==undefined)n.textContent=value;if(cls)n.className=cls;return n;};
  const stamp=at=>at?new Date(at*1000).toLocaleString('zh-CN',{hour12:false}):'';
  function facts(d,includeTime=false){
    return [includeTime?stamp(d.at):'',d.http_status==null?'':`HTTP ${d.http_status}`,
      d.provider_code==null?'':`接口码 ${d.provider_code}`,d.cli_exit==null?'':`CLI 退出码 ${d.cli_exit}`,
      d.duration_ms==null?'':d.duration_ms<1000?`${d.duration_ms} 毫秒`:`${(d.duration_ms/1000).toFixed(1)} 秒`,
      d.credits==null?'':`平台报告 ${d.credits} credits`,d.reference].filter(Boolean).join(' · ');
  }
  const state=(value,fallback='需核对')=>states[value]||fallback;
  let serial=0,dialog,activeAbort;
  const visible=()=>Boolean(dialog?.open);
  const close=()=>{++serial;activeAbort?.abort();activeAbort=null;if(visible())dialog.close();dialog?.querySelector('.task-feedback-body').replaceChildren();};
  function mount(){
    if(dialog)return dialog;
    dialog=node('dialog',undefined,'task-feedback-dialog');dialog.setAttribute('aria-labelledby','task-feedback-title');
    const head=node('div',undefined,'task-feedback-head'),title=node('h2','处理记录');title.id='task-feedback-title';
    const button=node('button','关闭','secondary');button.type='button';button.addEventListener('click',close);
    const body=node('div',undefined,'task-feedback-body');body.setAttribute('aria-live','polite');
    head.append(title,button);dialog.append(head,body);document.body.append(dialog);
    dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
    dialog.addEventListener('close',()=>{if(!visible())close();});
    return dialog;
  }
  async function open(url,context){
    const d=mount(),body=d.querySelector('.task-feedback-body'),request=++serial,epoch=typeof sessionEpoch==='number'?sessionEpoch:null;
    activeAbort?.abort();const abort=new AbortController();activeAbort=abort;
    const header=node('div',undefined,'task-feedback-context'),status=state(context.feedback_state||context.state);
    header.append(node('strong',`${context.kind||'当前任务'} · ${status}`),node('p',`中台任务编号：${context.id}`,'task-feedback-meta'));
    if(context.error)header.append(node('p',context.error));
    if(context.feedback_state==='unknown')header.append(node('p','请先在原平台核对。没有返回结果不代表没有执行或扣费，请勿重复提交。','task-feedback-meta'));
    const output=node('div');const history=node('div',undefined,'task-feedback-timeline');
    body.replaceChildren(header,output,history);output.append(node('p','正在读取处理记录…','task-feedback-meta'));
    if(!d.open)d.showModal();d.scrollTop=0;
    const live=()=>d.open&&request===serial&&!abort.signal.aborted&&(epoch===null||epoch===sessionEpoch);
    try{
      const response=await fetch(url,{credentials:'same-origin',signal:abort.signal});
      if(!live())return;
      if(response.status===404){output.textContent='未找到该处理记录。任务可能已更新、不可见，或服务尚未加载新版；请刷新任务列表核对。';return;}
      if(response.status===401){output.textContent='登录已失效，请重新登录后查看。';return;}
      if(!response.ok)throw Error('读取失败');
      const data=await response.json();if(!live())return;
      const items=Array.isArray(data.items)?data.items:[];output.replaceChildren();
      if(!items.length){output.append(node('p','未留存逐步记录。历史错误保留在上方，不补填未知的处理过程。','task-feedback-meta'));return;}
      output.append(node('p','最近步骤在前。步骤完成不等于整项任务完成；没有费用数据不代表未扣费。','task-feedback-meta'));
      const rows=document.createDocumentFragment();
      for(const item of items){
        const row=node('div',undefined,'task-feedback-event'),top=node('div',undefined,'task-feedback-event-title');
        top.append(node('strong',item.stage),node('span',state(item.outcome),'task-feedback-meta'));
        row.append(top,node('p',facts(item,true),'task-feedback-meta'));
        const extra=[item.error_type?`异常类 ${item.error_type}`:'',item.transport_started===0?'提交未进入发送阶段':item.transport_started===1?'已进入 HTTP 发送流程，不代表平台收到':'',item.remote_id_seen===1?'响应包含运行编号':item.remote_id_seen===0?'未取得运行编号':''].filter(Boolean);
        if(extra.length)row.append(node('p',extra.join(' · '),'task-feedback-meta'));rows.append(row);
      }
      history.append(rows);
    }catch(e){if(live())output.textContent='处理记录读取失败，关闭后可重新打开。';}
  }
  function studio(job,channel){
    const box=node('div',undefined,'task-feedback-inline');
    const kind=channel==='libtv'?'LibTV 视频生成':'TikTok 公司账号池 · 视频生成';
    if(job.error)box.append(node('p',job.error,'task-error'));
    if(job.feedback_state==='unknown'||job.state==='unknown')box.append(node('p','请先核对原任务，勿重复生成。','task-feedback-meta'));
    const meta=[job.feedback?.stage||job.stage||(job.state==='unknown'?'提交结果待核对':''),facts(job.feedback||{}),job.updated?`更新于 ${stamp(job.updated)}`:''].filter(Boolean);
    if(meta.length)box.append(node('p',meta.join(' · '),'task-feedback-meta'));
    const actions=node('div',undefined,'task-actions');
    const pending=String(job.id).startsWith('pending-');
    if(!pending)actions.append(node('span','中台编号 '+job.id,'task-meta'));
    if(!pending&&Object.hasOwn(job,'feedback')){
      const button=node('button','查看处理记录');button.type='button';
      button.onclick=()=>void open(`/api/studio/task-feedback/${channel}/${encodeURIComponent(job.id)}`,{...job,kind});actions.append(button);
    }
    box.append(actions);return box;
  }
  window.hubTaskFeedback={state,stamp,facts,open,close,visible,studio};
})();

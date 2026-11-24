'use strict';
(() => {
 const root=document.getElementById('storage-report'),button=document.getElementById('storage-refresh');
 const make=(tag,text,cls)=>{const x=document.createElement(tag);if(text!==undefined)x.textContent=text;if(cls)x.className=cls;return x;};
 const size=n=>n>=1024**3?(n/1024**3).toFixed(2)+' GB':(n/1024**2).toFixed(1)+' MB';
 const issue=x=>{const notes=[];if(x.errors)notes.push(x.errors+' 处无法读取');if(x.skipped_links)notes.push(x.skipped_links+' 个链接已跳过');if(x.truncated)notes.push('扫描未完成');return notes.length?' · '+notes.join('，')+'（结果不完整）':'';};
 function cards(title,items){
  const section=make('section',undefined,'storage-section');section.append(make('h2',title));const grid=make('div',undefined,'storage-grid');
  for(const x of items){const card=make('article',undefined,'storage-card');card.append(make('h3',x.label));if(!x.available && x.available!==undefined)card.append(make('p','目录不可用','storage-incomplete'));else{card.append(make('strong',size(x.bytes)),make('p',x.files+' 个文件'+issue(x),issue(x)?'storage-incomplete':''));if(x.largest?.length){const details=make('details'),summary=make('summary','查看较大文件（最多 10 个）'),list=make('ul');for(const f of x.largest)list.append(make('li',f.name+' · '+size(f.bytes)));details.append(summary,list);card.append(details);}}grid.append(card);}section.append(grid);return section;
 }
 let loading=false;
 async function refresh(){if(loading)return;loading=true;button.disabled=true;root.replaceChildren(make('p','正在统计，请稍候…'));try{
   const r=await fetch('/api/admin/storage-report',{credentials:'same-origin',cache:'no-store'});if(!r.ok)throw new Error(r.status===403?'仅管理员可查看':'统计暂时不可用，请稍后重试');const data=await r.json();
   root.replaceChildren(make('p',data.note,'storage-note'),cards('当前使用的文件',data.categories));
   const e=data.exports,task=make('section',undefined,'storage-section');task.append(make('h2','剪辑导出任务（累计）'),make('p',`排队 ${e.queued||0} · 导出中 ${e.rendering||0} · 已完成 ${e.ready||0} · 失败 ${e.failed||0}`));root.append(task);
  }catch(err){root.replaceChildren(make('p',err.message,'storage-incomplete'));}finally{button.disabled=false;loading=false;}}
 button.addEventListener('click',refresh);window.storageReport={refresh};
})();

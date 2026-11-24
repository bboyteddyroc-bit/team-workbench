'use strict';
window.hubAssistantLayout=({panel,head,tools,history,memo,settings,mode,imageSize,imageRatio,imageCount,options,form})=>{
 const make=(tag,text,cls)=>{const n=document.createElement(tag);n.textContent=text||'';if(cls)n.className=cls;return n;};
 const btn=(text,fn)=>{const b=make('button',text);b.type='button';b.onclick=fn;return b;};
 panel.classList.add('assistant-redesign');
 const controls=make('div','','assistant-header-actions'),close=head.querySelector('button');close.textContent='收起';
 const newChat=tools.querySelector('button');head.append(controls);
 const drawer=make('aside','','assistant-history-drawer');drawer.hidden=true;drawer.setAttribute('aria-label','历史对话');
 const historyList=make('div');drawer.append(make('h3','历史对话'),historyList);panel.append(drawer);
 const drawHistory=()=>{historyList.replaceChildren();for(const o of history.options){if(!o.value)continue;const b=btn(o.textContent,()=>{if(history.disabled)return;history.value=o.value;history.dispatchEvent(new Event('change'));drawer.hidden=true;});b.disabled=history.disabled;b.classList.toggle('active',o.selected);historyList.append(b);}if(!historyList.children.length)historyList.append(make('p','还没有历史对话'));};
 controls.append(btn('历史',()=>{drawer.hidden=!drawer.hidden;drawHistory();}),newChat);
 new MutationObserver(drawHistory).observe(history,{childList:true,attributes:true,attributeFilter:['disabled'],subtree:true});
 const more=make('details','','assistant-more'),summary=make('summary','更多'),menu=make('div','','assistant-more-menu');more.append(summary,menu);
 const connection=btn('连接设置',()=>{if(settings.hidden)return;settings.open=!settings.open;more.open=false;});connection.hidden=settings.hidden;new MutationObserver(()=>{connection.hidden=settings.hidden;}).observe(settings,{attributes:true,attributeFilter:['hidden']});
 menu.append(btn('个人记忆',()=>{memo.open=!memo.open;more.open=false;}),connection,tools.querySelector('button'));
 controls.append(more);tools.hidden=true;
 const tabs=make('div','','assistant-mode-tabs');
 for(const [value,text] of [['chat','对话'],['image','生图']]){const b=btn(text,()=>{if(mode.disabled)return;mode.value=value;mode.onchange();paintOptions();});b.dataset.mode=value;tabs.append(b);}
 mode.style.display='none';options.prepend(tabs);
 const params=make('details','','assistant-params'),paramTitle=make('summary','画面设置'),paramBody=make('div','','assistant-param-body');params.append(paramTitle,paramBody);options.append(params);
 for(const [select,label]of [[imageRatio,'比例'],[imageSize,'清晰度'],[imageCount,'数量']]){const row=make('div','','assistant-param-row');row.append(make('span',label));select.style.display='none';paramBody.append(select);for(const o of select.options){const b=btn(o.textContent,()=>{if(select.disabled||o.disabled)return;select.value=o.value;paintOptions();});b.dataset.value=o.value;row.append(b);}paramBody.append(row);select._row=row;}
 function paintOptions(){tabs.querySelectorAll('button').forEach(b=>{b.setAttribute('aria-pressed',String(b.dataset.mode===mode.value));b.disabled=mode.disabled;});params.hidden=mode.value!=='image';paramTitle.textContent=imageRatio.value+' · '+imageSize.value+' · '+imageCount.value+' 张';for(const select of [imageRatio,imageSize,imageCount])select._row.querySelectorAll('button').forEach(b=>{b.disabled=select.disabled||!![...select.options].find(o=>o.value===b.dataset.value)?.disabled;b.setAttribute('aria-pressed',String(b.dataset.value===select.value));});}
 const change=mode.onchange;mode.onchange=()=>{change();paintOptions();};paintOptions();
 new MutationObserver(paintOptions).observe(mode,{attributes:true,attributeFilter:['disabled']});
 let maximized=false,geometry=null;
 try{geometry=JSON.parse(localStorage.getItem('hub-assistant-window-v1'));}catch{}
 const clamp=(n,min,max)=>Math.max(min,Math.min(max,n));
 function fit(g){return {w:clamp(Number(g?.w)||720,Math.min(360,innerWidth-24),innerWidth-24),h:clamp(Number(g?.h)||innerHeight*.85,Math.min(360,innerHeight-24),innerHeight-24),x:Number(g?.x),y:Number(g?.y)};}
 function apply(){const g=fit(geometry);g.x=clamp(Number.isFinite(g.x)?g.x:innerWidth-g.w-24,12,innerWidth-g.w-12);g.y=clamp(Number.isFinite(g.y)?g.y:innerHeight-g.h-76,12,innerHeight-g.h-12);geometry=g;Object.assign(panel.style,maximized?{left:'12px',top:'12px',width:(innerWidth-24)+'px',height:(innerHeight-24)+'px'}:{left:g.x+'px',top:g.y+'px',width:g.w+'px',height:g.h+'px'});}
 const save=()=>{try{localStorage.setItem('hub-assistant-window-v1',JSON.stringify(geometry));}catch{}};
 const expand=btn('展开',()=>{maximized=!maximized;expand.textContent=maximized?'还原':'展开';apply();});controls.append(expand,close);apply();window.addEventListener('resize',apply);
 function drag(e,edge){if(e.button!==0||maximized||(!edge&&e.target.closest('button,details')))return;e.preventDefault();const original={...geometry},x=e.clientX,y=e.clientY;const target=e.currentTarget;target.setPointerCapture(e.pointerId);
  const move=event=>{const dx=event.clientX-x,dy=event.clientY-y;if(!edge)geometry={...original,x:original.x+dx,y:original.y+dy};else{let left=original.x,top=original.y,right=left+original.w,bottom=top+original.h;if(edge.includes('e'))right=clamp(right+dx,left+Math.min(360,innerWidth-24),innerWidth-12);if(edge.includes('s'))bottom=clamp(bottom+dy,top+Math.min(360,innerHeight-24),innerHeight-12);if(edge.includes('w'))left=clamp(left+dx,12,right-Math.min(360,innerWidth-24));if(edge.includes('n'))top=clamp(top+dy,12,bottom-Math.min(360,innerHeight-24));geometry={x:left,y:top,w:right-left,h:bottom-top};}apply();};
  const end=()=>{target.removeEventListener('pointermove',move);target.removeEventListener('lostpointercapture',end);save();};target.addEventListener('pointermove',move);target.addEventListener('lostpointercapture',end);
 }
 head.addEventListener('pointerdown',e=>drag(e,''));
 for(const edge of ['n','s','e','w','ne','nw','se','sw']){const handle=make('div','','assistant-resize '+edge);handle.setAttribute('aria-hidden','true');handle.onpointerdown=e=>drag(e,edge);panel.append(handle);}
 new MutationObserver(()=>{if(panel.hidden){drawer.hidden=true;more.open=params.open=memo.open=settings.open=false;}}).observe(panel,{attributes:true,attributeFilter:['hidden']});
};

/* UI organization only: no generation, account or persistence API calls. */
'use strict';
document.addEventListener('DOMContentLoaded',()=>{
  const by=id=>document.getElementById(id);
  const reduced=matchMedia('(prefers-reduced-motion: reduce)');
  const animate=(node)=>{
    if(!node||reduced.matches||!window.gsap)return;
    gsap.killTweensOf(node);
    gsap.fromTo(node,{opacity:.75,y:5},{opacity:1,y:0,duration:.22,ease:'power2.out',clearProps:'opacity,transform',overwrite:true});
  };
  // Optional canvas presentation moves no data and keeps the existing form handlers.
  const studio=by('studio'),list=by('composition-list'),form=by('create-form');
  let settingsPop=null;
  if(studio&&list&&form){
    const bar=document.createElement('div'),toggle=document.createElement('button'),hint=document.createElement('span');
    bar.className='canvas-view-toolbar';bar.hidden=true;toggle.type='button';toggle.className='secondary';toggle.textContent='切换画布视图';toggle.setAttribute('aria-pressed','true');studio.classList.add('canvas-view','simple-studio');
    bar.append(toggle,hint);form.before(bar);
    toggle.onclick=()=>{const on=studio.classList.toggle('canvas-view');toggle.textContent=on?'返回列表视图':'切换画布视图';toggle.setAttribute('aria-pressed',String(on));};
    const tools=document.createElement('div'),add=document.createElement('button'),save=document.createElement('button'),history=document.createElement('button'),settings=document.createElement('button');
    tools.className='simple-toolbar';const channel=by('generation-channel')?.closest('label');if(channel)channel.classList.add('simple-channel');for(const b of [add,save,history,settings]){b.type='button';b.className='secondary';}add.textContent='＋ 新建窗口';save.textContent='保存草稿';history.textContent='任务记录';settings.textContent='生成渠道';tools.append(add,settings,history);studio.prepend(tools);
    add.onclick=()=>by('add-composition').click();save.onclick=()=>by('save-compositions').click();
    // Settings holds generation-channel choices only; the rest of the old form stays retired.
    const pop=document.createElement('div');pop.className='settings-pop';pop.hidden=true;pop.setAttribute('role','dialog');pop.setAttribute('aria-label','生成渠道');
    const popHead=document.createElement('h3'),popClose=document.createElement('button');popHead.textContent='生成渠道';popClose.onclick=()=>document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));popClose.type='button';popClose.className='settings-close';popClose.textContent='×';popClose.setAttribute('aria-label','关闭设置');
    const popTop=document.createElement('div');popTop.className='settings-pop-head';popTop.append(popHead,popClose);pop.append(popTop);
    const setOpen=open=>{if(!open)document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',bubbles:true}));};
    const mount=document.createElement('span');settings.replaceWith(mount);studio.append(pop);window.hubPopover.mount(mount,pop,'生成渠道','channel');settingsPop=pop;studio.dataset.settingsPop='1';
    let lastChannelLabel='';const syncChannel=()=>{const ch=by('generation-channel');const name=ch?.value==='libtv'?pop.querySelector('[aria-label="LibTV 生成账号"]')?.selectedOptions[0]?.textContent:'公司账号池';const label=ch?.value==='libtv'?'LibTV · '+(name||'选择账号'):'TikTok · '+(name||'公司账号池');if(label!==lastChannelLabel){lastChannelLabel=label;pop.dataset.hubLabel=label;pop.dispatchEvent(new CustomEvent('hub-label',{detail:label}));}};
    document.addEventListener('change',syncChannel);new MutationObserver(syncChannel).observe(document.body,{childList:true,subtree:true});syncChannel();
    // 任务记录：与“更多设置”同款浮层，任务列表整体搬进来，不再把画布往下推。
    const hist=document.createElement('div');hist.className='history-pop';hist.hidden=true;hist.setAttribute('role','dialog');hist.setAttribute('aria-label','任务记录');
    const histHead=document.createElement('div'),histTitle=document.createElement('h3'),histClose=document.createElement('button'),histBody=document.createElement('div');
    histHead.className='settings-pop-head';histTitle.textContent='任务记录';histClose.type='button';histClose.className='settings-close';histClose.textContent='×';histClose.setAttribute('aria-label','关闭任务记录');
    histBody.className='history-pop-body';histHead.append(histTitle,histClose);hist.append(histHead,histBody);studio.append(hist);
    const histCount=document.createElement('span');histCount.className='history-count';histTitle.after(histCount);
    const countNode=by('task-count');
    if(countNode){const sync=()=>{histCount.textContent=(countNode.textContent||'').trim();};sync();new MutationObserver(sync).observe(countNode,{childList:true,characterData:true,subtree:true});}
    const queue=document.querySelector('.queue');if(queue)histBody.append(queue);
    const setHistory=open=>{hist.hidden=!open;history.setAttribute('aria-pressed',String(open));if(open)histBody.scrollTop=0;};
    history.onclick=()=>{setOpen(false);setHistory(hist.hidden);};histClose.onclick=()=>setHistory(false);
    window.hubStudioHistory={open:(filter)=>{setOpen(false);setHistory(true);if(filter==='failed')hist.querySelector('[data-filter="failed"]')?.click();},close:()=>setHistory(false)};
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!hist.hidden&&!window.hubTaskFeedback?.visible())setHistory(false);});
    // 挂在 body 上的下拉面板、任务详情不关闭任务记录。
    document.addEventListener('pointerdown',e=>{const target=e.target;if(target.closest?.('.bs-panel,.task-feedback-dialog'))return;if(!hist.hidden&&!hist.contains(target)&&!history.contains(target))setHistory(false);});
    // Cards and relay lines share canvas coordinates and a single camera transform.
    const viewport=document.createElement('div'),world=document.createElement('div'),zoom=document.createElement('div');
    const svgNS='http://www.w3.org/2000/svg',links=document.createElementNS(svgNS,'svg');
    viewport.className='canvas-viewport';world.className='canvas-world';
    links.setAttribute('class','relay-layer');links.setAttribute('aria-hidden','true');
    list.before(viewport);viewport.append(world);world.append(links,list);
    zoom.className='canvas-zoom';zoom.setAttribute('role','group');zoom.setAttribute('aria-label','画布视图');
    const zoomButton=(text,name)=>{const b=document.createElement('button');b.type='button';b.className='secondary';b.textContent=text;if(name)b.setAttribute('aria-label',name);return b;};
    const minus=zoomButton('−','缩小画布'),plus=zoomButton('+','放大画布'),reset=zoomButton('复位');
    const fit=zoomButton('适应窗口'),locate=zoomButton('定位最新卡片'),label=document.createElement('span');
    fit.title='以 50% 缩放查看画布';locate.title='定位到最近创建的创作卡片';
    zoom.append(minus,label,plus,reset,fit,locate);viewport.after(zoom);
    const fitZoom=.5,minZoom=.1,maxZoom=1.4;
    let camera={x:32,y:32,z:fitZoom},gesture=null,viewOwner=null,fitPending=false;
    let frame=0,viewTimer=0,geometryDirty=true,cameraDirty=true;
    let cards=new Map(),bounds=new Map(),edges=new Map(),incident=new Map();
    const currentCards=()=>[...list.children].filter(card=>card.classList.contains('composition'));
    const cameraKey=id=>'hub-canvas-view:'+id;
    function persistView(){
      clearTimeout(viewTimer);viewTimer=0;
      if(viewOwner==null||viewOwner!==me?.id)return;
      const w=viewport.clientWidth,h=viewport.clientHeight;
      if(viewOwner!=null&&viewOwner===me?.id&&w&&h)try{localStorage.setItem(cameraKey(viewOwner),JSON.stringify({...camera,viewportWidth:w,viewportHeight:h}));}catch{}
    }
    function paintCamera(){
      cameraDirty=false;
      world.style.transform=`translate3d(${camera.x}px,${camera.y}px,0) scale(${camera.z})`;
      const text=Math.round(camera.z*100)+'%';if(label.textContent!==text)label.textContent=text;
    }
    function syncEdges(){
      const next=new Map();incident=new Map();
      for(const c of compositions){
        if(!cards.has(c.relay_source)||!cards.has(c.id))continue;
        let edge=edges.get(c.id);
        if(!edge){
          const group=document.createElementNS(svgNS,'g'),path=document.createElementNS(svgNS,'path');
          path.setAttribute('class','relay-link');group.append(path);
          const dots=Array.from({length:2},()=>{const dot=document.createElementNS(svgNS,'circle');dot.setAttribute('r','3');dot.setAttribute('class','relay-link-dot');group.append(dot);return dot;});
          links.append(group);edge={group,path,dots};
        }
        edge.from=c.relay_source;edge.to=c.id;next.set(c.id,edge);
        for(const id of [edge.from,edge.to]){if(!incident.has(id))incident.set(id,new Set());incident.get(id).add(edge);}
      }
      for(const [id,edge] of edges)if(!next.has(id))edge.group.remove();
      edges=next;
    }
    function paintEdge(edge,p){
      const a=bounds.get(edge.from),b=bounds.get(edge.to);
      if(!a?.w||!b?.w){edge.group.style.display='none';return;}
      if(edge.group.style.display)edge.group.style.display='';
      const ax=a.x+a.w+(p?.id===edge.from?p.dx:0),ay=a.y+a.h*.42+(p?.id===edge.from?p.dy:0);
      const bx=b.x+(p?.id===edge.to?p.dx:0),by=b.y+b.h*.42+(p?.id===edge.to?p.dy:0);
      const bend=Math.max(36,Math.abs(bx-ax)*.42)*Math.sign(bx-ax||1);
      edge.path.setAttribute('d',`M${ax},${ay} C${ax+bend},${ay} ${bx-bend},${by} ${bx},${by}`);
      [[ax,ay],[bx,by]].forEach(([x,y],i)=>{edge.dots[i].setAttribute('cx',x);edge.dots[i].setAttribute('cy',y);});
    }
    const measure=card=>({x:card.offsetLeft,y:card.offsetTop,w:card.offsetWidth,h:card.offsetHeight});
    function paint(){
      frame=0;const p=gesture?.kind==='card'?gesture:null;
      if(geometryDirty){
        geometryDirty=false;bounds=new Map();
        for(const id of incident.keys()){const card=cards.get(id);if(card)bounds.set(id,measure(card));}
        for(const edge of edges.values())paintEdge(edge,p);
      }else if(p){for(const edge of incident.get(p.id)||[])paintEdge(edge,p);}
      if(p)p.card.style.translate=`${p.dx}px ${p.dy}px`;
      if(cameraDirty)paintCamera();
    }
    const queuePaint=()=>{if(!frame)frame=requestAnimationFrame(paint);};
    const redraw=()=>{geometryDirty=true;queuePaint();};
    const updateCamera=()=>{cameraDirty=true;queuePaint();};
    function moveGesture(e){
      const p=gesture;if(!p||p.pointer!==e.pointerId)return;
      const dx=e.clientX-p.x,dy=e.clientY-p.y;
      if(p.kind==='pan'){camera.x=p.origin.x+dx;camera.y=p.origin.y+dy;cameraDirty=true;}
      else{p.dx=dx/p.scale;p.dy=dy/p.scale;}
      queuePaint();
    }
    function endGesture(commit,e){
      const p=gesture;if(!p||(e&&p.pointer!==e.pointerId))return;
      if(commit)moveGesture(e);
      gesture=null;viewport.classList.remove('panning');
      if(viewport.hasPointerCapture(p.pointer))viewport.releasePointerCapture(p.pointer);
      if(p.kind==='pan'){
        if(!commit)camera=p.origin;
        updateCamera();if(commit)persistView();return;
      }
      if(commit&&p.card.isConnected&&compositions.includes(p.item)){
        const x=Math.round(p.origin.x+p.dx),y=Math.round(p.origin.y+p.dy);
        if(x!==p.origin.x||y!==p.origin.y){
          p.item.canvas_position={x,y};p.card.style.left=x+'px';p.card.style.top=y+'px';
          window.hubAutoSave?.schedule();
        }
      }
      p.card.style.removeProperty('translate');p.card.classList.remove('canvas-card-dragging');redraw();
    }
    const editing='button,input,select,textarea,summary,video,a,label,[contenteditable],.material-area,.reference-chips,.mention-menu,.parameter-body';
    viewport.addEventListener('pointerdown',e=>{
      if(e.button!==0||!e.isPrimary||gesture||e.target.closest(editing))return;
      const card=e.target.closest('.composition');
      const item=card&&compositions.find(c=>c.id===card.dataset.compositionId);
      if(card&&!item?.canvas_position)return;
      try{viewport.setPointerCapture(e.pointerId);}catch{return;}
      e.preventDefault();
      if(viewTimer){persistView();viewTimer=0;}
      const start={pointer:e.pointerId,x:e.clientX,y:e.clientY};
      if(card){
        gesture={...start,kind:'card',card,item,id:item.id,origin:{...item.canvas_position},scale:camera.z,dx:0,dy:0};
        card.classList.add('canvas-card-dragging');
      }else{gesture={...start,kind:'pan',origin:{...camera}};viewport.classList.add('panning');}
    });
    viewport.addEventListener('pointermove',moveGesture);
    viewport.addEventListener('pointerup',e=>endGesture(true,e));
    for(const type of ['pointercancel','lostpointercapture'])viewport.addEventListener(type,e=>endGesture(false,e));
    window.addEventListener('blur',()=>{if(gesture)endGesture(false);});

    function zoomAt(z,x,y){
      const n=Math.max(minZoom,Math.min(maxZoom,z));if(n===camera.z)return;
      const ratio=n/camera.z;camera={x:x-(x-camera.x)*ratio,y:y-(y-camera.y)*ratio,z:n};updateCamera();
    }
    function buttonZoom(delta){if(gesture)return;zoomAt(camera.z+delta,viewport.clientWidth/2,viewport.clientHeight/2);persistView();}
    minus.onclick=()=>buttonZoom(-.1);plus.onclick=()=>buttonZoom(.1);
    reset.onclick=()=>{if(!gesture){camera={x:32,y:32,z:1};updateCamera();persistView();}};
    const wheelNative='textarea,select,input,[contenteditable],.parameter-body,.reference-selected-gallery,.mention-menu';
    viewport.addEventListener('wheel',e=>{
      if(e.defaultPrevented||e.metaKey||e.altKey||!e.cancelable)return;
      if(!e.ctrlKey&&(e.target.closest(wheelNative)||(Math.abs(e.deltaX)>Math.abs(e.deltaY)&&e.target.closest('.window-results'))))return;
      if(!e.deltaY&&!e.deltaX)return;
      e.preventDefault();if(gesture)return;
      const unit=e.deltaMode===1?16:e.deltaMode===2?viewport.clientHeight:1;
      if(e.ctrlKey){
        const r=viewport.getBoundingClientRect(),delta=Math.max(-200,Math.min(200,e.deltaY*unit));
        zoomAt(camera.z*Math.exp(-delta*.0025),e.clientX-r.left,e.clientY-r.top);
      }else{
        camera.x-=e.deltaX*unit;camera.y-=e.deltaY*unit;updateCamera();
      }
      clearTimeout(viewTimer);viewTimer=setTimeout(persistView,200);
    },{passive:false});
    function center(box,z){
      const w=viewport.clientWidth,h=viewport.clientHeight;
      camera={x:Math.max(16,(w-box.w*z)/2)-box.x*z,y:Math.max(54,(h-box.h*z)/2)-box.y*z,z};
      updateCamera();persistView();
    }
    function fitCanvas(){
      const items=currentCards(),w=viewport.clientWidth,h=viewport.clientHeight;
      if(gesture||!items.length||!w||!h)return;
      fitPending=false;
      const rects=items.map(measure),x=Math.min(...rects.map(r=>r.x)),y=Math.min(...rects.map(r=>r.y));
      const box={x,y,w:Math.max(...rects.map(r=>r.x+r.w))-x,h:Math.max(...rects.map(r=>r.y+r.h))-y};
      // Distant cards must not shrink the workspace to an unreadable overview.
      center(box.w*fitZoom<=w-32&&box.h*fitZoom<=h-72?box:rects.at(-1),fitZoom);
    }
    fit.onclick=fitCanvas;
    function reveal(id,focus=false){
      const card=cards.get(id)||currentCards().find(card=>card.dataset.compositionId===id);
      if(!card||gesture||!viewport.clientWidth)return;
      center(measure(card),camera.z);
      card.querySelector('.parameter-popover[open]')?.reposition?.();
      if(focus)card.querySelector('textarea')?.focus({preventScroll:true});
    }
    locate.onclick=()=>{const card=currentCards().at(-1);if(card)reveal(card.dataset.compositionId,true);};
    window.hubCanvas={toCanvas:(clientX,clientY)=>{
      const r=viewport.getBoundingClientRect();return {x:(clientX-r.left-camera.x)/camera.z,y:(clientY-r.top-camera.y)/camera.z};
    },redraw,reveal};
    const sizeObserver=window.ResizeObserver?new ResizeObserver(()=>{if(fitPending)fitCanvas();redraw();}):null;
    function decorate(){
      if(gesture?.kind==='card'&&!list.contains(gesture.card))endGesture(false);
      for(const card of cards.values())sizeObserver?.unobserve(card);
      cards=new Map();const items=new Map(compositions.map(c=>[c.id,c]));
      for(const [i,card] of currentCards().entries()){
        const item=items.get(card.dataset.compositionId);if(!item)continue;
        if(!Number.isFinite(item.canvas_position?.x)||!Number.isFinite(item.canvas_position?.y))item.canvas_position={x:i*510,y:0};
        card.style.left=item.canvas_position.x+'px';card.style.top=item.canvas_position.y+'px';
        const heading=card.querySelector('.composition-heading');if(heading)heading.title='拖动窗口空白处或预览区移动；位置自动保存';
        cards.set(item.id,card);sizeObserver?.observe(card);
      }
      locate.disabled=!cards.size;fit.disabled=!cards.size;syncEdges();redraw();
      if(fitPending)fitCanvas();
    }
    new MutationObserver(decorate).observe(list,{childList:true});
    sizeObserver?.observe(viewport);window.addEventListener('resize',()=>{if(fitPending)fitCanvas();redraw();});
    window.addEventListener('hub-composer-restored',()=>{
      clearTimeout(viewTimer);viewOwner=me?.id;fitPending=true;camera={x:32,y:32,z:fitZoom};
      try{
        const saved=JSON.parse(localStorage.getItem(cameraKey(viewOwner))||'null');
        if(saved&&Number.isFinite(saved.x)&&Number.isFinite(saved.y)&&saved.z>=minZoom&&saved.z<=maxZoom){
          camera={x:saved.x,y:saved.y,z:saved.z};fitPending=false;
        }
      }catch{}
      updateCamera();if(fitPending)requestAnimationFrame(()=>{if(fitPending)fitCanvas();});
    });
    decorate();updateCamera();
    const relayPayload=e=>e.dataTransfer.getData('application/x-hub-relay')||e.dataTransfer.getData('application/x-seedance-relay');
    viewport.addEventListener('dragover',e=>{if([...e.dataTransfer.types].some(t=>t==='application/x-hub-relay'||t==='application/x-seedance-relay')){e.preventDefault();e.dataTransfer.dropEffect='copy';viewport.classList.add('relay-target');}});
    viewport.addEventListener('dragleave',e=>{if(!viewport.contains(e.relatedTarget))viewport.classList.remove('relay-target');});
    viewport.addEventListener('drop',e=>{
      const raw=relayPayload(e);if(!raw)return;
      e.preventDefault();viewport.classList.remove('relay-target');
      let payload;try{payload=JSON.parse(raw);}catch{payload={task:raw};}
      if(!payload||typeof payload!=='object')payload={task:String(raw)};
      const task=window.hubRelay.resolve(payload.task,payload.provider);
      if(!task){toast('找不到已完成的来源视频，请刷新任务',true);return;}
      const point=window.hubCanvas.toCanvas(e.clientX,e.clientY);
      const source=payload.composition?compositions.find(c=>c.id===payload.composition):null;
      const job=source?window.hubRelay.createFrom(source,task,point):window.hubRelay.fromTask(task,point);
      job.catch(err=>toast(err.message||String(err),true));
    });
    // A hidden or replaced workspace must not retain an active pointer gesture.
    new MutationObserver(()=>{if(studio.hidden&&gesture)endGesture(false);}).observe(studio,{attributes:true,attributeFilter:['hidden']});
  }
  const note=by('integration-note');
  if(note){const details=document.createElement('details'),summary=document.createElement('summary');details.className='capability-disclosure';summary.textContent='模型与参考素材支持说明';note.before(details);details.append(summary,note);}
  // Everything except the generation channel is read-only info; retired form controls stay hidden.
  if(settingsPop){
    const adopt=()=>{
      const label=by('generation-channel')?.closest('label');
      // Keep explanatory content out of this compact selector, but preserve it elsewhere for existing logic.
      if(label&&label.parentElement!==settingsPop)settingsPop.insertBefore(label,settingsPop.children[1]||null);
      return !!label;
    };
    adopt();
    // LibTV adds the channel select after this script runs; adopt it as soon as it appears.
    const host=form.parentElement;if(host&&!by('generation-channel')){const io=new MutationObserver(()=>{if(adopt())io.disconnect();});io.observe(host,{childList:true,subtree:true});setTimeout(()=>io.disconnect(),15000);}
  }
  function searchList(listId,rowClass,label){
    const list=by(listId);if(!list)return;
    if(list.parentElement.classList.contains('settings-grid')){const group=document.createElement('div');list.before(group);group.append(list);}
    const bar=document.createElement('div');bar.className='workbench-search';
    const input=document.createElement('input');input.type='search';input.autocomplete='off';input.name=listId+'-filter';input.placeholder=label;input.setAttribute('aria-label',label);
    const count=document.createElement('span');count.setAttribute('role','status');
    const empty=document.createElement('p');empty.className='search-empty';empty.textContent='没有匹配的记录，请修改搜索内容。';empty.hidden=true;
    bar.append(input,count);list.before(bar);list.after(empty);
    const apply=()=>{const rows=[...list.querySelectorAll(rowClass)],q=input.value.trim().toLocaleLowerCase();let n=0;for(const row of rows){row.hidden=!!q&&!row.textContent.toLocaleLowerCase().includes(q);if(!row.hidden)n++;}count.textContent=rows.length?`${n} / ${rows.length} 条`:'';empty.hidden=!rows.length||n>0;};
    input.addEventListener('input',apply);new MutationObserver(apply).observe(list,{childList:true});apply();
  }
  // Member search is provided by the member table.
  // Account search is provided by the account table.
  // Audit search is provided by the audit table.
  function disclosure(host,nodes,label){
    const available=nodes.filter(Boolean);if(!host||!available.length)return;
    const details=document.createElement('details'),summary=document.createElement('summary');details.className='tool-disclosure';summary.textContent=label;details.append(summary);available[0].before(details);available.forEach(n=>details.append(n));details.addEventListener('toggle',()=>{if(details.open)animate(details);});
  }
  const voice=by('voice-panel');
  // Keep voice selection and generate action visible; only auxiliary text import is folded.
  if(voice){const read=by('voice-read-all');if(read)disclosure(voice,[read.parentElement],'手动读取字幕到文案');}
  const editor=by('editor'),command=editor?.querySelector('.editor-commandbar');
  if(command){const focus=document.createElement('button');focus.type='button';focus.className='secondary focus-toggle';focus.textContent='专注剪辑';focus.setAttribute('aria-pressed','false');
    const setFocus=value=>{document.body.classList.toggle('editor-focus',value);focus.textContent=value?'退出专注':'专注剪辑';focus.setAttribute('aria-pressed',String(value));};
    focus.onclick=()=>setFocus(!document.body.classList.contains('editor-focus'));command.append(focus);
    document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.body.classList.contains('editor-focus')&&!document.querySelector('dialog[open]'))setFocus(false);});
    new MutationObserver(()=>{if(editor.hidden)setFocus(false);}).observe(editor,{attributes:true,attributeFilter:['hidden']});
  }
  document.querySelectorAll('.view').forEach(view=>new MutationObserver(()=>{if(!view.hidden)animate(view.querySelector('.page-heading'));}).observe(view,{attributes:true,attributeFilter:['hidden']}));
  document.querySelectorAll('dialog').forEach(dialog=>new MutationObserver(()=>{if(dialog.open)animate(dialog);}).observe(dialog,{attributes:true,attributeFilter:['open']}));
  reduced.addEventListener('change',()=>{if(reduced.matches&&window.gsap)document.querySelectorAll('.page-heading,dialog,.tool-disclosure').forEach(node=>{gsap.killTweensOf(node);node.style.removeProperty('opacity');node.style.removeProperty('transform');});});
});


'use strict';
(()=>{
  const scroll=document.querySelector('.track-scroll'),toolbar=document.querySelector('.clip-toolbar');if(!scroll||!toolbar)return;
  const row=document.createElement('div');row.className='track-row compound-row';row.hidden=true;
  const label=document.createElement('span');label.className='track-label';label.textContent='';
  const lane=document.createElement('div');lane.className='track-lane compound-lane';row.append(label,lane);document.getElementById('timeline-ruler').after(row);
  for(const [text,key,kind,remove]of [['组合','Ctrl+G','group',false],['取消组合','Ctrl+Shift+G','group',true],['创建复合片段','Alt+G','compound',false],['解除复合片段','Alt+Shift+G','compound',true]]){
    const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent=text;button.title=text+' · '+key;button.onclick=()=>window.hubEditor.bundle(kind,remove);toolbar.insertBefore(button,toolbar.querySelector('.fine'));
  }
  const context=document.createElement('div');context.className='compound-context';context.hidden=true;
  const back=document.createElement('button');back.type='button';back.textContent='完成编辑';
  const contextTitle=document.createElement('span');context.append(back,contextTitle);toolbar.before(context);
  let queued=false;
  function paint(){
    queued=false;const editor=window.hubEditor;if(!editor)return;
    const bundles=editor.bundleRows(),current=editor.current();lane.replaceChildren();scroll.querySelectorAll('.compound-block,.compound-edit-frame').forEach(n=>n.remove());row.hidden=true;
    lane.style.width=(parseFloat(document.getElementById('timeline-ruler').style.width)-104)+'px';lane.style.height=Math.max(44,bundles.length*44)+'px';
    scroll.querySelectorAll('[data-timeline-key]').forEach(n=>{n.classList.remove('compound-member-hidden');n.removeAttribute('data-bundle');const [kind,index]=n.dataset.timelineKey.split(':');const item=kind==='video'||kind==='original'?current?.body.clips[index]:kind==='caption'?current?.body.captions[index]:kind==='detached'?current?.body.audio_clips?.[index]:null;if(item?.edit_group)n.dataset.bundle='group';});
    const active=bundles.find(b=>b.expanded);context.hidden=!active;
    scroll.classList.toggle('compound-editing',!!active);
    scroll.querySelectorAll('[data-timeline-key]').forEach(n=>{n.classList.remove('compound-edit-member','compound-edit-outside');if(active)n.classList.add(active.keys.includes(n.dataset.timelineKey)?'compound-edit-member':'compound-edit-outside');});
    if(active){contextTitle.textContent='复合片段 '+(bundles.indexOf(active)+1)+' · 内部编辑';back.onclick=()=>editor.toggleCompound(active.id);}
    if(active){
      const members=active.keys.map(k=>scroll.querySelector('[data-timeline-key="'+k+'"]')).filter(Boolean);
      if(members.length){const rect=scroll.getBoundingClientRect(),boxes=members.map(n=>n.getBoundingClientRect()),top=Math.min(...boxes.map(b=>b.top))-rect.top+scroll.scrollTop,bottom=Math.max(...boxes.map(b=>b.bottom))-rect.top+scroll.scrollTop;
        const frame=document.createElement('div');frame.className='compound-edit-frame';frame.setAttribute('aria-hidden','true');Object.assign(frame.style,{left:(104+active.start*(window.hubTimelineScale||32))+'px',top:(top-2)+'px',width:Math.max(2,(active.end-active.start)*(window.hubTimelineScale||32))+'px',height:(bottom-top+4)+'px'});scroll.append(frame);
      }
    }
    bundles.forEach((bundle,i)=>{
      if(bundle.expanded)return;
      const block=document.createElement('button');block.type='button';block.className='compound-block';block.dataset.compound=bundle.id;block.dataset.timelineKeys=JSON.stringify(bundle.keys);block.textContent=(bundle.expanded?'▾ ':'▸ ')+'复合片段 '+(i+1)+' · '+bundle.keys.length;
      const members=bundle.keys.map(key=>scroll.querySelector('[data-timeline-key="'+key+'"]')).filter(Boolean),host=members.find(n=>n.dataset.timelineKey.startsWith('video:'))||members[0];
      const targetLane=host?.closest('.track-lane')||lane;
      const film=host?.querySelector('.timeline-preview,img');if(film){const thumb=film.cloneNode(true);thumb.removeAttribute('id');thumb.style.cssText+=';width:100%;height:42px;object-fit:cover;display:block;pointer-events:none';block.prepend(thumb);}
      block.style.height='calc(100% - 8px)';block.style.overflow='hidden';
      block.title='单击选中，拖动移动，双击编辑内部片段';Object.assign(block.style,{left:bundle.start*(window.hubTimelineScale||32)+'px',width:Math.max(2,(bundle.end-bundle.start)*(window.hubTimelineScale||32))+'px',top:'4px'});
      block.onpointerdown=e=>{if(e.button!==0)return;if(bundle.expanded){e.stopPropagation();return;}editor.setTimelineSelection(bundle.keys);editor.beginTimelineMove(e,bundle.keys[0],block);};
      block.onclick=()=>{scroll.focus({preventScroll:true});};
      for(const edge of ['start','end']){const handle=document.createElement('span');handle.className='trim-handle trim-'+edge;handle.title=edge==='start'?'裁剪复合片段入点':'裁剪复合片段出点';handle.onpointerdown=e=>editor.beginCompoundTrim(e,bundle.id,edge,block);handle.onclick=e=>e.stopPropagation();handle.ondblclick=e=>e.stopPropagation();block.append(handle);}

      block.ondblclick=()=>editor.toggleCompound(bundle.id);block.onkeydown=e=>{if(e.isComposing||e.keyCode===229)return;if(e.key==='Enter'){e.preventDefault();editor.toggleCompound(bundle.id);}};if(bundle.expanded){block.style.width='100px';block.style.right='0';block.style.left='auto';block.textContent='收起复合片段';block.onclick=()=>editor.toggleCompound(bundle.id);}targetLane.append(block);
      if(!bundle.expanded){const keys=new Set(bundle.keys);scroll.querySelectorAll('[data-timeline-key]').forEach(n=>{if(keys.has(n.dataset.timelineKey.replace('original:','video:')))n.classList.add('compound-member-hidden');});}
    });
  }
  const schedule=()=>{if(!queued){queued=true;requestAnimationFrame(paint);}};
  window.addEventListener('hub-project',schedule);window.addEventListener('hub-bundles',schedule);
  new MutationObserver(schedule).observe(document.getElementById('edit-clips'),{childList:true});
})();

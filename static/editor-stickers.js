'use strict';
// Built-in animated arrow stickers: library panel, timeline blocks and canvas overlay.
// Sticker assets ship with the app (static/stickers); a project only stores the style
// key plus layout numbers, so nothing here can reference a user file or a remote URL.
window.hubStickers=(()=>{
  const STYLES=[
    {key:'solid',label:'实心箭头'},
    {key:'outline',label:'描边箭头'},
    {key:'curved',label:'弯箭头'},
    {key:'double',label:'双向箭头'},
    {key:'dashed',label:'虚线箭头'},
    {key:'chevron',label:'双箭头'},
    {key:'tk-curve-pink',label:'粉色弯箭头',file:'01_curve_pink'},
    {key:'tk-bounce-yellow',label:'黄色弹跳箭头',file:'02_bounce_yellow'},
    {key:'tk-chevrons-cyan',label:'青色双箭头',file:'03_chevrons_cyan'},
    {key:'tk-glitch-down',label:'故障向下箭头',file:'04_glitch_down'},
    {key:'tk-wavy-right',label:'波浪向右箭头',file:'05_wavy_right'},
    {key:'tk-neon-diag',label:'霓虹斜箭头',file:'06_neon_diag'}
  ];
  [['01_laugh','大笑'],['02_cool','酷'],['03_love','爱心'],['04_angry','生气'],['05_shock','震惊'],['06_cry','哭泣'],['07_think','思考'],['08_hot','热'],['09_wink','眨眼'],['10_happy','开心'],['11_mindblown','脑洞大开'],['12_sleep','睡觉']].forEach(([file,label])=>STYLES.push({key:'emoji-'+file.slice(3),label,file:'emoji_'+file,category:'emoji',frames:36}));
  [['01_pixel_hand_click','像素手点击'],['02_finger_point','手指指向'],['03_red_scribble_circle','红色手绘圈'],['04_circle_with_arrow','圈选箭头'],['05_big_curve_arrow','大弯箭头'],['06_loop_arrow','回环箭头'],['07_dashed_arrow','虚线指向'],['08_down_arrow_ripple','向下波纹箭头'],['09_target_ring_arrow','目标环箭头'],['10_chevrons_yellow','黄色连续箭头'],['11_burst_lines','放射强调线'],['12_highlight_box_cursor','高亮框光标'],['13_double_underline','双下划线'],['14_location_pin','位置标记'],['15_check_circle','圆圈对勾'],['16_green_notch_arrow','绿色缺口箭头']].forEach(([file,label])=>STYLES.push({key:'pointing-'+file.slice(3),label,file:'pointing_'+file,category:'arrows',frames:48}));
  [['01_kiss','飞吻'],['02_smirk','坏笑'],['03_eyeroll','翻白眼'],['04_nervous','紧张'],['05_shy','害羞'],['06_dizzy','头晕'],['07_sick','生病'],['08_freezing','冰冻'],['09_moneyeyes','财迷'],['10_starstruck','星星眼'],['11_party','派对'],['12_devil','小恶魔'],['13_angel','天使'],['14_pleading','恳求'],['15_yawn','打哈欠'],['16_speechless','无语']].forEach(([file,label])=>STYLES.push({key:'emoji-more-'+file.slice(3),label,file:'emoji_more_'+file,category:'emoji',frames:36}));
  // Categories come from asset metadata; adding a future emoji category requires
  // only a category key on its styles and a label here, not another panel.
  const CATEGORY_LABELS={arrows:'箭头',emoji:'Emoji'};
  STYLES.forEach(style=>{style.category||='arrows';});
  let activeCategory='arrows',categoriesExpanded=true;
  const DRAG='application/x-seedance-sticker',FPS=24,DEFAULT=2;
  const asset=key=>{const s=STYLES.find(s=>s.key===key);return s?.file?'imported/'+s.file:'arrow-'+key;};
  const src=key=>'/static/stickers/'+asset(key)+'.gif';
  const images=new Map();
  const image=key=>{
    let img=images.get(key);
    if(!img){img=new Image();img.decoding='async';img.src=src(key);images.set(key,img);}
    return img;
  };
  const sprites=new Map();
  function sprite(key){let img=sprites.get(key);if(!img){img=new Image();img.decoding='async';img.onload=()=>{hub()?.seek?.(hub()?.position?.()||0);};img.src='/static/stickers/'+asset(key)+'.png';sprites.set(key,img);}return img;}
  const label=key=>STYLES.find(s=>s.key===key)?.label||'贴纸';
  const hub=()=>window.hubEditor||null;
  const body=()=>hub()?.body?.()||null;
  const stickers=()=>body()?.stickers||[];
  const frame=n=>Math.round((Number(n)||0)*FPS)/FPS;
  let selected=-1,panel=null,rows=null;

  function announce(){window.hubEditor?.mark?.();window.hubEditor?.repaint?.();}

  function ensureTrack(id){
    const target=body();if(!target)return null;
    target.tracks||=[];
    const reusable=id&&target.stickers?.some(s=>s.track===id)&&!target.clips.some(c=>c.track===id)&&!target.captions.some(c=>c.track===id)&&!(target.audio_clips||[]).some(c=>c.track===id);
    const trackId=reusable?id:('sticker-'+crypto.randomUUID());
    if(!target.tracks.some(t=>t.id===trackId))target.tracks.push({id:trackId,muted:false});
    return trackId;
  }

  function add(style,at,track){
    const target=body();
    if(!target)return null;
    if(!STYLES.some(s=>s.key===style))return null;
    target.stickers||=[];
    if(target.stickers.length>=50){hub()?.fail?.('最多 50 个贴纸');return null;}
    const start=Math.max(0,frame(at||0)),duration=DEFAULT;
    const sticker={id:'sticker-'+Math.random().toString(36).slice(2,10),style,start,end:frame(start+duration),
      x:.5,y:.5,width:.25,rotation:0,track:ensureTrack(track),locked:false};
    target.stickers.push(sticker);
    selected=target.stickers.length-1;
    announce();renderPanel();paintSelection();
    window.hubEditor?.seek?.(start);
    return sticker;
  }

  function remove(index){
    const target=body();
    if(!target?.stickers?.[index])return;
    target.stickers.splice(index,1);
    selected=Math.min(selected,target.stickers.length-1);
    announce();renderPanel();paintSelection();
  }

  // ---- timeline blocks -------------------------------------------------
  function renderBlocks(target,lanes,scale,actions){
    rows=lanes;
    const list=target.stickers||[];
    list.forEach((sticker,index)=>{
      const lane=lanes.get(sticker.track);
      if(!lane)return;
      const node=document.createElement('button');
      node.type='button';
      node.className='timeline-block sticker-block'+(index===selected?' is-selected':'');
      node.dataset.stickerIndex=String(index);
      node.dataset.timelineKey='sticker:'+index;
      node.style.position='absolute';
      node.style.left=sticker.start*scale+'px';
      node.style.width=Math.max(18,(sticker.end-sticker.start)*scale)+'px';
      node.style.top='4px';node.style.bottom='4px';node.style.height='auto';
      const chip=document.createElement('span');chip.className='sticker-block-art';
      chip.style.backgroundImage='url("'+src(sticker.style)+'")';
      const text=document.createElement('span');text.className='sticker-block-text';text.textContent=label(sticker.style);
      node.append(chip,text);
      node.title=label(sticker.style)+'　'+sticker.start.toFixed(2)+'s → '+sticker.end.toFixed(2)+'s';
      node.setAttribute('aria-label',node.title);
      lane.append(node);
      const handle=document.createElement('span');handle.className='trim-handle trim-end';handle.title='拖动调整贴纸结束时间';
      handle.onpointerdown=e=>beginTrim(e,index,node,scale);
      handle.onclick=e=>e.stopPropagation();
      node.append(handle);
      node.onclick=e=>{e.stopPropagation();if(actions.suppressed?.())return;selected=index;renderPanel();if(e.detail===0)actions.select?.('sticker:'+index,node);document.querySelector('.track-scroll')?.focus({preventScroll:true});};
      node.onpointerdown=e=>{if(e.target.closest('.trim-handle'))return;e.stopPropagation();selected=index;renderPanel();actions.move(e,'sticker:'+index,node);};
    });
  }

  function beginMove(event,index,node,scale){
    if(event.target.classList.contains('trim-handle'))return;
    event.stopPropagation();event.preventDefault();
    const sticker=body()?.stickers?.[index];if(!sticker||sticker.locked)return;
    const startX=event.clientX,origin=sticker.start,span=sticker.end-sticker.start;
    node.setPointerCapture?.(event.pointerId);
    const move=e=>{
      const delta=frame((e.clientX-startX)/scale);
      const next=Math.max(0,frame(origin+delta));
      sticker.start=next;sticker.end=frame(next+span);
      node.style.left=sticker.start*scale+'px';
    };
    const up=()=>{
      node.removeEventListener('pointermove',move);node.removeEventListener('pointerup',up);
      selected=index;announce();renderPanel();
    };
    node.addEventListener('pointermove',move);node.addEventListener('pointerup',up);
  }

  function beginTrim(event,index,node,scale){
    if(event.button===0&&hub()?.beginSelectionTrim?.(event,null,'sticker:'+index,'end'))return;
    event.stopPropagation();event.preventDefault();
    const sticker=body()?.stickers?.[index];if(!sticker||sticker.locked)return;
    const startX=event.clientX,origin=sticker.end;
    node.setPointerCapture?.(event.pointerId);
    const move=e=>{
      const next=Math.max(sticker.start+1/FPS,frame(origin+(e.clientX-startX)/scale));
      sticker.end=next;node.style.width=Math.max(18,(sticker.end-sticker.start)*scale)+'px';
    };
    const up=()=>{
      node.removeEventListener('pointermove',move);node.removeEventListener('pointerup',up);
      announce();renderPanel();
    };
    node.addEventListener('pointermove',move);node.addEventListener('pointerup',up);
  }

  // ---- canvas overlay --------------------------------------------------
  let dragTarget=null;

  function draw(context,target,time,w,h){
    bindCanvas();
    const list=target?.stickers;
    if(!list?.length)return;
    for(let index=0;index<list.length;index++){
      const sticker=list[index];
      if(time<sticker.start-1e-6||time>=sticker.end-1e-6)continue;
      const img=sprite(sticker.style);
      if(!img?.complete||!img.naturalWidth)continue;
      const size=Math.max(2,sticker.width*w);
      context.save();
      context.imageSmoothingQuality='high';
      context.translate(sticker.x*w,sticker.y*h);
      if(sticker.rotation)context.rotate(sticker.rotation*Math.PI/180);
      const imported=!!STYLES.find(s=>s.key===sticker.style)?.file;
      const cols=imported?10:12,frames=STYLES.find(s=>s.key===sticker.style)?.frames||(imported?48:12),fps=imported?30:12,tile=imported?192:96;
      const phase=Math.floor(Math.max(0,time-sticker.start)*fps)%frames;
      context.drawImage(img,(phase%cols)*tile,Math.floor(phase/cols)*tile,tile,tile,-size/2,-size/2,size,size);
      context.restore();
      if(index===selected)drawOutline(context,sticker,w,h,size);
    }
  }

  function drawOutline(context,sticker,w,h,size){
    context.save();
    context.translate(sticker.x*w,sticker.y*h);
    if(sticker.rotation)context.rotate(sticker.rotation*Math.PI/180);
    context.strokeStyle='#4da3ff';context.lineWidth=1.5;context.setLineDash([5,4]);
    context.strokeRect(-size/2,-size/2,size,size);
    context.setLineDash([]);context.fillStyle='#fff';
    for(const x of [-size/2,size/2])for(const y of [-size/2,size/2]){context.beginPath();context.arc(x,y,5,0,Math.PI*2);context.fill();}
    context.beginPath();context.moveTo(0,size/2);context.lineTo(0,size/2+24);context.stroke();
    context.beginPath();context.arc(0,size/2+24,6,0,Math.PI*2);context.fill();
    context.restore();
  }

  // Drag the selected sticker directly on the preview canvas (CapCut-style).
  function canvas(){
    return document.getElementById('multitrack-canvas');
  }

  function bindCanvas(){
    const node=canvas();
    if(!node||node.dataset.stickerBound)return;
    node.dataset.stickerBound='1';
    node.style.touchAction='none';
    node.addEventListener('pointerdown',event=>{
      const target=body();if(!target)return;
      hub()?.pause?.();
      const rect=node.getBoundingClientRect();
      const px=(event.clientX-rect.left)/rect.width,py=(event.clientY-rect.top)/rect.height;
      const time=hub()?.position?.()??0;
      const list=target.stickers||[];
      for(let index=list.length-1;index>=0;index--){
        const sticker=list[index];
        if(time<sticker.start-1e-6||time>=sticker.end-1e-6)continue;
        if(sticker.locked)continue;
        const angle=(sticker.rotation||0)*Math.PI/180,dx=(px-sticker.x)*rect.width,dy=(py-sticker.y)*rect.height;
        const lx=dx*Math.cos(angle)+dy*Math.sin(angle),ly=-dx*Math.sin(angle)+dy*Math.cos(angle),half=sticker.width*rect.width/2;
        const rotate=index===selected&&Math.hypot(lx,ly-half-24*rect.width/node.width)<12;
        const resize=index===selected&&Math.abs(Math.abs(lx)-half)<12&&Math.abs(Math.abs(ly)-half)<12;
        if(rotate||resize||(Math.abs(lx)<=half&&Math.abs(ly)<=half)){
          selected=index;dragTarget={index,mode:rotate?'rotate':resize?'resize':'move',x:px-sticker.x,y:py-sticker.y};renderPanel();paintSelection();
          node.setPointerCapture?.(event.pointerId);
          event.preventDefault();return;
        }
      }
      dragTarget=null;
    });
    node.addEventListener('pointermove',event=>{
      if(dragTarget===null)return;
      const sticker=body()?.stickers?.[dragTarget.index];if(!sticker||sticker.locked)return;
      const rect=node.getBoundingClientRect(),px=(event.clientX-rect.left)/rect.width,py=(event.clientY-rect.top)/rect.height;
      const dx=(px-sticker.x)*rect.width,dy=(py-sticker.y)*rect.height;
      if(dragTarget.mode==='rotate')sticker.rotation=((Math.atan2(dy,dx)*180/Math.PI-90+540)%360)-180;
      else if(dragTarget.mode==='resize')sticker.width=Math.min(1,Math.max(.02,Math.hypot(dx,dy)*Math.SQRT2/rect.width));
      else{sticker.x=Math.min(1,Math.max(0,px-dragTarget.x));sticker.y=Math.min(1,Math.max(0,py-dragTarget.y));}
      window.hubMultitrackPreview?.sync?.(body(),hub()?.position?.()??0,false);
      if(selected===dragTarget.index)renderPanel();
    });
    const stop=()=>{
      if(dragTarget!==null){announce();renderPanel();}
      dragTarget=null;
    };
    node.addEventListener('pointerup',stop);
    node.addEventListener('pointercancel',stop);
  }

  function paintSelection(){
    const target=body();if(!target)return;
    window.hubMultitrackPreview?.sync?.(target,hub()?.position?.()??0,false);
    window.hubEditor?.redrawTimeline?.();
  }

  // ---- library panel ---------------------------------------------------
  function slider(name,value,min,max,step,onInput){
    const row=document.createElement('label');row.className='sticker-field';
    const title=document.createElement('span');title.textContent=name;
    const input=document.createElement('input');input.type='range';input.min=min;input.max=max;input.step=step;input.value=value;
    const out=document.createElement('input');out.type='number';out.min=min;out.max=max;out.step=step;out.value=value;out.setAttribute('aria-label',name+'数值');out.style.width='64px';
    out.onchange=()=>{const n=Number(out.value);if(!Number.isFinite(n)){out.value=input.value;return;}const v=Math.max(min,Math.min(max,n));out.value=v;input.value=v;onInput(v);hub()?.mark?.();};
    input.oninput=()=>{out.value=input.value;onInput(Number(input.value));};
    input.onchange=()=>hub()?.mark?.();
    row.append(title,input,out);return row;
  }

  function renderPanel(){
    if(!panel)return;
    const target=body();
    panel.replaceChildren();
    const head=document.createElement('p');head.className='sticker-hint';
    head.textContent='点击贴纸加入当前播放位置，或拖到时间轴上的贴纸轨道。';
    const layout=document.createElement('div');layout.className='sticker-library-layout';
    const nav=document.createElement('nav');nav.className='sticker-category-nav';nav.setAttribute('aria-label','贴纸分类');
    const navTitle=document.createElement('button');navTitle.type='button';navTitle.className='sticker-category-title';navTitle.textContent='贴纸库';navTitle.setAttribute('aria-expanded',String(categoriesExpanded));navTitle.setAttribute('aria-controls','sticker-category-list');
    const chevron=document.createElement('span');chevron.textContent=categoriesExpanded?'⌃':'⌄';chevron.setAttribute('aria-hidden','true');navTitle.append(chevron);
    const categoryList=document.createElement('div');categoryList.id='sticker-category-list';categoryList.hidden=!categoriesExpanded;
    navTitle.onclick=()=>{categoriesExpanded=!categoriesExpanded;categoryList.hidden=!categoriesExpanded;navTitle.setAttribute('aria-expanded',String(categoriesExpanded));chevron.textContent=categoriesExpanded?'⌃':'⌄';};nav.append(navTitle,categoryList);
    const categories=[...new Set([...Object.keys(CATEGORY_LABELS),...STYLES.map(style=>style.category)])];
    if(!categories.includes(activeCategory))activeCategory=categories[0];
    categories.forEach(key=>{const button=document.createElement('button');button.type='button';button.className='sticker-category'+(key===activeCategory?' is-active':'');button.dataset.stickerCategory=key;button.setAttribute('aria-pressed',String(key===activeCategory));button.textContent=CATEGORY_LABELS[key]||key;button.onclick=()=>{const y=categoryList.scrollTop;activeCategory=key;renderPanel();const list=panel.querySelector('#sticker-category-list');if(list)list.scrollTop=y;panel.querySelector('[data-sticker-category="'+key+'"]')?.focus({preventScroll:true});};categoryList.append(button);});
    const content=document.createElement('div');content.className='sticker-category-content';
    const heading=document.createElement('h3');heading.className='sticker-category-heading';heading.textContent=CATEGORY_LABELS[activeCategory]||activeCategory;
    const count=document.createElement('span');count.textContent=STYLES.filter(s=>s.category===activeCategory).length+' 款';heading.append(count);
    const grid=document.createElement('div');grid.className='sticker-grid';
    STYLES.filter(style=>style.category===activeCategory).forEach(style=>{
      const card=document.createElement('button');card.type='button';card.className='sticker-card';
      card.draggable=true;card.dataset.stickerStyle=style.key;
      const art=document.createElement('img');window.hubMediaLazy.watchImage(art,src(style.key));art.alt=style.label;art.loading='lazy';
      const text=document.createElement('span');text.textContent=style.label;
      card.append(art,text);
      card.title='点击加入「'+style.label+'」，也可拖到时间轴';
      card.onclick=()=>add(style.key,hub()?.position?.()??0,null);
      card.ondragstart=event=>{
        event.dataTransfer.setData(DRAG,style.key);
        event.dataTransfer.effectAllowed='copy';
      };
      grid.append(card);
    });
    content.append(heading);
    if(grid.childElementCount){content.append(head,grid);}else{
      const empty=document.createElement('div');empty.className='sticker-category-empty';empty.setAttribute('role','status');
      const title=document.createElement('strong');title.textContent='暂无 Emoji 贴纸';
      const note=document.createElement('p');note.textContent='分类已准备好，添加 Emoji 素材包后将在这里显示。';empty.append(title,note);content.append(empty);
    }
    layout.append(nav,content);panel.append(layout);
    const sticker=target?.stickers?.[selected];
    if(!sticker)return;
    const box=document.createElement('div');box.className='sticker-inspector';
    const name=document.createElement('h4');name.textContent=label(sticker.style)+' 设置';
    const times=document.createElement('p');times.className='sticker-hint';
    times.textContent='出场 '+sticker.start.toFixed(2)+'s ～ '+sticker.end.toFixed(2)+'s';
    box.append(name,times);
    for(const edge of ['start','end']){
      const row=document.createElement('label');row.className='sticker-field';
      const title=document.createElement('span');title.textContent=edge==='start'?'入点':'出点';
      const input=document.createElement('input');input.type='number';input.min=0;input.max=86400;input.step=1/FPS;input.value=sticker[edge].toFixed(3);
      input.onchange=()=>{const v=frame(Number(input.value));if(!Number.isFinite(v)||v<0||v>86400||(edge==='start'?v>=sticker.end:v<=sticker.start)){renderPanel();return;}sticker[edge]=v;announce();renderPanel();paintSelection();};
      row.append(title,input);box.append(row);
    }
    box.append(
      slider('水平',Math.round(sticker.x*100),0,100,1,v=>{sticker.x=v/100;paintSelection();}),
      slider('垂直',Math.round(sticker.y*100),0,100,1,v=>{sticker.y=v/100;paintSelection();}),
      slider('缩放%',Math.round(sticker.width*100),2,100,1,v=>{sticker.width=v/100;paintSelection();}),
      slider('旋转',Math.round(sticker.rotation),-180,180,1,v=>{sticker.rotation=v;paintSelection();})
    );
    const actions=document.createElement('div');actions.className='sticker-actions';
    const del=document.createElement('button');del.type='button';del.className='sticker-delete';del.textContent='删除贴纸';
    del.onclick=()=>remove(selected);
    const commit=document.createElement('button');commit.type='button';commit.className='sticker-done';commit.textContent='完成';
    commit.onclick=()=>{announce();renderPanel();};
    const reset=document.createElement('button');reset.type='button';reset.textContent='重置变换';reset.onclick=()=>{Object.assign(sticker,{x:.5,y:.5,width:.25,rotation:0});announce();renderPanel();paintSelection();};
    actions.append(reset,del,commit);box.append(actions);
    panel.append(box);
  }

  function mount(container){
    panel=container;
    const title=document.createElement('h3');title.className='sticker-title';title.textContent='贴纸';
    container.prepend(title);
    renderPanel();
    bindCanvas();
  }

  return {styles:STYLES,src,mount,add,remove,renderBlocks,draw,renderPanel,
    selected:()=>selected,
    select:index=>{selected=index;renderPanel();paintSelection();}};
})();

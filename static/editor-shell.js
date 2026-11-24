'use strict';
/** Recompose existing editor nodes into one full-screen workspace. */
document.addEventListener('DOMContentLoaded',()=>{
  const editor=document.getElementById('editor');
  if(!editor||editor.dataset.unified==='true')return;
  editor.dataset.unified='true';
  const heading=editor.querySelector(':scope > .page-heading');
  const project=editor.querySelector(':scope > .edit-project-bar');
  const error=document.getElementById('edit-error');
  const workspace=editor.querySelector(':scope > .edit-workspace');
  const timeline=editor.querySelector(':scope > .edit-timeline');
  const bottom=editor.querySelector(':scope > .edit-bottom');
  const exportsSection=editor.querySelector(':scope > .edit-exports');
  const library=workspace?.querySelector('.edit-library');
  const properties=workspace?.querySelector('.edit-properties');
  if(!heading||!project||!workspace||!timeline||!bottom||!library||!properties)return;

  const command=document.createElement('header');
  command.className='editor-commandbar';
  editor.insertBefore(command,heading);
  command.append(heading,project);
  if(error)command.after(error);

  // Give the video a measured viewport independent of its absolutely positioned player.
  const preview=workspace.querySelector('.edit-preview');
  const stage=document.getElementById('edit-stage');
  if(preview&&stage){
    const viewport=document.createElement('div');
    viewport.className='editor-preview-viewport';
    stage.before(viewport);
    viewport.append(stage);
    // The transport and the ratio picker stay pinned at the bottom of the preview
    // column, so the frame may only use the space above them.
    // Dock is created later in this setup; resolve it when measurements run.
    let dock;
    const fitStage=()=>{
      dock=preview.querySelector('.edit-preview-dock');
      const width=viewport.clientWidth,height=viewport.clientHeight;
      if(!width||!height)return;
      const dockHeight=dock?dock.getBoundingClientRect().height:0;
      const dockTop=dock&&dockHeight?dock.getBoundingClientRect().top:preview.getBoundingClientRect().bottom;
      const room=Math.min(height,dockTop-viewport.getBoundingClientRect().top);
      if(room<40)return;
      // Preview window stays vertical regardless of the project's export ratio.
      const ratio=9/16;
      const fittedWidth=Math.min(width,room*ratio);
      // Legacy stylesheets pin width/height on the stage with !important, so inline rules must match.
      stage.style.setProperty('width',fittedWidth+'px','important');
      stage.style.setProperty('height',(fittedWidth/ratio)+'px','important');
    };
    new ResizeObserver(fitStage).observe(viewport);
    if(dock)new ResizeObserver(fitStage).observe(dock);
    // Keep the frame readable while the panel is measured, then mirror the empty-state copy.
    viewport.style.opacity='0';
    new MutationObserver(fitStage).observe(stage,{attributes:true,attributeFilter:['class']});
    fitStage();
    requestAnimationFrame(()=>{fitStage();viewport.style.opacity='';});
    new ResizeObserver(()=>fitStage()).observe(preview);
    // The material column grows first and the preview keeps the leftover width, like a desktop editor.
    let manualColumns=null;
    const applyColumns=()=>{
      const total=workspace.clientWidth;
      if(!total||total<720)return;
      // Reserve usable space for all three panels, independently of portrait height.
      const minSide= Math.min(260, total*.26), minPreview=Math.min(360,total*.36);
      let left=Math.min(400,Math.max(minSide,total*.25));
      let right=Math.min(360,Math.max(minSide,total*.24));
      if(manualColumns){
        left=Math.max(minSide,manualColumns[0]*total);
        right=Math.max(minSide,manualColumns[1]*total);
      }
      const excess=left+right-(total-minPreview);
      if(excess>0){
        const spare=left+right-2*minSide;
        const share=spare>0?(left-minSide)/spare:.5;
        left-=excess*share; right-=excess*(1-share);
      }
      const columns=`${Math.round(left)}px minmax(0,1fr) ${Math.round(right)}px`;
      if(workspace.style.getPropertyValue('grid-template-columns')!==columns)
        workspace.style.setProperty('grid-template-columns',columns,'important');
    };
    applyColumns();
    new ResizeObserver(applyColumns).observe(workspace);
    new ResizeObserver(applyColumns).observe(viewport);
    const key='hub-editor-columns-v1';
    try{const v=JSON.parse(localStorage.getItem(key));if(Array.isArray(v)&&v.length===2&&v.every(x=>Number.isFinite(x)&&x>0&&x<1))manualColumns=v;}catch{}
    const createSeparator=(side)=>{
      const handle=document.createElement('div');
      handle.className='editor-column-resizer editor-column-resizer--'+side;
      handle.setAttribute('role','separator');handle.setAttribute('aria-orientation','vertical');
      handle.setAttribute('aria-label',side==='left'?'调整素材区与预览区宽度':'调整预览区与编辑区宽度');
      handle.tabIndex=0;handle.title='拖动调整宽度，双击恢复默认';
      (side==='left'?library:properties).append(handle);
      const move=(x)=>{
        const box=workspace.getBoundingClientRect(),total=box.width;
        const l=library.getBoundingClientRect().width,r=properties.getBoundingClientRect().width;
        manualColumns=side==='left'?[Math.max(200,Math.min(total-r-200,x-box.left))/total,r/total]:[l/total,Math.max(200,Math.min(total-l-200,box.right-x))/total];
        applyColumns();
      };
      let dragging=false;
      handle.addEventListener('pointerdown',e=>{if(e.button!==0)return;e.preventDefault();dragging=true;handle.setPointerCapture(e.pointerId);handle.classList.add('dragging');});
      handle.addEventListener('pointermove',e=>{if(dragging)move(e.clientX);});
      const end=()=>{if(!dragging)return;dragging=false;handle.classList.remove('dragging');try{localStorage.setItem(key,JSON.stringify(manualColumns));}catch{}};
      handle.addEventListener('pointerup',end);handle.addEventListener('pointercancel',end);handle.addEventListener('lostpointercapture',end);
      handle.addEventListener('dblclick',()=>{manualColumns=null;try{localStorage.removeItem(key);}catch{}applyColumns();});
      handle.addEventListener('keydown',e=>{if(e.key==='Home'){e.preventDefault();manualColumns=null;try{localStorage.removeItem(key);}catch{}applyColumns();return;}if(!['ArrowLeft','ArrowRight'].includes(e.key))return;e.preventDefault();const rect=handle.getBoundingClientRect();move(rect.left+rect.width/2+(e.key==='ArrowRight'?1:-1)*(e.shiftKey?50:10));try{localStorage.setItem(key,JSON.stringify(manualColumns));}catch{}});
    };
    createSeparator('left');createSeparator('right');applyColumns();
  }

  const makeTabs=(host,items,label,group)=>{
    const tabs=document.createElement('div');
    tabs.className='editor-panel-tabs';
    tabs.setAttribute('role','tablist');
    tabs.setAttribute('aria-label',label);
    const show=(key,focus=false)=>{
      items.forEach(item=>{
        const active=item.key===key;
        item.panel.hidden=!active;
        item.panel.setAttribute('aria-hidden',String(!active));
        item.button.classList.toggle('active',active);
        item.button.setAttribute('aria-selected',String(active));
        item.button.tabIndex=active?0:-1;
      });
      const item=items.find(candidate=>candidate.key===key);
      item?.activate?.();
      if(focus)item?.button.focus();
    };
    items.forEach((item,index)=>{
      const button=document.createElement('button');
      button.type='button';
      button.textContent=item.label;
      button.id=`editor-${group}-tab-${item.key}`;
      button.setAttribute('role','tab');
      button.setAttribute('aria-controls',item.panel.id);
      item.panel.setAttribute('role','tabpanel');
      item.panel.setAttribute('aria-labelledby',button.id);
      item.button=button;
      button.onclick=()=>show(item.key);
      button.onkeydown=e=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
        e.preventDefault();
        const next=e.key==='Home'?0:e.key==='End'?items.length-1:(index+(e.key==='ArrowRight'?1:-1)+items.length)%items.length;
        show(items[next].key,true);
      };
      tabs.append(button);
    });
    host.prepend(tabs);
    return show;
  };

  // Dock the transport and the ratio picker below the frame so the frame keeps its full height.
  const dockFor=stage?.closest('.edit-preview');
  if(dockFor){
    const seek=document.getElementById('edit-seek');
    const transport=dockFor.querySelector('.edit-transport');
    const ratioLabel=dockFor.querySelector('.edit-ratio-label');
    const dock=document.createElement('div');
    dock.className='edit-preview-dock';
    if(seek){
      const slider=seek.closest('.elastic-slider');
      dock.append(slider||seek);
    }
    if(transport)dock.append(transport);
    if(ratioLabel&&transport)transport.append(ratioLabel);
    dockFor.append(dock);
    const previewHeading=document.createElement('div');
    previewHeading.className='editor-preview-heading';
    previewHeading.textContent='预览';
    dockFor.prepend(previewHeading);
    // Preserve the range node for existing playback code; timeline owns seeking.
    if(seek){seek.hidden=true;seek.tabIndex=-1;}
    if(transport){
      const clock=document.getElementById('edit-clock');
      if(clock)transport.prepend(clock);
      const play=document.getElementById('edit-play');
      if(play){
        const syncPlayIcon=()=>{
          const paused=play.textContent.trim()!=='暂停';
          play.dataset.playing=String(!paused);
          play.setAttribute('aria-label',paused?'播放':'暂停');
          play.title=paused?'播放（空格）':'暂停（空格）';
        };
        syncPlayIcon();
        new MutationObserver(syncPlayIcon).observe(play,{childList:true,characterData:true,subtree:true});
      }

      for(const [id,label] of [['edit-prev-frame','上一帧'],['edit-next-frame','下一帧']]){
        const button=document.getElementById(id);
        if(button){button.setAttribute('aria-label',label);button.title=label;}
      }
    }
    const empty=document.getElementById('edit-empty');
    const note=dockFor.querySelector('.edit-empty-note');
    if(empty&&note){
      // The empty hint used to live inside the frame; a narrow 9:16 frame cannot hold it.
      note.textContent=empty.textContent;
      new MutationObserver(()=>{note.textContent=empty.textContent;}).observe(empty,{childList:true,characterData:true,subtree:true});
    }
  }

  const materialPanel=document.createElement('div');
  materialPanel.id='editor-tool-materials';
  materialPanel.className='editor-tool-panel';
  [...library.children].filter(node=>!node.classList.contains('editor-column-resizer')).forEach(node=>materialPanel.append(node));
  library.append(materialPanel);

  const bottomSections=[...bottom.querySelectorAll(':scope > section')].filter(node=>node.id!=='edit-text-section');
  const captionSection=bottomSections[0];
  const audioSection=bottomSections[1];
  const voice=document.getElementById('voice-panel');
  const captionPanel=document.createElement('div');
  captionPanel.id='editor-tool-captions';
  captionPanel.className='editor-tool-panel';
  if(captionSection)[...captionSection.children].filter(node=>node!==voice).forEach(node=>captionPanel.append(node));
  const voicePanel=document.createElement('div');
  voicePanel.id='editor-tool-voice';
  voicePanel.className='editor-tool-panel';
  if(voice)voicePanel.append(voice);
  const audioPanel=document.createElement('div');
  audioPanel.id='editor-tool-audio';
  audioPanel.className='editor-tool-panel';
  if(audioSection)[...audioSection.children].forEach(node=>audioPanel.append(node));
  const detachedSection=bottomSections[2];
  if(detachedSection){
    const detached=document.createElement('div');
    detached.className='editor-detached-audio';
    [...detachedSection.children].forEach(node=>detached.append(node));
    audioPanel.append(detached);
  }
  const textSection=document.getElementById('edit-text-section');
  const textPanel=document.createElement('div');
  textPanel.id='editor-tool-text';
  textPanel.className='editor-tool-panel';
  if(textSection)[...textSection.children].forEach(node=>textPanel.append(node));
  const stickerPanel=document.createElement('div');
  stickerPanel.id='editor-tool-stickers';
  stickerPanel.className='editor-tool-panel';
  library.append(audioPanel,stickerPanel);
  properties.append(voicePanel,captionPanel,textPanel);
  const showLeft=makeTabs(library,[
    {key:'materials',label:'素材',panel:materialPanel},
    {key:'audio',label:'音频',panel:audioPanel},
    {key:'sticker',label:'贴纸',panel:stickerPanel}
  ],'素材、声音与贴纸工具','left');
  showLeft('materials');
  window.hubStickers?.mount?.(stickerPanel);
  window.hubEditorShell={openLeft:key=>showLeft(key)};

  const propertyTabs=document.getElementById('editor-property-tabs');
  const base=document.getElementById('editor-base-panel');
  const repair=document.getElementById('editor-repair-panel');
  const versions=document.getElementById('editor-versions-panel');
  if(propertyTabs&&base&&repair&&versions){
    propertyTabs.hidden=true;
    repair.querySelector('h3')?.replaceChildren('画面替换');
    const exportPanel=document.createElement('div');
    exportPanel.id='editor-exports-panel';
    exportPanel.className='editor-side-panel';
    if(exportsSection)exportPanel.append(exportsSection);
    properties.append(exportPanel);
    const speedPanel=document.getElementById('editor-speed-panel');
    const adjustPanel=document.getElementById('editor-adjust-panel');
    versions.hidden=true;
    // 动画分类先提供明确的功能入口，未接入预览和导出前不展示可误操作的效果按钮。
    const animationPanel=document.createElement('div');
    animationPanel.id='editor-tool-animation';
    animationPanel.className='editor-tool-panel animation-panel';
    properties.append(animationPanel);
    const animationItems=[
      {key:'media',label:'素材动画',description:'为视频、图片等素材设置动画，包括入场、出场和组合动画。'},
      {key:'text',label:'文字与字幕动画',description:'为文字或字幕设置出现、消失及持续期间的动画。'},
      {key:'keyframes',label:'自定义关键帧动画',description:'通过关键帧自定义位置、缩放、旋转和透明度等属性的变化。'}
    ].map(item=>{
      const panel=document.createElement('div');
      panel.id='editor-animation-'+item.key;
      panel.className='animation-category';
      const heading=document.createElement('h3');heading.textContent=item.label;
      const description=document.createElement('p');description.className='fine';description.textContent=item.description;
      panel.append(heading,description);
      if(item.key==='text'){
        // 字幕效果（模板）与字幕动画都由编辑器填充：预览与导出共用同一套字段与 ASS 标签。
        const host=document.createElement('div');host.id='editor-subtitle-effects';host.className='subtitle-effects';
        const animHost=document.createElement('div');animHost.id='editor-subtitle-animations';animHost.className='subtitle-animations';
        panel.append(host,animHost);
      }else{
        const status=document.createElement('p');status.className='animation-status';status.textContent='动画效果、预览和导出尚未接入。';
        panel.append(status);
      }
      animationPanel.append(panel);
      return {...item,panel};
    });
    const showAnimation=makeTabs(animationPanel,animationItems,'动画分类','animation');
    showAnimation('media');
    const rightItems=[
      {key:'voice',label:'配音',panel:voicePanel},
      {key:'captions',label:'字幕',panel:captionPanel},
      {key:'text',label:'文本',panel:textPanel,activate:()=>{
        const api=window.hubEditor;
        if(api&&api.captionIndex?.()==null&&api.captionCount?.()>0)api.selectCaption?.(0,true);
      }},
      ...(adjustPanel?[{key:'adjust',label:'调整',panel:adjustPanel,activate:()=>window.dispatchEvent(new Event('hub-adjust-refresh'))}]:[]),
      {key:'animation',label:'动画',panel:animationPanel},
      ...(speedPanel?[{key:'speed',label:'变速',panel:speedPanel}]:[]),
      {key:'exports',label:'导出',panel:exportPanel,activate:()=>window.hubEditor?.refreshExports?.()}
    ];
    const showRight=makeTabs(properties,rightItems,'剪辑属性','right');
    base.hidden=repair.hidden=true;
    base.classList.add('editor-retired-panel');repair.classList.add('editor-retired-panel');
    showRight('voice');
    window.hubEditorShell.openLeft=key=>['voice','captions','text'].includes(key)?showRight(key):showLeft(key);
    window.hubEditorShell.openRight=showRight;
  }

  bottom.hidden=true;
  const timelineHeading=timeline.querySelector('.edit-section-heading h2');
  if(timelineHeading)timelineHeading.textContent='时间轴';
  window.dispatchEvent(new CustomEvent('hub-editor-shell-ready'));
});

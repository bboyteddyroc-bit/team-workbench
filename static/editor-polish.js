'use strict';
// Reuse original commands; the top-layer popover cannot be clipped by editor panels.
document.addEventListener('DOMContentLoaded',()=>{
  const toolbar=document.querySelector('#editor .clip-toolbar');
  if(!toolbar||toolbar.querySelector('.editor-more'))return;
  const labels=new Set(['向前移动','向后移动','仅保留人声','仅保留背景声','统一音量','组合','取消组合','创建复合片段','解除复合片段']);
  const buttons=[...toolbar.children].filter(n=>n.tagName==='BUTTON'&&labels.has(n.textContent.trim()));
  if(!buttons.length)return;
  const host=document.createElement('div');host.className='editor-more';
  const trigger=document.createElement('button');trigger.type='button';trigger.textContent='更多操作 ···';trigger.setAttribute('aria-expanded','false');
  const panel=document.createElement('div');panel.className='editor-more-panel';panel.id='editor-more-commands';panel.hidden=true;
  trigger.setAttribute('aria-controls',panel.id);
  const topLayer=typeof panel.showPopover==='function';if(topLayer)panel.setAttribute('popover','manual');
  host.append(trigger,panel);toolbar.insertBefore(host,toolbar.querySelector('.fine'));buttons.forEach(b=>panel.append(b));
  let opened=false;
  const position=()=>{
    const r=trigger.getBoundingClientRect(),above=r.top>innerHeight/2;
    panel.style.left=Math.max(8,Math.min(r.left,innerWidth-192))+'px';
    panel.style.top=above?'auto':(r.bottom+6)+'px';
    panel.style.bottom=above?(innerHeight-r.top+6)+'px':'auto';
    panel.style.maxHeight=Math.max(40,(above?r.top:innerHeight-r.bottom)-14)+'px';
  };
  const close=(focus=false)=>{if(!opened)return;opened=false;if(topLayer)panel.hidePopover();panel.hidden=true;trigger.setAttribute('aria-expanded','false');if(focus)trigger.focus({preventScroll:true});};
  trigger.addEventListener('click',()=>{if(opened){close();return;}position();panel.hidden=false;if(topLayer)panel.showPopover();opened=true;trigger.setAttribute('aria-expanded','true');});
  // Keep focus stable between pointerdown and click; focusout must not hide
  // the popover before the original button receives its activation.
  panel.addEventListener('pointerdown',e=>{if(e.button===0&&e.target.closest('button:not(:disabled)'))e.preventDefault();});
  panel.addEventListener('click',e=>{if(e.target.closest('button:not(:disabled)'))close(true);});
  host.addEventListener('keydown',e=>{
    if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}
    if(opened&&['ArrowDown','ArrowUp'].includes(e.key)){e.preventDefault();const enabled=buttons.filter(b=>!b.disabled);if(!enabled.length)return;const i=enabled.indexOf(document.activeElement);enabled[(i+(e.key==='ArrowDown'?1:enabled.length-1)+enabled.length)%enabled.length].focus({preventScroll:true});}
  });
  document.addEventListener('pointerdown',e=>{if(!host.contains(e.target))close();});
  host.addEventListener('focusout',()=>{queueMicrotask(()=>{if(opened&&!host.contains(document.activeElement))close();});});
  window.addEventListener('resize',()=>{if(opened)position();});
  document.addEventListener('scroll',e=>{if(opened&&!panel.contains(e.target))position();},true);
});

/* Native adaptation of beUI motion/tabs: preserve existing activation handlers. */
'use strict';
document.addEventListener('DOMContentLoaded',()=>{
  const selector='.tabs,.segmented,.workflow-tabs,.mode-switch[aria-label="生成工作流"],.editor-panel-tabs',mounted=new WeakSet(),reduced=matchMedia('(prefers-reduced-motion: reduce)');
  function mount(host){
    if(mounted.has(host))return;mounted.add(host);host.classList.add('beui-tabs');
    const indicator=document.createElement('span');indicator.className='beui-tab-indicator';indicator.setAttribute('aria-hidden','true');host.append(indicator);
    const buttons=()=>[...host.children].filter(n=>n.tagName==='BUTTON'&&!n.hidden&&!n.disabled);
    let frame=0,initialized=false;
    function update(){frame=0;if(!host.isConnected||!host.getClientRects().length)return;const all=buttons(),active=all.find(b=>b.classList.contains('active')||b.getAttribute('aria-selected')==='true'||b.getAttribute('aria-pressed')==='true');
      indicator.hidden=!active;if(!active)return;
      const a=active.getBoundingClientRect(),h=host.getBoundingClientRect(),values={x:a.left-h.left+host.scrollLeft-host.clientLeft,y:a.top-h.top+host.scrollTop-host.clientTop,width:a.width,height:a.height};
      if(window.gsap){if(initialized&&!reduced.matches)gsap.to(indicator,{...values,duration:.32,ease:'power3.out',overwrite:true});else gsap.set(indicator,values);}else Object.assign(indicator.style,{left:values.x+'px',top:values.y+'px',width:values.width+'px',height:values.height+'px'});initialized=true;
    }
    function schedule(){if(!frame)frame=requestAnimationFrame(update);}
    new MutationObserver(schedule).observe(host,{subtree:true,childList:true,attributes:true,attributeFilter:['class','aria-selected','aria-pressed','disabled']});new ResizeObserver(schedule).observe(host);
    host.addEventListener('click',schedule);host.addEventListener('keydown',e=>{if(e.defaultPrevented||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;const all=buttons(),i=all.indexOf(e.target);if(i<0)return;e.preventDefault();const next=all[e.key==='Home'?0:e.key==='End'?all.length-1:(i+(e.key==='ArrowRight'?1:-1)+all.length)%all.length];next.focus({preventScroll:true});next.click();const b=next.getBoundingClientRect(),h=host.getBoundingClientRect();if(b.left<h.left)host.scrollBy({left:b.left-h.left});else if(b.right>h.right)host.scrollBy({left:b.right-h.right});});
    reduced.addEventListener('change',()=>{window.gsap?.killTweensOf(indicator);initialized=false;schedule();});schedule();
  }
  function scan(){document.querySelectorAll(selector).forEach(mount);}scan();new MutationObserver(records=>{if(records.some(r=>r.addedNodes.length))scan();}).observe(document.body,{childList:true,subtree:true});
});

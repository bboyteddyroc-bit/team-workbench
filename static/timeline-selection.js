'use strict';
// Empty track space selects clips; the ruler and playhead continue to seek.
(()=>{
  const scroller=document.querySelector('.track-scroll');if(!scroller)return;
  scroller.addEventListener('pointerdown',event=>{
    if(event.button!==0||event.target.closest('[data-timeline-key],button,input,#timeline-ruler,.timeline-playhead')||!window.hubEditor?.current())return;
    const rect=scroller.getBoundingClientRect();if(event.clientX<rect.left+104)return;
    event.preventDefault();scroller.focus({preventScroll:true});window.hubEditor.pause();
    const previous=window.hubEditor.timelineSelection(),base=event.ctrlKey||event.metaKey||event.shiftKey?previous:[];
    const start={x:event.clientX-rect.left+scroller.scrollLeft,y:event.clientY-rect.top+scroller.scrollTop};
    const box=document.createElement('div');box.className='timeline-marquee';box.setAttribute('aria-hidden','true');scroller.append(box);
    let x=event.clientX,y=event.clientY,frame=0,moved=false,dirty=true,previousTime=0,lastSignature=null;
    // Capture content coordinates once; scrolling does not change them.
    const candidates=[...scroller.querySelectorAll('[data-timeline-key],[data-timeline-keys]')].filter(n=>!n.classList.contains('compound-member-hidden')).map(n=>{
      const b=n.getBoundingClientRect();return {left:b.left-rect.left+scroller.scrollLeft,top:b.top-rect.top+scroller.scrollTop,width:b.width,height:b.height,keys:n.dataset.timelineKeys?JSON.parse(n.dataset.timelineKeys):[n.dataset.timelineKey]};
    });
    const draw=()=>{
      const r=scroller.getBoundingClientRect(),end={x:x-r.left+scroller.scrollLeft,y:y-r.top+scroller.scrollTop};
      const left=Math.min(start.x,end.x),top=Math.min(start.y,end.y),right=Math.max(start.x,end.x),bottom=Math.max(start.y,end.y);
      moved=moved||right-left>4||bottom-top>4;
      Object.assign(box.style,{left:left+'px',top:top+'px',width:(right-left)+'px',height:(bottom-top)+'px'});
      const keys=new Set(base);
      if(moved)for(const n of candidates){if(n.left<right&&n.left+n.width>left&&n.top<bottom&&n.top+n.height>top)n.keys.forEach(k=>keys.add(k));}
      const signature=[...keys].sort().join('|');
      if(signature!==lastSignature){lastSignature=signature;window.hubEditor.setTimelineSelection([...keys]);}
    };
    const tick=now=>{
      const elapsed=previousTime?Math.min(40,now-previousTime):16.67;previousTime=now;
      const r=scroller.getBoundingClientRect(),left=scroller.scrollLeft,top=scroller.scrollTop;
      if(moved){
        const velocity=(p,min,max)=>p<min?-Math.min(720,(min-p)*18):p>max?Math.min(720,(p-max)*18):0;
        scroller.scrollLeft+=velocity(x,r.left+136,r.right-32)*elapsed/1000;
        scroller.scrollTop+=velocity(y,r.top+24,r.bottom-24)*elapsed/1000;
      }
      if(dirty||left!==scroller.scrollLeft||top!==scroller.scrollTop){dirty=false;draw();}
      frame=requestAnimationFrame(tick);
    };
    const move=e=>{x=e.clientX;y=e.clientY;dirty=true;};
    const clean=()=>{cancelAnimationFrame(frame);box.remove();window.removeEventListener('pointermove',move);window.removeEventListener('pointerup',finish);window.removeEventListener('pointercancel',cancel);window.removeEventListener('blur',cancel);window.removeEventListener('keydown',escape);};
    const finish=()=>{if(dirty)draw();clean();if(!moved){const r=document.getElementById('timeline-ruler').getBoundingClientRect();window.hubEditor.seek((x-r.left-104)/(window.hubTimelineScale||32));}};const cancel=()=>{clean();window.hubEditor.setTimelineSelection(previous);};
    const escape=e=>{if(e.key==='Escape'){e.preventDefault();cancel();}};
    window.addEventListener('pointermove',move);window.addEventListener('pointerup',finish);window.addEventListener('pointercancel',cancel);window.addEventListener('blur',cancel);window.addEventListener('keydown',escape);draw();frame=requestAnimationFrame(tick);
  });
})();

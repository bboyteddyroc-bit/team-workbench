/* Original motion layer: presentation only; no media, timeline or network writes. */
'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const groups = [];
  document.querySelectorAll('.sidebar nav,.editor-panel-tabs').forEach(host => {
    const indicator = document.createElement('span');
    indicator.className = 'hub-selection-indicator';
    indicator.setAttribute('aria-hidden', 'true');
    host.classList.add('hub-motion-navigation');
    host.append(indicator);
    let initialized = false;
    const update = () => {
      const active = host.querySelector('button.active,button[aria-selected="true"]');
      if (!active || !host.getClientRects().length) return;
      const a = active.getBoundingClientRect(), h = host.getBoundingClientRect();
      const values = {x:a.left-h.left+host.scrollLeft, y:a.top-h.top+host.scrollTop, width:a.width, height:a.height};
      if (window.gsap) {
        if (initialized && !reduced.matches) gsap.to(indicator, {...values,duration:.32,ease:'power3.out',overwrite:true});
        else gsap.set(indicator, values);
      } else Object.assign(indicator.style,{left:values.x+'px',top:values.y+'px',width:values.width+'px',height:values.height+'px'});
      initialized = true;
    };
    new MutationObserver(update).observe(host,{subtree:true,attributes:true,attributeFilter:['class','aria-selected']});
    new ResizeObserver(update).observe(host);
    groups.push({indicator,update});
    update();
  });
  // Reveal tool contents, never animate the edit stage or timeline clips.
  document.querySelectorAll('[role="tabpanel"]').forEach(panel => {
    new MutationObserver(() => {
      if (panel.hidden || reduced.matches || !window.gsap) return;
      gsap.fromTo(panel,{opacity:.65},{opacity:1,duration:.18,overwrite:true,clearProps:'opacity'});
    }).observe(panel,{attributes:true,attributeFilter:['hidden']});
  });
  reduced.addEventListener('change', () => {
    groups.forEach(({indicator,update}) => {window.gsap?.killTweensOf(indicator);update();});
    if(reduced.matches) document.querySelectorAll('[role="tabpanel"]').forEach(panel=>{window.gsap?.killTweensOf(panel);panel.style.removeProperty('opacity');});
  });
});

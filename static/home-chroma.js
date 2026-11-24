/* Chroma spotlight adapted from the supplied ChromaGrid to the existing gallery. */
'use strict';
document.addEventListener('DOMContentLoaded', () => {
  const host = document.getElementById('home-stage');
  if (!host) return;
  const reduce = matchMedia('(prefers-reduced-motion: reduce)');
  let current = null, raf = 0, previous = 0;
  const point = { x: 0, y: 0, tx: 0, ty: 0 };
  function stop() {
    if (current) current.classList.remove('chroma-active');
    current = null;
    cancelAnimationFrame(raf); raf = 0; previous = 0;
  }
  function draw(now) {
    raf = 0;
    if (!current) return;
    const dt = previous ? Math.min((now - previous) / 1000, .05) : 1 / 60;
    previous = now;
    const follow = 1 - Math.exp(-dt / .12);
    point.x += (point.tx - point.x) * follow;
    point.y += (point.ty - point.y) * follow;
    current.style.setProperty('--spot-x', point.x + 'px');
    current.style.setProperty('--spot-y', point.y + 'px');
    if (Math.abs(point.tx - point.x) + Math.abs(point.ty - point.y) > .15) raf = requestAnimationFrame(draw);
    else previous = 0;
  }
  host.addEventListener('pointermove', e => {
    if (e.pointerType === 'touch' || e.buttons || reduce.matches) { stop(); return; }
    const art = e.target.closest('.gallery-art');
    if (!art) { stop(); return; }
    const box = art.getBoundingClientRect();
    point.tx = (e.clientX - box.left) * art.offsetWidth / box.width;
    point.ty = (e.clientY - box.top) * art.offsetHeight / box.height;
    if (current !== art) {
      stop(); current = art; point.x = point.tx; point.y = point.ty;
      art.classList.add('chroma-active');
    }
    if (!raf) raf = requestAnimationFrame(draw);
  });
  host.addEventListener('pointerleave', stop);
  host.addEventListener('pointerdown', stop);
  host.addEventListener('pointercancel', stop);
  document.addEventListener('visibilitychange', stop);
  const page = document.getElementById('home');
  if (page) new MutationObserver(stop).observe(page, { attributes: true, attributeFilter: ['hidden'] });
  reduce.addEventListener('change', stop);
});

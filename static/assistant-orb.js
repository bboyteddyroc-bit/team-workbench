'use strict';
// GlassSurface 的透明玻璃降级层：真实页面背景用 backdrop-filter 取样。
window.hubAssistantOrb = launch => {
  launch.classList.add('glass-surface', 'glass-surface--fallback');
  launch.title = '点击打开 AI 助理，拖动调整位置';
  const mark = document.createElement('span');
  mark.className = 'assistant-orb-mark';
  mark.setAttribute('aria-hidden', 'true');
  mark.textContent = '✦';
  const sheen = document.createElement('span');
  sheen.className = 'glass-surface__sheen';
  sheen.setAttribute('aria-hidden', 'true');
  const rim = document.createElement('span');
  rim.className = 'glass-surface__rim';
  rim.setAttribute('aria-hidden', 'true');
  launch.replaceChildren(sheen, rim, mark);
  let drag = null, suppressClick = false, position = null;
  const clamp = (v, max) => Math.max(0, Math.min(Math.max(0, max), v));
  function apply(x, y) {
    const r = launch.getBoundingClientRect();
    position = {x: clamp(x, innerWidth - r.width), y: clamp(y, innerHeight - r.height)};
    launch.style.left = position.x + 'px';
    launch.style.top = position.y + 'px';
    launch.style.right = 'auto';
    launch.style.bottom = 'auto';
  }
  launch.addEventListener('pointerdown', e => {
    if (!e.isPrimary || e.button !== 0) return;
    const r = launch.getBoundingClientRect();
    drag = {id:e.pointerId, x:e.clientX, y:e.clientY, left:r.left, top:r.top, moved:false};
    suppressClick = false;
    launch.setPointerCapture(e.pointerId);
  });
  launch.addEventListener('pointermove', e => {
    if (!drag || e.pointerId !== drag.id) return;
    const dx=e.clientX-drag.x, dy=e.clientY-drag.y;
    if (!drag.moved && Math.hypot(dx,dy) < 5) return;
    drag.moved = true;
    launch.classList.add('is-dragging');
    apply(drag.left+dx, drag.top+dy);
  });
  const finish = e => {
    if (!drag || e.pointerId !== drag.id) return;
    suppressClick = drag.moved;
    drag = null;
    launch.classList.remove('is-dragging');
  };
  launch.addEventListener('pointerup', finish);
  launch.addEventListener('pointercancel', finish);
  launch.addEventListener('lostpointercapture', finish);
  launch.addEventListener('click', e => {
    if (!suppressClick || e.detail === 0) return;
    e.preventDefault(); e.stopImmediatePropagation();
    suppressClick = false;
  }, true);
  window.addEventListener('resize', () => { if (position) apply(position.x, position.y); });
};

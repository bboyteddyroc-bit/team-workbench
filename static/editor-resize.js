'use strict';
/* Draggable timeline height: keeps the whole editor usable while letting the
   user trade preview space for more tracks. Height is remembered per browser. */
(() => {
  const KEY = 'hub-timeline-height';
  const MIN = 220;
  const editor = document.getElementById('editor');
  const timeline = editor?.querySelector('.edit-timeline');
  if (!editor || !timeline) return;

  const handle = document.createElement('div');
  handle.className = 'timeline-resizer';
  handle.id = 'timeline-resizer';
  handle.tabIndex = 0;
  handle.setAttribute('role', 'separator');
  handle.setAttribute('aria-orientation', 'horizontal');
  handle.setAttribute('aria-label', '调整时间轴高度');
  handle.title = '上下拖动调整时间轴高度，双击恢复默认，聚焦后按 ↑ ↓（Shift 加速，PageUp/PageDown 大步，Home 复位）';
  timeline.prepend(handle);

  // The editor grid is as tall as its content, so the ceiling must come from the
  // window instead: keep the preview block visible while letting the user pull the
  // timeline up to most of the viewport.
  const viewport = () => window.innerHeight || document.documentElement.clientHeight || 800;
  const maxHeight = () => Math.max(MIN + 40, Math.round(viewport() * 0.72));
  const clamp = value => Math.max(MIN, Math.min(maxHeight(), Math.round(value)));
  const current = () => Math.round(timeline.getBoundingClientRect().height);
  // The grid row can be slightly taller than the panel box (margins), so dragging and
  // stepping work from the value we asked for instead of the measured height.
  const target = () => Math.round(Number.parseFloat(editor.style.getPropertyValue('--timeline-h'))) || current();
  const stored = () => {
    try {
      const value = Number(localStorage.getItem(KEY));
      return Number.isFinite(value) && value > 0 ? value : 0;
    } catch { return 0; }
  };

  function apply(height) {
    const next = clamp(height);
    editor.style.setProperty('--timeline-h', next + 'px');
    handle.setAttribute('aria-valuenow', String(next));
    handle.setAttribute('aria-valuemin', String(MIN));
    handle.setAttribute('aria-valuemax', String(maxHeight()));
    return next;
  }
  function reset() {
    try { localStorage.removeItem(KEY); } catch {}
    editor.style.removeProperty('--timeline-h');
    handle.removeAttribute('aria-valuenow');
  }
  function remember(height) {
    try { localStorage.setItem(KEY, String(height)); } catch {}
  }
  const saved = stored();
  if (saved) apply(saved);

  let drag = null;
  const stop = () => {
    if (!drag) return;
    const height = drag.last ?? target();
    try { if (handle.hasPointerCapture?.(drag.id)) handle.releasePointerCapture(drag.id); } catch {}
    drag = null;
    handle.classList.remove('dragging');
    document.body.style.cursor = '';
    document.body.style.userSelect = '';
    remember(height);
  };

  handle.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.pointerType === 'mouse' && event.buttons !== 1) return;
    event.preventDefault();
    drag = { id: event.pointerId, y: event.clientY, height: target() };
    handle.classList.add('dragging');
    try { handle.setPointerCapture?.(event.pointerId); } catch {}
    document.body.style.cursor = 'row-resize';
    document.body.style.userSelect = 'none';
    handle.focus({ preventScroll: true });
  });
  handle.addEventListener('pointermove', event => {
    if (!drag) return;
    event.preventDefault();
    drag.last = apply(drag.height + drag.y - event.clientY);
  });
  handle.addEventListener('pointerup', stop);
  handle.addEventListener('pointercancel', stop);
  handle.addEventListener('lostpointercapture', stop);

  handle.addEventListener('dblclick', () => reset());

  // ArrowUp/ArrowDown/Home are swallowed by a capture-phase shortcut listener
  // elsewhere in the app, so keyboard resizing is registered on the window in the
  // capture phase too (same-node listeners are not affected by stopPropagation)
  // and Shift+arrows / PageUp / PageDown are offered as the reliable variants.
  const onKey = event => {
    if (event.target !== handle && document.activeElement !== handle) return;
    if (event.key === 'Home' || event.key === 'Escape') {
      event.preventDefault();
      reset();
      return;
    }
    const up = event.key === 'ArrowUp' || event.key === 'PageUp';
    const down = event.key === 'ArrowDown' || event.key === 'PageDown';
    if (!up && !down) return;
    event.preventDefault();
    event.stopPropagation();
    const step = event.shiftKey || event.key === 'PageUp' || event.key === 'PageDown' ? 60 : 14;
    remember(apply(target() + (up ? step : -step)));
  };
  window.addEventListener('keydown', onKey, true);

  window.addEventListener('resize', () => {
    const height = stored();
    if (height) apply(height);
  });

  window.hubTimelineResize = {
    reset,
    set: value => { remember(apply(value)); },
    get: current
  };
})();

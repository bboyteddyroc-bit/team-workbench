/* NB-TK login: local Fluid Glass stage (WebGL2) plus the reveal controller.
   Everything is served from /static: no network, no dependency, no post-login overlay. */
(() => {
  'use strict';
  const auth = document.getElementById('auth');
  const canvas = document.getElementById('auth-glass');
  if (!auth || !canvas) return;
  const form = auth.querySelector('.auth-form');
  if (!form) return;

  const motion = matchMedia('(prefers-reduced-motion: reduce)');
  const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
  const font = '"HubVintage", "Brush Script MT", "Segoe Script", cursive';

  // Raymarch budget. Below 1.75 the shader traces a 2x2 grid per pixel, so the
  // device pixel count has to pay for four traces. Small viewports can therefore
  // afford a sharp device ratio, large ones settle at 1:1 with the 4-tap rim.
  const TRACE_BUDGET = 6.5e6;
  const pixelRatio = (width, height) => {
    const area = width * height;
    const device = window.devicePixelRatio || 1;
    const sharp = Math.min(device, 2.5);
    if (area * sharp * sharp * 4 <= TRACE_BUDGET) return sharp;
    return clamp(Math.sqrt(TRACE_BUDGET / (4 * area)), 0.75, sharp);
  };

  // Pixel budget keeps the raymarch affordable and the single trace path sharp.
  const settings = {
    text: 'NB-TK',
    textColor: '#e9ede3',
    fontFamily: font,
    fontWeight: 400,
    src: '/static/media/auth-glass-bg.jpg',
    fit: 'cover',
    background: '#090e10',
    shape: 'blob',
    size: 520,
    refraction: 1,
    dispersion: 0.35,
    reflection: 1,
    frost: 0,
    color: '#ffffff',
    tint: 0,
    shadow: 0.5,
    elevation: 0.4,
    // The glass trails the bare cursor: no press, no hold.
    interaction: 'follow',
    smoothness: 0.35,
    wobble: 0.5,
    spin: 0.3,
    idle: true,
    morphOnClick: false,
    position: [0.5, 0.5],
    intro: true,
    maxDevicePixelRatio: 1,
    onClick: () => reveal(true)
  };

  let glass = null;
  let opened = false;
  const box = () => auth.getBoundingClientRect();

  function fit() {
    const rect = box();
    if (!rect.width || !rect.height) return false;
    settings.size = clamp(Math.min(rect.width, rect.height) * 0.54, 250, 560);
    settings.maxDevicePixelRatio = pixelRatio(rect.width, rect.height);
    return true;
  }

  function mount() {
    if (!window.mountFluidGlass) return;
    if (glass) return;
    if (!fit()) return;
    glass = window.mountFluidGlass(auth, canvas, null, settings);
  }

  // The card fades in over 450ms; retry until the caret actually lands, because a
  // still-transitioning card can swallow the first focus() call.
  function focusInput() {
    const input = form.querySelector('input');
    if (!input) return;
    let tries = 0;
    const tick = () => {
      if (!opened || auth.hidden) return;
      input.focus({ preventScroll: true });
      if (document.activeElement === input) return;
      tries += 1;
      if (tries < 12) setTimeout(tick, 80);
    };
    setTimeout(tick, 320);
  }

  function reveal(shouldFocus = true) {
    if (opened || auth.hidden) return;
    opened = true;
    auth.dataset.loginOpen = 'true';
    form.inert = false;
    form.removeAttribute('aria-hidden');
    if (shouldFocus) focusInput();
  }

  function arm() {
    opened = false;
    auth.dataset.loginOpen = 'false';
    form.inert = true;
    form.setAttribute('aria-hidden', 'true');
    auth.classList.add('glass-ready');
    mount();
    if (glass) {
      fit();
      glass.wake();
    }
  }

  auth.addEventListener('click', event => {
    if (event.target === auth) reveal();
  });

  document.addEventListener('keydown', event => {
    if (auth.hidden || opened || event.ctrlKey || event.metaKey || event.altKey) return;
    if (event.key === 'Enter' || event.key === ' ' || event.key === 'Tab') {
      event.preventDefault();
      reveal();
    }
  });

  new MutationObserver(records => {
    if (!records.some(record => record.attributeName === 'hidden')) return;
    if (auth.hidden) return;
    arm();
  }).observe(auth, { attributes: true, attributeFilter: ['hidden'] });

  const error = document.getElementById('auth-error');
  if (error) {
    new MutationObserver(() => {
      const invalid = Boolean(error.textContent.trim());
      form.querySelectorAll('input').forEach(input => {
        input.setAttribute('aria-invalid', String(invalid));
        input.setAttribute('aria-describedby', 'auth-error');
      });
      if (invalid) reveal(false);
    }).observe(error, { childList: true, subtree: true, characterData: true });
  }

  window.addEventListener('resize', () => {
    if (!glass || auth.hidden) return;
    fit();
    // Re-fit the wordmark against the new canvas instead of keeping a stale texture.
    glass.hooks.refreshText();
    glass.wake();
  });

  // Preload once so the first frame after reveal already refracts the plate.
  const plate = new Image();
  plate.decoding = 'async';
  plate.src = settings.src;

  window.hubAuthGlass = {
    reveal,
    arm,
    instance: () => glass,
    state: () => {
      const rect = box();
      const stats = glass ? glass.stats() : { frames: 0, x: 0, y: 0, grabbed: false, awake: false };
      return {
        opened,
        dragging: Boolean(stats.grabbed),
        x: rect.width ? stats.x / rect.width : 0.5,
        y: rect.height ? stats.y / rect.height : 0.5,
        px: stats.x,
        py: stats.y,
        frames: stats.frames,
        animating: Boolean(stats.awake),
        webgl: Boolean(glass),
        reduced: motion.matches,
        font: document.fonts.check('100px HubVintage')
      };
    }
  };

  new MutationObserver(records => {
    if (!records.some(record => record.attributeName === 'hidden')) return;
    if (!auth.hidden) return;
    form.inert = false;
    opened = false;
  }).observe(auth, { attributes: true, attributeFilter: ['hidden'] });

  if (!auth.hidden) arm();
  else {
    form.inert = true;
    auth.dataset.loginOpen = 'false';
  }

  const rearm = () => {
    if (auth.hidden || !glass) return;
    fit();
    glass.hooks.refreshText();
    glass.wake();
  };
  document.fonts.load('100px HubVintage').then(rearm).catch(() => document.fonts.ready.then(rearm));
  document.fonts.ready.then(rearm);
  motion.addEventListener('change', rearm);
})();

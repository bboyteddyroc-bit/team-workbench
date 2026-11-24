/* Elastic Slider（中台统一滑块组件）—— 原生 input[type=range] 的渐进增强。
   做法：把每个 range 包进 .elastic-slider，原生 input 透明地留在最上层负责取值/拖拽/键盘，
   下面这层轨道 + 填充 + 手柄只负责画面：悬停与拖动时轨道加粗，拖到两端有弹性拉伸，松手回弹，
   并且不再绘制任何聚焦描边。页面里动态插入的滑块会被自动接管。 */
(() => {
  if (window.HubElasticSlider) return;
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const rubber = (distance, limit) => (limit > 0 ? 2 * (1 / (1 + Math.exp(-distance / limit)) - 0.5) * limit : 0);
  const reduced = () => !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const instances = new WeakMap();
  let count = 0;

  const ratioOf = input => {
    const min = Number(input.min || 0);
    const max = Number(input.max || 100);
    if (!Number.isFinite(min) || !Number.isFinite(max) || max <= min) return 0;
    return clamp((Number(input.value) - min) / (max - min), 0, 1);
  };

  const paint = st => {
    const length = Math.max(1, st.length || 1);
    const p = ratioOf(st.input);
    const thick = st.thickness + (st.activeThickness - st.thickness) * st.a;
    st.track.style.height = `${thick.toFixed(2)}px`;
    const along = 1 + st.s / length;
    const across = 1 - 0.22 * clamp(st.s / 50, -1, 1);
    st.track.style.transformOrigin = st.side > 0 ? '0% 50%' : '100% 50%';
    st.track.style.transform = `scale(${along.toFixed(4)}, ${across.toFixed(4)})`;
    const x = st.pad + (st.side > 0 ? p * length * along : length - (1 - p) * length * along);
    st.thumb.style.transform = `translate3d(${x.toFixed(2)}px, 0, 0) scale(${(1 + 0.12 * st.a).toFixed(3)})`;
    st.range.style.clipPath = `inset(0 ${((1 - p) * 100).toFixed(3)}% 0 0 round 999px)`;
  };

  const step = (st, now) => {
    let frame = Math.min(0.05, (now - st.last) / 1000) || 0.016;
    st.last = now;
    // 定步长积分（每步 1/120 秒），帧率再低也不会把弹簧算崩。
    const spring = (x, v, target, k, damp, dt) => {
      const nv = v + ((target - x) * k - v * damp) * dt;
      return [x + nv * dt, nv];
    };
    while (frame > 0) {
      const dt = Math.min(1 / 120, frame);
      frame -= dt;
      [st.a, st.va] = spring(st.a, st.va, st.targetA, 220, 26, dt);
      [st.s, st.vs] = spring(st.s, st.vs, st.targetS, 260, 16, dt);
    }
    st.a = clamp(st.a, 0, 1.15);
    const settled = Math.abs(st.a - st.targetA) < 0.002 && Math.abs(st.va) < 0.02
      && Math.abs(st.s - st.targetS) < 0.06 && Math.abs(st.vs) < 0.6;
    if (settled) {
      st.a = st.targetA;
      st.va = 0;
      st.s = st.targetS;
      st.vs = 0;
      st.raf = 0;
      paint(st);
      return;
    }
    paint(st);
    st.raf = requestAnimationFrame(t => step(st, t));
  };

  const kick = st => {
    if (reduced()) {
      st.a = st.targetA;
      st.s = st.targetS;
      st.va = 0;
      st.vs = 0;
      paint(st);
      return;
    }
    if (st.raf) return;
    st.last = performance.now();
    st.raf = requestAnimationFrame(t => step(st, t));
  };

  const sync = st => {
    st.length = st.track.clientWidth || st.length;
    st.wrap.toggleAttribute('data-disabled', !!st.input.disabled);
    paint(st);
  };

  // 隐藏状态（display:none 的视图/弹层）里 getComputedStyle 量不出真实宽度，
  // 于是回到样式表里找这条 input 最终生效的 width 声明，照抄到外壳上。
  const declaredWidth = input => {
    if (input.style.width) return input.style.width;
    let best = null;
    let bestScore = -1;
    for (const sheet of Array.from(document.styleSheets)) {
      let rules = null;
      try {
        rules = sheet.cssRules;
      } catch (error) {
        continue;
      }
      if (!rules) continue;
      const walk = list => {
        for (const rule of Array.from(list)) {
          if (rule.cssRules && rule.cssRules.length) walk(rule.cssRules);
          if (!rule.selectorText || !rule.style) continue;
          const width = rule.style.width;
          if (!width) continue;
          let matched = false;
          try {
            matched = input.matches(rule.selectorText);
          } catch (error) {
            matched = false;
          }
          if (!matched) continue;
          const selector = rule.selectorText;
          const score = (selector.match(/#/g) || []).length * 10
            + (selector.match(/\[/g) || []).length * 4
            + (selector.match(/\./g) || []).length * 2
            + (selector.match(/[ >+~]/g) || []).length;
          if (score >= bestScore) {
            bestScore = score;
            best = width;
          }
        }
      };
      walk(rules);
    }
    return best;
  };

  const create = input => {
    if (!input || input.tagName !== 'INPUT' || input.type !== 'range') return null;
    const known = instances.get(input);
    if (known) return known;
    if (!input.parentNode) return null;
    // getComputedStyle 返回的是活对象，接完图层就变了，先把布局相关的值抄下来。
    const live = getComputedStyle(input);
    const cs = {
      flexGrow: live.flexGrow,
      flexShrink: live.flexShrink,
      flexBasis: live.flexBasis,
      margin: live.margin,
      alignSelf: live.alignSelf
    };
    const measuredWidth = input.getBoundingClientRect().width;

    const wrap = document.createElement('span');
    wrap.className = 'elastic-slider';
    wrap.setAttribute('data-orientation', 'horizontal');
    const hit = document.createElement('span');
    hit.className = 'elastic-slider__hit';
    const track = document.createElement('span');
    track.className = 'elastic-slider__track';
    const range = document.createElement('span');
    range.className = 'elastic-slider__range';
    const thumb = document.createElement('span');
    thumb.className = 'elastic-slider__thumb';
    track.appendChild(range);
    hit.appendChild(track);
    hit.appendChild(thumb);

    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(hit);
    wrap.appendChild(input);
    // 站内其它样式表可能用 !important 给聚焦态画描边，行内 !important 一定压得住。
    input.style.setProperty('outline', 'none', 'important');
    input.style.setProperty('box-shadow', 'none', 'important');
    input.classList.add('elastic-slider__input');
    input.dataset.elasticSlider = '1';

    // 布局沿用原来那条 input 的占位：声明的宽度 → flex 伸缩 → 量到的实际宽度 → 铺满。
    const width = declaredWidth(input);
    const usesFlex = parseFloat(cs.flexGrow) > 0 || (cs.flexBasis && cs.flexBasis !== 'auto');
    if (usesFlex) {
      wrap.style.flex = `${cs.flexGrow} ${cs.flexShrink} ${cs.flexBasis}`;
      if (width) wrap.style.width = width;
    } else {
      wrap.style.width = width || (measuredWidth > 1 ? `${Math.round(measuredWidth)}px` : '100%');
    }
    if (cs.margin && cs.margin !== '0px') wrap.style.margin = cs.margin;
    if (cs.alignSelf && cs.alignSelf !== 'auto') wrap.style.alignSelf = cs.alignSelf;

    const style = getComputedStyle(wrap);
    const st = {
      input,
      wrap,
      hit,
      track,
      range,
      thumb,
      thickness: parseFloat(style.getPropertyValue('--elastic-slider-thickness')) || 6,
      activeThickness: parseFloat(style.getPropertyValue('--elastic-slider-active-thickness')) || 12,
      pad: (parseFloat(style.getPropertyValue('--elastic-slider-thumb-size')) || 14) / 2,
      length: 0,
      a: 0,
      va: 0,
      targetA: 0,
      s: 0,
      vs: 0,
      targetS: 0,
      side: 1,
      raf: 0,
      last: 0,
      drag: null
    };
    instances.set(input, st);
    count += 1;

    input.addEventListener('input', () => sync(st));
    input.addEventListener('change', () => sync(st));
    wrap.addEventListener('pointerenter', () => {
      st.targetA = 1;
      kick(st);
    });
    wrap.addEventListener('pointerleave', () => {
      if (st.drag) return;
      st.targetA = 0;
      kick(st);
    });
    input.addEventListener('pointerdown', event => {
      st.drag = { id: event.pointerId, rect: input.getBoundingClientRect() };
      st.targetA = 1;
      try {
        input.setPointerCapture(event.pointerId);
      } catch (error) {}
      kick(st);
    });
    const release = () => {
      if (!st.drag) return;
      st.drag = null;
      st.targetS = 0;
      st.targetA = wrap.matches(':hover') ? 1 : 0;
      kick(st);
    };
    input.addEventListener('pointerup', release);
    input.addEventListener('pointercancel', release);
    window.addEventListener('pointermove', event => {
      if (!st.drag || st.drag.id !== event.pointerId) return;
      const rect = st.drag.rect;
      const width = Math.max(1, rect.width - st.pad * 2);
      const fraction = (event.clientX - rect.left - st.pad) / width;
      const over = fraction < 0 ? -fraction * width : fraction > 1 ? (fraction - 1) * width : 0;
      if (over > 1.5) {
        st.side = fraction < 0 ? -1 : 1;
        st.targetS = rubber(over, 50);
      } else {
        st.targetS = 0;
      }
      kick(st);
    }, { passive: true });

    if (typeof ResizeObserver !== 'undefined') {
      const observer = new ResizeObserver(() => {
        st.length = track.clientWidth;
        paint(st);
      });
      observer.observe(hit);
    }
    new MutationObserver(() => sync(st)).observe(input, {
      attributes: true,
      attributeFilter: ['min', 'max', 'step', 'disabled']
    });
    st.length = track.clientWidth;
    sync(st);
    return st;
  };

  // 代码里直接写 input.value 时不会触发 input 事件，这里补一次绘制（只对已接入的滑块生效）。
  const descriptor = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  if (descriptor && descriptor.set) {
    Object.defineProperty(HTMLInputElement.prototype, 'value', {
      configurable: true,
      enumerable: descriptor.enumerable,
      get: descriptor.get,
      set(value) {
        descriptor.set.call(this, value);
        const st = instances.get(this);
        if (st) sync(st);
      }
    });
  }

  const enhance = root => {
    if (!root || !root.querySelectorAll) return;
    root.querySelectorAll('input[type="range"]').forEach(create);
  };

  enhance(document);
  // 观察回调里新节点的计算样式还没刷新（拿不到 flex/宽度），推到下一帧再接管。
  const pending = new Set();
  let queued = false;
  const flush = () => {
    queued = false;
    const nodes = Array.from(pending);
    pending.clear();
    nodes.forEach(node => {
      if (node.isConnected === false) return;
      if (node.matches && node.matches('input[type="range"]')) create(node);
      else enhance(node);
    });
  };
  const queue = node => {
    pending.add(node);
    if (queued) return;
    queued = true;
    requestAnimationFrame(flush);
  };
  new MutationObserver(records => {
    records.forEach(record => {
      record.addedNodes.forEach(node => {
        if (node.nodeType === 1) queue(node);
      });
    });
  }).observe(document.documentElement, { childList: true, subtree: true });

  window.HubElasticSlider = {
    enhance,
    syncAll() {
      document.querySelectorAll('input[type="range"]').forEach(input => {
        const st = instances.get(input);
        if (st) sync(st);
      });
    },
    get size() {
      return count;
    }
  };
})();
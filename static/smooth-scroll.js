/* ============================================================
   Seedance 平滑滚动（smooth-scroll）
   Lenis 风格，原生 JS 实现，无依赖

   原理：
   - 拦截 wheel 事件，阻止原生瞬时滚动
   - 用 requestAnimationFrame 逐帧逼近目标位置（指数缓动）
   - 对所有可滚动容器生效（页面 + 侧栏 + 面板 + 列表）

   特点：
   - 键盘方向键 / 触摸 / 拖动滚动条不受影响（只接管 wheel）
   - 尊重 prefers-reduced-motion，用户要求减弱动效时自动禁用
   - 页面隐藏时暂停 rAF，不消耗 CPU
   ============================================================ */
(function () {
  'use strict';

  /* ---------- 配置 ---------- */
  var LERP = 0.16;          // 缓动系数，越小越"绵"，0.12~0.22 之间手感较好
  var WHEEL_RATIO = 1.0;    // 滚轮位移倍率

  var reduce = window.matchMedia &&
               window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (reduce) return;       // 减弱动效：完全不做

  /* ---------- 找到可滚动的祖先 ---------- */
  function scrollParent(node) {
    var el = node;
    while (el && el !== document.body && el !== document.documentElement) {
      var cs = getComputedStyle(el);
      var oy = cs.overflowY;
      if ((oy === 'auto' || oy === 'scroll') && el.scrollHeight > el.clientHeight + 2) {
        return el;
      }
      el = el.parentElement;
    }
    return null;            // null 表示滚整个页面
  }

  /* ---------- 每个容器一份状态 ---------- */
  var states = new WeakMap();  // target -> { current, target, raf }
  var pageState = { current: window.scrollY || 0, target: window.scrollY || 0, raf: 0 };

  function stateFor(el) {
    if (!el) return pageState;
    var st = states.get(el);
    if (!st) {
      st = { current: el.scrollTop, target: el.scrollTop, raf: 0 };
      states.set(el, st);
    }
    return st;
  }

  function maxScroll(el) {
    if (!el) return Math.max(0, document.documentElement.scrollHeight - window.innerHeight);
    return Math.max(0, el.scrollHeight - el.clientHeight);
  }

  /* ---------- 逐帧逼近 ---------- */
  function step(el, st) {
    var dist = st.target - st.current;

    if (Math.abs(dist) < 0.5) {
      st.current = st.target;
      apply(el, st.current);
      st.raf = 0;
      return;
    }

    st.current += dist * LERP;
    apply(el, st.current);
    st.raf = requestAnimationFrame(function () { step(el, st); });
  }

  function apply(el, value) {
    var v = Math.round(value * 100) / 100;
    if (el) el.scrollTop = v;
    else window.scrollTo(0, v);
  }

  function kick(el, st) {
    if (st.raf) return;                       // 已在跑，只需更新 target
    st.current = el ? el.scrollTop : (window.scrollY || 0);
    st.raf = requestAnimationFrame(function () { step(el, st); });
  }

  /* ---------- 接管 wheel ---------- */
  document.addEventListener('wheel', function (e) {
    // 组合键缩放（Ctrl+wheel）不接管
    if (e.ctrlKey) return;
    if (e.defaultPrevented) return;

    var el = scrollParent(e.target);
    var st = stateFor(el);
    var limit = maxScroll(el);

    // 该容器不可滚 → 交回浏览器
    if (limit <= 0) return;

    var delta = e.deltaY;
    if (e.deltaMode === 1) delta *= 16;       // 行模式
    else if (e.deltaMode === 2) delta *= window.innerHeight;  // 页模式

    var base = (st.raf ? st.target : (el ? el.scrollTop : (window.scrollY || 0)));
    var next = Math.max(0, Math.min(limit, base + delta * WHEEL_RATIO));

    // 已经在边界且继续往外滚 → 让浏览器处理（可能滚到外层）
    if (next === base) return;

    e.preventDefault();
    st.target = next;
    kick(el, st);
  }, { passive: false });

  /* ---------- 用户手动拖动滚动条 / 键盘时，同步 target ---------- */
  function syncTarget(e) {
    var el = e.target && e.target.nodeType === 1 ? e.target : null;
    if (el && el.scrollTop !== undefined && el !== document.body) {
      var st = states.get(el);
      if (st) { st.current = el.scrollTop; st.target = el.scrollTop; }
    }
  }
  document.addEventListener('scroll', function (e) {
    // 只在不是平滑滚动驱动的情况下同步（避免抖动）
    var el = e.target;
    if (el === document || el === document.documentElement || el === window) {
      if (!pageState.raf) { pageState.current = window.scrollY; pageState.target = window.scrollY; }
    } else if (el && el.nodeType === 1) {
      var st = states.get(el);
      if (st && !st.raf) { st.current = el.scrollTop; st.target = el.scrollTop; }
    }
  }, true);

  /* ---------- 页面隐藏时暂停 ---------- */
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      if (pageState.raf) { cancelAnimationFrame(pageState.raf); pageState.raf = 0; }
    }
  });

  /* ---------- 锚点平滑跳转（可选） ---------- */
  window.hubSmoothScroll = {
    to: function (y) {
      pageState.target = Math.max(0, Math.min(maxScroll(null), y));
      kick(null, pageState);
    },
    config: function (opts) {
      if (opts && typeof opts.lerp === 'number') LERP = opts.lerp;
    }
  };
})();

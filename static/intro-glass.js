/* 启动动画：登录后的一段液态玻璃（Fluid Glass）过渡。
   纯 Canvas 2D 绘制，不引入外部库，不改动登录逻辑；结束时自动移除自己。 */
(function () {
  'use strict';

  var overlay = document.getElementById('hub-intro');
  if (!overlay) return;
  var canvas = document.getElementById('hub-intro-canvas');
  var ctx = canvas && canvas.getContext ? canvas.getContext('2d') : null;
  if (!ctx) { overlay.hidden = true; return; }

  var scene = document.createElement('canvas');
  var sctx = scene.getContext('2d');
  var refr = document.createElement('canvas');
  var rctx = refr.getContext('2d');
  var motion = window.matchMedia ? window.matchMedia('(prefers-reduced-motion: reduce)') : null;
  var LABEL = (overlay.dataset.label || 'NB-TK').trim() || 'NB-TK';
  var FONT = 'system-ui, -apple-system, "Segoe UI", "Microsoft YaHei", sans-serif';
  var SEEN_KEY = 'hub-intro-seen';

  // 时间轴（毫秒）：文字浮现 → 玻璃横扫 → 收拢高光 → 淡出
  var T = { sweepIn: 380, sweepOut: 1780, settle: 1780, fade: 2080, end: 2480 };

  var W = 0, H = 0, dpr = 1;
  var raf = 0, t0 = 0, running = false, finished = false, pausedAt = 0;
  var grain = null;

  function clamp(v, a, b) { return v < a ? a : v > b ? b : v; }
  function easeInOut(p) { return p < 0.5 ? 2 * p * p : 1 - Math.pow(-2 * p + 2, 2) / 2; }
  function reduced() { return !!(motion && motion.matches); }

  function roundRect(c, x, y, w, h, r) {
    r = Math.min(r, w / 2, h / 2);
    c.beginPath();
    c.moveTo(x + r, y);
    c.arcTo(x + w, y, x + w, y + h, r);
    c.arcTo(x + w, y + h, x, y + h, r);
    c.arcTo(x, y + h, x, y, r);
    c.arcTo(x, y, x + w, y, r);
    c.closePath();
  }

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = Math.max(320, window.innerWidth || 320);
    H = Math.max(240, window.innerHeight || 240);
    [canvas, scene, refr].forEach(function (c) {
      c.width = Math.round(W * dpr);
      c.height = Math.round(H * dpr);
    });
    if (canvas.style) { canvas.style.width = W + 'px'; canvas.style.height = H + 'px'; }
  }

  function makeGrain() {
    var size = 96, tile = document.createElement('canvas');
    tile.width = tile.height = size;
    var g = tile.getContext('2d'), img = g.createImageData(size, size);
    for (var i = 0; i < img.data.length; i += 4) {
      var v = 128 + Math.round((Math.random() - 0.5) * 120);
      img.data[i] = img.data[i + 1] = img.data[i + 2] = v;
      img.data[i + 3] = 255;
    }
    g.putImageData(img, 0, 0);
    return ctx.createPattern(tile, 'repeat');
  }

  function paintBackground(c, t) {
    var base = c.createLinearGradient(0, 0, 0, H);
    base.addColorStop(0, '#071614');
    base.addColorStop(0.55, '#04100e');
    base.addColorStop(1, '#020a09');
    c.fillStyle = base;
    c.fillRect(0, 0, W, H);

    var blobs = [
      { x: 0.28 + Math.sin(t * 0.00021) * 0.06, y: 0.30 + Math.cos(t * 0.00017) * 0.05, r: 0.60, c: 'rgba(26,170,156,0.50)' },
      { x: 0.74 + Math.cos(t * 0.00024) * 0.07, y: 0.64 + Math.sin(t * 0.00019) * 0.06, r: 0.52, c: 'rgba(20,116,166,0.40)' },
      { x: 0.52 + Math.sin(t * 0.00013) * 0.04, y: 0.50, r: 0.34, c: 'rgba(214,255,250,0.10)' }
    ];
    blobs.forEach(function (b) {
      var rr = Math.max(W, H) * b.r;
      var g = c.createRadialGradient(b.x * W, b.y * H, 0, b.x * W, b.y * H, rr);
      g.addColorStop(0, b.c);
      g.addColorStop(1, 'rgba(0,0,0,0)');
      c.fillStyle = g;
      c.fillRect(0, 0, W, H);
    });

    var vg = c.createRadialGradient(W / 2, H / 2, Math.min(W, H) * 0.18, W / 2, H / 2, Math.max(W, H) * 0.78);
    vg.addColorStop(0, 'rgba(0,0,0,0)');
    vg.addColorStop(1, 'rgba(0,0,0,0.58)');
    c.fillStyle = vg;
    c.fillRect(0, 0, W, H);
  }

  function labelMetrics() {
    var size = Math.min(W * 0.17, H * 0.36, 250);
    return { size: size, x: W / 2, y: H / 2 };
  }

  function paintLabel(c, alpha, blur, scale, glow) {
    var m = labelMetrics();
    c.save();
    c.translate(m.x, m.y);
    c.scale(scale, scale);
    c.textAlign = 'center';
    c.textBaseline = 'middle';
    try { c.letterSpacing = '-0.035em'; } catch (e) { /* 老版本浏览器忽略 */ }
    c.font = '800 ' + m.size + 'px ' + FONT;
    c.globalAlpha = alpha;
    if (blur > 0.2) { try { c.filter = 'blur(' + blur.toFixed(2) + 'px)'; } catch (e) {} }
    var g = c.createLinearGradient(0, -m.size * 0.62, 0, m.size * 0.62);
    g.addColorStop(0, '#ffffff');
    g.addColorStop(0.55, '#e9faf6');
    g.addColorStop(1, '#b6d4ce');
    if (glow > 0) { c.shadowColor = 'rgba(120,255,240,0.30)'; c.shadowBlur = m.size * 0.34 * glow; }
    c.fillStyle = g;
    c.fillText(LABEL, 0, 0);
    c.restore();
    var w = 0;
    try { w = c.measureText ? (function () { var mc = c; mc.save(); mc.font = '800 ' + m.size + 'px ' + FONT; try { mc.letterSpacing = '-0.035em'; } catch (e) {} var v = mc.measureText(LABEL).width; mc.restore(); return v; })() : 0; } catch (e) { w = 0; }
    m.width = w || m.size * 2.6;
    return m;
  }

  // 超椭圆 + 轻微起伏：保持玻璃片的分量感，同时带一点液态流动
  function blobPath(c, cx, cy, rx, ry, t, amp) {
    var n = 64, k = 2 / 4.2;
    c.beginPath();
    for (var i = 0; i <= n; i++) {
      var a = i / n * Math.PI * 2;
      var ca = Math.cos(a), sa = Math.sin(a);
      var wob = 1 + 0.055 * amp * Math.sin(3 * a + t * 0.0032) + 0.03 * amp * Math.sin(5 * a - t * 0.0045);
      var x = cx + Math.sign(ca) * Math.pow(Math.abs(ca), k) * rx * wob;
      var y = cy + Math.sign(sa) * Math.pow(Math.abs(sa), k) * ry * wob;
      if (i === 0) c.moveTo(x, y); else c.lineTo(x, y);
    }
    c.closePath();
  }

  // 液态玻璃：在玻璃片内按竖条重采样背景，产生折射、拉伸与边缘色散。
  function paintLens(c, t, m) {
    var p = clamp((t - T.sweepIn) / (T.sweepOut - T.sweepIn), 0, 1);
    var ease = easeInOut(p);
    var w = Math.min(W * 0.46, Math.max((m.width || W * 0.4) * 0.64, W * 0.24));
    var h = Math.min(H * 0.34, m.size * 1.18);
    var cx = -w * 0.62 + (W / 2 + w * 0.62) * ease;
    var cy = H / 2;
    var settle = clamp((t - T.settle) / 320, 0, 1);
    if (settle > 0) { w *= 1 + 0.03 * settle; h *= 1 + 0.02 * settle; }
    var x0 = cx - w / 2, y0 = cy - h / 2;
    var amp = Math.sin(clamp(p, 0.0001, 0.9999) * Math.PI) * 0.9 + settle * 0.35;

    c.save();
    // 外侧冷光
    c.shadowColor = 'rgba(96,236,222,0.22)';
    c.shadowBlur = Math.min(90, h * 0.34);
    c.fillStyle = 'rgba(255,255,255,0.015)';
    blobPath(c, cx, cy, w / 2, h / 2, t, amp);
    c.fill();
    c.restore();

    c.save();
    blobPath(c, cx, cy, w / 2, h / 2, t, amp);
    c.clip();

    // 折射：桶形放大 + 波面抖动，越靠近玻璃中心折射越明显
    var step = 3, hw = w / 2;
    for (var x = x0; x < x0 + w; x += step) {
      var u = (x - cx) / hw;
      var edgeK = Math.max(0, 1 - u * u);
      var sx = cx + (x - cx) * (1 - 0.22 * edgeK) + Math.sin((x - cx) / 23 - t * 0.0068) * 6 * amp * edgeK;
      var sy = y0 - 3.4 * amp * edgeK;
      var sh = h * (1 + 0.055 * amp * edgeK);
      c.drawImage(scene, sx * dpr, sy * dpr, step * dpr, sh * dpr, x, y0, step + 0.8, h);
    }

    // 玻璃体：整体略提亮，文字依旧清楚
    var body = c.createLinearGradient(x0, y0, x0, y0 + h);
    body.addColorStop(0, 'rgba(232,255,252,0.10)');
    body.addColorStop(0.52, 'rgba(206,244,255,0.03)');
    body.addColorStop(1, 'rgba(255,255,255,0.07)');
    c.fillStyle = body;
    c.fillRect(x0, y0, w, h);

    var sheen = c.createLinearGradient(0, y0, 0, y0 + h * 0.22);
    sheen.addColorStop(0, 'rgba(255,255,255,0.18)');
    sheen.addColorStop(1, 'rgba(255,255,255,0)');
    c.fillStyle = sheen;
    c.fillRect(x0, y0, w, h * 0.22);

    var bottom = c.createLinearGradient(0, y0 + h * 0.62, 0, y0 + h);
    bottom.addColorStop(0, 'rgba(0,0,0,0)');
    bottom.addColorStop(1, 'rgba(0,0,0,0.26)');
    c.fillStyle = bottom;
    c.fillRect(x0, y0 + h * 0.62, w, h * 0.38);

    // 边缘色散：左偏暖、右偏冷
    c.globalCompositeOperation = 'lighter';
    var lg = c.createLinearGradient(x0, 0, x0 + 3, 0);
    lg.addColorStop(0, 'rgba(255,120,140,0.22)');
    lg.addColorStop(1, 'rgba(255,120,140,0)');
    c.fillStyle = lg; c.fillRect(x0, y0, 3, h);
    var rg = c.createLinearGradient(x0 + w - 3, 0, x0 + w, 0);
    rg.addColorStop(0, 'rgba(110,205,255,0)');
    rg.addColorStop(1, 'rgba(110,205,255,0.22)');
    c.fillStyle = rg; c.fillRect(x0 + w - 3, y0, 3, h);
    c.globalCompositeOperation = 'source-over';

    // 移动的细高光
    var bandW = Math.max(70, w * 0.12);
    var bx = x0 - bandW + ((t * 0.5) % (w + bandW * 2));
    var band = c.createLinearGradient(bx, 0, bx + bandW, 0);
    band.addColorStop(0, 'rgba(255,255,255,0)');
    band.addColorStop(0.5, 'rgba(255,255,255,0.10)');
    band.addColorStop(1, 'rgba(255,255,255,0)');
    c.fillStyle = band;
    c.save();
    c.translate(bx + bandW / 2, cy);
    c.rotate(-0.34);
    c.fillRect(-bandW / 2, -h, bandW, h * 2);
    c.restore();

    // 描边：外缘亮边 + 内侧细边（玻璃厚度）
    c.lineWidth = 1.3;
    var rim = c.createLinearGradient(x0, y0, x0 + w, y0 + h);
    rim.addColorStop(0, 'rgba(255,255,255,0.62)');
    rim.addColorStop(0.5, 'rgba(255,255,255,0.16)');
    rim.addColorStop(1, 'rgba(255,255,255,0.44)');
    c.strokeStyle = rim;
    blobPath(c, cx, cy, w / 2 - 0.7, h / 2 - 0.7, t, amp);
    c.stroke();
    c.strokeStyle = 'rgba(255,255,255,0.10)';
    c.lineWidth = 1;
    blobPath(c, cx, cy, w / 2 - 5, h / 2 - 5, t, amp);
    c.stroke();
    c.restore();
  }

  function render(t) {
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    sctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    var inProg = clamp(t / 520, 0, 1);
    var alpha = 0.15 + 0.85 * inProg;
    var blur = 10 * (1 - inProg);
    var scale = 0.965 + 0.035 * inProg;
    var glow = inProg;

    paintBackground(sctx, t);
    var m = paintLabel(sctx, alpha, blur, scale, glow);

    ctx.clearRect(0, 0, W, H);
    ctx.drawImage(scene, 0, 0, W, H);

    if (t >= T.sweepIn) paintLens(ctx, t, m);

    if (grain) {
      ctx.save();
      ctx.globalAlpha = 0.045;
      ctx.globalCompositeOperation = 'overlay';
      ctx.fillStyle = grain;
      ctx.translate(-(t * 0.008) % 96, -(t * 0.011) % 96);
      ctx.fillRect(0, 0, W + 96, H + 96);
      ctx.restore();
    }
  }

  function stop() {
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
  }

  function finish() {
    stop();
    running = false;
    finished = true;
    overlay.dataset.state = 'out';
    overlay.hidden = true;
    try { ctx.setTransform(1, 0, 0, 1, 0, 0); ctx.clearRect(0, 0, canvas.width, canvas.height); } catch (e) {}
  }

  function tick(now) {
    if (!running) return;
    raf = 0;
    var t = now - t0;
    render(t);
    if (t >= T.fade && overlay.dataset.state !== 'out') overlay.dataset.state = 'out';
    if (t >= T.end) { finish(); return; }
    raf = requestAnimationFrame(tick);
  }

  function play(opts) {
    opts = opts || {};
    if (running || finished || !ctx) return false;
    var seen = false;
    try { seen = sessionStorage.getItem(SEEN_KEY) === '1'; } catch (e) {}
    if (seen && !opts.force) return false;
    try { sessionStorage.setItem(SEEN_KEY, '1'); } catch (e) {}

    overlay.hidden = false;
    overlay.dataset.state = 'in';
    resize();
    if (!grain) grain = makeGrain();
    running = true;
    finished = false;
    pausedAt = 0;
    stop();

    if (reduced()) {
      t0 = performance.now();
      render(1200);
      setTimeout(finish, 620);
      return true;
    }
    t0 = performance.now();
    raf = requestAnimationFrame(tick);
    return true;
  }

  function skip() {
    if (!running) return;
    stop();
    overlay.dataset.state = 'out';
    setTimeout(finish, 220);
    running = false;
  }

  // 预览/截图用：冻结在某一时刻的画面
  function renderAt(ms) {
    overlay.hidden = false;
    overlay.dataset.state = 'in';
    resize();
    if (!grain) grain = makeGrain();
    render(Math.max(0, ms | 0));
    return { width: W, height: H, label: LABEL };
  }

  overlay.addEventListener('pointerdown', skip);
  window.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' || e.key === ' ' || e.key === 'Enter') skip();
  });
  window.addEventListener('resize', function () { if (running) { resize(); render(performance.now() - t0); } });
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) { if (running) { pausedAt = performance.now(); stop(); } }
    else if (running && pausedAt) { t0 += performance.now() - pausedAt; pausedAt = 0; raf = requestAnimationFrame(tick); }
  });
  if (motion && motion.addEventListener) motion.addEventListener('change', function () { if (running) { resize(); render(performance.now() - t0); } });

  window.hubIntro = { play: play, skip: skip, renderAt: renderAt, isPlaying: function () { return running; } };
})();

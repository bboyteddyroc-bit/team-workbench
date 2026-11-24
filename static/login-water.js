
(function () {
  // ---- 可配置项 ----
  var CONFIG = {
    rows: 85,          // 纵深方向的细丝层数，越多越像一整片水面
    particles: 100,     // 细小光点数量（0 为关闭）
    bokeh: 18,          // 虚化大光斑数量（0 为关闭）
    bloom: 0.7,         // 柔光强度，0 关闭，1 为基准，越大越像一整片发光的水
    introMs: 3200,      // 水面铺开时长
    exitMs: 1100,       // 点击进入后的退场时长
    autoEnterMs: 0,     // >0 时自动进入（毫秒），0 为手动点击
    onEnter: function () { /* 在这里跳转或挂载中台首页，例如 location.href = '/home' */ }
  };

  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var canvas = document.getElementById('login-flow');
  var ctx = canvas.getContext('2d');
  if(!ctx)return;
  var auth=document.getElementById('auth'), raf=0;
  var small1 = document.createElement('canvas'), s1 = small1.getContext('2d');
  var small2 = document.createElement('canvas'), s2 = small2.getContext('2d');
  var W = 0, H = 0, dpr = 1;
  var mouseX = 0, mouseTarget = 0;

  function resize() {
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    W = window.innerWidth; H = window.innerHeight;
    canvas.width = Math.round(W * dpr); canvas.height = Math.round(H * dpr);
    small1.width = Math.max(2, Math.ceil(W / 4)); small1.height = Math.max(2, Math.ceil(H / 4));
    small2.width = Math.max(2, Math.ceil(W / 14)); small2.height = Math.max(2, Math.ceil(H / 14));
    s1.imageSmoothingEnabled = true; s1.imageSmoothingQuality = 'high';
    s2.imageSmoothingEnabled = true; s2.imageSmoothingQuality = 'high';
  }
  window.addEventListener('resize', resize);
  window.addEventListener('pointermove', function (e) { mouseTarget = (e.clientX / W - 0.5); });
  resize();

  var seed = 11;
  function rnd() { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; }

  var fib = [];
  for (var i = 0; i < CONFIG.rows; i++) fib.push(rnd() * 2 - 1);

  var parts = [];
  for (var j = 0; j < CONFIG.particles; j++) {
    parts.push({ x: rnd(), r: 0.08 + rnd() * 0.92, sp: 0.01 + rnd() * 0.03, lift: Math.pow(rnd(), 2) * 1.3, s: 0.35 + rnd() * 0.9, a: 0.3 + rnd() * 0.6, tw: rnd() * 6.28 });
  }
  var bokeh = [];
  for (var q = 0; q < CONFIG.bokeh; q++) {
    bokeh.push({ x: rnd(), r: 0.2 + rnd() * 0.8, sp: 0.006 + rnd() * 0.016, lift: 0.2 + rnd() * 1.4, s: 3 + rnd() * 9, a: 0.1 + rnd() * 0.28, tw: rnd() * 6.28 });
  }

  // 水面高度场：几组方向和速度各异的行波叠加，f 为每根细丝自己的微小相位差
  function hfun(u, r, t, f) {
    var env = 0.65 + 0.35 * Math.sin(u * 3.1 + t * 0.18 + r * 1.5);
    var a = 0.55 * Math.sin(u * 5.2 + r * 2.1 - t * 0.8 + f * 0.15)
          + 0.30 * Math.sin(u * 9.7 - r * 3.3 - t * 1.15 + 1.3 + f * 0.2)
          + 0.16 * Math.sin(u * 17.0 + r * 6.0 - t * 1.7 + 2.1 + f * 0.35)
          + 0.28 * Math.sin(u * 2.4 - t * 0.5 + r * 1.2);
    return a * env + 0.05 * Math.sin(u * 31 + f * 40 - t * 1.1);
  }
  function baseY(r) { return H * 0.27 + H * 0.7 * Math.pow(r, 1.5); }
  function hScale(r) { return H * 0.17 * (0.3 + 0.95 * r); }
  function clamp01(x) { return x < 0 ? 0 : x > 1 ? 1 : x; }
  function ease(x) { return x < 0 ? 0 : x > 1 ? 1 : 1 - Math.pow(1 - x, 3); }

  var ALPHAS = [0.035, 0.06, 0.09, 0.125, 0.165, 0.21, 0.27];
  var WIDTHS = [0.5, 0.55, 0.6, 0.65, 0.75, 0.85, 1.0];

  var startTime = performance.now();
  var last = startTime;
  var t = 0;
  var exiting = false, exitStart = 0, finished = false;

  function frame(now) {
    raf=0;if(auth.hidden||document.hidden)return;
    var dt = Math.min(0.05, (now - last) / 1000); last = now;
    var exitP = exiting ? Math.min(1, (now - exitStart) / CONFIG.exitMs) : 0;
    var speed = reduce ? 0 : 0.55;
    t += dt * speed;
    mouseX += (mouseTarget - mouseX) * 0.04;
    var introP = reduce ? 1 : Math.min(1, (now - startTime) / CONFIG.introMs);
    var front = -0.25 * W + ease(introP) * 1.65 * W;
    var master = 1 - exitP;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.globalCompositeOperation = 'source-over';
    ctx.globalAlpha = 1;
    ctx.fillStyle = '#090d0e';
    ctx.fillRect(0, 0, W, H);

    if (master > 0.002) {
      ctx.globalCompositeOperation = 'lighter';
      ctx.lineCap = 'round';
      var core0 = 0.5 + 0.28 * Math.sin(t * 0.12) + mouseX * 0.12;
      function core(u) { var d = u - core0; return 0.42 + 0.95 * Math.exp(-d * d / 0.05); }

      // 细丝：每层一条极细的线，按坡度、高度、景深分到 7 档亮度，一档一次描边
      var R = CONFIG.rows;
      var step = Math.max(6, Math.round(W / 200));
      var xEnd = Math.min(W + step, front);
      var paths = [];
      for (var b = 0; b < 7; b++) paths.push(new Path2D());

      for (var ri = 0; ri < R; ri++) {
        var r = ri / (R - 1);
        var f = fib[ri];
        var base = baseY(r), hs = hScale(r);
        var dep = 0.35 + 0.65 * Math.sin(r * Math.PI * 0.95);
        var px = 0, py = 0, havePrev = false;
        for (var x = -step; x <= xEnd; x += step) {
          var u = x / W;
          var h = hfun(u, r, t, f);
          var y = base - h * hs;
          if (havePrev) {
            var dydx = (y - py) / step;
            var br = 0.42 - dydx * 1.5 + 0.28 * h;
            var fade = clamp01((front - x) / (0.3 * W));
            br *= dep * core(u) * fade * master;
            if (br > 0.06) {
              var bi = Math.min(6, Math.floor(br * 7.5));
              paths[bi].moveTo(px, py);
              paths[bi].lineTo(x, y);
            }
          }
          px = x; py = y; havePrev = true;
        }
      }
      ctx.strokeStyle = '#8fd6e1';
      for (var bb = 0; bb < 7; bb++) {
        ctx.globalAlpha = ALPHAS[bb];
        ctx.lineWidth = WIDTHS[bb];
        ctx.stroke(paths[bb]);
      }

      // 细小光点：贴着水面上方漂移
      ctx.fillStyle = '#c8edf0';
      for (var m = 0; m < parts.length; m++) {
        var P = parts[m];
        var pu = ((P.x + t * P.sp) % 1.1) - 0.05;
        var pxx = pu * W;
        if (pxx > front) continue;
        var pf = clamp01((front - pxx) / (0.2 * W));
        var pyy = baseY(P.r) - hfun(pu, P.r, t, 0) * hScale(P.r) - P.lift * hScale(P.r) * 0.55;
        var tw = 0.5 + 0.5 * Math.sin(t * 2.2 + P.tw);
        ctx.globalAlpha = P.a * tw * pf * master * (0.35 + 0.8 * core(pu));
        ctx.beginPath();
        ctx.arc(pxx, pyy, P.s * (0.6 + P.r * 1.1), 0, 6.2832);
        ctx.fill();
      }

      // 虚化大光斑：景深里没对上焦的亮点
      for (var n = 0; n < bokeh.length; n++) {
        var B = bokeh[n];
        var bu = ((B.x + t * B.sp) % 1.1) - 0.05;
        var bx = bu * W;
        if (bx > front) continue;
        var bf = clamp01((front - bx) / (0.2 * W));
        var by = baseY(B.r) - hfun(bu, B.r, t, 0) * hScale(B.r) - B.lift * hScale(B.r) * 0.6;
        var rad = B.s * (0.6 + B.r);
        var btw = 0.55 + 0.45 * Math.sin(t * 0.9 + B.tw);
        var gr = ctx.createRadialGradient(bx, by, 0, bx, by, rad);
        gr.addColorStop(0, 'rgba(80,190,210,1)');
        gr.addColorStop(0.6, 'rgba(80,190,210,0.5)');
        gr.addColorStop(1, 'rgba(80,190,210,0)');
        ctx.globalAlpha = B.a * btw * bf * master;
        ctx.fillStyle = gr;
        ctx.beginPath();
        ctx.arc(bx, by, rad, 0, 6.2832);
        ctx.fill();
      }
      ctx.globalAlpha = 1;

      // 柔光：缩小再放大叠回去，得到廉价而稳定的模糊光晕，细丝因此融成一片
      if (CONFIG.bloom > 0) {
        ctx.setTransform(1, 0, 0, 1, 0, 0);
        s1.clearRect(0, 0, small1.width, small1.height);
        s1.drawImage(canvas, 0, 0, canvas.width, canvas.height, 0, 0, small1.width, small1.height);
        s2.clearRect(0, 0, small2.width, small2.height);
        s2.drawImage(small1, 0, 0, small1.width, small1.height, 0, 0, small2.width, small2.height);
        ctx.globalCompositeOperation = 'lighter';
        ctx.globalAlpha = 0.9 * CONFIG.bloom;
        ctx.drawImage(small1, 0, 0, canvas.width, canvas.height);
        ctx.globalAlpha = 1.1 * CONFIG.bloom;
        ctx.drawImage(small2, 0, 0, canvas.width, canvas.height);
        ctx.globalAlpha = 1;
        ctx.globalCompositeOperation = 'source-over';
      }
    }

    if(!reduce)raf=requestAnimationFrame(frame);
  }
  var authWasVisible=false;
  function sync(){
    if(raf)cancelAnimationFrame(raf);raf=0;
    if(auth.hidden){authWasVisible=false;return;}
    if(!authWasVisible){startTime=performance.now();authWasVisible=true;}
    if(document.hidden)return;
    last=performance.now();raf=requestAnimationFrame(frame);
  }
  new MutationObserver(sync).observe(auth,{attributes:true,attributeFilter:['hidden']});
  document.addEventListener('visibilitychange',sync);
  window.addEventListener('resize',sync);
  window.matchMedia('(prefers-reduced-motion: reduce)').addEventListener('change',e=>{reduce=e.matches;sync();});
  sync();
  // Native adaptation of beUI input error/focus states; authentication stays in app.js.
  const error=document.getElementById('auth-error');
  const fields=Array.from(auth.querySelectorAll('input'));
  new MutationObserver(()=>{
    const invalid=!!error.textContent.trim();
    fields.forEach(input=>{input.setAttribute('aria-invalid',String(invalid));input.setAttribute('aria-describedby','auth-error');});
    if(invalid&&!reduce)auth.querySelector('#login-form').animate([{transform:'translateX(0)'},{transform:'translateX(-6px)'},{transform:'translateX(6px)'},{transform:'translateX(-3px)'},{transform:'translateX(0)'}],{duration:450});
  }).observe(error,{childList:true,characterData:true,subtree:true});
})();

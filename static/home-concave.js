'use strict';

document.addEventListener('DOMContentLoaded', () => {
  const home = document.querySelector('#home');
  const shell = document.querySelector('#shell');
  const sidebar = shell?.querySelector('.sidebar');
  if (!home || !sidebar) return;
  home.classList.add('sphere-home');
  home.innerHTML = `
  <section class="stage" aria-label="工作模块球面画廊">
    <canvas tabindex="0" aria-label="球面画廊，拖动或用方向键浏览，点击或按回车聚焦，Esc 返回"></canvas>
    <div class="sphere-brand" role="img" aria-label="DS">
      <svg class="sphere-mark" viewBox="275 105 896 871" aria-hidden="true">
        <defs><filter id="home-sphere-ink" x="0" y="0" width="1" height="1" color-interpolation-filters="sRGB">
          <feColorMatrix type="matrix" values="0 0 0 0 0  0 0 0 0 0  0 0 0 0 0  .51 1.71 .18 0 -.38"/>
          <feMorphology operator="dilate" radius="3.8"/>
        </filter></defs>
        <image href="/static/home-sphere-mark.webp" width="1448" height="1086" filter="url(#home-sphere-ink)"/>
      </svg>
    </div>
    <div class="fallback" hidden aria-label="工作模块"></div>
    <button type="button" class="peek previous-tile" tabindex="-1" aria-hidden="true"><span></span></button>
    <button type="button" class="peek next-tile" tabindex="-1" aria-hidden="true"><span></span></button>
  </section>
  <header class="top-tools">
    <button type="button" class="button return" hidden>返回画廊</button>
    <div class="caption" aria-live="polite" hidden><h2>工作模块</h2></div>
    <nav class="controls" aria-label="画廊控制">
      <button type="button" class="arrow previous" aria-label="上一个模块"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m12 4-6 6 6 6"/></svg></button>
      <button type="button" class="arrow next" aria-label="下一个模块"><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m8 4 6 6-6 6"/></svg></button>
      <button type="button" class="button enter" hidden>进入模块</button>
    </nav>
  </header>
  `;

  const artwork = ['/static/home-sphere-image.webp'];
  const canvas = home.querySelector('canvas');
  const stage = home.querySelector('.stage');
  const caption = home.querySelector('.caption');
  const fallback = home.querySelector('.fallback');
  const returnButton = home.querySelector('.return');
  const enterButton = home.querySelector('.enter');
  const peeks = [...home.querySelectorAll('.peek')];
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  const tau = Math.PI * 2;
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  const angleDelta = (from, to) => Math.atan2(Math.sin(to - from), Math.cos(to - from));
  const lerp = (a,b,t) => a + (b - a) * t;
  const ease = t => t * t * (3 - 2 * t);
  const styleClasses = ['art-original','art-silver','art-blue','art-amber'];

  // The curved frame has equal horizontal and vertical arc lengths at its center.
  const tileSide = .35;
  let modules = [];
  let tiles = [];
  let navigationKey = '';
  let initialized = false;
  const isHomeVisible = () => !shell.hidden && !home.hidden && !document.hidden;

  function setModules() {
    const visible = [...sidebar.querySelectorAll('button[data-view]:not([hidden])')]
      .filter(button => button.dataset.view !== 'home');
    const key = visible.map(button => button.dataset.view).join(',');
    if (key === navigationKey) return;
    navigationKey = key;
    modules = visible.map(button => ({
      button, title:button.getAttribute('aria-label') || button.textContent.trim()
    }));
    tiles = Array.from({length:7},(_,band) => {
      const latitude = (band - 3) * .389;
      const circumference = Math.cos(latitude);
      const count = Math.max(2,Math.floor(tau * circumference / (tileSide + .037)));
      return Array.from({length:count},(_,slot) => ({
        latitude, longitude:tau * (slot + ((band + 1) % 2) * .5) / count,
        span:tileSide / circumference, height:tileSide,
        module:(slot + band * 5) % modules.length, style:(slot + band) % styleClasses.length
      }));
    }).flat();
    state.index = -1;
    if (state.selected) resetFocus();
    if (initialized && !renderer) showFallback();
    schedule();
  }
  const state = {
    yaw:0,pitch:0,targetYaw:0,targetPitch:0,viewYaw:0,viewPitch:0,morph:0,zoom:0,
    selected:null,flattening:null,index:-1,transition:null,
    reveal:0,entry:0,scale:.52,revealStart:null,loaded:0,lensMotion:0
  };
  const parallax = {x:0,y:0,targetX:0,targetY:0};
  let width = 1, height = 1, focal = 1, camera = 3.05, frame = 0, lastFrame = 0;
  let pointer = null, renderer = null, hovered = null;
  const homeCamera = .12;
  const focusCamera = 1.92;
  let peekKey = '';

  const vertexSource = `
    attribute vec2 aUv;
    uniform vec4 uTile;
    uniform vec2 uTurn;
    uniform vec2 uProjection;
    uniform float uCamera;
    uniform mediump float uMorph;
    uniform float uScale;
    uniform float uReverseCurve;
    uniform float uInterior;
    uniform vec2 uFlat;
    varying mediump vec2 vUv;
    varying mediump float vLight;
    void main(){
      vUv = aUv;
      float longitude = uTile.x + (aUv.x - .5) * (1. - 2. * uReverseCurve) * uTile.z - uTurn.x;
      float latitude = uTile.y + (aUv.y - .5) * uTile.w;
      vec3 sphere = vec3(cos(latitude) * sin(longitude), sin(latitude), cos(latitude) * cos(longitude));
      float c = cos(uTurn.y), s = sin(uTurn.y);
      sphere.yz = vec2(sphere.y * c - sphere.z * s, sphere.y * s + sphere.z * c);
      vec3 plane = vec3((aUv - .5) * uFlat, 1.015);
      vec3 p = mix(sphere * uScale, plane, uMorph);
      float depth = uCamera - p.z;
      gl_Position = vec4(p.xy * uProjection, 1.004 * depth - .07, depth);
      float light = mix(clamp(.28 + sphere.z * .76,.2,1.),.9 + .08 * abs(sphere.z),uInterior);
      vLight = mix(light,1.02,uMorph);
    }`;
  const fragmentSource = `
    precision mediump float;
    uniform sampler2D uArtwork;
    uniform vec2 uCrop;
    uniform float uOpacity;
    uniform float uMirror;
    uniform mediump float uMorph;
    uniform float uDissolve;
    uniform float uSeed;
    uniform float uStyle;
    varying vec2 vUv;
    varying float vLight;
    float randomValue(vec2 p){
      vec3 q = fract(vec3(p.xyx) * vec3(.1031,.11369,.13787));
      q += dot(q,q.yzx + 19.19);
      return fract((q.x + q.y) * q.z);
    }
    float noise(vec2 p){
      vec2 i = floor(p), f = fract(p);
      f = f * f * (3. - 2. * f);
      return mix(mix(randomValue(i),randomValue(i+vec2(1,0)),f.x),
                 mix(randomValue(i+vec2(0,1)),randomValue(i+vec2(1,1)),f.x),f.y);
    }
    vec3 styleImage(vec3 original){
      float luma = dot(original,vec3(.2126,.7152,.0722));
      if (uStyle < .5) return original;
      if (uStyle < 1.5) return vec3(pow(luma,.84));
      if (uStyle < 2.5) {
        float density = pow(1. - luma,1.65);
        return mix(vec3(.022,.017,.13),vec3(.25,.85,1.),density);
      }
      return mix(vec3(.10,.019,.034),vec3(1.,.71,.42),pow(luma,.78));
    }
    void main(){
      float inset = .019 * (1. - uMorph);
      vec2 p = abs(vUv - .5) - vec2(.5 - 1.75 * inset);
      float edge = length(max(p, 0.)) + min(max(p.x,p.y),0.) - inset;
      if (edge > .001) discard;
      vec2 imageUv = .5 + (vec2(mix(vUv.x,1. - vUv.x,uMirror),vUv.y) - .5) * uCrop;
      float margin = min(min(imageUv.x,imageUv.y),min(1.-imageUv.x,1.-imageUv.y));
      vec3 color = margin >= 0. ? styleImage(texture2D(uArtwork, imageUv).rgb) : vec3(.946,.929,.91);
      float alpha = (1. - smoothstep(-.002,.001,edge)) * uOpacity;
      if (uDissolve > .001){
        vec2 seed = vec2(uSeed * 3.7, uSeed * 1.2);
        float grain = .65 * noise(vUv * 4. + seed) + .35 * noise(vUv * 12. + seed);
        float remaining = grain - mix(-.13,1.06,uDissolve);
        alpha *= smoothstep(-.02,.02,remaining);
        color += vec3(.24,.24,.26) * (1. - smoothstep(.012,.09,remaining));
      }
      gl_FragColor = vec4(color * vLight, alpha);
    }`;

  const lensVertex = `
    attribute vec2 aUv;
    varying mediump vec2 vUv;
    void main(){
      vUv = aUv;
      gl_Position = vec4(aUv * 2. - 1., 0., 1.);
    }`;
  const coreFragment = `
    precision mediump float;
    uniform vec3 uCore;
    varying vec2 vUv;
    void main(){
      vec2 p = (vUv * 2. - 1.) / uCore.xy;
      float radius = length(p);
      if (radius > 1.) discard;
      float normal = sqrt(1. - radius * radius);
      float light = clamp(.48 + .39 * normal - .16 * p.x + .12 * p.y,0.,1.);
      gl_FragColor = vec4(vec3(.30,.38,.40) * light,uCore.z * (1. - smoothstep(.99,1.,radius)));
    }`;
  const lensFragment = `
    precision mediump float;
    uniform sampler2D uScene;
    uniform vec3 uLens;
    varying vec2 vUv;
    void main(){
      vec2 offset = vUv - .5;
      float radius = length(offset * vec2(uLens.z,1.));
      float rim = smoothstep(.20 - .12 * uLens.y,.68,radius);
      float spread = rim * (rim * uLens.x + .12 * uLens.y);
      vec4 color = texture2D(uScene,vUv);
      if (spread > .001){
        for (int i = 1; i <= 12; ++i){
          float k = float(i) / 12.;
          vec4 sampleColor = texture2D(uScene,vUv - offset * spread * k);
          sampleColor.r = texture2D(uScene,vUv - offset * spread * k * .87).r;
          sampleColor.b = texture2D(uScene,vUv - offset * spread * k * 1.13).b;
          color += sampleColor;
        }
        color /= 13.;
      }
      gl_FragColor = color;
    }`;

  function buildProgram(gl, vertex, fragment) {
    const program = gl.createProgram();
    for (const [type, source] of [[gl.VERTEX_SHADER, vertex],[gl.FRAGMENT_SHADER, fragment]]) {
      const shader = gl.createShader(type);
      gl.shaderSource(shader, source);
      gl.compileShader(shader);
      if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) throw Error(gl.getShaderInfoLog(shader));
      gl.attachShader(program, shader);
      gl.deleteShader(shader);
    }
    gl.bindAttribLocation(program,0,'aUv');
    gl.linkProgram(program);
    if (!gl.getProgramParameter(program, gl.LINK_STATUS)) throw Error(gl.getProgramInfoLog(program));
    return program;
  }

  function createRenderer(gl) {
    const program = buildProgram(gl,vertexSource,fragmentSource);
    const lensProgram = buildProgram(gl,lensVertex,lensFragment);
    const coreProgram = buildProgram(gl,lensVertex,coreFragment);
    const lensUniform = gl.getUniformLocation(lensProgram,'uLens');
    const coreUniform = gl.getUniformLocation(coreProgram,'uCore');
    const frameBuffer = gl.createFramebuffer();
    const frameTexture = gl.createTexture();
    gl.bindTexture(gl.TEXTURE_2D,frameTexture);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
    const quad = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER,quad);
    gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([0,0,1,0,0,1,1,1]),gl.STATIC_DRAW);
    let targetWidth = 0, targetHeight = 0, lensAvailable = true;

    const size = 20;
    const vertices = [];
    const indices = [];
    for (let y = 0; y <= size; y++) {
      for (let x = 0; x <= size; x++) vertices.push(x / size, y / size);
    }
    for (let y = 0; y < size; y++) {
      for (let x = 0; x < size; x++) {
        const a = y * (size + 1) + x;
        const b = a + size + 1;
        indices.push(a,a+1,b,a+1,b+1,b);
      }
    }
    const meshBuffer = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, meshBuffer);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(vertices), gl.STATIC_DRAW);
    const attribute = gl.getAttribLocation(program, 'aUv');
    gl.enableVertexAttribArray(attribute);
    gl.vertexAttribPointer(attribute, 2, gl.FLOAT, false, 0, 0);
    gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, gl.createBuffer());
    gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, new Uint16Array(indices), gl.STATIC_DRAW);
    gl.enable(gl.BLEND);
    gl.blendFuncSeparate(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA, gl.ONE, gl.ONE_MINUS_SRC_ALPHA);
    gl.enable(gl.CULL_FACE);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);

    const uniforms = Object.fromEntries(['Tile','Turn','Projection','Camera','Morph','Crop','Opacity','Mirror','Scale','Flat','Dissolve','Seed','Style','Interior','ReverseCurve']
      .map(name => [name, gl.getUniformLocation(program, 'u' + name)]));
    const textures = artwork.map(source => {
      const texture = gl.createTexture();
      gl.bindTexture(gl.TEXTURE_2D, texture);
      gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,1,1,0,gl.RGBA,gl.UNSIGNED_BYTE,new Uint8Array([49,62,65,255]));
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);
      gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);
      const asset = {texture,aspect:1.6};
      const image = new Image();
      image.onerror = showFallback;
      image.onload = () => {
        gl.bindTexture(gl.TEXTURE_2D,texture);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,image);
        asset.aspect = image.naturalWidth / image.naturalHeight;
        state.loaded++;
        schedule();
      };
      image.src = source;
      return asset;
    });

    return () => {
      if (targetWidth !== canvas.width || targetHeight !== canvas.height) {
        targetWidth = canvas.width;
        targetHeight = canvas.height;
        gl.bindTexture(gl.TEXTURE_2D,frameTexture);
        gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,targetWidth,targetHeight,0,gl.RGBA,gl.UNSIGNED_BYTE,null);
        gl.bindFramebuffer(gl.FRAMEBUFFER,frameBuffer);
        gl.framebufferTexture2D(gl.FRAMEBUFFER,gl.COLOR_ATTACHMENT0,gl.TEXTURE_2D,frameTexture,0);
        lensAvailable = gl.checkFramebufferStatus(gl.FRAMEBUFFER) === gl.FRAMEBUFFER_COMPLETE;
      }
      const useLens = lensAvailable && !reduced.matches && (state.zoom < .998 || state.lensMotion > .006);
      gl.bindFramebuffer(gl.FRAMEBUFFER,useLens ? frameBuffer : null);
      gl.viewport(0,0,canvas.width,canvas.height);
      gl.clearColor(0,0,0,0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.BLEND);
      gl.enable(gl.CULL_FACE);
      gl.cullFace(gl.BACK);
      const exterior = state.entry < 1 ? ease(clamp((camera - 1.02) / .54,0,1)) : 0;
      if (state.reveal > 0 && exterior > 0 && camera > 1.02) {
        const radius = state.scale * .983;
        const silhouette = 2 * focal * radius / Math.sqrt(camera * camera - radius * radius);
        gl.useProgram(coreProgram);
        gl.bindBuffer(gl.ARRAY_BUFFER,quad);
        gl.vertexAttribPointer(attribute,2,gl.FLOAT,false,0,0);
        gl.uniform3f(coreUniform,silhouette / width,silhouette / height,state.reveal * exterior * .30);
        gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
      }
      gl.useProgram(program);
      gl.bindBuffer(gl.ARRAY_BUFFER,meshBuffer);
      gl.vertexAttribPointer(attribute,2,gl.FLOAT,false,0,0);
      gl.uniform2f(uniforms.Projection, focal * 2 / width, focal * 2 / height);
      gl.uniform2f(uniforms.Turn,state.viewYaw,state.viewPitch);
      gl.uniform1f(uniforms.Camera,camera);
      gl.uniform1f(uniforms.Scale,state.scale);
      if (state.reveal > 0 && state.zoom < .999) {
        const dissolve = Math.max((1 - state.reveal) * .68,state.zoom);
        const interior = 1 - ease(clamp((camera - 1.12) / .75,0,1));
        if (state.entry === 1 || interior > 0) {
          gl.cullFace(gl.FRONT);
          gl.uniform1f(uniforms.Camera,state.entry === 1 ? homeCamera : camera);
          for (const tile of tiles) {
            if (tile !== state.flattening) draw(tile,0,state.reveal * (state.entry === 1 ? 1 : interior),dissolve,'inside');
          }
        }
        if (exterior > 0) {
          gl.cullFace(gl.BACK);
          gl.uniform1f(uniforms.Camera,camera);
          for (const tile of tiles) draw(tile,0,state.reveal * exterior,dissolve);
        }
      }
      gl.disable(gl.CULL_FACE);
      gl.uniform1f(uniforms.Camera,camera);
      const switchProgress = state.transition?.switchProgress;
      if (state.transition?.outgoing && switchProgress < .62) {
        draw(state.transition.outgoing,1,1,Math.min(1,switchProgress * 1.65),'focus');
      }
      if (state.flattening) {
        const dissolve = switchProgress == null ? 0 : clamp((.65 - switchProgress) * 1.4,0,1);
        draw(state.flattening,state.morph,1,dissolve,'focus');
      }
      if (!useLens) return;
      gl.bindFramebuffer(gl.FRAMEBUFFER,null);
      gl.disable(gl.BLEND);
      gl.useProgram(lensProgram);
      gl.bindBuffer(gl.ARRAY_BUFFER,quad);
      gl.vertexAttribPointer(attribute,2,gl.FLOAT,false,0,0);
      gl.bindTexture(gl.TEXTURE_2D,frameTexture);
      gl.uniform3f(lensUniform,.17 * (1 - state.zoom),state.lensMotion,clamp(width / height,.65,1.85));
      gl.drawArrays(gl.TRIANGLE_STRIP,0,4);
    };

    function draw(tile, morph, opacity, dissolve, surface = 'outside') {
      if (opacity < .006) return;
      const asset = textures[0];
      const angularAspect = tile.span * Math.cos(tile.latitude) / tile.height;
      const flatSize = fitArtwork(asset.aspect);
      gl.bindTexture(gl.TEXTURE_2D,asset.texture);
      gl.uniform4f(uniforms.Tile,tile.longitude,tile.latitude,tile.span,tile.height);
      const padding = 1.08;
      const ratio = angularAspect / asset.aspect;
      gl.uniform2f(uniforms.Crop,lerp(Math.max(1,ratio) * padding,1,morph),lerp(Math.max(1,1 / ratio) * padding,1,morph));
      gl.uniform2f(uniforms.Flat,...flatSize);
      gl.uniform1f(uniforms.Morph,morph);
      gl.uniform1f(uniforms.Opacity,opacity);
      gl.uniform1f(uniforms.Mirror,Number(surface === 'inside'));
      gl.uniform1f(uniforms.Interior,Number(surface !== 'outside'));
      gl.uniform1f(uniforms.ReverseCurve,Number(surface === 'focus'));
      gl.uniform1f(uniforms.Dissolve,dissolve);
      gl.uniform1f(uniforms.Seed,tile.module + 13 * tile.longitude);
      gl.uniform1f(uniforms.Style,tile.style);
      gl.drawElements(gl.TRIANGLES,indices.length,gl.UNSIGNED_SHORT,0);
    }
  }

  function fitArtwork(aspect) {
    const factor = (focusCamera - 1.015) / focal;
    const maxWidth = Math.min(width * .65,height * 1.4) * factor;
    const maxHeight = height * .76 * factor;
    return [Math.min(maxWidth,maxHeight * aspect),Math.min(maxHeight,maxWidth / aspect)];
  }

  function measure() {
    const rect = canvas.getBoundingClientRect();
    width = Math.max(1, rect.width);
    height = Math.max(1, rect.height);
    focal = Math.min(height * 1.08,width * 1.34);
    const resolution = Math.min(1.6,devicePixelRatio || 1,Math.sqrt(2400000 / (width * height)));
    canvas.width = Math.round(width * resolution);
    canvas.height = Math.round(height * resolution);
    schedule();
  }

  function pick(x, y, yaw = state.viewYaw, pitch = state.viewPitch) {
    const bounds = canvas.getBoundingClientRect();
    const px = (x - bounds.left - width / 2) / focal;
    const py = (height / 2 - (y - bounds.top)) / focal;
    const a = px * px + py * py + 1;
    const discriminant = camera * camera - a * (camera * camera - 1);
    if (discriminant < 0) return null;
    const distance = (camera + (camera < 1 ? 1 : -1) * Math.sqrt(discriminant)) / a;
    const z = camera - distance;
    const screenY = py * distance;
    const latitude = Math.asin(clamp(screenY * Math.cos(pitch) + z * Math.sin(pitch),-1,1));
    const longitude = Math.atan2(px * distance,z * Math.cos(pitch) - screenY * Math.sin(pitch)) + yaw;
    return tiles.find(tile => Math.abs(latitude - tile.latitude) < tile.height * .5 &&
      Math.abs(angleDelta(tile.longitude,longitude)) < tile.span * .5) || null;
  }

  function aimInside(tile) {
    return state.viewYaw + angleDelta(state.viewYaw,tile.longitude - Math.PI);
  }

  function showModule(index) {
    if (state.index === index) return;
    state.index = index;
    caption.querySelector('h2').textContent = modules[index].title;
  }

  function setFocused(tile) {
    if (state.selected === tile) return;
    const outgoing = state.selected && tile ? state.selected : null;
    state.targetYaw = tile ? aimInside(tile) : state.viewYaw;
    state.targetPitch = tile ? -tile.latitude : 0;
    state.transition = {
      start:performance.now(), duration:outgoing ? 760 : tile ? 920 : 640,
      yaw:state.viewYaw, pitch:state.viewPitch, zoom:state.zoom,
      morph:outgoing ? Math.min(state.morph,.67) : state.morph, outgoing
    };
    state.selected = tile;
    hovered = null;
    state.flattening = tile || state.flattening;
    canvas.classList.remove('hovering');
    stage.classList.toggle('focused',Boolean(tile));
    returnButton.hidden = !tile;
    enterButton.hidden = !tile;
    caption.hidden = !tile;
    if (tile) showModule(tile.module);
    syncPeeks();
    for (const [index,button] of Array.from(fallback.children).entries()) {
      button.setAttribute('aria-pressed',String(tile?.module === index));
    }
    schedule();
  }

  function syncPeeks() {
    const ready = Boolean(renderer && state.selected && !state.transition && modules.length > 1);
    const key = ready ? String(state.selected.module) : '';
    if (key === peekKey) return;
    peekKey = key;
    peeks.forEach((button,i) => {
      button.classList.toggle('ready',ready);
      button.tabIndex = ready ? 0 : -1;
      button.setAttribute('aria-hidden',String(!ready));
      if (!ready) return;
      const index = neighborIndex(state.selected.module,i ? 1 : -1);
      const title = modules[index].title;
      const image = button.querySelector('img') || new Image();
      decorateImage(image,tiles.find(tile => tile.module === index));
      if (!image.isConnected) button.prepend(image);
      button.querySelector('span').textContent = title;
      button.setAttribute('aria-label',`${i ? '下一个模块' : '上一个模块'} ${title}`);
    });
  }

  function decorateImage(image,tile) {
    image.alt = '';
    image.src = artwork[0];
    image.className = styleClasses[tile.style];
  }

  function neighborIndex(index,direction) {
    return (Math.max(index,0) + direction + modules.length) % modules.length;
  }

  function schedule() {
    if (renderer && isHomeVisible() && !frame) frame = requestAnimationFrame(tick);
  }

  function tick(now) {
    frame = 0;
    if (!isHomeVisible()) return;
    const dt = lastFrame ? clamp(now - lastFrame,1,32) : 16;
    lastFrame = now;
    if (state.revealStart === null && state.loaded >= artwork.length) state.revealStart = now;
    const entry = state.revealStart === null ? 0 : reduced.matches ? 1 : clamp((now - state.revealStart) / 2250,0,1);
    state.entry = entry;
    state.reveal = ease(clamp(entry / .55,0,1));
    state.scale = lerp(.52,1,state.reveal);
    const previousCamera = camera;
    const transition = state.transition;
    if (transition) {
      const t = reduced.matches ? 1 : clamp((now - transition.start) / transition.duration,0,1);
      const amount = ease(t);
      const target = Number(Boolean(state.selected));
      state.viewYaw = state.yaw = lerp(transition.yaw,state.targetYaw,amount);
      state.viewPitch = state.pitch = lerp(transition.pitch,state.targetPitch,amount);
      state.morph = lerp(transition.morph,target,amount);
      state.zoom = lerp(transition.zoom,target,amount);
      if (transition.outgoing) transition.switchProgress = t;
      if (t === 1) {
        state.transition = null;
        parallax.x = parallax.y = 0;
        if (!state.selected) state.flattening = null;
        syncPeeks();
      }
    } else {
      const move = reduced.matches ? 1 : 1 - Math.exp(-dt * .012);
      const drift = reduced.matches ? 1 : 1 - Math.exp(-dt * .006);
      state.yaw = lerp(state.yaw,state.targetYaw,move);
      state.pitch = lerp(state.pitch,state.targetPitch,move);
      parallax.x = lerp(parallax.x,state.selected ? 0 : parallax.targetX,drift);
      parallax.y = lerp(parallax.y,state.selected ? 0 : parallax.targetY,drift);
      state.viewYaw = state.yaw + parallax.x + (1 - state.reveal) * 1.12;
      state.viewPitch = state.pitch + parallax.y + (1 - state.reveal) * .46;
    }
    const entryCamera = lerp(3.9,homeCamera,ease(clamp((entry - .16) / .84,0,1)));
    const pullback = transition?.outgoing ? .09 * Math.sin(Math.PI * transition.switchProgress) : 0;
    camera = lerp(entryCamera,focusCamera,state.zoom) + pullback;
    const velocity = clamp(Math.abs(camera - previousCamera) * 145 / dt,0,1);
    state.lensMotion = lerp(state.lensMotion,velocity,1 - Math.exp(-dt * .014));
    renderer();
    if (!state.selected && !state.transition && entry === 1) {
      const bounds = canvas.getBoundingClientRect();
      const center = [.5,.46,.54].map(offset =>
        pick(width * offset + bounds.left,height / 2 + bounds.top,state.yaw,state.pitch)
      ).find(Boolean);
      if (center) showModule(center.module);
    }
    if (state.transition || (entry < 1 && state.revealStart !== null) ||
        Math.abs(state.targetYaw - state.yaw) + Math.abs(state.targetPitch - state.pitch) > .001 ||
        (!state.selected && Math.abs(parallax.targetX - parallax.x) + Math.abs(parallax.targetY - parallax.y) > .001) ||
        (!reduced.matches && state.lensMotion > .004)) schedule();
    else lastFrame = 0;
  }

  function step(direction) {
    if (!modules.length || (renderer && state.entry < 1)) return;
    const index = neighborIndex(state.selected?.module ?? state.index,direction);
    const tile = tiles.find(candidate => candidate.module === index);
    if (state.selected || !renderer) {
      setFocused(tile);
      return;
    }
    state.targetYaw = aimInside(tile);
    state.targetPitch = -tile.latitude;
    showModule(index);
    schedule();
  }

  function back() {
    setFocused(null);
    if (renderer) canvas.focus({preventScroll:true});
    else fallback.children[Math.max(0,state.index)]?.focus();
  }

  canvas.addEventListener('pointerdown', event => {
    if (state.entry < 1 || !event.isPrimary || event.button !== 0) return;
    pointer = {id:event.pointerId, x:event.clientX, y:event.clientY, yaw:state.targetYaw,pitch:state.targetPitch,moved:false};
    canvas.setPointerCapture(event.pointerId);
  });
  canvas.addEventListener('pointermove', event => {
    if (state.entry < 1) return;
    if (!pointer) {
      if (state.selected || state.transition || event.pointerType !== 'mouse') return;
      const bounds = canvas.getBoundingClientRect();
      const strength = reduced.matches ? 0 : .11;
      parallax.targetX = clamp((event.clientX - bounds.left) / width * 2 - 1,-1,1) * strength;
      parallax.targetY = clamp((event.clientY - bounds.top) / height * 2 - 1,-1,1) * strength;
      const tile = pick(event.clientX,event.clientY);
      if (tile !== hovered) {
        hovered = tile;
        canvas.classList.toggle('hovering',Boolean(tile));
      }
      schedule();
      return;
    }
    if (event.pointerId !== pointer.id) return;
    const dx = event.clientX - pointer.x;
    const dy = event.clientY - pointer.y;
    if (!pointer.moved && Math.max(Math.abs(dx),Math.abs(dy)) < 6) return;
    if (!pointer.moved) {
      pointer.moved = true;
      hovered = null;
      canvas.classList.add('dragging');
    }
    if (state.selected || state.transition) return;
    state.targetYaw = pointer.yaw - dx / width * tau;
    state.targetPitch = clamp(pointer.pitch + dy / width * Math.PI,-Math.PI / 4,Math.PI / 4);
    schedule();
  });
  canvas.addEventListener('pointerup', event => {
    if (pointer?.id !== event.pointerId) return;
    const moved = pointer.moved || Math.max(Math.abs(event.clientX - pointer.x),Math.abs(event.clientY - pointer.y)) >= 6;
    pointer = null;
    canvas.classList.remove('dragging');
    if (moved) return;
    if (state.selected) {
      back();
      return;
    }
    if (state.transition) return;
    const tile = pick(event.clientX,event.clientY);
    if (tile) setFocused(tile);
  });
  for (const event of ['pointercancel','lostpointercapture']) {
    canvas.addEventListener(event,() => {
      pointer = null;
      canvas.classList.remove('dragging');
    });
  }
  canvas.addEventListener('pointerleave',() => {
    hovered = null;
    parallax.targetX = parallax.targetY = 0;
    canvas.classList.remove('hovering');
    schedule();
  });
  canvas.addEventListener('wheel',event => {
    if (state.selected || state.transition || state.entry < 1) return;
    event.preventDefault();
    const delta = event.deltaX || event.deltaY;
    state.targetYaw += clamp(delta * (event.deltaMode === 1 ? .055 : .003),-.5,.5);
    schedule();
  },{passive:false});
  canvas.addEventListener('keydown',event => {
    if (state.entry < 1) return;
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      if (state.selected) enterButton.click();
      else {
        const bounds = canvas.getBoundingClientRect();
        setFocused(pick(bounds.left + width / 2,bounds.top + height / 2) ||
          tiles.find(tile => tile.module === Math.max(state.index,0)));
      }
    } else if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
      event.preventDefault();
      step(event.key === 'ArrowLeft' ? -1 : 1);
    } else if (!state.selected && (event.key === 'ArrowUp' || event.key === 'ArrowDown')) {
      event.preventDefault();
      state.targetPitch = clamp(state.targetPitch + (event.key === 'ArrowUp' ? .39 : -.39),-Math.PI / 4,Math.PI / 4);
      schedule();
    }
  });
  document.addEventListener('keydown',event => {
    if (event.key === 'Escape' && state.selected && isHomeVisible()) back();
  });
  reduced.addEventListener('change',() => {
    if (reduced.matches) parallax.targetX = parallax.targetY = 0;
    schedule();
  });
  home.querySelector('.previous').onclick = () => step(-1);
  home.querySelector('.next').onclick = () => step(1);
  peeks.forEach((button,i) => {
    button.onclick = () => {
      step(i ? 1 : -1);
      canvas.focus({preventScroll:true});
    };
  });
  returnButton.onclick = back;
  function openModule(tile) {
    const button = modules[tile?.module]?.button;
    if (isHomeVisible() && button && !button.hidden) button.click();
  }
  enterButton.onclick = () => openModule(state.selected);

  function showFallback() {
    renderer = null;
    cancelAnimationFrame(frame);
    frame = lastFrame = 0;
    resetFocus();
    syncPeeks();
    home.classList.add('no-webgl');
    canvas.hidden = true;
    fallback.hidden = false;
    fallback.replaceChildren(...modules.map(({title},index) => {
      const button = document.createElement('button');
      const image = new Image();
      const label = document.createElement('span');
      const tile = tiles.find(tile => tile.module === index);
      decorateImage(image,tile);
      label.textContent = title;
      button.type = 'button';
      button.setAttribute('aria-pressed',String(state.selected?.module === index));
      button.append(image,label);
      button.onclick = () => openModule(tile);
      return button;
    }));
  }

  function resetFocus() {
    state.selected = state.flattening = state.transition = null;
    state.morph = state.zoom = 0;
    state.lensMotion = 0;
    state.targetPitch = state.viewPitch = state.pitch = 0;
    state.targetYaw = state.viewYaw = state.yaw;
    parallax.x = parallax.y = parallax.targetX = parallax.targetY = 0;
    stage.classList.remove('focused');
    caption.hidden = returnButton.hidden = enterButton.hidden = true;
    syncPeeks();
  }

  function syncHome() {
    if (!isHomeVisible()) {
      cancelAnimationFrame(frame);
      frame = lastFrame = 0;
      pointer = null;
      canvas.classList.remove('dragging','hovering');
      if (home.hidden || shell.hidden) resetFocus();
      if (shell.hidden) {
        state.entry = state.reveal = 0;
        state.revealStart = null;
      }
      return;
    }
    setModules();
    if (!modules.length) return;
    if (!initialized) {
      initialized = true;
      try {
        const gl = canvas.getContext('webgl',{alpha:true,antialias:true});
        if (!gl) throw Error('WebGL is unavailable');
        renderer = createRenderer(gl);
        new ResizeObserver(() => {
          if (renderer && isHomeVisible()) measure();
        }).observe(stage);
        canvas.addEventListener('webglcontextlost',showFallback);
      } catch (error) {
        console.warn('Home gallery uses the module grid:',error);
        showFallback();
      }
    }
    if (renderer) measure();
  }

  const visibility = new MutationObserver(syncHome);
  visibility.observe(home,{attributes:true,attributeFilter:['hidden']});
  visibility.observe(shell,{attributes:true,attributeFilter:['hidden']});
  visibility.observe(sidebar,{subtree:true,attributes:true,attributeFilter:['hidden']});
  document.addEventListener('visibilitychange',syncHome);
  syncHome();
});

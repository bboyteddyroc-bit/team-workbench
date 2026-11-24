/* 取色器（原生复刻 @beui/color-picker）
 * 触发器是一个色块芯片，点开后芯片形变为“饱和度/亮度”区域；拖动拇指时放大镜抬起并随速度倾斜。
 * 只输出不透明 #rrggbb（后端字幕样式校验要求），因此没有 alpha 滑杆。
 * 用法：window.hubColorPicker.mount({value:'#ffffff',label:'字幕文字颜色',onInput,onCommit})
 */
'use strict';
(function(){
  const registry=new Set();
  const clamp=(n,lo,hi)=>Math.min(hi,Math.max(lo,n));
  const reduced=()=>window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  const G=()=>window.gsap;

  /* ---------- 颜色换算 ---------- */
  function parseHex(input){
    if(typeof input!=='string')return null;
    let s=input.trim().replace(/^#/,'');
    if(/^[0-9a-f]{3}$/i.test(s))s=s.split('').map(c=>c+c).join('');
    if(/^[0-9a-f]{4}$/i.test(s))s=s.split('').map(c=>c+c).join('');
    if(!/^([0-9a-f]{6}|[0-9a-f]{8})$/i.test(s))return null;
    return{r:parseInt(s.slice(0,2),16),g:parseInt(s.slice(2,4),16),b:parseInt(s.slice(4,6),16)};
  }
  function toHex({r,g,b}){
    const f=n=>clamp(Math.round(n),0,255).toString(16).padStart(2,'0');
    return `#${f(r)}${f(g)}${f(b)}`;
  }
  function rgbToHsv(r,g,b){
    r/=255;g/=255;b/=255;
    const max=Math.max(r,g,b),min=Math.min(r,g,b),d=max-min;
    let h=0;if(d){if(max===r)h=((g-b)/d)%6;else if(max===g)h=(b-r)/d+2;else h=(r-g)/d+4;h*=60;if(h<0)h+=360;}
    return{h,s:max?d/max*100:0,v:max*100};
  }
  function hsvToRgb(h,s,v){
    s/=100;v/=100;const c=v*s,x=c*(1-Math.abs((h/60)%2-1)),m=v-c;
    let r=0,g=0,b=0;
    if(h<60){r=c;g=x;}else if(h<120){r=x;g=c;}else if(h<180){g=c;b=x;}
    else if(h<240){g=x;b=c;}else if(h<300){r=x;b=c;}else{r=c;b=x;}
    return{r:(r+m)*255,g:(g+m)*255,b:(b+m)*255};
  }
  const hexToHsv=hex=>{const rgb=parseHex(hex);return rgb?rgbToHsv(rgb.r,rgb.g,rgb.b):{h:0,s:0,v:100};};
  const hsvToHex=hsv=>toHex(hsvToRgb(hsv.h,hsv.s,hsv.v));
  const PRESETS=['#ffffff','#101010','#ff3b30','#ffcc00','#34c759','#23a9bd','#0a84ff','#ff2d55'];

  const DROPPER='<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m2 22 1-1h3l9-9"/><path d="M3 21v-3l9-9"/><path d="m15 6 3.4-3.4a2.1 2.1 0 1 1 3 3L18 9l.4.4a2.1 2.1 0 1 1-3 3l-3.8-3.8a2.1 2.1 0 1 1 3-3l.4.4Z"/></svg>';

  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};

  class ColorPicker{
    constructor(opts={}){
      this.opts=opts;
      this.hex=toHex(parseHex(opts.value)||{r:255,g:255,b:255});
      this.hsva=hexToHsv(this.hex);
      this.open=false;this.morphing=false;this.dragging=null;this.lastEmit=this.hex;this.dirty=false;this.frame=0;this.commitTimer=0;
      this.build();
      registry.add(this);
      this.render({animate:false});
    }

    /* ---------- DOM ---------- */
    build(){
      const id=`cp-${Math.random().toString(36).slice(2,8)}`;
      this.root=node('div','cp');
      this.trigger=node('button','cp-trigger');
      this.trigger.type='button';
      this.trigger.setAttribute('aria-haspopup','dialog');
      this.trigger.setAttribute('aria-expanded','false');
      this.trigger.setAttribute('aria-label',this.opts.label||'选择颜色');
      this.socket=node('span','cp-socket');
      this.chip=node('span','cp-chip');
      this.socket.append(this.chip);
      this.valueLabel=node('span','cp-value',this.hex);
      this.trigger.append(this.socket,this.valueLabel);
      this.root.append(this.trigger);

      this.layer=node('div','cp-layer');
      this.panel=node('div','cp-panel');
      this.panel.tabIndex=-1;
      this.panel.setAttribute('role','dialog');
      this.panel.setAttribute('aria-modal','false');
      this.panel.setAttribute('aria-label',`${this.opts.label||'颜色'}选择器`);
      this.panel.id=`${id}-panel`;
      this.panel.hidden=true;
      this.trigger.setAttribute('aria-controls',this.panel.id);

      // 饱和度 / 亮度区
      this.area=node('div','cp-area cp-stagger');
      this.area.style.setProperty('--cp-i','0');
      this.area.tabIndex=0;
      this.area.setAttribute('role','slider');
      this.area.setAttribute('aria-roledescription','2D 滑杆');
      this.area.setAttribute('aria-label','饱和度与亮度');
      this.area.setAttribute('aria-valuemin','0');
      this.area.setAttribute('aria-valuemax','100');
      this.areaThumb=this.buildThumb('area');
      this.spectrum=node('div','cp-spectrum');
      this.spectrum.append(this.areaThumb);
      this.area.append(this.spectrum);

      // 色相滑杆
      this.hue=node('div','cp-slider cp-stagger');
      this.hue.style.setProperty('--cp-i','1');
      this.hue.tabIndex=0;
      this.hue.setAttribute('role','slider');
      this.hue.setAttribute('aria-label','色相');
      this.hue.setAttribute('aria-valuemin','0');
      this.hue.setAttribute('aria-valuemax','360');
      this.hueThumb=this.buildThumb('hue');
      this.hue.append(this.hueThumb);

      // 十六进制 + 吸管
      this.hexRow=node('div','cp-hex-row cp-stagger');
      this.hexRow.style.setProperty('--cp-i','2');
      this.hexInput=node('input','cp-hex');
      this.hexInput.type='text';this.hexInput.maxLength=7;this.hexInput.autocomplete='off';this.hexInput.spellcheck=false;
      this.hexInput.setAttribute('aria-label','十六进制颜色值');
      this.hexInput.value=this.hex.slice(1).toUpperCase();
      this.dropper=node('button','cp-dropper');
      this.dropper.type='button';this.dropper.title='从屏幕取色';this.dropper.setAttribute('aria-label','从屏幕取色');
      this.dropper.innerHTML=DROPPER;
      if(!window.EyeDropper)this.dropper.hidden=true;
      this.hexRow.append(node('span','cp-hash','#'),this.hexInput,this.dropper);

      // 预设色
      this.presets=node('div','cp-presets cp-stagger');
      this.presets.style.setProperty('--cp-i','3');
      this.presets.setAttribute('role','group');
      this.presets.setAttribute('aria-label','常用颜色');
      this.ring=node('span','cp-ring');
      this.presetButtons=PRESETS.map(hex=>{
        const b=node('button','cp-preset');
        b.type='button';b.style.setProperty('--cp-color',hex);
        b.setAttribute('aria-label',`设为 ${hex}`);
        b.onclick=()=>{this.apply(hexToHsv(hex),{live:true});this.commit();};
        return b;
      });
      this.presets.append(...this.presetButtons,this.ring);

      this.panel.append(this.area,this.hue,this.hexRow,this.presets);
      this.layer.append(this.panel);
      document.body.append(this.layer);

      this.bind();
    }
    buildThumb(kind){
      const thumb=node('span',`cp-thumb cp-thumb-${kind}`);
      thumb.append(node('span','cp-dot'));
      const loupe=node('span','cp-loupe');
      const body=node('span','cp-loupe-body');
      body.append(node('span','cp-loupe-fill'));
      loupe.append(body);
      thumb.append(loupe);
      thumb.loupeBody=body;
      return thumb;
    }

    /* ---------- 事件 ---------- */
    bind(){
      this.trigger.onclick=()=>{this.open?this.close():this.show();};
      this.panel.addEventListener('keydown',e=>{
        if(e.key==='Escape'){e.preventDefault();e.stopPropagation();this.close(true);}
        else if(e.key==='Tab'){/* 让焦点在面板内自然流动 */}
      });
      this.area.addEventListener('keydown',e=>this.onAreaKey(e));
      this.hue.addEventListener('keydown',e=>this.onHueKey(e));
      this.onDocPointer=e=>{if(!this.open)return;if(this.panel.contains(e.target)||this.root.contains(e.target))return;this.close(false);};
      this.onReflow=()=>{if(this.open&&!this.morphing)this.position();};
      document.addEventListener('pointerdown',this.onDocPointer,true);
      window.addEventListener('resize',this.onReflow);
      window.addEventListener('scroll',this.onReflow,true);
      this.drag(this.area,'area');
      this.drag(this.hue,'hue');
      this.hexInput.addEventListener('input',()=>this.onHexInput());
      this.hexInput.addEventListener('change',()=>this.onHexCommit());
      this.hexInput.addEventListener('blur',()=>this.onHexCommit());
      this.hexInput.addEventListener('keydown',e=>{
        if(e.isComposing||e.keyCode===229)return;
        this.panel.dataset.input='keyboard';
        if(e.key==='Enter'){e.preventDefault();this.onHexCommit();this.hexInput.blur();}
        else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();this.close(true);}
      });
      this.dropper.onclick=async e=>{
        e.preventDefault();
        try{const result=await new window.EyeDropper().open();if(result&&result.sRGBHex){this.apply(hexToHsv(result.sRGBHex),{live:true});this.commit();}}catch(_){/* 用户取消 */}
      };
    }

    /* ---------- 指针拖动 ---------- */
    drag(target,kind){
      const thumb=kind==='area'?this.areaThumb:this.hueThumb;
      const move=e=>{this.point(target,kind,e);};
      target.addEventListener('pointerdown',e=>{
        if(e.button!==0)return;
        e.preventDefault();
        this.dragging=kind;this.touched=false;
        this.panel.dataset.input='pointer';
        target.setPointerCapture?.(e.pointerId);
        target.classList.add('is-dragging');
        thumb.classList.add('is-dragging');
        this.velocity={s:this.hsva.s,t:performance.now(),prev:kind==='area'?this.hsva.s:this.hsva.h};
        target.focus({preventScroll:true});
        this.point(target,kind,e);
      });
      target.addEventListener('pointermove',e=>{if(this.dragging===kind)move(e);});
      const end=e=>{
        if(this.dragging!==kind)return;
        const touched=this.touched;
        this.dragging=null;
        target.releasePointerCapture?.(e.pointerId);
        target.classList.remove('is-dragging');
        thumb.classList.remove('is-dragging');
        const g=G();
        if(g&&!reduced())g.to(thumb.loupeBody,{rotate:-45,duration:.32,ease:'power2.out',overwrite:true});
        else if(!g)thumb.loupeBody.style.transform='rotate(-45deg)';
        if(touched)this.commit();
      };
      target.addEventListener('pointerup',end);
      target.addEventListener('pointercancel',end);
    }
    point(target,kind,e){
      const r=target.getBoundingClientRect();
      if(!r.width)return;
      this.touched=true;
      const now=performance.now();
      if(kind==='area'){
        const s=clamp((e.clientX-r.left)/r.width*100,0,100);
        const v=clamp((1-(e.clientY-r.top)/r.height)*100,0,100);
        this.tilt(s,now);
        this.apply({h:this.hsva.h,s,v},{live:true});
      }else{
        const h=clamp((e.clientX-r.left)/r.width,0,1)*360;
        this.tilt(h,now);
        this.apply({h,s:this.hsva.s,v:this.hsva.v},{live:true});
      }
    }
    /* loupe 随拖拽速度倾斜：速度 %/s 映射 [-400,400] → [16,-16]deg */
    tilt(value,now){
      const state=this.velocity;
      if(!state){this.velocity={prev:value,t:now};return;}
      const dt=Math.max(8,now-state.t);
      const speed=(value-state.prev)/(dt/1000);
      state.prev=value;state.t=now;
      const deg=-clamp(speed,-400,400)/400*16;
      const thumb=this.dragging==='hue'?this.hueThumb:this.areaThumb;
      const g=G();
      if(g&&!reduced())g.to(thumb.loupeBody,{rotate:-45+deg,duration:.24,ease:'power2.out',overwrite:true});
      else if(!g)thumb.loupeBody.style.transform=`rotate(${(-45+deg).toFixed(2)}deg)`;
    }

    /* ---------- 键盘 ---------- */
    onAreaKey(e){
      const step=e.shiftKey?10:1;let{h,s,v}=this.hsva,handled=true;
      switch(e.key){
        case 'ArrowLeft':s-=step;break;case 'ArrowRight':s+=step;break;
        case 'ArrowUp':v+=step;break;case 'ArrowDown':v-=step;break;
        case 'PageUp':v+=10;break;case 'PageDown':v-=10;break;
        case 'Home':s=0;break;case 'End':s=100;break;
        default:handled=false;
      }
      if(!handled)return;
      e.preventDefault();e.stopPropagation();
      this.apply({h,s:clamp(s,0,100),v:clamp(v,0,100)},{live:true});
      this.queueCommit();
    }
    onHueKey(e){
      const step=e.shiftKey?10:1;let h=this.hsva.h,handled=true;
      switch(e.key){
        case 'ArrowLeft':case 'ArrowDown':h-=step;break;
        case 'ArrowRight':case 'ArrowUp':h+=step;break;
        case 'PageDown':h-=10;break;case 'PageUp':h+=10;break;
        case 'Home':h=0;break;case 'End':h=359;break;
        default:handled=false;
      }
      if(!handled)return;
      e.preventDefault();e.stopPropagation();
      this.apply({h:(h+360)%360,s:this.hsva.s,v:this.hsva.v},{live:true});
      this.queueCommit();
    }

    /* ---------- 十六进制输入 ---------- */
    onHexInput(){
      this.dirty=true;
      const rgb=parseHex(this.hexInput.value);
      if(!rgb)return;
      this.apply(rgbToHsv(rgb.r,rgb.g,rgb.b),{live:true});
    }
    onHexCommit(){
      const rgb=parseHex(this.hexInput.value);
      this.dirty=false;
      if(rgb){this.apply(rgbToHsv(rgb.r,rgb.g,rgb.b),{live:true});this.commit();return;}
      this.hexInput.value=this.hex.slice(1).toUpperCase();
      this.hexInput.classList.remove('is-invalid');
      void this.hexInput.offsetWidth;
      this.hexInput.classList.add('is-invalid');
      setTimeout(()=>this.hexInput.classList.remove('is-invalid'),340);
    }

    /* ---------- 数值应用与渲染 ---------- */
    apply(next,{live}={}){
      const hsva={h:((next.h%360)+360)%360,s:clamp(next.s,0,100),v:clamp(next.v,0,100)};
      this.hsva=hsva;
      const hex=hsvToHex(hsva);
      const changed=hex!==this.hex;
      this.hex=hex;
      if(changed||live)this.render({animate:true});
      if(changed||(live&&hex!==this.lastEmit))this.emit(hex);
    }
    emit(hex){
      if(hex===this.lastEmit)return;
      this.lastEmit=hex;
      if(!this.opts.onInput)return;
      if(this.frame)return;
      this.frame=requestAnimationFrame(()=>{this.frame=0;this.opts.onInput?.(this.hex);});
    }
    commit(){
      this.clearCommitTimer();
      this.opts.onCommit?.(this.hex);
      const event=new Event('change',{bubbles:true});
      this.root.dispatchEvent(event);
    }
    /* 键盘连按合并为一步历史：300ms 内的多次调整只提交最后一次 */
    queueCommit(){
      this.clearCommitTimer();
      this.commitTimer=setTimeout(()=>{this.commitTimer=0;this.commit();},300);
    }
    clearCommitTimer(){
      if(this.commitTimer){clearTimeout(this.commitTimer);this.commitTimer=0;return true;}
      return false;
    }
    flushCommit(){if(this.clearCommitTimer())this.commit();}
    render({animate}={}){
      const {h,s,v}=this.hsva;
      this.chip.style.setProperty('--cp-color',this.hex);
      this.trigger.setAttribute('aria-label',`${this.opts.label||'颜色'}：${this.hex}`);
      this.valueLabel.textContent=this.hex;
      if(document.activeElement!==this.hexInput||!this.dirty)this.hexInput.value=this.hex.slice(1).toUpperCase();
      this.area.style.setProperty('--cp-h',h.toFixed(2));
      this.hueThumb.style.setProperty('--cp-hue',`hsl(${h.toFixed(2)} 100% 50%)`);
      this.areaThumb.style.setProperty('--cp-color',this.hex);
      this.hueThumb.style.setProperty('--cp-color',`hsl(${h.toFixed(2)} 100% 50%)`);
      this.area.setAttribute('aria-valuenow',Math.round(s));
      this.area.setAttribute('aria-valuetext',`饱和度 ${Math.round(s)}%，亮度 ${Math.round(v)}%`);
      this.hue.setAttribute('aria-valuenow',Math.round(h));
      this.hue.setAttribute('aria-valuetext',`色相 ${Math.round(h)} 度`);
      const g=G();
      const place=(el,left,top)=>{
        if(g&&animate&&!reduced())g.to(el,{left,top,duration:.18,ease:'power2.out',overwrite:true});
        else{el.style.left=left;el.style.top=top;}
      };
      place(this.areaThumb,`${s.toFixed(2)}%`,`${(100-v).toFixed(2)}%`);
      place(this.hueThumb,`${(h/360*100).toFixed(2)}%`,'50%');
      this.renderPresets(animate);
    }
    renderPresets(animate){
      const active=this.presetButtons.findIndex(b=>b.style.getPropertyValue('--cp-color').toLowerCase()===this.hex.toLowerCase());
      this.presetButtons.forEach((b,i)=>b.setAttribute('aria-pressed',String(i===active)));
      if(active<0){this.ring.classList.remove('is-on');return;}
      const button=this.presetButtons[active];
      if(!button.offsetWidth){requestAnimationFrame(()=>{if(this.open)this.renderPresets(false)});return;}
      const g=G(),PAD=3,props={left:button.offsetLeft-PAD,top:button.offsetTop-PAD,width:button.offsetWidth+PAD*2,height:button.offsetHeight+PAD*2};
      if(g&&animate&&!reduced())g.to(this.ring,{...props,duration:.34,ease:'back.out(1.6)',overwrite:true});
      else if(g)g.set(this.ring,props);
      else Object.assign(this.ring.style,{left:props.left+'px',top:props.top+'px',width:props.width+'px',height:props.height+'px'});
      this.ring.classList.add('is-on');
    }

    /* ---------- 开合：芯片 ↔ 取色区 形变 ---------- */
    position(){
      const r=this.trigger.getBoundingClientRect();
      const width=this.panel.offsetWidth||292;
      const height=this.panel.offsetHeight||300;
      const vw=window.innerWidth,vh=window.innerHeight;
      let left=clamp(r.left,8,Math.max(8,vw-width-8));
      let top=r.bottom+8;
      if(top+height>vh-8)top=Math.max(8,r.top-8-height);
      this.panel.style.left=`${Math.round(left)}px`;
      this.panel.style.top=`${Math.round(top)}px`;
    }
    show(){
      if(this.open)return;
      registry.forEach(p=>{if(p!==this&&p.open)p.close(false);});
      this.open=true;
      this.panel.hidden=false;
      this.panel.classList.remove('is-closing','is-ready','is-veil','is-open-fallback');
      this.position();
      this.trigger.setAttribute('aria-expanded','true');
      this.socket.classList.add('is-open');
      const chipRect=this.socket.getBoundingClientRect();
      const areaRect=this.area.getBoundingClientRect();
      const g=G();
      if(!g||reduced()){
        this.panel.classList.add('is-open-fallback');
        this.settle();
        this.panel.focus({preventScroll:true});
        return;
      }
      this.morphing=true;
      const morph=node('div','cp-morph');
      morph.style.setProperty('--cp-h',this.hsva.h.toFixed(2));
      morph.style.setProperty('--cp-color',this.hex);
      const fill=node('div','cp-morph-fill');
      fill.style.setProperty('--cp-color',this.hex);
      morph.append(fill);
      this.layer.append(morph);
      g.set(morph,{left:chipRect.left,top:chipRect.top,width:chipRect.width,height:chipRect.height,borderRadius:7});
      this.timers=[];
      this.timers.push(setTimeout(()=>this.panel.classList.add('is-veil'),60));
      this.timers.push(setTimeout(()=>this.panel.classList.add('is-ready'),220));
      g.to(fill,{opacity:0,duration:.4,delay:.06,ease:'power2.out'});
      g.to(morph,{
        left:areaRect.left,top:areaRect.top,width:areaRect.width,height:areaRect.height,borderRadius:12,
        duration:.5,ease:'back.out(1.15)',
        onComplete:()=>{
          this.morphing=false;
          if(!this.open){morph.remove();return;}
          this.panel.classList.add('is-ready','is-veil');
          morph.remove();
          this.renderPresets(false);
          this.panel.focus({preventScroll:true});
        }
      });
    }
    settle(){/* 无动画路径：直接把面板交给 CSS 的最终态 */this.panel.classList.add('is-ready','is-veil');this.renderPresets(false)}
    close(refocus){
      if(!this.open)return;
      this.flushCommit();
      this.open=false;
      (this.timers||[]).forEach(clearTimeout);
      this.timers=[];
      this.panel.classList.remove('is-ready','is-veil');
      this.panel.classList.add('is-closing');
      this.trigger.setAttribute('aria-expanded','false');
      const g=G();
      const finish=()=>{
        this.panel.hidden=true;
        this.panel.classList.remove('is-closing','is-open-fallback');
        this.socket.classList.remove('is-open');
        if(refocus&&this.trigger.isConnected)this.trigger.focus({preventScroll:true});
      };
      if(!g||reduced()||this.morphing){
        this.morphing=false;
        this.layer.querySelectorAll('.cp-morph').forEach(n=>n.remove());
        finish();
        return;
      }
      const areaRect=this.area.getBoundingClientRect();
      const chipRect=this.socket.getBoundingClientRect();
      const morph=node('div','cp-morph');
      morph.style.setProperty('--cp-h',this.hsva.h.toFixed(2));
      const fill=node('div','cp-morph-fill');
      fill.style.setProperty('--cp-color',this.hex);
      fill.style.opacity='0';
      morph.append(fill);
      this.layer.append(morph);
      g.set(morph,{left:areaRect.left,top:areaRect.top,width:areaRect.width,height:areaRect.height,borderRadius:12});
      g.to(fill,{opacity:1,duration:.28,ease:'power2.out'});
      g.to(morph,{
        left:chipRect.left,top:chipRect.top,width:chipRect.width,height:chipRect.height,borderRadius:7,
        duration:.42,ease:'power3.inOut',
        onComplete:()=>{morph.remove();finish();}
      });
    }

    set(hex){
      const rgb=parseHex(hex);if(!rgb)return;
      this.hsva=rgbToHsv(rgb.r,rgb.g,rgb.b);
      this.hex=toHex(rgb);
      this.render({animate:false});
    }

    destroy(){
      if(this.commitTimer){this.flushCommit();}
      registry.delete(this);
      (this.timers||[]).forEach(clearTimeout);
      if(this.frame)cancelAnimationFrame(this.frame);
      document.removeEventListener('pointerdown',this.onDocPointer,true);
      window.removeEventListener('resize',this.onReflow);
      window.removeEventListener('scroll',this.onReflow,true);
      if(window.gsap){window.gsap.killTweensOf([this.areaThumb,this.hueThumb,this.ring]);this.layer.querySelectorAll('.cp-morph').forEach(n=>window.gsap.killTweensOf(n));}
      this.layer.remove();
      this.root.remove();
    }
  }

  window.hubColorPicker={
    mount(opts){
      const picker=new ColorPicker(opts);
      return{
        el:picker.root,
        get value(){return picker.hex;},
        set:hex=>picker.set(hex),
        destroy:()=>picker.destroy(),
        picker
      };
    },
    destroyAll(){[...registry].forEach(p=>p.destroy());},
    ColorPicker
  };
})();

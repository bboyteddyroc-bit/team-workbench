'use strict';
// Real-time preview: evaluate the same selective HSL formula in a WebGL fragment shader.
// Export remains the authoritative FFmpeg 3D LUT. If WebGL is unavailable, use the CPU path.
window.HubColorGPU=(()=>{
  let canvas,gl,program,texture,locations,failed=false;
  const vertex=`attribute vec2 p; varying vec2 uv; void main(){uv=(p+1.0)*0.5;gl_Position=vec4(p,0.,1.);}`;
  const fragment=`precision highp float;
    varying vec2 uv; uniform sampler2D image; uniform vec3 basic; uniform vec3 changes[8];
    float clamp01(float x){return clamp(x,0.0,1.0);}
    float hueToRgb(float p,float q,float t){t=mod(t+1.0,1.0);if(t<1.0/6.0)return p+(q-p)*6.0*t;if(t<0.5)return q;if(t<2.0/3.0)return p+(q-p)*(2.0/3.0-t)*6.0;return p;}
    void main(){vec4 source=texture2D(image,uv);vec3 rgb=source.rgb;
      float mx=max(max(rgb.r,rgb.g),rgb.b),mn=min(min(rgb.r,rgb.g),rgb.b),d=mx-mn,l=(mx+mn)*0.5,s=0.0,h=0.0;
      if(d>0.000001){s=l>0.5?d/(2.0-mx-mn):d/(mx+mn);if(mx==rgb.r)h=mod((rgb.g-rgb.b)/d+6.0,6.0)/6.0;else if(mx==rgb.g)h=((rgb.b-rgb.r)/d+2.0)/6.0;else h=((rgb.r-rgb.g)/d+4.0)/6.0;}
      float centers[8];centers[0]=0.0;centers[1]=30.0;centers[2]=60.0;centers[3]=120.0;centers[4]=180.0;centers[5]=240.0;centers[6]=270.0;centers[7]=315.0;
      vec3 delta=vec3(0.0);for(int i=0;i<8;i++){float distance=abs(mod(h*360.0-centers[i]+540.0,360.0)-180.0);float w=max(0.0,1.0-distance/45.0)*min(1.0,s*8.0);delta+=w*changes[i];}
      h=mod(h+delta.x*0.6/360.0+1.0,1.0);s=clamp01(s*(1.0+delta.y/100.0));l=clamp01(l+delta.z/200.0);
      if(s>0.0){float q=l<0.5?l*(1.0+s):l+s-l*s,p=2.0*l-q;rgb=vec3(hueToRgb(p,q,h+1.0/3.0),hueToRgb(p,q,h),hueToRgb(p,q,h-1.0/3.0));}else rgb=vec3(l);
      float gray=dot(rgb,vec3(0.2126,0.7152,0.0722));rgb=clamp((vec3(gray)+(rgb-vec3(gray))*(1.0+basic.z/100.0)-0.5)*(1.0+basic.y/100.0)+0.5+basic.x/200.0,0.0,1.0);
      gl_FragColor=vec4(rgb,source.a);
    }`;
  function init(){
    canvas=document.createElement('canvas');gl=canvas.getContext('webgl',{alpha:false,antialias:false,preserveDrawingBuffer:true});if(!gl)throw Error('WebGL unavailable');
    const compile=(type,src)=>{const s=gl.createShader(type);gl.shaderSource(s,src);gl.compileShader(s);if(!gl.getShaderParameter(s,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(s));return s;};
    program=gl.createProgram();gl.attachShader(program,compile(gl.VERTEX_SHADER,vertex));gl.attachShader(program,compile(gl.FRAGMENT_SHADER,fragment));gl.linkProgram(program);if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));gl.useProgram(program);
    const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,1,-1,-1,1,1,1]),gl.STATIC_DRAW);const p=gl.getAttribLocation(program,'p');gl.enableVertexAttribArray(p);gl.vertexAttribPointer(p,2,gl.FLOAT,false,0,0);
    texture=gl.createTexture();gl.bindTexture(gl.TEXTURE_2D,texture);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MIN_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_MAG_FILTER,gl.LINEAR);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_S,gl.CLAMP_TO_EDGE);gl.texParameteri(gl.TEXTURE_2D,gl.TEXTURE_WRAP_T,gl.CLAMP_TO_EDGE);gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL,true);
    locations={basic:gl.getUniformLocation(program,'basic'),changes:gl.getUniformLocation(program,'changes[0]')};
    canvas.addEventListener('webglcontextlost',()=>{failed=true;});
  }
  function apply(ctx,w,h,a){if(failed)return false;try{if(!gl)init();if(gl.isContextLost())return false;if(canvas.width!==w||canvas.height!==h){canvas.width=w;canvas.height=h;}gl.viewport(0,0,w,h);gl.useProgram(program);gl.bindTexture(gl.TEXTURE_2D,texture);gl.texImage2D(gl.TEXTURE_2D,0,gl.RGBA,gl.RGBA,gl.UNSIGNED_BYTE,ctx.canvas);gl.uniform3f(locations.basic,a.brightness||0,a.contrast||0,a.saturation||0);const values=[];for(const key of ['red','orange','yellow','green','cyan','blue','purple','magenta']){const c=a.hsl?.[key]||{};values.push(c.h||0,c.s||0,c.l||0);}gl.uniform3fv(locations.changes,values);gl.drawArrays(gl.TRIANGLE_STRIP,0,4);ctx.drawImage(canvas,0,0);return true;}catch(e){failed=true;console.warn('调色 GPU 预览不可用，切换到 CPU',e);return false;}}
  return {apply};
})();

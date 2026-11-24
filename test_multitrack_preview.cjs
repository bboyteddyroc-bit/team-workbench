const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');let drawn=[],videos=[],empty={};
let visibilityWrites=0;const visibleObject=(obj,initial=false)=>{let value=initial;Object.defineProperty(obj,'hidden',{get:()=>value,set:v=>{visibilityWrites++;value=v;}});return obj;};
visibleObject(empty);
const canvas=visibleObject({width:720,height:1280,getContext:()=>({fillRect(){},drawImage:v=>drawn.push(v.src),clearRect(){}})}),stage={prepend(){}},context={window:{hubEditor:{pause(){}}},document:{getElementById:id=>id==='edit-stage'?stage:empty,createElement:kind=>{

 if(kind==='canvas')return canvas;
 const handlers={};const v={dataset:{},readyState:0,seeking:false,currentTime:0,videoWidth:100,videoHeight:100,addEventListener:(k,f)=>handlers[k]=f,pause(){},play:()=>Promise.resolve(),removeAttribute(){},load(){},handlers};videos.push(v);return v;
}}};
vm.runInNewContext(fs.readFileSync('static/timeline-model.js','utf8'),context);context.HubTimeline=context.window.HubTimeline;vm.runInNewContext(fs.readFileSync('static/multitrack-preview.js','utf8'),context);const preview=context.window.hubMultitrackPreview;
const body={ratio:'9:16',tracks:[{id:'v'}],clips:[{task_id:'a',at:0,start:0,end:1,volume:1,track:'v'},{task_id:'b',at:1,start:0,end:1,volume:1,track:'v'}]};
preview.sync(body,0,false);assert.equal(videos.length,2,'next clip preloaded');videos.forEach(v=>v.readyState=2);videos[0].handlers.loadeddata();assert.ok(drawn.at(-1).includes('/a/'));
videos[1].readyState=0;preview.sync(body,1,true);assert.ok(drawn.at(-1).includes('/a/'),'hold decoded frame while next buffers');assert.equal(preview.ready(body,1),false);
videos[1].readyState=2;videos[1].handlers.loadeddata();assert.ok(drawn.at(-1).includes('/b/'));assert.equal(preview.ready(body,1),true);
body.tracks[0].muted=true;preview.sync(body,1,true);assert.equal(videos[1].volume,0);preview.pause();assert.equal(videos[1]._play,false);
console.log('Preview passed: preloads next clip, retains frame through buffer, switches decoded frame, track mute and pause.');

const count=videos.length;
preview.sync(body,.3,false);preview.sync(body,1.2,false);preview.sync(body,.4,false);
assert.equal(videos.length,count,'scrubbing across a cut reuses warm media');
const first=videos[0];let actual=.4;
Object.defineProperty(first,'currentTime',{get:()=>actual,set:value=>{actual=value;first.seeking=true;},configurable:true});
first.seeking=true;first._target=.8;first.seeking=false;
const before=drawn.length;first.handlers.seeked();
assert.ok(drawn.length>before,'decoded frame paints before starting the pending seek');
assert.equal(first.seeking,true,'latest pending target still seeks');
first.seeking=false;
const many={...body,clips:Array.from({length:12},(_,i)=>({task_id:'item'+i,at:i*4,start:0,end:2,volume:1,track:'v'}))};
preview.sync(many,0,false);const stale=videos.at(-1);let released=0;
stale.removeAttribute=()=>released++;
for(let i=1;i<12;i++)preview.sync(many,i*4,false);
assert.ok(released>0,'old media evicted from bounded cache');
console.log('Scrubbing passed: warm-cache reuse, decoded-frame display, bounded eviction.');
preview.reset();preview.sync(body,0,false);const fresh=videos.at(-2);fresh.readyState=2;let frames=10;fresh.getVideoPlaybackQuality=()=>({totalVideoFrames:frames});fresh.handlers.loadeddata();
preview.sync(body,0,true);let renders=drawn.length;preview.sync(body,.01,true);assert.equal(drawn.length,++renders,'stale frame counter does not block playback painting');
frames++;preview.sync(body,.02,true);assert.equal(drawn.length,++renders,'new decoded frame is painted');
body.clips[0].color={brightness:10};preview.sync(body,.03,true);assert.equal(drawn.length,++renders,'color change invalidates frame');
fresh.handlers.seeked();assert.equal(drawn.length,++renders,'seeked forces a fresh frame');
preview.sync(body,.03,false);assert.equal(drawn.length,++renders,'paused preview always paints');
delete fresh.getVideoPlaybackQuality;preview.sync(body,.03,true);preview.sync(body,.04,true);assert.equal(drawn.length,renders+2,'unsupported frame counters retain fallback rendering');
const writesBefore=visibilityWrites;preview.sync(body,.05,true);preview.sync(body,.06,true);assert.equal(visibilityWrites,writesBefore,'unchanged visibility does not mutate DOM every frame');
assert.equal(canvas.width,360);assert.equal(canvas.height,640);preview.pause();assert.equal(canvas.width,720);assert.equal(canvas.height,1280,'pause restores full preview resolution');
console.log('Playback painting passed: stale counter, new frame, color, seeking, pause and resolution restoration.');

(async()=>{
  const version='a'.repeat(64),original='/api/tasks/proxy-test/video';
  const probeBody={...body,clips:[{...body.clips[0],task_id:'proxy-test'}]};
  let request;
  context.fetch=async (url,options)=>{request={url,options};return {ok:true,json:async()=>({state:'ready',version})};};
  preview.reset();preview.sync(probeBody,0,true);const initial=videos.at(-1);
  assert.equal(initial.src,original);
  await new Promise(resolve=>setImmediate(resolve));
  assert.equal(request.options.headers['X-Hub-Request'],'1');
  preview.sync(probeBody,.1,true);assert.equal(videos.at(-1),initial,'do not replace during playback');
  preview.sync(probeBody,.1,false);const proxy=videos.at(-1);
  assert.equal(proxy.src,request.url+'/'+version);
  proxy.onerror();assert.equal(proxy.src,original,'proxy read error restores original');
  preview.sync(probeBody,.2,false);assert.equal(videos.at(-1),proxy,'fallback does not loop');
  console.log('Proxy selection passed: authenticated request header, no mid-play swap and original fallback.');
})().catch(e=>{console.error(e);process.exitCode=1;});

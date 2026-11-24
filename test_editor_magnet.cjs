const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const s=fs.readFileSync('static/editor.js','utf8');
const HubLayout=require('./static/timeline-layout.js');
let body,magnetOn=false;
const ctx={HubLayout,length:c=>HubLayout.len(c),__magnetValue:()=>magnetOn,project:null,source:()=>({duration:20}),
  clips:()=>ctx.project.body.clips,offset:i=>ctx.project.body.clips[i].at||0};
function load(){
  body={clips:[{task_id:'a',start:0,end:2,at:0,track:'video-main'},{task_id:'b',start:0,end:2,at:3,track:'video-main'},{task_id:'o',start:0,end:2,at:1,track:'ov'}],captions:[{start:0,end:9}],audio_clips:[{at:6,start:0,end:2,track:'audio-0'}],tracks:[{id:'video-main'},{id:'ov'},{id:'audio-0'}]};
  ctx.project={body};
}
vm.createContext(ctx);vm.runInContext('Object.defineProperty(globalThis,"magnetOn",{get:()=>__magnetValue()})',ctx);
vm.runInContext(s.slice(s.indexOf('  function timelineEntries(){'),s.indexOf('  function selectedKeys(){'))+s.slice(s.indexOf('  function laneOf('),s.indexOf('  function moveSelectionTo('))+s.slice(s.indexOf('  function trimLimits('),s.indexOf('  function beginTrim(')),ctx);
const rows=keys=>ctx.timelineEntries().filter(r=>keys.includes(r.key));
const near=(a,b,msg)=>assert.ok(Math.abs(a-b)<1e-9,`${msg||''} got ${a}, want ${b}`);
load();
near(ctx.resolveDelta(rows(['video:1']),-2),-1,'b stops against a');
near(ctx.resolveDelta(rows(['video:1']),4),4,'free space on the right');
{const d=ctx.resolveDelta(rows(['video:0']),2.5);assert.ok(d!==null&&(Math.abs(d-1)<1e-9||Math.abs(d-5)<1e-9),'a cannot land on b, got '+d);}
near(ctx.resolveDelta(rows(['video:2']),1),1,'overlay lane independent');
near(ctx.resolveDelta(rows(['caption:0']),3),3,'captions overlap freely');
near(ctx.resolveDelta(rows(['caption:0']),-5),0,'captions clamp at zero');
// dragging a 2s clip into a busy lane lands in the nearest free slot
body.clips.push({task_id:'p',start:0,end:2,at:2,track:'ov'});
near(ctx.resolveDelta(rows(['video:0']),0,new Map([['video:0','ov']])),4,'only free 2s slot is after p (4..6)');
// magnet on: main-lane moves are never blocked, they get re-packed afterwards
load();magnetOn=true;
near(ctx.resolveDelta(rows(['video:1']),-2),-2,'magnet bypass');
// trim limits
magnetOn=false;load();
near(ctx.trimLimits(body.clips[1],'start').min,0,'source start bound');
body.clips[1].at=2.5;body.clips[1].start=2;body.clips[1].end=4;
near(ctx.trimLimits(body.clips[1],'start').min,1.5,'start edge stops at neighbour a (ends 2)');
load();body.clips.push({task_id:'c',start:0,end:2,at:7,track:'video-main'});
near(ctx.trimLimits(body.clips[1],'end').max,4,'end edge stops at neighbour c (starts 7)');
magnetOn=true;near(ctx.trimLimits(body.clips[1],'end').max,20,'magnet main lane bound by source only');
console.log('Magnet checks passed: collision resolve, captions free, magnet bypass, trim limits.');
// Run with node test_editor_ripple.cjs. Q / W ripple trim: playhead decides the new edge.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/editor.js','utf8');
const code=source.slice(source.indexOf('  /* Q / W 波纹裁剪'),source.indexOf('  const shortcutActions={'));
let list=[],under=-1,trims=[],messages=[],seeks=[];
const ctx={
  videoSelection:new Set(),timelineSelection:new Set(),selected:0,position:0,expandedCompounds:new Set(),
  clips:()=>list,
  clipAtPlayhead:()=>under,
  offset:i=>list[i].at||0,
  length:c=>(c.end-c.start)/(c.speed||1),
  total:()=>Math.max(0,...list.map(c=>(c.at||0)+(c.end-c.start)/(c.speed||1))),
  seek:t=>seeks.push(t),
  fail:message=>messages.push(message),
  trim:(edge,value)=>{trims.push([edge,value]);list[ctx.selected][edge]=value;},
};
vm.createContext(ctx);vm.runInContext(code,ctx);
const reset=()=>{trims=[];messages=[];seeks=[];ctx.videoSelection=new Set();ctx.timelineSelection=new Set();ctx.selected=0;};

// Two back-to-back clips; magnet layout puts the second one at the first one's end.
list=[{task_id:'a',start:0,end:5,at:0},{task_id:'b',start:0,end:5,at:5}];
reset();ctx.position=2;under=0;
assert.equal(ctx.rippleTrim('start'),true);
assert.deepEqual(trims,[['start',2]]);
assert.deepEqual(seeks,[2]);
list=[{task_id:'a',start:0,end:5,at:0},{task_id:'b',start:0,end:5,at:5}];
reset();ctx.position=3;under=0;
assert.equal(ctx.rippleTrim('end'),true);
assert.deepEqual(trims,[['end',3]]);
console.log('Ripple checks passed: Q sets the in-point, W sets the out-point, playhead stays put.');

// Speed changes which source second the playhead maps to.
list=[{task_id:'a',start:1,end:9,at:0,speed:2},{task_id:'b',start:0,end:5,at:4}];
reset();ctx.position=1;under=0;
assert.equal(ctx.rippleTrim('end'),true);
assert.deepEqual(trims,[['end',3]]);
console.log('Speed-adjusted ripple check passed.');

// The playhead has to sit inside the clip, and at least 0.1 s has to remain.
reset();ctx.position=0;under=0;
assert.equal(ctx.rippleTrim('start'),false);
assert.equal(trims.length,0);
assert.match(messages[0],/播放头/);
reset();ctx.position=4;ctx.selected=0;under=-1;
list=[{task_id:'a',start:0,end:4,at:0},{task_id:'b',start:0,end:5,at:4}];
ctx.videoSelection=new Set([list[0]]);
ctx.position=0.04;
assert.equal(ctx.rippleTrim('start'),false);
assert.equal(trims.length,0);
assert.match(messages[0],/0\.1 秒/);
console.log('Ripple guards passed: playhead must be inside the clip, 0.1 s minimum kept.');

// A single selected clip wins when the playhead sits inside it; otherwise the playhead clip is used.
list=[{task_id:'a',start:0,end:5,at:0},{task_id:'b',start:0,end:5,at:5}];
reset();ctx.videoSelection=new Set([list[1]]);ctx.selected=1;under=0;ctx.position=7;
assert.equal(ctx.rippleTrim('end'),true);
assert.deepEqual(trims,[['end',2]]);
assert.equal(ctx.selected,1);
list=[{task_id:'a',start:0,end:5,at:0},{task_id:'b',start:0,end:5,at:5}];
reset();ctx.videoSelection=new Set([list[1]]);ctx.selected=1;under=-1;ctx.position=7;
assert.equal(ctx.rippleTrim('start'),true);
assert.deepEqual(trims,[['start',2]]);
assert.equal(ctx.selected,1);
console.log('Selection precedence passed: selected clip first, playhead clip as fallback.');

// No clips, or the playhead outside every clip, reports instead of mutating.
list=[];reset();under=-1;ctx.position=1;
assert.equal(ctx.rippleTrim('end'),false);
assert.match(messages[0],/时间轴/);
list=[{task_id:'a',start:0,end:5,at:0}];reset();under=-1;ctx.position=1;
assert.equal(ctx.rippleTrim('end'),false);
assert.match(messages[0],/播放头/);
assert.equal(trims.length,0);
console.log('Ripple empty-state checks passed.');

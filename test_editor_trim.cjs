const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const s=fs.readFileSync('static/editor.js','utf8');const code=s.slice(s.indexOf('  function beginTrim('),s.indexOf('  const waveCache='));
const events={};let commits=[],renders=0;const clip={task_id:'a',start:1,end:5};const button={draggable:true,classList:{add(){},remove(){}},style:{}};
const ctx={beginMultiVideoTrim:()=>false,videoSelection:new Set(),edgeScroll:()=>({delta:()=>0,stop(){}}),busy:false,trimmingActive:false,selected:0,project:{},position:2,window:{hubTimelineScale:40,addEventListener:(n,f)=>events[n]=f,removeEventListener:n=>delete events[n]},pause(){},renderProperties(){},offset:()=>0,source:()=>({duration:10}),boundaries:()=>[0,4],snapTime:x=>x,trimLimits:(c,e)=>{const r=c.speed||1;return e==='start'?{min:0,max:c.end-.1*r}:{min:c.start+.1*r,max:10};},dragNote:{},clips:()=>[clip],trim:(k,v)=>commits.push([k,v]),renderTimeline:()=>renders++};
vm.createContext(ctx);vm.runInContext(code,ctx);
function start(edge){commits=[];ctx.beginTrim({button:0,clientX:100,preventDefault(){},stopPropagation(){}},clip,0,edge,button);}
start('start');events.pointermove({clientX:140});assert.equal(commits.length,0);events.pointerup();assert.deepEqual(commits,[['start',2]]);assert.equal(ctx.trimmingActive,false);
start('end');events.pointermove({clientX:1000});events.pointerup();assert.deepEqual(commits,[['end',10]]);
start('start');events.pointermove({clientX:1000});events.pointerup();assert.deepEqual(commits,[['start',4.9]]);
start('end');events.pointermove({clientX:140});events.keydown({key:'Escape',preventDefault(){}});assert.equal(commits.length,0);assert.equal(button.draggable,true);assert.equal(Object.keys(events).length,0);
console.log('Trim checks passed: single commit, source bounds, minimum length, Escape cleanup.');

clip.speed=2;start('end');events.pointermove({clientX:140});events.pointerup();assert.deepEqual(commits,[['end',7]]);
start('start');events.pointermove({clientX:1000});events.pointerup();assert.equal(commits[0][1],4.8);
console.log('Speed-adjusted trim checks passed.');

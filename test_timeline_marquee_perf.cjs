const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
let down,frame,reads=0,updates=0,selected=[],seeks=0;const handlers={};
const scroller={scrollLeft:0,scrollTop:0,addEventListener:(k,f)=>down=f,focus(){},append(){},getBoundingClientRect:()=>({left:0,top:0,right:600,bottom:400}),querySelectorAll:()=>[{dataset:{timelineKey:'video:0'},classList:{contains:()=>false},getBoundingClientRect:()=>{reads++;return {left:150,top:100,width:100,height:40}}}]};
const ctx={document:{querySelector:()=>scroller,createElement:()=>({style:{},setAttribute(){},remove(){}}),getElementById:()=>({getBoundingClientRect:()=>({left:0})})},window:{hubTimelineScale:32,hubEditor:{current:()=>true,pause(){},timelineSelection:()=>selected,setTimelineSelection:x=>{selected=x;updates++},seek:()=>seeks++},addEventListener:(k,f)=>handlers[k]=f,removeEventListener:k=>delete handlers[k]},requestAnimationFrame:f=>(frame=f,1),cancelAnimationFrame(){}};
vm.runInNewContext(fs.readFileSync('static/timeline-selection.js','utf8'),ctx);
down({button:0,target:{closest:()=>null},clientX:140,clientY:90,preventDefault(){}});
handlers.pointermove({clientX:180,clientY:120});handlers.pointermove({clientX:230,clientY:150});assert.equal(updates,1);frame(16);assert.deepEqual([...selected],['video:0']);assert.equal(reads,1);const before=updates;frame(32);assert.equal(updates,before);handlers.pointerup();assert.equal(seeks,0);
selected=[];down({button:0,target:{closest:()=>null},clientX:140,clientY:90,preventDefault(){}});handlers.pointermove({clientX:230,clientY:150});handlers.pointerup();assert.deepEqual([...selected],['video:0']);assert.equal(seeks,0);
console.log('PASS marquee: cached bounds, one update per frame, unchanged selection skipped, pointerup flush');

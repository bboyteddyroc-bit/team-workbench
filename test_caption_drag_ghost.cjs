const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const s=fs.readFileSync('static/editor.js','utf8'),code=s.slice(s.indexOf('  function beginTimelineMove('),s.indexOf('  function primeThumbnail('));
function setup(count=1){
 const handlers={},ghosts=[],tracks=[{id:'a'},{id:'b'},{id:'c'}];let frame,commits=0,target='b';
 const rows=Array.from({length:count},(_,i)=>({key:'caption:'+i,item:{track:tracks[i].id,start:i,end:i+1},start:i,end:i+1}));
 const lanes=tracks.map((t,i)=>({dataset:{trackId:t.id},getBoundingClientRect:()=>({top:100+i*40})}));
 const nodes=rows.map(r=>({dataset:{timelineKey:r.key},classList:{contains:()=>false},style:{opacity:''},closest:()=>lanes.find(l=>l.dataset.trackId===r.item.track),querySelectorAll:()=>[],getBoundingClientRect:()=>({left:100,top:100,width:100,height:26}),cloneNode:()=>({style:{cssText:'',setProperty(){}},querySelectorAll:()=>[],removeAttribute(){},setAttribute(){},remove(){this.removed=true}})}));
 const ctx={busy:false,project:{body:{tracks}},commitEdits(){},primaryCaption:null,selectedKeys:()=>rows.map(r=>r.key),expandKeys:x=>x,timelineEntries:()=>rows,pause(){},position:0,rangePoints:()=>[],window:{hubTimelineScale:32,addEventListener:(n,f)=>handlers[n]=f,removeEventListener:n=>delete handlers[n]},edgeScroll:()=>({delta:()=>0,stop(){}}),requestAnimationFrame:f=>(frame=f,1),cancelAnimationFrame(){},snapEnabled:true,altHeld:false,snapSpan:x=>x,showGuide(){},dragNote:{},trimmingActive:false,suppressTimelineClick:false,setTimeout:f=>f(),document:{body:{append:n=>ghosts.push(n)},elementFromPoint:()=>({closest:()=>({dataset:{trackId:target}})})},getComputedStyle:()=>[],scroll:{querySelectorAll:q=>q.includes('multi-track')?lanes:nodes},resolveDelta:(_,x)=>x,editTimeline:f=>{commits++;f()},mark(){},render(){},setTimelineSelection(){},fail:msg=>{throw Error(msg)}};
 vm.createContext(ctx);vm.runInContext(code,ctx);
 return {ctx,rows,nodes,ghosts,handlers,commits:()=>commits,begin:()=>ctx.beginTimelineMove({button:0,target:{closest:()=>null},clientX:120,clientY:110},'caption:0',nodes[0]),move:(x,y)=>{handlers.pointermove({clientX:x,clientY:y});frame();}};
}
let t=setup();t.begin();t.move(120,150);assert.equal(t.ghosts[0].style.transform,'translate(0px,40px)');t.handlers.pointerup();assert.equal(t.rows[0].item.track,'b');assert(t.ghosts[0].removed);assert.equal(t.nodes[0].style.opacity,'');assert.equal(t.commits(),1);
t=setup(2);t.begin();t.move(152,150);assert.equal(t.ghosts.length,2);assert(t.ghosts.every(g=>g.style.transform==='translate(32px,40px)'));t.handlers.pointerup();assert.equal(t.rows[0].item.start,1);assert.equal(t.rows[1].item.start,2);assert.equal(t.rows[1].item.track,'c');assert.equal(t.commits(),1);
t=setup(2);t.begin();t.move(152,150);t.handlers.keydown({key:'Escape',preventDefault(){}});assert.equal(t.commits(),0);assert(t.ghosts.every(g=>g.removed));assert(t.nodes.every(n=>n.style.opacity===''));assert.equal(Object.keys(t.handlers).length,0);
t=setup();t.ctx.resolveDelta=()=>2;t.begin();t.move(152,150);assert.equal(t.ghosts[0].style.transform,'translate(64px,40px)');t.handlers.pointerup();assert.equal(t.rows[0].item.start,2);
t=setup();t.begin();t.handlers.pointerup();assert.equal(t.commits(),0);assert.equal(t.ghosts.length,0);
console.log('PASS drag: cross-track ghost, all-selection preview, collision landing, single commit, cancel, click without move');

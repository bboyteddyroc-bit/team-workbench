const assert=require('node:assert/strict');
const L=require('./static/timeline-layout.js');
const near=(a,b)=>assert.ok(Math.abs(a-b)<1e-6,`${a} != ${b}`);
const clip=(at,start,end,extra={})=>({task_id:'t',start,end,at,track:'video-main',...extra});

// resolveMove
const obs=[{start:4,end:6,lane:'a'}];
near(L.resolveMove([{start:0,end:2,lane:'a'}],obs,1),1);
near(L.resolveMove([{start:0,end:2,lane:'a'}],obs,3),2);     // touches the obstacle instead of overlapping
near(L.resolveMove([{start:0,end:2,lane:'a'}],obs,5),6);     // nearer to the far side
near(L.resolveMove([{start:1,end:3,lane:'a'}],obs,-5),-1);   // never before time 0
near(L.resolveMove([{start:0,end:2,lane:'b'}],obs,4),4);     // other lane is free
near(L.resolveMove([{start:0,end:2,lane:'a'},{start:2,end:3,lane:'a'}],obs,3.2),1); // group moves as one block
assert.equal(L.resolveMove([],obs,2),2);

// pack: magnet closes gaps and orders by centre
let body={clips:[clip(0,0,2),clip(5,0,3),clip(9,0,1,{track:'overlay'})]};
assert.equal(L.pack(body),true);
near(body.clips[0].at,0);near(body.clips[1].at,2);near(body.clips[2].at,9);
body={clips:[clip(0,0,2),clip(2,0,2),clip(4,0,2)]};
body.clips[0].at=3;
L.pack(body);
near(body.clips[1].at,0);near(body.clips[0].at,2);near(body.clips[2].at,4);
assert.equal(L.pack(body),false);                           // idempotent

// deoverlap pushes later clips on one track, leaves other tracks alone
body={clips:[clip(0,0,3),clip(2,0,2),clip(1,0,1,{track:'t2'})],audio_clips:[{at:0,start:0,end:4,track:'a1'},{at:3,start:0,end:2,track:'a1'}]};
assert.equal(L.deoverlap(body),true);
near(body.clips[1].at,3);near(body.clips[2].at,1);near(body.audio_clips[1].at,4);
assert.equal(L.deoverlap(body),false);

// linkage: captions / audio / overlay follow their main clip; voice items and deleted anchors do not
const a=clip(0,0,2),b=clip(2,0,3);
body={clips:[a,b,clip(2.5,0,1,{track:'overlay'})],captions:[{text:'x',start:2.5,end:3.5},{text:'v',start:2.5,end:3,voice_job_id:'j'}],audio_clips:[{at:3,start:0,end:1,track:'a1'},{at:3,start:0,end:1,source:'voice',voice_job_id:'j',track:'a2'}]};
let snap=L.snapshot(body);
body.clips.splice(0,1);L.pack(body);L.apply(body,snap);        // delete first clip: b moves 2 -> 0
near(b.at,0);near(body.captions[0].start,0.5);near(body.captions[0].end,1.5);near(body.audio_clips[0].at,1);near(body.clips[1].at,0.5);
near(body.captions[1].start,2.5);near(body.audio_clips[1].at,3);   // voice-linked items keep their own linkage

// stay: the trimmed clip keeps its own attachments, followers still ripple
const c1=clip(0,0,2),c2=clip(2,0,2);
body={clips:[c1,c2],captions:[{text:'1',start:0.5,end:1},{text:'2',start:2.5,end:3}],audio_clips:[]};
snap=L.snapshot(body);c1.end=1;L.pack(body);L.apply(body,snap,new Set([c1]));
near(body.captions[0].start,0.5);near(body.captions[1].start,1.5);near(c2.at,1);

// excluded items (selection moved by the user) are not dragged twice
const d=clip(0,0,2),cap={text:'m',start:1,end:1.5};
body={clips:[d],captions:[cap],audio_clips:[]};snap=L.snapshot(body,new Set([cap]));d.at=3;L.apply(body,snap);near(cap.start,1);

// caption anchored at a negative shift never goes below zero
const e=clip(1,0,2),cap2={text:'n',start:1.2,end:2};
body={clips:[e],captions:[cap2],audio_clips:[]};snap=L.snapshot(body);e.at=0;L.apply(body,snap);near(cap2.start,0.2);
body.captions[0]={text:'n',start:1.2,end:2};snap=L.snapshot(body);e.at=-5;L.apply(body,snap);assert.ok(body.captions[0].start>=0);
// edit(): magnet + link + de-overlap in one call, apply is idempotent per binding
const m1=clip(0,0,2),m2=clip(2,0,2);body={clips:[m1,m2],captions:[{text:'a',start:2.5,end:3}],audio_clips:[]};
L.edit(body,()=>{body.clips.splice(0,1);},{link:true,magnet:true});
near(m2.at,0);near(body.captions[0].start,0.5);
L.edit(body,()=>{},{link:true,magnet:true});near(body.captions[0].start,0.5);
console.log('Timeline layout checks passed: collision, magnet pack, de-overlap, linkage, stay/exclude rules.');

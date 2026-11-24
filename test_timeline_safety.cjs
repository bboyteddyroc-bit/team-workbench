const assert=require('node:assert/strict'),L=require('./static/timeline-layout');
const clip=(track,at)=>({track,at,start:0,end:2,speed:1});
for(const main of ['video-main','track-legacy']){
 const b={tracks:[{id:main},{id:'overlay'}],clips:[clip(main,0),clip('overlay',5)],captions:[],audio_clips:[]};
 L.edit(b,()=>b.clips.shift(),{magnet:true});
 assert.equal(L.mainTrack(b),main);
 L.edit(b,()=>{}, {magnet:true});assert.equal(b.clips[0].at,5);
 const saved=JSON.parse(JSON.stringify(b));assert.equal(L.mainTrack(saved),main);
}
const b={tracks:[{id:'video-main'}],clips:[clip('video-main',0),clip('video-main',2)],captions:[{start:2,end:3}],audio_clips:[{track:'a',at:2,start:0,end:1,locked:true},{track:'b',at:2,start:0,end:1,locked:false}]};
L.edit(b,()=>b.clips[0].speed=2,{magnet:true,link:true,preserveOrder:true});
assert.equal(b.audio_clips[0].at,2);assert.equal(b.audio_clips[1].at,1);assert.equal(b.captions[0].start,1);
b.audio_clips.push({track:'a',at:1.5,start:0,end:1,locked:false});L.deoverlap(b);assert.equal(b.audio_clips[0].at,2);assert.equal(b.audio_clips[2].at,3);
console.log('Safety passed: stable empty main incl. legacy, persisted identity, locked linkage and collision protection');

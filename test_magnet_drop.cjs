const assert=require('node:assert/strict'), fs=require('fs'), vm=require('vm');
const L=require('./static/timeline-layout.js');
const src=fs.readFileSync(__dirname+'/static/editor.js','utf8');
const from=src.indexOf('      insert:(id,track,time,range)=>{'),to=src.indexOf('\n    });paintPlayhead()',from);
assert.ok(from>=0&&to>from);const fn=src.slice(from,to).trim().replace(/^insert:/,'');
function setup(existing,magnet=true,snap=true){
 const project={body:{clips:existing,tracks:[],captions:[],audio_clips:[]}};
 project.body.tracks=[...new Set(existing.map(c=>c.track))].map(id=>({id}));let selected=-1;
 const ctx={source:()=>({duration:2}),clips:()=>project.body.clips,project,magnetOn:magnet,HubLayout:L,crypto:{randomUUID:()=> 'new'},pause(){},position:0, boundaries:()=>existing.flatMap(c=>[c.at,c.at+L.len(c)]),snapSpan:(a,b,points)=>{if(!snap)return a;let best=null,d=.25;for(const p of points)for(const edge of [a,b])if(Math.abs(p-edge)<d){d=Math.abs(p-edge);best=a+(p-edge)}return best??a;},showGuide(){},timelineEntries:()=>project.body.clips.map(c=>({item:c,key:'video:0',start:c.at,end:c.at+L.len(c)})),laneOf:r=>r.item.track,fail:m=>{throw Error(m)},editTimeline:(fn,stay,exclude,options)=>L.edit(project.body,fn,{link:true,magnet,...options}),mark(){},render(){},revealAt(){},seek(){},offset:i=>project.body.clips[i].at,Math,Number,Set};
 Object.defineProperty(ctx,'selected',{get:()=>selected,set:v=>selected=v});vm.createContext(ctx);return {project,insert:vm.runInContext('('+fn+')',ctx)};
}
const clip=(at,track='video-main')=>({at,track,start:0,end:2,speed:1});
let t=setup([clip(0),clip(2)]);t.insert('x','video-main',2.2,null);assert.deepEqual(t.project.body.clips.map(c=>c.at),[0,4,2]);
t=setup([]);t.insert('x',null,10,null);assert.equal(t.project.body.clips[0].at,0);assert.equal(t.project.body.clips[0].track,'video-main');
t=setup([clip(0,'track-old'),clip(2,'track-old')]);t.insert('x','track-old',6,null);assert.deepEqual(t.project.body.clips.map(c=>c.at),[0,2,4]);
t=setup([clip(0)],false,false);t.insert('x','video-main',5,null);assert.equal(t.project.body.clips[1].at,5);
t=setup([clip(0)],false,true);t.insert('x','video-main',2.1,null);assert.equal(t.project.body.clips[1].at,2);
let body={tracks:[{id:'track-old'}],clips:[clip(0,'track-old'),clip(2,'track-old'),clip(4,'track-old')],captions:[{start:4.5,end:5}],audio_clips:[]};
L.edit(body,()=>{body.clips[0].speed=2;body.clips[1].speed=2},{magnet:true,link:true,preserveOrder:true});assert.deepEqual(body.clips.map(c=>c.at),[0,1,2]);assert.equal(body.captions[0].start,2.5);
body={tracks:[{id:'track-old'}],clips:[clip(0,'track-old'),clip(2,'track-old')],captions:[],audio_clips:[]};L.edit(body,()=>{body.clips[0].speed=2;body.clips[1].speed=2},{magnet:false,preserveOrder:true});assert.equal(body.clips[1].at,2);
console.log('Drop insert, snap toggle, generated main lane, batch speed ripple and linkage passed');

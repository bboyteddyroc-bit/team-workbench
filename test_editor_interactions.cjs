// Source-backed integration regressions. All media/APIs/projects are isolated in memory.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const root=__dirname,source=fs.readFileSync(path.join(root,'static/editor.js'),'utf8');
const HubLayout=require('./static/timeline-layout.js');
const model={window:{}};vm.runInNewContext(fs.readFileSync(path.join(root,'static/timeline-model.js'),'utf8'),model);const HubTimeline=model.window.HubTimeline;
function fn(name,text=source){
  const start=text.search(new RegExp('^  (?:async )?function '+name+'\\(','m'));assert.ok(start>=0,name+' exists');
  let pos=text.indexOf('(',start),parens=1;for(pos++;parens&&pos<text.length;pos++){if(text[pos]==='(')parens++;if(text[pos]===')')parens--;}
  const open=text.indexOf('{',pos);let depth=0,quote='',line=false,block=false;
  for(let i=open;i<text.length;i++){const c=text[i],n=text[i+1];
    if(line){if(c==='\n')line=false;continue;}if(block){if(c==='*'&&n==='/'){block=false;i++;}continue;}
    if(quote){if(c==='\\'){i++;continue;}if(c===quote)quote='';continue;}
    if(c==='"'||c==="'"||c==='`'){quote=c;continue;}if(c==='/'&&n==='/'){line=true;i++;continue;}if(c==='/'&&n==='*'){block=true;i++;continue;}
    if(c==='{')depth++;if(c==='}'&&--depth===0)return text.slice(start,i+1);
  }throw Error('unclosed '+name);
}
function load(ctx,names){for(const name of names)vm.runInContext(fn(name),ctx,{filename:'editor.js:'+name});}
const base=()=>({ratio:'9:16',tracks:[{id:'video-main',muted:false},{id:'audio-one',muted:false},{id:'caption-main',muted:false}],main_track:'video-main',clips:[{task_id:'fixture-video',start:0,end:4,at:0,track:'video-main',volume:1,speed:1}],captions:[],audio_clips:[],audio:null});
function make(body=base(),keys=[]){
  const nodes=new Map(),get=id=>{if(!nodes.has(id))nodes.set(id,{disabled:false,textContent:'',dataset:{}});return nodes.get(id);};let serial=0;
  const ctx={HubLayout,HubTimeline,project:{id:'fixture-project',version:1,title:'fixture',body:structuredClone(body)},selected:0,position:0,epoch:0,me:{id:'fixture-user'},dirty:true,projects:[],pendingSaves:new WeakMap(),separatingClips:new WeakSet(),timelineSelection:new Set(keys),videoSelection:new Set(),trackSelection:null,expandedCompounds:new Set(),volumeMemory:new WeakMap(),magnetOn:true,linkOn:true,primaryCaption:null,marqueeSelectionActive:true,busy:false,$:get,nodes,proxies:[],document:{querySelectorAll:()=>ctx.proxies},crypto:{randomUUID:()=>`fixture-${++serial}`},requestKey:'fixture',window:{dispatchEvent(){}},Event:function(){},scroll:{querySelectorAll:()=>[]},pause(){},commitEdits(){},mark(){ctx.marks++;},marks:0,render(){ctx.renders++;HubTimeline.migrate(ctx.project.body);},renders:0,renderProjects(){ctx.projectRenders++;},projectRenders:0,seek(t){ctx.position=t;},fail(e){ctx.error=e.message||String(e);},renderProperties(){},renderSpeed(){},paintRange(){},paintSelectionClasses(){},scheduleSelectionSync(){},announce(){},seconds:n=>Math.round(n*100)/100,source:()=>({duration:20}),pendingCommit:0,clearTimeout(){},undo:[],redo:[],lastEdit:null,panelSig:''};
  ctx.clips=()=>ctx.project?.body.clips||[];ctx.length=c=>HubTimeline.length(c);ctx.offset=i=>ctx.clips()[i]?.at??ctx.clips().slice(0,i).reduce((v,c)=>v+ctx.length(c),0);ctx.total=()=>Math.max(0,...ctx.clips().map((c,i)=>ctx.offset(i)+ctx.length(c)),...(ctx.project?.body.captions||[]).map(c=>c.end),...(ctx.project?.body.audio_clips||[]).map(c=>c.at+c.end-c.start));
  HubTimeline.migrate(ctx.project.body);vm.createContext(ctx);
  load(ctx,['timelineEntries','selectedKeys','selectedRows','expandKeys','editTimeline','setTimelineSelection','speedClips','applySpeed','appendAudioAsset','insertAudioAsset','separateSelected','save']);
  ctx.snapshot=()=>JSON.stringify({title:ctx.project.title,body:ctx.project.body});
  return ctx;
}
function history(ctx){vm.runInContext(source.match(/^  const snapshot=.*$/m)[0]+'\n'+fn('mark')+'\n'+fn('markCore')+'\n'+fn('historyStep')+'\nlastEdit=snapshot();',ctx);}
let checks=0;const passed=name=>{checks++;console.log('PASS '+name);};
async function saving(){
  const ctx=make(),a=ctx.project,b={id:'fixture-B',version:8,title:'B',body:base()};let resolve,calls=0,payload;
  ctx.api=(_,data)=>{calls++;payload=data;return new Promise(r=>resolve=r);};
  const pending=ctx.save();ctx.project=b;ctx.dirty=false;const before=JSON.stringify(b);const stale=assert.rejects(pending,/项目已切换/);
  resolve({...structuredClone(a),version:2});await stale;
  assert.equal(JSON.stringify(b),before);assert.equal(ctx.dirty,false);assert.equal(ctx.projects[0].id,a.id);assert.equal(ctx.renders,0);assert.equal(ctx.projectRenders,1);assert.equal(calls,1);assert.notEqual(payload,a);
  passed('save response cannot alter a switched project or report it as saved');
  const concurrent=make();let reply,n=0;concurrent.api=(_,data)=>{n++;return new Promise(r=>reply=r);};
  const p=concurrent.save(),q=concurrent.save();assert.equal(n,1);const target=concurrent.project;target.title='edited during save';
  reply({...structuredClone(target),title:'fixture',version:2});await Promise.all([p,q]);
  assert.equal(concurrent.project,target);assert.equal(target.title,'edited during save');assert.equal(target.version,2);assert.equal(concurrent.dirty,true);assert.equal(concurrent.pendingSaves.has(target),false);
  passed('concurrent callers share one save; intervening edits stay dirty with the returned version');
  const clean=make();const original=clean.project;clean.api=async()=>({...structuredClone(original),version:2});await clean.save();assert.equal(clean.project,original);assert.equal(clean.dirty,false);assert.equal(original.version,2);
  passed('unchanged save retains project identity and marks only that project clean');
  const reset=make();let finish;reset.api=()=>new Promise(r=>finish=r);const pendingReset=reset.save();reset.epoch++;reset.project=null;finish({id:'old'});assert.equal(await pendingReset,undefined);assert.equal(reset.project,null);assert.equal(reset.projects.length,0);
  passed('logout/reset invalidates delayed save responses');
  const failure=make();let count=0;failure.api=async()=>{count++;throw Error('unknown outcome fixture');};await assert.rejects(failure.save(),/unknown outcome/);assert.equal(count,1);assert.equal(failure.pendingSaves.has(failure.project),false);assert.equal(failure.dirty,true);
  passed('unknown save outcomes are surfaced without automatic retries');
}
async function separation(){
  for(const [name,change] of [
    ['speed',c=>c.applySpeed(2)],['volume',c=>{c.project.body.clips[0].volume=.4;}],
    ['trim',c=>{c.project.body.clips[0].end=3;}],['position',c=>{c.project.body.clips[0].at=2;}],
    ['source',c=>{c.project.body.clips[0].task_id='different-source';}],['lock',c=>{c.project.body.clips[0].locked=true;}],
    ['project',c=>{c.project={id:'another',version:9,title:'another',body:base()};}],
    ['undo replacement',c=>{c.project.body=structuredClone(c.project.body);}],
  ]){
    const ctx=make(base(),['video:0']);let resolve;ctx.api=()=>new Promise(r=>resolve=r);const button={};const p=ctx.separateSelected('vocal',button);assert.equal(button.disabled,true);change(ctx);const before=JSON.stringify(ctx.project.body);resolve({id:'fixture-audio',kind:'vocal'});await p;
    assert.equal(JSON.stringify(ctx.project.body),before,name+' must not attach/mute stale result');assert.match(ctx.error,/素材库.*变更/);assert.equal(button.disabled,false);
    passed('separation rejects stale '+name+' changes without touching the timeline');
  }
  const ctx=make(base(),['video:0']);history(ctx);let calls=0;ctx.api=async()=>{calls++;return {id:'fixture-audio',kind:'background'};};
  await ctx.separateSelected('background',{});assert.equal(calls,1);assert.equal(ctx.undo.length,1);assert.equal(ctx.renders,1);assert.equal(ctx.project.body.audio_clips.length,1);assert.equal(ctx.project.body.clips[0].volume,0);assert.equal(ctx.project.body.clips[0].audio_detached,true);
  ctx.historyStep(ctx.undo,ctx.redo);assert.equal(ctx.project.body.clips[0].volume,1);assert.equal(ctx.project.body.clips[0].audio_detached,undefined);assert.equal(ctx.project.body.audio_clips.length,0);
  ctx.historyStep(ctx.redo,ctx.undo);assert.equal(ctx.project.body.audio_clips.length,1);assert.equal(ctx.project.body.clips[0].volume,0);
  passed('one separation is one undo transaction; redo restores both audio and original mute');
  const duplicate=make(base(),['video:0']);let resolve,n=0;duplicate.api=()=>{n++;return new Promise(r=>resolve=r);};const first=duplicate.separateSelected('vocal',{});await duplicate.separateSelected('background',{});assert.equal(n,1);assert.match(duplicate.error,/正在分离/);resolve({id:'fixture-audio',kind:'vocal'});await first;assert.equal(duplicate.project.body.audio_clips.length,1);
  passed('vocal/background commands cannot launch duplicate separation for one clip');
  const limit=make(base(),['video:0']);let reply;limit.api=()=>new Promise(r=>reply=r);const p=limit.separateSelected('vocal',{});limit.project.body.audio_clips=Array.from({length:50},(_,i)=>({source:'asset',asset_id:'fixture-'+i,start:0,end:1,at:0,track:'audio-'+i,volume:1}));reply({id:'fixture-result',kind:'vocal'});await p;assert.equal(limit.project.body.audio_clips.length,50);assert.equal(limit.project.body.clips[0].volume,1);assert.equal(limit.marks,0);assert.match(limit.error,/50/);
  passed('capacity change cannot leave the original muted without inserted audio');
}
function movement(){
  const body=base();body.audio_clips=[{source:'voice',voice_job_id:'fixture-job',start:0,end:2,at:1,track:'audio-one',volume:1,locked:false,muted:false,link_captions:true}];body.captions=[{text:'linked',start:1.25,end:2.5,track:'caption-main',voice_job_id:'fixture-job'}];
  const prepare=(keys=['detached:0'])=>{const c=make(body,keys);load(c,['laneOf','resolveDelta','moveSelectionTo']);return c;};
  for(const linked of [true,false]){const c=prepare();c.linkOn=linked;const caption=c.project.body.captions[0];c.moveSelectionTo(5);assert.equal(c.project.body.audio_clips[0].at,5);assert.equal(caption.start,5.25);assert.equal(c.project.body.captions[0],caption);assert.equal(c.marks,1);}
  passed('position/nudge movement follows voice subtitles with either main-track link setting');
  const selected=prepare(['detached:0','caption:0']);selected.moveSelectionTo(5);assert.equal(selected.project.body.captions[0].start,5.25);
  const grouped=prepare();grouped.project.body.audio_clips[0].edit_group='fixture-group';grouped.project.body.captions[0].edit_group='fixture-group';grouped.moveSelectionTo(5);assert.equal(grouped.project.body.captions[0].start,5.25);
  passed('explicit or grouped subtitle selection moves exactly once');
  const independent=prepare();independent.project.body.audio_clips[0].link_captions=false;independent.moveSelectionTo(5);assert.equal(independent.project.body.captions[0].start,1.25);
  const locked=prepare();locked.project.body.captions[0].locked=true;locked.moveSelectionTo(5);assert.equal(locked.project.body.captions[0].start,1.25);
  passed('unlinked and locked subtitles are not moved automatically');
  const legacy=prepare();load(legacy,['linkedCaptions']);const audio=legacy.project.body.audio_clips[0];legacy.editTimeline(()=>{const next={...audio,at:5};legacy.linkedCaptions(audio,next);Object.assign(audio,next);},undefined,new Set([audio]));assert.equal(legacy.project.body.captions[0].start,5.25);
  passed('legacy audio drag/property linkage is not applied twice');
  const lockedLegacy=prepare();load(lockedLegacy,['linkedCaptions']);lockedLegacy.project.body.captions[0].locked=true;const oldLocked=JSON.stringify(lockedLegacy.project.body.captions[0]);lockedLegacy.linkedCaptions(lockedLegacy.project.body.audio_clips[0],{...lockedLegacy.project.body.audio_clips[0],at:5});assert.equal(JSON.stringify(lockedLegacy.project.body.captions[0]),oldLocked);
  passed('legacy audio controls respect locked linked subtitles too');
  const collision=prepare();collision.project.body.audio_clips.push({source:'asset',asset_id:'obstacle',start:0,end:2,at:3,track:'audio-one',volume:1});collision.editTimeline(()=>{collision.project.body.audio_clips[0].at=4;});const moved=collision.project.body.audio_clips[0];assert.equal(moved.at,5);assert.equal(collision.project.body.captions[0].start,5.25);
  passed('voice subtitles follow the final collision-resolved audio position');
  const trimmed=prepare();trimmed.editTimeline(()=>{trimmed.project.body.audio_clips[0].start=.5;trimmed.project.body.audio_clips[0].at=1.5;});assert.equal(trimmed.project.body.captions[0].start,1.5);assert.equal(trimmed.project.body.captions[0].end,2.5);
  passed('voice-source trim clips linked subtitles without retiming their text');
  const dragged=prepare(),listeners=new Map(),frames=new Map();let frameId=0;
  Object.assign(dragged,{dragNote:{textContent:''},trimmingActive:false,suppressTimelineClick:false,requestAnimationFrame:f=>{frames.set(++frameId,f);return frameId;},cancelAnimationFrame:id=>frames.delete(id),setTimeout:f=>f(),edgeScroll:()=>({delta:()=>0,stop(){}}),rangePoints:()=>[],snapSpan:n=>n});
  Object.assign(dragged.window,{hubTimelineScale:32,addEventListener:(name,f)=>listeners.set(name,f),removeEventListener:(name,f)=>{if(listeners.get(name)===f)listeners.delete(name);}});dragged.document.elementFromPoint=()=>({closest:()=>({dataset:{trackId:'audio-one'}})});load(dragged,['beginTimelineMove']);
  dragged.beginTimelineMove({button:0,target:{closest:()=>null},clientX:0,clientY:0,shiftKey:false,ctrlKey:false,metaKey:false},'detached:0',{style:{}});listeners.get('pointermove')({clientX:128,clientY:0});listeners.get('pointerup')();
  assert.equal(dragged.project.body.audio_clips[0].at,5);assert.equal(dragged.project.body.captions[0].start,5.25);assert.equal(listeners.size,0);
  passed('current multitrack pointer handler moves voice subtitles and cleans listeners');
}
function selectionCommands(){
  const body=base();body.clips[0].volume=.6;body.captions=[{text:'fixture',start:1,end:2,track:'caption-main'}];body.audio_clips=[{source:'asset',asset_id:'fixture-audio',start:0,end:2,at:0,track:'audio-one',volume:.4,locked:false,muted:false}];
  const prepare=keys=>{const c=make(body,keys);load(c,['toggleMute','canDeleteSelection','deleteSelection','deleteTimelineSelection','deleteTrack','renderProperties']);return c;};
  const captions=prepare(['caption:0']);assert.equal(captions.toggleMute(),false);assert.equal(captions.project.body.clips[0].volume,.6);assert.equal(captions.marks,0);assert.match(captions.error,/字幕/);
  const empty=prepare([]);assert.equal(empty.toggleMute(),false);assert.equal(empty.project.body.clips[0].volume,.6);assert.equal(empty.deleteSelection(),false);assert.equal(empty.project.body.clips.length,1);
  passed('caption-only and empty selections never mute/delete a previously selected video');
  const mixed=prepare(['video:0','detached:0','caption:0']);history(mixed);const originalTimes=JSON.stringify(mixed.timelineEntries().map(r=>[r.start,r.end]));mixed.toggleMute();assert.equal(mixed.project.body.clips[0].volume,0);assert.equal(mixed.project.body.audio_clips[0].muted,true);assert.equal(mixed.undo.length,1);assert.equal(JSON.stringify(mixed.timelineEntries().map(r=>[r.start,r.end])),originalTimes);mixed.toggleMute();assert.equal(mixed.project.body.clips[0].volume,.6);assert.equal(mixed.project.body.audio_clips[0].muted,false);assert.equal(mixed.project.body.audio_clips[0].volume,.4);
  passed('mixed selection mutes/restores video and audio together in one history step without relayout');
  const partial=prepare(['video:0','detached:0']);partial.project.body.audio_clips[0].muted=true;partial.toggleMute();assert.equal(partial.project.body.clips[0].volume,0);assert.equal(partial.project.body.audio_clips[0].muted,true);
  passed('partially muted mixed selection has one predictable all-muted target state');
  const locked=prepare(['video:0','detached:0']);locked.project.body.audio_clips[0].locked=true;const before=JSON.stringify(locked.project.body);assert.equal(locked.toggleMute(),false);assert.equal(locked.deleteSelection(),false);assert.equal(JSON.stringify(locked.project.body),before);assert.equal(locked.marks,0);assert.match(locked.error,/锁定/);
  passed('locked mixed selections block the whole mute/delete command, not just part of it');
  for(const [name,keys,counts] of [['caption',['caption:0'],[1,0,1]],['audio',['detached:0'],[1,1,0]],['mixed',['caption:0','detached:0'],[1,0,0]]]){
    const c=prepare(keys);c.proxies=[{dataset:{editAction:'edit-remove'}},{dataset:{editAction:'edit-detach'}}];c.renderProperties();assert.equal(c.proxies[0].disabled,false);assert.equal(c.proxies[1].disabled,true);assert.equal(c.$('edit-clip-fields').disabled,true);assert.equal(c.deleteSelection(),true);assert.deepEqual([c.clips().length,c.project.body.captions.length,c.project.body.audio_clips.length],counts);assert.equal(c.marks,1);passed(name+' selection enables Delete without enabling video-only controls');
  }
  const batch=prepare(['video:0','video:1']);batch.project.body.clips.push({...batch.clips()[0],task_id:'second',at:4});batch.proxies=[{dataset:{editAction:'edit-remove'}},{dataset:{editAction:'edit-detach'}}];batch.renderProperties();assert.equal(batch.proxies[0].disabled,false);assert.equal(batch.proxies[1].disabled,true);batch.deleteSelection();assert.equal(batch.clips().length,0);assert.equal(batch.project.body.captions.length,1);assert.equal(batch.project.body.audio_clips.length,1);
  passed('batch-video Delete removes only selected media and is available in the toolbar');
  const legacy=prepare([]);legacy.trackSelection={kind:'detached',index:0};legacy.renderProperties();assert.equal(legacy.$('edit-remove').disabled,false);legacy.deleteSelection();assert.equal(legacy.project.body.audio_clips.length,0);assert.equal(legacy.clips().length,1);
  passed('legacy track selection uses the same Delete capability and command');
  const html=fs.readFileSync(path.join(root,'static/index.html'),'utf8');const fields=html.slice(html.indexOf('<fieldset id="edit-clip-fields"'),html.indexOf('</fieldset>',html.indexOf('<fieldset id="edit-clip-fields"')));assert.ok(!fields.includes('id="edit-remove"'));assert.ok(source.includes("$('edit-remove').onclick=deleteSelection;"));assert.match(source,/deleteSelection,\s+remove:deleteSelection,/);
  passed('Delete DOM is outside the video-only fieldset and buttons/shortcuts share one command');
}
async function dependentCallers(){
  const voiceSource=fs.readFileSync(path.join(root,'static/voice.js'),'utf8');
  for(const mode of ['switch','dirty','rejected','valid']){
    let current={id:'fixture-A',version:3,body:base()},dirty=false,posts=0,message='';const controls=new Map();
    const c={submitting:false,currentJob:null,selectedVoice:'fixture-voice',lastRequestKey:null,crypto:{randomUUID:()=> 'fixture-request'},$:id=>{if(!controls.has(id))controls.set(id,{value:id==='voice-source'?'manual':id==='voice-speed'?'1':'',checked:false});return controls.get(id);},currentText:()=> 'manual fixture text',status:text=>{message=text;},pollJob(){},updateGenerateButton(){},window:{hubEditor:{current:()=>structuredClone(current),position:()=>0,isDirty:()=>dirty,save:async()=>{if(mode==='rejected')throw Error('save unknown outcome fixture');const result=structuredClone(current);if(mode==='switch')current={id:'fixture-B',version:8,body:base()};if(mode==='dirty')dirty=true;return result;}}},api:async(url,request)=>{posts++;assert.equal(url,'/api/voice/jobs');const data=JSON.parse(request.body);assert.equal(data.project_id,'fixture-A');assert.equal(data.project_version,3);assert.equal(data.make_captions,false);return {job:{id:'mock-job'}};}};
    vm.createContext(c);vm.runInContext(fn('generate',voiceSource),c);await c.generate();assert.equal(posts,mode==='valid'?1:0);assert.equal(c.submitting,false);if(mode==='switch')assert.match(message,/已切换/);if(mode==='rejected')assert.match(message,/unknown outcome/);
    passed('voice save prerequisite '+mode+' is checked before any paid submission (mock only)');
  }
  for(const mode of ['switch before save','edit before save','switch after save','valid']){
    const c=make();let saves=0,exports=0;const target=c.project;
    c.askExportName=async()=>{if(mode==='switch before save')c.project={id:'fixture-B',version:8,title:'B',body:base()};return 'mock-export';};c.lock=()=>{};c.exportSelection=()=>null;c.toast=()=>{};c.exports=async()=>{};
    c.save=async()=>{saves++;if(mode==='switch after save')c.project={id:'fixture-B',version:8,title:'B',body:base()};c.dirty=false;return target;};
    c.api=async(url)=>{if(url==='/editor/selection-export-capability'){if(mode==='edit before save')c.project.body.clips[0].speed=2;return {selection_export:1};}assert.match(url,/\/export$/);exports++;return {};};
    const handler=source.match(/^  \$\('edit-export'\)\.onclick=.*$/m)[0];vm.runInContext(handler,c);await c.$('edit-export').onclick();assert.equal(exports,mode==='valid'?1:0);assert.equal(saves,/before save/.test(mode)?0:1);
    passed('export '+mode+' cannot reuse another project or stale selection (mock only)');
  }
}
(async()=>{await saving();await separation();movement();selectionCommands();await dependentCallers();console.log(`Editor interaction regressions passed: ${checks} checks; API/media/project writes: mocked only.`);})().catch(e=>{console.error(e.stack);process.exitCode=1;});

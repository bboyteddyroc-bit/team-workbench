// Run with node test_editor_shortcuts.cjs. Exercises the installed keydown handler together with static/shortcuts.js.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const editorSource=fs.readFileSync('static/editor.js','utf8');
const start=editorSource.indexOf("  document.addEventListener('keydown',e=>{");
const end=editorSource.indexOf("  setInterval",start);
let calls=[],prevented=0,editing=false,modal=false;
const store=new Map();
const sandbox={
  console,navigator:{platform:'Win32',userAgent:'node'},localStorage:{getItem:k=>store.has(k)?store.get(k):null,setItem:(k,v)=>store.set(k,String(v)),removeItem:k=>store.delete(k)},
  CustomEvent:class{constructor(type,init){this.type=type;Object.assign(this,init||{});}},
  window:{addEventListener(){},removeEventListener(){},dispatchEvent(){},toast(){}},
  document:{
    createElement:()=>({style:{},dataset:{},classList:{add(){},remove(){}},setAttribute(){},append(){},appendChild(){},addEventListener(){}}),
    querySelector:selector=>modal&&selector==='dialog[open]'?{}:null,
    querySelectorAll:()=>[],
    body:{append(){}},
    addEventListener:(_,fn)=>{sandbox.__handler=fn;},
  },
};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync('static/shortcuts.js','utf8'),sandbox,{filename:'shortcuts.js'});
const engine=sandbox.window.HubShortcuts;
assert.ok(engine,'shortcuts.js must publish window.HubShortcuts');
/* Record the resolved action id instead of running the timeline mutation. */
const realRun=engine.run;let ran=[];
engine.run=(id)=>{ran.push(id);return true;};
sandbox.shortcutApi=engine;
sandbox.marqueeSelectionActive=false;sandbox.timelineSelection=new Set();sandbox.trackSelection=null;
sandbox.me=true;sandbox.view='editor';sandbox.project={};sandbox.busy=false;sandbox.trimmingActive=false;
sandbox.selected=0;sandbox.clips=()=>[{}];sandbox.$=id=>({disabled:false,value:'40',click:()=>calls.push(id)});
sandbox.repeatable=new Set(['play','prevFrame','nextFrame']);
vm.runInContext(editorSource.slice(start,end),sandbox,{filename:'editor-keydown.js'});
const handler=sandbox.__handler;
assert.equal(typeof handler,'function','keydown listener must be installed');
function key(key,extra={}){
  calls=[];prevented=0;ran=[];
  const event={key,code:key===' '?'Space':(key.length===1?'Key'+key.toUpperCase():key),ctrlKey:false,metaKey:false,shiftKey:false,altKey:false,defaultPrevented:false,isComposing:false,repeat:false,
    target:{closest:selector=>editing&&/^input/.test(selector)?{}:null},stopImmediatePropagation(){},preventDefault:()=>prevented++};
  handler(Object.assign(event,extra));
  return ran;
}

assert.deepEqual(key('b',{ctrlKey:true}),['split']);
assert.deepEqual(key('z',{ctrlKey:true}),['undo']);
assert.deepEqual(key('z',{ctrlKey:true,shiftKey:true}),['redo']);
assert.deepEqual(key('y',{ctrlKey:true}),['redo']);
assert.deepEqual(key('Backspace'),['deleteSelection']);
assert.deepEqual(key(' '),['play']);
assert.deepEqual(key('e',{ctrlKey:true}),['export']);
assert.deepEqual(key('s',{ctrlKey:true}),['save']);
assert.deepEqual(key('q'),['rippleIn']);
assert.deepEqual(key('w'),['rippleOut']);
assert.deepEqual(key('=',{ctrlKey:true}),['zoomIn']);
assert.deepEqual(key('-',{ctrlKey:true}),['zoomOut']);
assert.equal(prevented,1);

editing=true;assert.deepEqual(key('Backspace'),[]);assert.equal(prevented,0);editing=false;
modal=true;assert.deepEqual(key('b',{ctrlKey:true}),[]);modal=false;
sandbox.busy=true;assert.deepEqual(key('b',{ctrlKey:true}),[]);sandbox.busy=false;
sandbox.trimmingActive=true;assert.deepEqual(key('q'),[]);sandbox.trimmingActive=false;
sandbox.view='studio';assert.deepEqual(key('Backspace'),[]);sandbox.view='editor';
assert.deepEqual(key('b',{ctrlKey:true,isComposing:true}),[]);
assert.deepEqual(key('b',{ctrlKey:true,repeat:true}),[]);
assert.deepEqual(key(' ',{repeat:true}),['play']);
console.log('Shortcut engine checks passed: mapping, input, modal, busy, trim, other view, IME, repeat.');

/* The registry itself: Q / W are rebindable, the wheel zoom row is fixed. */
const catalog=Object.fromEntries(engine.catalog.map(item=>[item.id,item]));
assert.deepEqual([...catalog.rippleIn.keys],['Q']);
assert.deepEqual([...catalog.rippleOut.keys],['W']);
assert.equal(catalog.rippleIn.group,'剪辑');
assert.equal(catalog.rippleOut.group,'剪辑');
assert.equal(catalog.zoomWheel.fixed,true);
assert.equal(catalog.zoomWheel.group,'时间轴视图');
const fixedHit=engine.resolve({key:'滚轮',ctrlKey:true,altKey:false,shiftKey:false});
assert.equal(fixedHit,null,'fixed rows must never resolve from a keyboard event');
/* Rebinding survives a reload through localStorage, and clearing restores Q / W. */
store.set('hub-shortcuts.v1',JSON.stringify({v:1,bindings:{rippleIn:['Alt+Q']}}));
vm.runInContext(fs.readFileSync('static/shortcuts.js','utf8'),sandbox,{filename:'shortcuts.js'});
const reloaded=sandbox.window.HubShortcuts;
assert.deepEqual([...reloaded.binding('rippleIn')],['Alt+Q']);
assert.deepEqual([...reloaded.binding('rippleOut')],['W']);
assert.equal(reloaded.resolve({key:'q',ctrlKey:false,altKey:false,shiftKey:false}),null);
const altHit=reloaded.resolve({key:'q',ctrlKey:false,altKey:true,shiftKey:false});
assert.equal(altHit.id,'rippleIn');assert.equal(altHit.combo,'Alt+Q');
reloaded.resetAll();
assert.deepEqual([...reloaded.binding('rippleIn')],['Q']);
console.log('Shortcut catalog checks passed: Q / W rows, fixed wheel row, persisted rebinding.');

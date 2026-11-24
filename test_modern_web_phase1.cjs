'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const source=name=>fs.readFileSync(path.join(__dirname,'static',name),'utf8');
function handler(text,marker){
  const start=text.indexOf(marker);assert.ok(start>=0,marker);
  const arrow=text.indexOf('e=>{',start);let depth=1,i=arrow+4;
  for(;depth&&i<text.length;i++){if(text[i]==='{')depth++;else if(text[i]==='}')depth--;}
  assert.equal(depth,0);return text.slice(arrow,i);
}
const cases=[
 ['search',handler(source('materials.js'),"search.addEventListener('keydown'"),()=>{
   const calls=[];const search={value:'中文候选',blur:()=>calls.push('blur')};
   return {ctx:{search,saveRecent:v=>calls.push('save:'+v),showRecent:()=>calls.push('recent'),sync:()=>calls.push('sync'),refresh:()=>calls.push('refresh'),close:()=>calls.push('close')},calls};
 }],
 ['hex',handler(source('color-picker.js'),"this.hexInput.addEventListener('keydown'"),()=>{
   const calls=[];return {ctx:{},calls,self:{panel:{dataset:{}},onHexCommit:()=>calls.push('commit'),hexInput:{blur:()=>calls.push('blur')},close:()=>calls.push('close')}};
 }],
 ['compound',handler(source('timeline-bundles.js'),'block.onkeydown='),()=>{
   const calls=[];return {ctx:{bundle:{id:'sample'},editor:{toggleCompound:id=>calls.push('toggle:'+id)}},calls};
 }],
];
let checks=0;
for(const [name,code,setup]of cases){
 for(const kind of ['composition','webkit229','enter','escape']){
  const state=setup();const fn=vm.runInNewContext('(function(){return '+code+';})',state.ctx).call(state.self);
  let prevented=0,stopped=0;
  fn({key:kind==='escape'?'Escape':'Enter',isComposing:kind==='composition',keyCode:kind==='webkit229'?229:13,preventDefault:()=>prevented++,stopPropagation:()=>stopped++});
  if(kind==='composition'||kind==='webkit229'){assert.deepEqual(state.calls,[],name+' '+kind);assert.equal(prevented,0);if(state.self)assert.deepEqual(state.self.panel.dataset,{});}
  if(kind==='enter'){assert.equal(prevented,1);assert.ok(state.calls.length>0,name+' normal Enter');}
  if(kind==='escape'&&name==='search'){assert.equal(state.ctx.search.value,'');assert.deepEqual(state.calls,['sync','refresh']);}
  if(kind==='escape'&&name==='hex'){assert.deepEqual(state.calls,['close']);assert.equal(stopped,1);}
  if(kind==='escape'&&name==='compound')assert.deepEqual(state.calls,[]);
  checks++;
 }
}
const html=source('index.html');const refs=[...html.matchAll(/href="([^\"]*account-table\.css[^\"]*)"/g)].map(m=>m[1]);
assert.deepEqual(refs,['/static/account-table.css?v=2']);checks++;
for(const [file,version]of [['materials.js','ime-safe1'],['color-picker.js','cp8-ime1'],['timeline-bundles.js','compound-cut1-ime1']]){assert.ok(html.includes(file+'?v='+version));checks++;}
console.log('PASS modern-web phase1: '+checks+' checks (actual source handlers: composition, keyCode229, Enter, Escape; CSS dedup; cache versions)');

const fs=require('fs'),vm=require('vm'),assert=require('assert');
const code=fs.readFileSync('static/editor-mobile.js','utf8');
assert(code.includes('content.append(left,right)'),'dialog content must be mounted');
const fn=code.slice(code.indexOf(' async function updateTransfer(){'),code.indexOf(' create.onclick='));
async function check(legacy){
 let calls=[];
 const context={current:{id:'old',url:'same',expires:Date.now()/1000+1800},updating:false,serial:0,authEpoch:0,selected:()=>['a','b'],create:{},applied:[],note:{textContent:''},dialog:{open:true},showConnection(){},refresh:async()=>{},Date,result:{replaceChildren(){}},revoke:{},api:async(path,data)=>{calls.push(path);if(path.endsWith('/selection')){if(legacy){let e=Error('old server');e.status=404;throw e;}return {expires:Date.now()/1000+1600};}if(path==='mobile/transfers')return {id:'new',url:'new-url',expires:Date.now()/1000+1800};return {ok:true};}};
 vm.createContext(context);vm.runInContext(fn,context);await vm.runInContext('updateTransfer()',context);
 assert.equal(context.applied.length,2);assert.equal(context.updating,false);
 if(legacy){assert.equal(context.current.id,'new');assert(calls.includes('mobile/transfers/old/revoke'));assert.match(context.note.textContent,/旧版/);}
 else{assert.equal(context.current.url,'same');assert.equal(calls.length,1);}
}
(async()=>{await check(false);await check(true);console.log('PASS stable-token update, old-live-server compatibility fallback, visible rescan warning, dialog content mounted');})().catch(e=>{console.error(e);process.exit(1)});

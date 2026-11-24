const fs=require('fs'),vm=require('vm'),assert=require('assert');
(async()=>{
 const scripts=[],window={};const context={window,document:{head:{append:s=>scripts.push(s)},createElement:()=>({remove(){}})}};
 vm.runInNewContext(fs.readFileSync('static/deferred-pages.js','utf8'),context);
 const proxy=window.hubCreativeTasks,body={isConnected:true,textContent:''};let opens=0,reference;
 proxy.setReference({id:'test'});const a=proxy.open(body),b=proxy.open(body);assert.equal(scripts.length,1);
 window.hubCreativeTasks={setReference:r=>reference=r,open:async()=>{opens++}};scripts[0].onload();await Promise.all([a,b]);assert.equal(opens,1);assert.equal(reference.id,'test');
 const other={isConnected:true,textContent:''};const failure=window.hubExceptionCenter.open(other);scripts[1].onerror();await failure;assert.match(other.textContent,/加载失败/);
 const retry=window.hubExceptionCenter.open(other);assert.equal(scripts.length,3);other.textContent='different tab';window.hubExceptionCenter={open:async()=>{throw Error('stale open')}};scripts[2].onload();await retry;
 console.log('PASS deferred pages: once-only load, latest open, reference, failure retry, stale-tab guard');
})().catch(e=>{console.error(e);process.exitCode=1});

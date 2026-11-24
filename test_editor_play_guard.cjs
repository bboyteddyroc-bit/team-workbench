// Run with node test_editor_play_guard.cjs. Guards against the AbortError banner
// "The play() request was interrupted by a call to pause()" showing up in the editor.
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync('static/editor.js','utf8');
const start=source.indexOf('function tryPlay(');
assert.ok(start>0,'tryPlay helper exists in editor.js');
const helper=source.slice(start,source.indexOf('\n',start)+1);
let failures=[];
const sandbox={fail:e=>failures.push(e),run:null};
vm.runInNewContext(helper+'\nthis.tryPlay=tryPlay;',sandbox);

// A fake media element whose play() promise hands its rejection handler back to the test.
function media(){
  const media={};media.play=()=>({catch:handler=>{media.handler=handler;}});return media;
}
const media1=media();sandbox.run=media1;vm.runInNewContext('this.tryPlay(this.run)',sandbox);
assert.equal(typeof media1.handler,'function','play() rejection is always handled');
media1.handler(Object.assign(new Error('The play() request was interrupted by a call to pause().'),{name:'AbortError'}));
assert.deepEqual(failures,[],'AbortError from a pause() race stays silent');

const media2=media();sandbox.run=media2;vm.runInNewContext('this.tryPlay(this.run)',sandbox);
const real=Object.assign(new Error('媒体格式不支持'),{name:'NotSupportedError'});
media2.handler(real);
assert.equal(failures.length,1,'real playback failure reaches the error line');
assert.equal(failures[0].message,'媒体格式不支持');

// Engines that return undefined must not throw.
sandbox.run={play:()=>undefined};
vm.runInNewContext('this.tryPlay(this.run)',sandbox);
failures=[];
// No call site may route a play() rejection straight into the error line.
assert.equal(/\.play\(\)\.catch\(fail\)/.test(source),false,'no raw play().catch(fail) left in editor.js');
assert.ok((source.match(/tryPlay\(/g)||[]).length>=5,'voice audio and detached sounds all use tryPlay');

const preview=fs.readFileSync('static/multitrack-preview.js','utf8');
assert.match(preview,/\.play\(\)\.catch\(/,'preview video playback still swallows its own rejections');
console.log('Editor play-guard checks passed: AbortError silenced, real errors reported, no raw play().catch(fail).');

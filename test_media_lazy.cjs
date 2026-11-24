'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const code=fs.readFileSync(__dirname+'/static/media-lazy.js','utf8');
let callback,observed=new Set();
class Observer{constructor(fn){callback=fn;}observe(m){observed.add(m);}unobserve(m){observed.delete(m);}}
const window={};const hiddenPlaying={paused:false,pause(){this.paused=true;}};
vm.runInNewContext(code,{window,IntersectionObserver:Observer,document:{querySelectorAll:()=>[hiddenPlaying]},Set});
function media(tag='VIDEO'){return {tagName:tag,dataset:{},events:{},isConnected:true,hiddenParent:false,loads:0,getClientRects(){return this.hiddenParent?[]:[{}];},closest(){return this.hiddenParent?{}:null;},setAttribute(k,v){this[k]=v;},addEventListener(k,fn){this.events[k]=fn;},load(){this.loads++;}};}
const m=media();window.hubMediaLazy.watch(m,'/sample.mp4');assert.equal(m.src,undefined);assert.equal(m.preload,'none');assert.equal(m.width,640);
m.hiddenParent=true;callback([{target:m,isIntersecting:true}]);assert.equal(m.src,undefined);
m.hiddenParent=false;callback([{target:m,isIntersecting:true}]);assert.equal(m.src,'/sample.mp4');assert.equal(m.loads,1);callback([{target:m,isIntersecting:true}]);assert.equal(m.loads,1);
const audio=media('AUDIO');window.hubMediaLazy.watch(audio,'/sample.mp3','none');audio.events.focus();assert.equal(audio.src,'/sample.mp3');assert.equal(audio.preload,'none');
const image=media('IMG');delete image.load;window.hubMediaLazy.watchImage(image,'/sample.gif');assert.equal(image.src,undefined);callback([{target:image,isIntersecting:true}]);assert.equal(image.src,'/sample.gif');assert.equal(image.decoding,'async');
const removed=media();window.hubMediaLazy.watch(removed,'/gone');removed.isConnected=false;window.hubMediaLazy.visibility();assert.equal(observed.has(removed),false);assert.equal(hiddenPlaying.paused,true);
const fallback={};vm.runInNewContext(code,{window:fallback,document:{},Set});const basic=media();fallback.hubMediaLazy.watch(basic,'/fallback');assert.equal(basic.src,'/fallback');assert.equal(basic.preload,'none');
const app=fs.readFileSync(__dirname+'/static/app.js','utf8'),composer=fs.readFileSync(__dirname+'/static/composer.js','utf8');assert.ok(app.includes("if($('#studio').hidden)return;"));assert.ok(composer.includes("if($('#studio').hidden)return;"));
console.log('PASS lazy media: deferred src, hidden guard, intersection, once-only load, focus, audio, cleanup, navigation pause, no-IO fallback, studio deferral');

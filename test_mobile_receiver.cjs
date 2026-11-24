'use strict';
const fs=require('fs'),vm=require('vm'),assert=require('assert');
class Node{constructor(){this.children=[];this.files=[];this.value='';this.disabled=false;this.textContent='';}append(...x){this.children.push(...x);}replaceChildren(...x){this.children=x;}click(){}remove(){}}
const nodes=Object.fromEntries(['status','files','upload','list','all','download','progress','upload-summary','download-status','refresh'].map(k=>[k,new Node()]));
let uploads=0,requests=0,mode='success',refreshTimer,records=[];
const document={hidden:false,body:new Node(),getElementById:id=>nodes[id],createElement:()=>new Node(),querySelectorAll:()=>[],addEventListener(){}};
const context={document,location:{hash:'#test-local-credential',pathname:'/mobile/'},history:{replaceState(){}},sessionStorage:{getItem(){},setItem(){}},Date,encodeURIComponent,Error,Promise,JSON,setInterval(fn){refreshTimer=fn;return 1},clearInterval(){},fetch:async()=>{requests++;return {ok:true,json:async()=>({expires:Date.now()/1000+1800,files:[]})}},XMLHttpRequest:class{constructor(){this.upload={}}open(){}setRequestHeader(){}send(){uploads++;records.push(this);if(mode==='wait')return;this.upload.onprogress({lengthComputable:true,loaded:1,total:1});this.upload.onload();if(mode==='network'){this.onerror();return;}this.status=200;this.responseText=JSON.stringify(mode==='bad-response'?{}:{id:'footage-test'});this.onload();}}};
vm.createContext(context);vm.runInContext(fs.readFileSync('static/mobile-receiver.js','utf8'),context);
const settle=async()=>{for(let i=0;i<8;i++)await Promise.resolve();};
(async()=>{
 await settle();assert.equal(nodes.files.disabled,false);assert.equal(typeof nodes.files.onchange,'function');
 nodes.files.files=[{name:'phone.mp4',size:1024}];await nodes.files.onchange();assert.equal(uploads,1);assert.match(nodes['upload-summary'].textContent,/1 条已入库/);assert.equal(nodes.files.value,'');
 mode='network';nodes.files.files=[{name:'phone.mov',size:1024}];await nodes.files.onchange();assert.equal(uploads,2);assert.match(nodes['upload-summary'].textContent,/1 条未确认或失败/);assert.equal(uploads,2,'must not auto retry');
 mode='bad-response';nodes.files.files=[{name:'phone.mp4',size:1024}];await nodes.files.onchange();assert.match(nodes['upload-summary'].textContent,/0 条已入库/);
 mode='wait';nodes.files.files=[{name:'phone.mp4',size:1024}];const waiting=nodes.files.onchange();await nodes.files.onchange();assert.equal(uploads,4,'busy guard prevents duplicates');
 const x=records.at(-1);x.status=200;x.responseText='{"id":"real-id"}';x.onload();await waiting;
 const before=uploads;nodes.files.files=[{name:'invalid.txt',size:1}];await nodes.files.onchange();assert.equal(uploads,before);assert.match(nodes['upload-summary'].textContent,/0 条已入库/);
 await refreshTimer();await settle();assert(requests>2);
 console.log('PASS phone: selection auto-uploads, duplicate guard, server-id confirmation, no network retry, invalid-file rejection, live download-list refresh');
})().catch(e=>{console.error(e);process.exit(1)});

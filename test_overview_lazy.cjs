'use strict';
const fs=require('node:fs'),assert=require('node:assert/strict'),vm=require('node:vm');
const js=fs.readFileSync(__dirname+'/static/ui-v2.js','utf8');
const start=js.indexOf('  function preview('),end=js.indexOf('  async function refresh',start);assert.ok(start>=0&&end>start);
let received;
const fn=vm.runInNewContext('('+js.slice(start,end).trim()+')',{el:()=>({setAttribute(k,v){this[k]=v;}}),window:{hubMediaLazy:{watch(v,url){received={v,url};return v;}}}});
const v=fn({id:'test123',prompt:'中文预览'},true);assert.equal(received.url,'/api/tasks/test123/video#t=0.1');assert.equal(v.controls,true);assert.equal(v.muted,true);assert.equal(v.src,undefined);assert.equal(v['aria-label'],'中文预览');
const css=fs.readFileSync(__dirname+'/static/obsidian-theme.css','utf8');assert.ok(css.includes('scrollbar-color:#65717b var(--bg-page)'));assert.ok(css.includes('@supports not (scrollbar-color:auto)'));assert.ok(css.includes('@media (forced-colors:active)'));console.log('PASS overview delegates to shared lazy loader, native controls/label/mute preserved; scrollbar standard/fallback/forced-colors rules present');

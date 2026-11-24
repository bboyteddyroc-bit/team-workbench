const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('static/editor.js','utf8'),start=source.indexOf('      reorderTrack:'),end=source.indexOf('      mute:',start);
const body={tracks:[{id:'v1'},{id:'a'},{id:'v2'}]},ctx={project:{body},position:2,commits:0,renders:0,commitEdits(){},pause(){},mark(){thisUnused=0},render(){},seek(){}};let marks=0;ctx.mark=()=>marks++;
const action=vm.runInNewContext('({'+source.slice(start,end).replace('      resizeCaption:beginCaptionTrim,','')+'})',ctx).reorderTrack;
action('v2',-1);assert.deepEqual(body.tracks.map(t=>t.id),['v1','v2','a']);assert.equal(marks,1);action('v1',-1);assert.equal(marks,1);action('v2',-1);assert.equal(body.tracks[0].id,'v2');
const view=fs.readFileSync('static/multitrack-view.js','utf8');assert(!view.slice(view.indexOf('function orderedRows'),view.indexOf('function volumeChip')).includes('.sort('));
console.log('PASS track order: adjacent move, boundary no-op, one mark, no type sorting');

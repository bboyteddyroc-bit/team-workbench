// Current voice workspace is intentionally manual-only; subtitle queries do not supply paid speech text.
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const source=fs.readFileSync('static/voice.js','utf8');
const controls={'voice-source':{value:'all'},'voice-text':{value:'  manual text  '},'voice-manual-field':{hidden:true},'voice-caption-summary':{textContent:''}};
let captions=[{text:'later',start:2},{text:'first',start:0}],selected=[0],updates=0;
const ctx={$:id=>controls[id],updateGenerateButton(){updates++;},window:{hubEditor:{current:()=>({body:{captions}}),captionSelection:()=>selected}}};
vm.createContext(ctx);vm.runInContext(source.slice(source.indexOf('  function voiceCaptions('),source.indexOf('  function updateGenerateButton(')),ctx);
assert.deepEqual(Array.from(ctx.voiceCaptions(),c=>c.text),['first','later']);assert.equal(ctx.currentText(),'manual text');
captions[1].text='edited';assert.equal(ctx.currentText(),'manual text');
controls['voice-source'].value='selected';assert.deepEqual(Array.from(ctx.voiceCaptions(),c=>c.text),['later']);assert.equal(ctx.currentText(),'manual text');
selected=[];assert.equal(ctx.voiceCaptions().length,0);assert.equal(ctx.currentText(),'manual text');
ctx.syncCaptionState();assert.equal(controls['voice-source'].value,'manual');assert.equal(controls['voice-manual-field'].hidden,false);assert.equal(updates,1);
controls['voice-text'].value='   ';assert.equal(ctx.currentText(),'');
console.log('Voice text checks passed: manual-only text, trim, subtitle query order/selection, manual panel state, empty text.');

const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function element(){return {style:{},dataset:{},classList:{add(){}},children:[],append(...items){this.children.push(...items)},replaceChildren(){this.children=[]},setAttribute(){},querySelector(){return null},querySelectorAll(){return []},focus(){},getBoundingClientRect(){return {left:0}}};}
const scroll=element(),ruler=element();scroll.clientWidth=800;const window={hubTimelineScale:32,hubEditor:{total:()=>2}};
const ctx={window,document:{querySelector:()=>scroll,getElementById:()=>ruler,createElement:element},HubTimeline:{length:c=>c.end-c.start}};
vm.runInNewContext(fs.readFileSync('static/multitrack-view.js','utf8'),ctx);
const video=element();let seek=0,move=0,select=0,suppress=false;
const actions={seekAt(){seek++},move(){move++},select(){select++},suppressed:()=>suppress};
window.hubMultitrackView.render({clips:[{track:'v',start:0,end:2,at:0}],captions:[],audio_clips:[],tracks:[{id:'v'}]},[video],[],actions);
let stopped=0;
video.onpointerdown({button:0,stopPropagation(){stopped++}});video.onclick({detail:1});assert.equal(stopped,1,'pointer selection must not bubble');assert.equal(move,1,'pointer starts the editor move/selection handler');assert.equal(select,0,'pointer click does not double-select');assert.equal(seek,0,'view delegates seek to editor actions');
video.onclick({detail:0});assert.equal(select,1,'keyboard selection works');
suppress=true;video.onclick({detail:0});assert.equal(select,1,'drag suppression blocks selection');
console.log('Multitrack interaction passed: delegated pointer selection, keyboard activation and drag suppression.');

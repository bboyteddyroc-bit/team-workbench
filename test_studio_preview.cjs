const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/composer.js','utf8');
function el(tag,_,cls){return {tag,cls,children:[],dataset:{},style:{},classList:{toggle(){},add(){}},addEventListener(){},setAttribute(){},append(...xs){this.children.push(...xs);},replaceChildren(){this.children=[];},querySelector(tag){return this.children.find(x=>x.tag===tag)||this.children.map(x=>x.querySelector(tag)).find(Boolean);},pause(){this.pauses=(this.pauses||0)+1;}};}
const mounts=[],items=['a','b','c'].map(key=>({key,state:'ready',videoUrl:'/api/assets/'+key,libtv:{id:key}}));
const context={el,previewItems:()=>items,waitStates:new Set(),$:()=>({hidden:false}),window:{hubMediaLazy:{watch:(video,url)=>mounts.push([video,url])}}};
vm.runInNewContext(source.slice(source.indexOf('function renderCompositionPreview'),source.indexOf('function refreshCompositionPreviews')),context);
const preview=el('div');context.renderCompositionPreview({},preview);
const result=preview.children[0], controls=preview.children[1];
assert.deepEqual(mounts.map(x=>x[1]),['/api/assets/a']);
controls.children[2].onclick({stopPropagation(){}});
assert.deepEqual(mounts.map(x=>x[1]),['/api/assets/a','/api/assets/b']);
assert.ok(result.children[0].querySelector('video').pauses);
context.renderCompositionPreview({},preview);assert.equal(preview.children[0],result);
controls.children[0].onclick({stopPropagation(){}});assert.equal(mounts.length,2);
items.splice(1);const single=el('div');context.renderCompositionPreview({},single);
assert.equal(mounts.at(-1)[1],'/api/assets/a');
console.log('Studio preview: inactive cards defer source, switching pauses previous, polling preserves preview and single card loads.');

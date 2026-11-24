'use strict';
// Atomic edits on existing flat compound members; no media is rendered or duplicated.
(function(root){
 const clone=v=>JSON.parse(JSON.stringify(v)),fps=24,q=t=>Math.round(t*fps)/fps;
 const lists=['clips','captions','audio_clips'];
 const span=(c,kind)=>kind==='captions'?[c.start,c.end]:[c.at,c.at+(c.end-c.start)/(kind==='clips'?(c.speed||1):1)];
 function bounds(body,id){const all=lists.flatMap(kind=>(body[kind]||[]).filter(c=>c.edit_compound===id).map(c=>span(c,kind)));if(!all.length)throw Error('复合片段不存在');return [Math.min(...all.map(x=>x[0])),Math.max(...all.map(x=>x[1]))];}
 function crop(c,kind,lo,hi,id){const [a,b]=span(c,kind),start=Math.max(a,lo),end=Math.min(b,hi);if(end-start<1e-7)return null;
  const out=clone(c);out.edit_compound=id;delete out.edit_group;
  if(kind==='captions'){
   out.start=start;out.end=end;
   if(out.words){out.words=out.words.map(w=>({...w,start:Math.max(0,w.start-(start-a)),end:Math.min(end-start,w.end-(start-a))})).filter(w=>w.end>w.start);if(!out.words.length)delete out.words;}
  }else{const speed=kind==='clips'?(c.speed||1):1;out.at=start;out.start=c.start+(start-a)*speed;out.end=Math.min(c.end,c.start+(end-a)*speed);
   if(out.end-out.start<.1-1e-7)throw Error('切点会留下不足 0.1 秒的内部素材，请稍微移动切点');
   if(kind==='audio_clips'){out.fade_in=start>a+1e-7?0:(c.fade_in||0);out.fade_out=end<b-1e-7?0:(c.fade_out||0);const sum=out.fade_in+out.fade_out,len=out.end-out.start;if(sum>len){out.fade_in*=len/sum;out.fade_out*=len/sum;}}
  }return out;
 }
 function cut(body,id,options){const [a,b]=bounds(body,id);const lo=q(options.start??a),hi=q(options.end??b),cut=options.split==null?null:q(options.split);
  if(lo<a-1e-6||hi>b+1e-6||hi-lo<1/fps-1e-7)throw Error('裁剪范围超出复合片段');
  if(cut!==null&&(cut<=a+1e-7||cut>=b-1e-7||!options.rightId))throw Error('请把播放头移到复合片段内部');
  const result={};for(const kind of lists){result[kind]=[];for(const c of body[kind]||[]){if(c.edit_compound!==id){result[kind].push(c);continue;}if(c.locked)throw Error('请先解锁复合片段内的素材');
   const ranges=cut===null?[[lo,hi,id]]:[[a,cut,id],[cut,b,options.rightId]];
   for(const [l,h,target]of ranges){const part=crop(c,kind,l,h,target);if(part)result[kind].push(part);}
  }if(kind!=='captions'&&result[kind].length>50)throw Error('分割后素材数量超过 50 段');}
  const members=lists.flatMap(k=>result[k].filter(c=>c.edit_compound===id));if(!members.length)throw Error('裁剪范围内没有素材');
  if(cut!==null&&!lists.some(k=>result[k].some(c=>c.edit_compound===options.rightId)))throw Error('切点右侧没有素材');
  return result;
 }
 function members(body,id){return Object.fromEntries(lists.map(k=>[k,clone((body[k]||[]).filter(c=>c.edit_compound===id))]));}
 function canonical(v){if(typeof v==='number')return Math.round(v*1e6)/1e6;if(Array.isArray(v))return v.map(canonical);if(v&&typeof v==='object')return Object.fromEntries(Object.keys(v).sort().map(k=>[k,canonical(v[k])]));return v;}
 function signature(body){return JSON.stringify(canonical(lists.map(k=>body[k]||[])));}
 function source(body,id){const current=members(body,id),saved=body.compound_sources?.[id];if(!saved)return current;
  const delta=bounds(current,id)[0]-bounds(saved.visible,id)[0],shift=b=>{const out=clone(b);for(const k of lists)for(const c of out[k]||[]){if(k==='captions'){c.start+=delta;c.end+=delta;}else c.at+=delta;}return out;};
  const visible=shift(saved.visible);
  if(signature(current)!==signature(visible))throw Error('内部片段已修改，请先撤销内部修改后恢复裁剪范围');
  const original=shift(saved.source);
  // Refuse stale restoration rather than overwrite newer member edits.
  return original;
 }
 function limits(body,id){return bounds(source(body,id),id);}
 function edit(body,id,options){
  const original=source(body,id),[start,end]=bounds(body,id),archives=clone(body.compound_sources||{});
  let result;
  if(options.split!=null){result=cut(body,id,options);delete archives[id];
   // Each half retains only its own source interval, so extending cannot cross the split.
   const all=cut(original,id,{split:options.split,rightId:options.rightId});
   for(const target of [id,options.rightId])archives[target]={source:members(all,target),visible:members(result,target)};
  }else{
   const trimmed=cut(original,id,{start:options.start??start,end:options.end??end});
   result=Object.fromEntries(lists.map(k=>[k,[...(body[k]||[]).filter(c=>c.edit_compound!==id),...trimmed[k]]]));
   for(const k of lists)if(result[k].length>(k==='captions'?600:50))throw Error('恢复后片段数量超过限制');
   archives[id]={source:original,visible:members(result,id)};
  }
  const live=new Set(lists.flatMap(k=>(result[k]||[]).map(c=>c.edit_compound).filter(Boolean)));for(const key of Object.keys(archives))if(!live.has(key))delete archives[key];
  result.compound_sources=archives;return result;
 }
 const api={bounds,edit,limits};if(typeof module!=='undefined')module.exports=api;root.HubCompound=api;
})(typeof window!=='undefined'?window:globalThis);

const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const busy=new Set(['queued','resolving','fetching']);
const labels={
 idle:'尚未从链接取数',queued:'已排队',resolving:'正在识别商品链接',fetching:'正在查询 Kalodata',
 ready:'已取得商品资料',failed:'取数未完成',attention:'资料待核对',unknown:'查询结果待核对',
 cancelled:'查询已取消',unsupported:'此档案无法从链接取数',
};
const stamp=t=>t?new Date(t*1000).toLocaleString('zh-CN',{hour12:false}):'';
const row=(label,value)=>value?`<div class="vc-row"><span class="vc-row-label">${label}</span><div class="vc-row-content" dir="auto">${esc(value)}</div></div>`:'';

const readyTitle=s=>s.source?.name||s.source?.category||s.source?.description?labels.ready:'已识别商品，暂无可用文字资料';
const imageMessage=s=>{
 if(s.cover_source==='manual')return '主图：人工上传（优先展示）';
 if(s.cover_source==='listing')return '主图：TikTok Shop 商品页（经 Kalodata）';
 if(s.image_state==='checking')return '正在保存商品主图';
 if(s.image_state==='missing')return '当前资料没有提供商品主图';
 if(s.image_state==='unavailable')return '主图暂未取到，可手动上传';
 return '';
};
export function mountLookup(host,goods,api,signal,onEvidence,onCover){
 const supportsCover='cover_source' in goods.lookup;
 const path=`/${encodeURIComponent(goods.id)}/lookup`;
 let state=goods.lookup,pending=false,uncertain=false,reading=false,timer,generation=0;
 const alive=()=>host.isConnected&&!signal.aborted;
 host.innerHTML='<div class="og-line"><h3>商品链接与资料</h3><div class="vc-actions" data-lookup-actions></div></div><p role="status" tabindex="-1" data-lookup-status></p><details class="og-appendix" data-lookup-detail hidden><summary>查看商品 ID 与资料来源</summary><div data-lookup-source></div></details>';
 const status=host.querySelector('[data-lookup-status]'),actions=host.querySelector('[data-lookup-actions]');
 const detail=host.querySelector('[data-lookup-detail]'),source=host.querySelector('[data-lookup-source]');
 function render(override=''){
  const focus=actions.contains(document.activeElement), data=state.source||{};
  const hint=state.error||(state.state==='idle'?(goods.can_edit?'可按商品链接补充资料；普通保存不扣费。':'由录入人或管理员发起查询。'):'');
  const title=state.state==='ready'?readyTitle(state):labels[state.state]||'取数状态待核对';
  const image=imageMessage(state);
  status.textContent=override||[title,hint,image,!supportsCover?'新版取数服务尚未启用。':null].filter(Boolean).join(' · ');
  actions.innerHTML=uncertain?'<button type="button" data-lookup-check>核对取数状态</button>':
   supportsCover&&goods.can_edit&&state.can_lookup?`<button type="button" class="primary" data-lookup-start ${pending?'disabled':''}>${state.state==='idle'?'从链接取数':'重新查询'}</button>`:'';
  if(focus)(actions.querySelector('button:not(:disabled)')||status).focus({preventScroll:true});
  detail.hidden=!state.product_id;
  source.innerHTML=state.product_id?row('TikTok Shop 商品 ID',state.product_id)+
   (/^https:\/\/(?:www\.|m\.|shop\.)?tiktok\.com\//.test(state.resolved_url||'')?`<p><a href="${esc(state.resolved_url)}" target="_blank" rel="noopener noreferrer">打开商品页 ↗</a></p>`:'')+
   (state.state==='ready'?row('资料来源',state.reused?(data.basis==='existing_detail_cache'?'Kalodata 已有商品详情（仅复用缓存字段）':'Kalodata 商品详情（复用缓存）'):'Kalodata 商品详情')+
    (data.basis==='existing_detail_cache'?row('缓存查询区间截止日',state.observed?new Date(state.observed*1000).toISOString().slice(0,10):''):row('资料日期',stamp(state.observed)))+
    row('商品名称',data.name)+row('店铺名称',data.shop)+row('类目',data.category)+row('商品描述',data.description)+
    row('商品主图',[imageMessage(state),state.cover_source==='listing'?stamp(state.cover_observed):''].filter(Boolean).join(' · '))+
    '<p class="og-note">以上为第三方记录或商品页标称，不是已核实规格。请在「商品标签与来源」核对标签。</p>':''):'';
 }
 function apply(next){
  const changed=next.id!==state.id||next.state!==state.state||next.image_state!==state.image_state||next.updated!==state.updated;
  const identity=next.product_id!==state.product_id;
  const dataReady=next.state==='ready'&&(next.id!==state.id||state.state!=='ready');
  const coverChanged=next.cover_url!==state.cover_url||next.cover_source!==state.cover_source||next.cover_observed!==state.cover_observed;
  if(uncertain&&next.id!==state.id)uncertain=false;
  state=next;
  if(changed||coverChanged||uncertain)render(uncertain?'尚未确认是否受理，请勿重复提交；可再次核对状态。':'');
  if(coverChanged)onCover?.(next,identity||dataReady);
  if(identity||dataReady)onEvidence();
 }
 function schedule(){
  clearTimeout(timer);
  if(alive()&&!uncertain&&(busy.has(state.state)||state.image_state==='checking'))timer=setTimeout(()=>void read(),2200);
 }
 async function read(){
  if(!alive()||reading)return;
  reading=true;
  const version=generation;
  try{const fresh=await api(path,undefined,signal);if(alive()&&!pending&&version===generation)apply(fresh);}
  catch(e){if(alive()&&!pending&&version===generation&&!uncertain)status.textContent='状态暂未读取到；只会刷新状态，不会重复提交。';}
  finally{reading=false;schedule();}
 }
 actions.onclick=async e=>{
  const b=e.target.closest('button');if(!b||pending||!alive())return;
  if(b.hasAttribute('data-lookup-check')){await read();return;}
  if(!goods.can_edit||!state.can_lookup||uncertain||!b.hasAttribute('data-lookup-start'))return;
  if(!confirm('按此链接识别 TikTok Shop 商品，读取该商品的资料和主图。没有可用缓存时，最多提交一次 Kalodata 商品详情查询，可能消耗 API Credits。不会重试结果未知的查询。继续？'))return;
  generation++;pending=true;render('正在登记本次查询…');
  try{
   const next=await api(path,{confirmed:true,revision:goods.revision,last_lookup_id:state.id||''});
   if(alive()){pending=false;apply(next);render();}
  }catch(e){
   if(alive()){
    pending=false;
    if(e.observed)render(e.message);
    else{uncertain=true;render('提交结果待核对，请勿再次提交。正在读取原查询状态…');void read();}
   }
  }finally{pending=false;schedule();}
 };
 render();schedule();
 signal.addEventListener('abort',()=>clearTimeout(timer),{once:true});
 return read;
}

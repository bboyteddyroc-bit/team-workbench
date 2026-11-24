import {renderReport} from './own-goods-scroll-report.js?v=scroll-report1';
export {disposeReport} from './own-goods-scroll-report.js?v=scroll-report1';
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const glyphs={fit:'◇',demand:'◌',scene:'◷',barrier:'⊖',performance:'↗',shots:'▷'};
const safeImage=url=>typeof url==='string'&&(/^https:\/\//i.test(url)||/^\/(?:api|static)\//.test(url));
const percent=row=>Number.isFinite(row.hits)&&row.total>0?Math.max(0,Math.min(100,100*row.hits/row.total)):null;
function thumb(e){
 return safeImage(e?.thumb)?`<img loading="lazy" alt="" src="${esc(e.thumb)}">`:'<span class="og-no-frame" aria-hidden="true">▷</span>';
}
function timecode(seconds){return Number.isFinite(seconds)?Math.floor(seconds/60)+':'+String(Math.floor(seconds%60)).padStart(2,'0'):'';}
const shotStyles=[
 ['前后对比',/前后对比|前后对照|before.and.after|messy to tidy/i],
 ['痛点呈现',/乱扔|乱丢|衣服.{0,6}(散落|堆积)|痛点|clothes on the floor/i],
 ['动作演示',/投篮|投掷|投进|演示|示范|demonstrat|shoot.{0,10}hoop/i],
 ['效果展示',/成果|效果展示|成品展示|result reveal/i],
 ['引导互动',/引导评论|评论区|下单|购买链接|call.to.action|comment below/i]
];
function compareShots(rows,cases){
 const byId=new Map(cases.map(v=>[v.id,v]));
 const stages=new Map();
 for(const row of rows){
  if(!stages.has(row.label))stages.set(row.label,new Map());
  const videos=stages.get(row.label);
  for(const e of row.evidence||[]){
   const key=e.video||e.case_id;
   if(!key||videos.has(key))continue;
   const sample=byId.get(e.case_id);
   videos.set(key,{...e,description:row.detail,handle:sample?.handle||row.value,
    style:shotStyles.find(([,pattern])=>pattern.test(row.detail||''))?.[0]||'其他拍法',
    views:sample?.views_snapshot,baseline:sample?.baseline});
  }
 }
 return [...stages].map(([label,videos])=>({label,value:videos.size+' 条视频',evidence:[...videos.values()]}));
}
export function dashboard(out,tools,d,state,signal){
 const methods=d.methods||[];
 const method=methods.find(m=>m.id==='__all__');
 if(!method){tools.replaceChildren();out.innerHTML='<p class="og-empty">综合报告尚未加载，请在服务更新后刷新报告。</p>';return;}
 state.method=method.id;
 const cases=(d.cases||[]).filter(v=>method.cases?.includes(v.id));
 const cards=(method.cards||[]).map(c=>{
  if(c.id==='shots')return {...c,rows:compareShots(c.rows||[],cases)};
  if(c.rows?.length||!['demand','barrier'].includes(c.id)||!cases.length)return {...c};
  const grouped=new Map();
  for(const v of cases){
   const sample=v.comments||{};
   const stage=sample.research_state||sample.ai_state;
   const status={running:'AI 正在分析评论',pending:'评论等待 AI 分析',queued:'评论等待 AI 分析',attention:'评论分析需要处理',ready:'已分析，本维度未检出可核实证据',legacy:'已有主题，尚缺本维度标注',stale:'样本已更新，标注待更新'};
   const reason=!v.included?'仅作参考，未纳入同类汇总':sample.comments||sample.replies?(status[stage]||'评论等待标注'):({queued:'评论采集已排队',running:'正在采集评论',attention:'评论采集需要处理',empty:'本次取样未取得评论'}[sample.state]||'尚无已采集的评论');
   if(!grouped.has(reason))grouped.set(reason,[]);
   grouped.get(reason).push({case_id:v.id,title:'@'+v.handle,source:'评论样本状态',text:[reason,sample.research_error||sample.ai_error||sample.error].filter(Boolean).join(' · '),url:v.url});
  }
  return {...c,rows:Array.from(grouped,([label,evidence])=>({label,value:evidence.length+' 条视频',detail:'按关联视频去重',evidence}))};
 });
 renderReport(out,tools,cards,cases,d.coverage||{},signal);
}

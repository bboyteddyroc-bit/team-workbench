const API = '/api/intelligence/script-board';
const PHASES = {opening:'开场', pain:'痛点', demo:'演示', proof:'效果证明', cta:'行动引导'};
const TABS = {videos:'全部视频', phrases:'话术组件', groups:'同结构脚本', accounts:'账号对比', archive:'文案档案'};
const METRICS = {views:'播放量', likes:'点赞率', collects:'收藏率', comments:'评论率'};
const COMPARATORS = {ge:'≥', gt:'>', le:'≤', lt:'<'};
const PAGE = 8;
const format = new Intl.NumberFormat('zh-CN',{maximumFractionDigits:1});
const searchForm = value => String(value ?? '').normalize('NFKC').toLowerCase();
const html = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[c]);
const words = value => searchForm(value).replaceAll('’',"'").match(/[\p{L}\p{N}]+(?:'[a-z]+)?/gu) || [];
const accountLabel = account => account ? '@'+account.replace(/^@/,'') : '账号未提供';
const time = value => {
  const ticks=Math.round(value*100);
  return Math.floor(ticks/6000)+':'+String(Math.floor(ticks/100)%60).padStart(2,'0')+'.'+String(ticks%100).padStart(2,'0');
};
const dated = value => typeof value==='number' && value>0 && value<253402300800 ? new Date(value*1000).toISOString().slice(0,10) : typeof value==='string' && /^\d{4}-\d\d-\d\d/.test(value) ? value.slice(0,10) : '';

function metric(row,key) {
  const value=row.metrics[key];
  if (value==null) return null;
  if (key==='views') return value;
  const views=row.metrics.views;
  return views>0 && value<=views ? value/views*100 : null;
}
function display(value,key) {
  if(value==null)return '—';
  if(key!=='views')return format.format(value)+'%';
  return value>=10000 ? format.format(value/10000)+' 万' : format.format(value);
}
function similar(a,b) {
  if (a.join(' ')===b.join(' ')) return a.length>0;
  if (a.length!==b.length || a.length<5) return false;
  const differences=a.reduce((sum,word,i)=>sum+(word!==b[i]),0);
  return differences<=Math.min(2,Math.floor(a.length/5));
}
function indexGroups(items) {
  const structures=[], phrases=[];
  const structureIndex=new Map(), phraseIndex=new Map();
  function add(index, groupList, signature, shapes, row, component) {
    const candidates=index.get(signature) || [];
    let group=candidates.find(item=>item.shapes.every((shape,i)=>similar(shape,shapes[i])));
    if(!group){
      group={id:groupList.length, shapes, items:[], phases:row.components.map(c=>c.phase), text:component?.text || row.components[0].text};
      groupList.push(group);candidates.push(group);index.set(signature,candidates);
    }
    group.items.push(component ? {row,...component} : row);
  }
  for(const row of items) {
    for(const component of row.components) {
      const shape=words(component.text);
      if(shape.length)add(phraseIndex,phrases,component.phase+':'+shape.length,[shape],row,component);
    }
    if(row.components.length>=2){
      const shapes=row.components.map(c=>words(c.text));
      if(shapes.every(s=>s.length))add(structureIndex,structures,row.components.map((c,i)=>c.phase+':'+shapes[i].length).join('|'),shapes,row);
    }
  }
  return {structures,phrases};
}
function cssLink(){
  if(document.querySelector('link[data-script-board]'))return;
  const link=document.createElement('link');
  link.rel='stylesheet';link.href='/static/script-board.css?v=1';link.dataset.scriptBoard='';document.head.append(link);
}
function action(name,label,value='',options='') {
  return `<button type="button" data-sb="${name}" data-value="${html(value)}" ${options}>${label}</button>`;
}
function selected(value){return value ? ' aria-pressed="true"' : ' aria-pressed="false"';}
function link(row){return row.url ? `<a href="${html(row.url)}" target="_blank" rel="noopener noreferrer">打开原视频 ↗</a>` : '';}
function gmv(row){
  return row.gm==null ? '—' : html((row.currency ? row.currency+' ' : '')+format.format(row.gm));
}
function stats(values){
  return `<div class="sb-stats">${values.map(([value,label])=>`<div><strong>${value}</strong><span>${label}</span></div>`).join('')}</div>`;
}
function scopeLabel(row) {
  return row.metric_source ? `<span title="${html(row.metric_source)}">${display(metric(row,'views'),'views')}</span>` : '—';
}
function table(rows,headers,klass='') {
  return `<div class="sb-table-wrap"><table class="${klass}"><thead><tr>${headers.map(h=>`<th scope="col">${h}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
}
function option(value,label,current) {
  return `<option value="${html(value)}" ${value===current?'selected':''}>${html(label)}</option>`;
}
function ruleControls(rule) {
  const {key,op,value}=rule;
  return `<div class="sb-rule"><select aria-label="指标" data-metric>${Object.entries(METRICS).map(([k,label])=>option(k,label,key)).join('')}</select>
    <select aria-label="比较方式" data-op>${Object.entries(COMPARATORS).map(([k,label])=>option(k,label,op)).join('')}</select>
    <label><input aria-label="指标数值" type="number" data-limit value="${html(value)}" min="0" step="any" required><span>${key==='views'?'次':'%'}</span></label>
    ${action('remove-rule','移除')}</div>`;
}
async function request(url){
  const response=await fetch(url,{cache:'no-store'});
  if(!response.ok)throw Object.assign(Error('读取失败'),{status:response.status});
  return response.json();
}

export function open(pane,archive){
  cssLink();
  pane.classList.add('script-board');
  pane.innerHTML=`<div class="sb-head"><h2>爆款文案库</h2>${action('refresh','刷新')}</div>
    <div class="sb-tabs" aria-label="文案库视图"></div>
    <div class="intel-direct-tools sb-tools">
      <input type="search" autocomplete="off" aria-label="搜索文案、脚本或账号" placeholder="搜索文案、脚本或账号">
      ${action('filters','指标筛选')}${action('viral','爆款规则')}${action('clear','清除筛选')}
      <div class="sb-chips" aria-live="polite"></div>
    </div><div class="sb-view"></div><dialog class="sb-dialog"></dialog>`;
  const view=pane.querySelector('.sb-view'), tools=pane.querySelector('.sb-tools');
  const tabs=pane.querySelector('.sb-tabs'), dialog=pane.querySelector('dialog'), search=tools.querySelector('input');
  let current='groups', dataset=null, index=null, loadError=false, archiveOpen=false, loading=false;
  let query='', active='', phase='opening', page=0, matchedOnly=false, expanded=false, viral=false;
  let filters={rules:[],mode:'all',account:'',days:'',reuse:'',category:''};
  let openingWindow=false;
  let detail=null, archiveTarget=null, detailRequest=0;
  const performanceFilter=()=>viral || filters.rules.length>0;
  function matches(row) {
    if(viral && !((metric(row,'views')??0)>=700000 || ((metric(row,'views')??0)>=10000 &&
      [['likes',5],['collects',.8],['comments',.15]].some(([key,threshold])=>(metric(row,key)??-1)>=threshold))))return false;
    const check=rule=>{
      const x=metric(row,rule.key), y=rule.value;
      if(x==null)return false;
      return {ge:x>=y,gt:x>y,le:x<=y,lt:x<y}[rule.op];
    };
    return !filters.rules.length || (filters.mode==='all' ? filters.rules.every(check) : filters.rules.some(check));
  }
  function scoped(ignoreAccount=false){
    const min=filters.days ? new Date(Date.parse(dataset.date)-(Number(filters.days)-1)*86400000).toISOString().slice(0,10) : '';
    const base=dataset.items.filter(row=>(ignoreAccount || !filters.account || row.account===filters.account) &&
      (!min || dated(row.published)>=min) && (!filters.category || row.category===filters.category));
    const included=new Set(base.map(r=>r.id));
    const candidates=filters.reuse ? new Set(index.structures.flatMap(group=>{
      const totals=new Map();
      const rows=group.items.filter(r=>included.has(r.id) && r.account);
      for(const r of rows)totals.set(r.account,(totals.get(r.account)||0)+1);
      return rows.filter(r=>totals.get(r.account)>=Number(filters.reuse)).map(r=>r.id);
    })) : included;
    return base.filter(row=>candidates.has(row.id) && (!query ||
      searchForm([row.description,row.account,row.category,...row.tags,...row.components.map(p=>p.text)].join(' ')).includes(query)));
  }
  function overview(groups,items){
    const ids=new Set(items.map(row=>row.id));
    return groups.map(g=>{
      const selected=g.items.filter(row=>ids.has((row.row || row).id));
      const videos=selected.map(row=>row.row || row);
      return {...g,items:selected,videoCount:videos.length,accounts:new Set(videos.map(row=>row.account).filter(Boolean)).size,passed:videos.filter(matches).length};
    }).filter(g=>g.items.length).sort((a,b)=>b.videoCount-a.videoCount || a.id-b.id);
  }
  function status(row){return performanceFilter() ? `<td><span class="sb-result ${matches(row)?'sb-hit':''}">${matches(row)?'符合':'未命中'}</span></td>` : '';}
  function pages(rows){
    const total=Math.max(1,Math.ceil(rows.length/PAGE));
    page=Math.max(0,Math.min(page,total-1));
    return {items:rows.slice(page*PAGE,(page+1)*PAGE),nav:total>1 ? `<div class="sb-pager">
      ${action('page','上一页',-1,page===0?'disabled':'')}<span>${page+1} / ${total}</span>${action('page','下一页',1,page===total-1?'disabled':'')}</div>` : ''};
  }
  function sampleTable(list,filterable=false){
    const matchCount=list.filter(matches).length;
    const filtered=filterable && matchedOnly && performanceFilter() ? list.filter(matches) : list;
    const result=pages(filtered);
    return `<section class="sb-panel sb-samples"><header><h3>${filterable?'样本视频':'全部视频'} <small>${filtered.length} 条</small></h3>
      ${filterable && performanceFilter()? `<div class="sb-options">${action('sample-scope','全部样本 · '+list.length,'all',selected(!matchedOnly))}
      ${action('sample-scope','符合指标 · '+matchCount,'matched',selected(matchedOnly))}</div>` : ''}</header>
      ${result.items.length ? table(result.items.map(row=>`<tr>
        <td>${action('video',html(row.description || '查看视频'),row.id,'class="sb-text-link sb-title"')}</td>
        <td>${html(accountLabel(row.account))}</td><td>${scopeLabel(row)}</td><td>${display(metric(row,'likes'),'likes')}</td>
        <td title="${html(row.gm_scope)}">${gmv(row)}</td><td>${dated(row.published)||'—'}</td><td>${row.has_transcript?'已有逐字稿':'待提取'}</td>${status(row)}</tr>`).join(''),
        ['发布文案','账号','播放量','点赞率','估算 GMV','发布时间','口播',...(performanceFilter()?['当前指标']:[])],'sb-video-table')
       : '<p class="sb-empty">没有符合当前筛选的视频。</p>'}${result.nav}</section>`;
  }
  function representatives(group){
    const list=group.items.filter(r=>metric(r,'views')!=null).sort((a,b)=>metric(b,'views')-metric(a,'views'));
    const positions=[0,Math.floor((list.length-1)/2),list.length-1];
    const labels=['播放最高','接近中位','播放最低'];
    return `<section class="sb-panel sb-comparison"><header><h3>代表视频对比</h3><small>按播放量取样</small></header>
     ${list.length ? `<div class="sb-shots">${positions.map((position,i)=>{
      const row=list[position];
      if(!row || positions.indexOf(position)!==i)return '';
      const component=row.components.find(c=>c.phase===phase) || row.components[0];
      const stamp=component?.start;
      const frame=row.preview && stamp!=null ? row.preview.replace(/\/preview$/,'/still')+'?ms='+Math.round(stamp*1000) : '';
      return `<article class="sb-shot">
        ${action('video',`${frame||row.cover?`<img loading="lazy" alt="" src="${html(frame||row.cover)}" data-cover="${html(frame ? row.cover : '')}">`:''}<span>${stamp==null?'查看口播':time(stamp)}</span>`,row.id,'class="sb-media" data-phase="'+component.phase+'"')}
        <div><h4>${labels[i]}</h4><div class="sb-shot-stats"><span><small>播放量</small><strong>${scopeLabel(row)}</strong></span>
        <span><small>点赞率</small><strong>${display(metric(row,'likes'),'likes')}</strong></span></div>
        <p title="${html(component?.text)}">${html(component?.text || row.description)}</p><small>${html(accountLabel(row.account))}</small></div></article>`;
     }).join('')}</div>` : '<p class="sb-empty">这组视频暂缺播放量。</p>'}</section>`;
  }
  function accountRows(list) {
    const counts=new Map();
    for(const row of list){
      const account=row.account || '';
      if(!counts.has(account))counts.set(account,[]);
      counts.get(account).push(row);
    }
    return [...counts].sort((a,b)=>b[1].length-a[1].length);
  }
  function groupHTML(items){
    const groups=overview(index.structures,items);
    if(!groups.length)return `<section class="sb-panel sb-empty">当前范围还没有具备两个以上口播环节的脚本组。${action('tab','查看已收录视频','videos','class="sb-text-link"')}</section>${sampleTable(items.filter(matches))}`;
    const group=groups.find(g=>'g'+g.id===active)||groups[0];
    active='g'+group.id;
    const summary=group.phases.map(p=>PHASES[p]).join(' → ');
    const accounts=accountRows(group.items);
    const accountCells=(label,records)=>`<tr><td>${label}</td><td><div class="sb-meter">${records.length} 条
      <span aria-hidden="true"><i style="width:${100*records.length/group.videoCount}%"></i></span></div></td>
      <td>${performanceFilter()?records.filter(matches).length+' 条':'—'}</td></tr>`;
    const short=expanded?accounts:accounts.slice(0,2);
    const extra=expanded?[]:accounts.slice(2);
    const lead=group.items.find(r=>r.components.some(c=>c.phase===phase));
    const example=lead?.components.find(c=>c.phase===phase);
    const shown=groups.slice(0,40);
    return `<div class="sb-top"><section class="sb-panel sb-group-list">${table(shown.map(g=>`<tr ${g===group?'class="sb-selected"':''}>
      <td>${action('group',html(g.text),'g'+g.id,'class="sb-text-link sb-title"')}<small>${g.phases.map(p=>PHASES[p]).join(' → ')}</small></td>
      <td>${g.videoCount} 条</td><td>${g.accounts} 个</td><td>${performanceFilter()?g.passed+' / '+g.videoCount:'—'}</td></tr>`).join(''),
      ['脚本组','使用视频','账号数','符合指标'])}${groups.length>shown.length?`<p class="sb-empty">显示前 ${shown.length} 组，共 ${groups.length} 组，可搜索其余脚本。</p>`:''}</section>
    <section class="sb-panel sb-detail"><h3>${html(group.text)}</h3><small class="sb-route">${summary}</small>
      ${stats([[group.videoCount+' 条','使用视频'],[group.accounts+' 个','独立账号'],[performanceFilter()?group.passed+' / '+group.videoCount:'—','符合指标']])}
      <div class="sb-steps">${Object.entries(PHASES).map(([key,label])=>action('phase',label,key,(group.phases.includes(key)?'':'disabled')+selected(phase===key))).join('')}</div>
      ${example?`<p class="sb-quote">${html(example.text)} ${action('video',example.start==null?'查看口播':time(example.start),lead.id,'class="sb-text-link"')}</p>`:''}
      <header><h3>按账号展开</h3>${accounts.length>2?action('expand',expanded?'收起':'展开全部','','class="sb-text-link"'):''}</header>
      ${table(short.map(([name,records])=>accountCells(name?action('account',html(accountLabel(name)),name,'class="sb-text-link"'):html(accountLabel(name)),records)).join('')+
        (extra.length?accountCells(action('expand','其他 '+extra.length+' 个账号','','class="sb-text-link"'),extra.flatMap(([,records])=>records)):''),['账号','使用','符合'])}
    </section></div>
    ${representatives(group)}${sampleTable([...group.items].sort((a,b)=>(metric(b,'views')??-1)-(metric(a,'views')??-1)),true)}`;
  }
  function phraseHTML(items){
    let entries=index.phrases.filter(g=>g.items[0].phase===phase);
    if(phase==='opening' && openingWindow)entries=entries.map(g=>({...g,items:g.items.filter(entry=>entry.start!=null && entry.start<3)}));
    const groups=overview(entries,items);
    const group=groups.find(g=>'p'+g.id===active)||groups[0];
    const buttons=`<div class="sb-steps">${Object.entries(PHASES).map(([key,label])=>action('phase',label,key,selected(phase===key))).join('')}</div>
      ${phase==='opening'?`<div class="sb-options">${action('opening-window','仅看前 3 秒','','title="仅统计有时间证据的原句"'+selected(openingWindow))}</div>`:''}`;
    if(!group)return buttons+'<p class="sb-panel sb-empty">这个环节还没有可核实的口播。</p>';
    active='p'+group.id;
    const variants=new Map();
    for(const entry of group.items){
      if(!variants.has(entry.text))variants.set(entry.text,[]);
      variants.get(entry.text).push(entry);
    }
    return buttons+`<div class="sb-top"><section class="sb-panel sb-group-list">${table(groups.slice(0,40).map(g=>`<tr class="${g===group?'sb-selected':''}"><td>${action('phrase',html(g.text),'p'+g.id,'class="sb-text-link sb-title"')}</td>
      <td>${g.videoCount} 条</td><td>${g.accounts} 个</td><td>${performanceFilter()?g.passed+' / '+g.videoCount:'—'}</td></tr>`).join(''),['话术','使用视频','账号','符合指标'])}
      ${groups.length>40?`<p class="sb-empty">显示前 40 组，共 ${groups.length} 组，可搜索其余话术。</p>`:''}</section>
      <section class="sb-panel sb-detail"><h3>${PHASES[phase]} · 原句变体</h3>
      ${[...variants].map(([text,entries])=>`<div class="sb-variant"><p>${html(text)}</p><small>${entries.length} 条视频</small>
      ${action('video',entries[0].start==null?'查看口播':time(entries[0].start),entries[0].row.id,'class="sb-text-link"')}</div>`).join('')}</section></div>
      ${sampleTable(group.items.map(e=>e.row),true)}`;
  }
  function accountHTML(items){
    const accounts=accountRows(items).filter(([name])=>name);
    const [name,records]=accounts.find(([account])=>'a'+account===active)||accounts[0]||[];
    if(!records)return '<p class="sb-panel sb-empty">当前范围没有可对比的账号。</p>';
    active='a'+name;
    const all=overview(index.structures,scoped(true));
    const groups=overview(index.structures,records);
    const list=accounts.slice(0,40);
    return `<div class="sb-top"><section class="sb-panel sb-group-list">${table(list.map(([account,rows])=>`<tr class="${account===name?'sb-selected':''}"><td>${action('account',html(accountLabel(account)),account,'class="sb-text-link"')}</td>
      <td>${rows.length} 条</td><td>${performanceFilter()?rows.filter(matches).length:'—'}</td></tr>`).join(''),['账号','收录视频','符合指标'])}
      ${accounts.length>list.length?'<p class="sb-empty">显示前 40 个账号，可搜索其余账号。</p>':''}</section>
      <section class="sb-panel sb-detail"><h3>${html(accountLabel(name))} · 同账号复用</h3>
      ${groups.length ? table(groups.map(g=>{const total=all.find(item=>item.id===g.id);return `<tr><td>${action('go-group',html(g.text),'g'+g.id,'class="sb-text-link"')}</td><td>${g.videoCount} / ${total?.videoCount??g.videoCount}</td><td>${total?.accounts??1} 个</td></tr>`;}).join(''),['脚本','当前账号 / 跨账号','采用账号']) : '<p class="sb-empty">该账号尚无可比对的完整脚本。</p>'}
      </section></div>${sampleTable(records,true)}`;
  }
  function render(){
    if(!pane.isConnected)return;
    tabs.innerHTML=Object.entries(TABS).map(([key,name])=>action('tab',name,key,selected(current===key))).join('');
    tools.hidden=current==='archive';
    const viralButton=tools.querySelector('[data-sb=viral]');
    viralButton.setAttribute('aria-pressed',viral);
    viralButton.title='累计播放至少 70 万，或播放至少 1 万且点赞率、收藏率、评论率任一达标';
    const summary=filters.rules.map(r=>METRICS[r.key]+' '+COMPARATORS[r.op]+' '+format.format(r.value)+(r.key==='views'?' 次':'%')).join(filters.mode==='all'?' 且 ':' 或 ');
    tools.querySelector('.sb-chips').textContent=[summary,filters.account?accountLabel(filters.account):'',filters.category,filters.days?'近 '+filters.days+' 天':'',filters.reuse?'同账号 ≥ '+filters.reuse+' 条':''].filter(Boolean).join(' · ');
    if(current==='archive') {
      if(!archiveOpen){
        archiveOpen=true;
        archiveTarget=document.createElement('div');view.replaceChildren(archiveTarget);
        if(archive)archive(archiveTarget);else archiveTarget.textContent='原文案档案暂不可用。';
      }
      return;
    }
    if(!dataset) {
      view.innerHTML=loadError ? '<p role="alert" class="sb-panel sb-empty">视频读取失败，请点「刷新」重试。</p>' : '<p role="status" class="sb-panel sb-empty">正在读取文案和已采集视频…</p>';
      return;
    }
    const items=scoped();
    view.innerHTML=(current==='groups'?groupHTML(items):current==='phrases'?phraseHTML(items):current==='accounts'?accountHTML(items):sampleTable(items.filter(matches)))+
      '<p class="sb-note">播放与互动率使用各视频同一数据快照。GMV 为带时间范围的估算，缺失值显示为 —。</p>';
  }
  async function load(){
    if(loading)return;
    loading=true;loadError=false;
    const refresh=pane.querySelector('[data-sb=refresh]');
    refresh.disabled=true;
    render();
    try{
      const first=await request(API);
      const items=[...first.items];
      for(let offset=items.length;offset<first.total;offset+=400){
        if(!pane.isConnected)return;
        const next=await request(API+'?offset='+offset);
        items.push(...next.items);
      }
      if(!pane.isConnected)return;
      dataset={...first, items:[...new Map(items.map(row=>[row.id,row])).values()]};
      dataset.items.sort((a,b)=>dated(b.published).localeCompare(dated(a.published)));
      index=indexGroups([...dataset.items].sort((a,b)=>a.id.localeCompare(b.id)));
    }catch(error){
      dataset=null;loadError=true;
      if(error.status===404 && current==='groups' && archive)current='archive';
    }finally{loading=false;refresh.disabled=false;render();}
  }
  function showFilters(){
    const accounts=[...new Set((dataset?.items||[]).map(r=>r.account).filter(Boolean))].sort();
    const categories=[...new Set((dataset?.items||[]).map(r=>r.category).filter(Boolean))].sort();
    dialog.innerHTML=`<form><header><h3>指标筛选</h3>${action('close','关闭')}</header>
      <label>指标关系 <select name="mode">${option('all','满足全部（且）',filters.mode)}${option('any','满足任一（或）',filters.mode)}</select></label>
      <div class="sb-rules">${filters.rules.map(ruleControls).join('')}</div>${action('add-rule','添加指标')}
      <div class="sb-filter-fields"><label>账号<select name="account">${option('','全部账号',filters.account)}${accounts.map(a=>option(a,accountLabel(a),filters.account)).join('')}</select></label>
      <label>发布时间<select name="days">${[['','全部日期'],['7','近 7 天'],['14','近 14 天'],['30','近 30 天']].map(([k,v])=>option(k,v,filters.days)).join('')}</select></label>
      <label>商品类目<select name="category">${option('','全部类目',filters.category)}${categories.map(c=>option(c,c,filters.category)).join('')}</select></label>
      <label>同账号使用同一结构的次数<input type="number" name="reuse" min="1" step="1" value="${html(filters.reuse)}" placeholder="不限"></label></div>
      <footer><button class="primary" type="submit">应用筛选</button></footer></form>`;
    dialog.showModal();
  }
  async function showVideo(id,selectedPhase){
    detail=dataset?.items.find(row=>row.id===id);
    if(!detail)return;
    const row=detail, requested=++detailRequest;
    dialog.innerHTML=`<header><h3>视频拆解</h3>${action('close','关闭')}</header>
      <p class="sb-note">${html(accountLabel(row.account))} · ${dated(row.published)||'发布日期未提供'}</p>
      ${stats([[scopeLabel(row),'播放量'],[display(metric(row,'likes'),'likes'),'点赞率'],[gmv(row),'估算 GMV']])}
      <p class="sb-quote"><strong>发布文案</strong><br>${html(row.description || '未提供')}</p>
      <h4>口播环节</h4>${row.components.length ? row.components.map((c,i)=>`<div class="sb-variant${selectedPhase===c.phase?' sb-evidence-selected':''}">
        <strong>${PHASES[c.phase]}</strong><p>${html(c.text)}</p>
        ${row.preview && c.start!=null ? action('seek',time(c.start),i,'class="sb-text-link"') : `<small>${c.start==null?'暂无时间点':time(c.start)+' · '+html(c.timing_source)}</small>`}</div>`).join('') : '<p>暂无可核实的口播环节。</p>'}
      <details><summary>完整逐字稿</summary><p class="sb-transcript">${row.has_transcript?'正在读取…':'暂无逐字稿'}</p></details>
      <div class="sb-preview"></div><footer>${link(row)}</footer>`;
    dialog.showModal();
    if(row.has_transcript){
      try{
        const result=await request(API+'?transcript='+encodeURIComponent(id));
        if(requested!==detailRequest || !dialog.open)return;
        dialog.querySelector('.sb-transcript').textContent=result.text||'暂无逐字稿';
      }catch{if(requested===detailRequest && dialog.open)dialog.querySelector('.sb-transcript').textContent='逐字稿读取失败。';}
    }
  }
  dialog.addEventListener('close',()=>{detailRequest++;dialog.replaceChildren();});
  dialog.addEventListener('change',event=>{
    if(event.target.matches('[data-metric]'))event.target.closest('.sb-rule').querySelector('label span').textContent=event.target.value==='views'?'次':'%';
  });
  dialog.addEventListener('submit',event=>{
    event.preventDefault();
    const values=new FormData(event.target);
    const rules=[...dialog.querySelectorAll('.sb-rule')].map(r=>({key:r.querySelector('[data-metric]').value,op:r.querySelector('[data-op]').value,value:Number(r.querySelector('[data-limit]').value)}));
    filters={rules,mode:values.get('mode'),account:values.get('account'),days:values.get('days'),reuse:values.get('reuse'),category:values.get('category')};
    page=0;dialog.close();render();
  });
  search.addEventListener('input',()=>{query=searchForm(search.value.trim());page=0;render();});
  pane.addEventListener('error',event=>{
    if(!event.target.matches('.sb-media img'))return;
    const cover=event.target.dataset.cover;
    if(cover){event.target.dataset.cover='';event.target.src=cover;}
    else event.target.remove();
  },true);
  pane.addEventListener('click',event=>{
    const target=event.target.closest('[data-sb]');
    if(!target || !pane.contains(target))return;
    const {sb,value}=target.dataset;
    switch(sb){
      case 'refresh':if(current==='archive' && archiveTarget){archive(archiveTarget);return;}void load();return;
      case 'tab':
        if(current==='archive' && value!=='archive'){archive(null);archiveOpen=false;archiveTarget=null;}
        current=value;active='';page=0;break;
      case 'filters':showFilters();return;
      case 'close':dialog.close();return;
      case 'add-rule':dialog.querySelector('.sb-rules').insertAdjacentHTML('beforeend',ruleControls({key:'views',op:'ge',value:''}));return;
      case 'remove-rule':target.closest('.sb-rule').remove();return;
      case 'viral':viral=!viral;page=0;break;
      case 'clear':filters={rules:[],mode:'all',account:'',days:'',reuse:'',category:''};query='';search.value='';viral=false;openingWindow=false;page=0;break;
      case 'group':active=value;page=0;expanded=false;break;
      case 'go-group':active=value;current='groups';page=0;expanded=false;break;
      case 'phrase':active=value;page=0;break;
      case 'account':current='accounts';active='a'+value;page=0;break;
      case 'phase':phase=value;page=0;break;
      case 'opening-window':openingWindow=!openingWindow;page=0;break;
      case 'expand':expanded=!expanded;break;
      case 'sample-scope':matchedOnly=value==='matched';page=0;break;
      case 'page':page+=Number(value);break;
      case 'video':void showVideo(value,target.dataset.phase);return;
      case 'seek':{
        const preview=dialog.querySelector('.sb-preview');
        let video=preview.querySelector('video');
        const seconds=detail.components[Number(value)].start;
        if(!video){video=document.createElement('video');video.controls=true;video.playsInline=true;video.src=detail.preview;preview.append(video);}
        if(video.readyState>0)video.currentTime=seconds;
        else video.onloadedmetadata=()=>{video.currentTime=seconds;};
        video.scrollIntoView({block:'nearest'});return;
      }
      default:return;
    }
    const wasFocused=document.activeElement===target;
    render();
    if(wasFocused && !target.isConnected){
      const buttons=[...pane.querySelectorAll('[data-sb]')];
      (buttons.find(b=>b.dataset.sb===sb && b.dataset.value===value && !b.disabled) ||
        buttons.find(b=>b.dataset.sb==='tab' && b.dataset.value===current))?.focus({preventScroll:true});
    }
  });
  void load();
}

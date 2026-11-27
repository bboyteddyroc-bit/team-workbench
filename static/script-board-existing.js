const MONITOR = '/api/intelligence/apify/accounts';
const CASES = '/api/intelligence/cases';
const counts = ['views','likes','collects','comments','shares'];
const number = value => typeof value==='number' && Number.isFinite(value) && value>=0 ? value : null;
const metrics = row => Object.fromEntries(counts.map(key=>[key,number(row?.[key])]));
const held = value => typeof value==='string' ? value.trim() : '';
const key = video => 'tiktok:'+video;
const normalize = value => held(value).normalize('NFKC').toLowerCase().match(/[\p{L}\p{N}]+/gu)?.join(' ') || '';
const intervalValid = value => Number.isFinite(value?.start) && Number.isFinite(value?.end) && value.start>=0 && value.end>value.start && value.end<=1200;

function tikTokUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol==='https:' && !url.username && !url.password && !url.port &&
      ['tiktok.com','www.tiktok.com','vm.tiktok.com','vt.tiktok.com'].includes(url.hostname) ? url.href : '';
  } catch { return ''; }
}

export async function loadExisting(request, active) {
  const items = new Map();
  let failures = 0;
  const loaded = async task => {
    try { return await task(); }
    catch { failures++; return null; }
  };
  async function batch(inputs, action) {
    let cursor = 0;
    await Promise.all(Array.from({length:Math.min(4,inputs.length)},async()=>{
      while (cursor<inputs.length && active()) {
        const value=inputs[cursor++];
        await loaded(()=>action(value));
      }
    }));
  }
  function base(id){
    if(!items.has(id))items.set(id,{id,account:'',description:'',url:'',category:'',gm:null,metrics:{},tags:[],components:[],collected:-1});
    return items.get(id);
  }
  function gmv(row,data) {
    if(number(data?.gmv)==null || (row.gm!=null && row.gm_scope))return;
    row.gm=data.gmv;
    row.currency=held(data.currency);
    row.gm_scope=data.period_start && data.period_end ? '第三方区间估算 · '+data.period_start+' — '+data.period_end : '第三方区间估算';
  }
  async function snapshots(account) {
    const path=MONITOR+'/'+encodeURIComponent(account.id)+'/videos';
    const first=await request(path+'?page=1');
    function ingest(list) {
      for(const entry of list) {
        if(!/^\d+$/.test(entry.video))continue;
        const row=base(key(entry.video));
        if((number(entry.collected)??0)<row.collected)continue;
        Object.assign(row,{account:held(account.handle),description:held(entry.title),published:entry.published,
          metrics:metrics(entry),metric_source:'Apify 累计快照',collected:number(entry.collected)??0,
          url:tikTokUrl(entry.url)||tikTokUrl('https://www.tiktok.com/@'+encodeURIComponent(account.handle)+'/video/'+entry.video),
          cover:entry.cover?MONITOR+'/'+encodeURIComponent(account.id)+'/cover/'+entry.video:row.cover});
        gmv(row,entry.kalodata?.data);
      }
    }
    if(Array.isArray(first)){
      ingest(first);
      if(first.length>=500)failures++;
      return;
    }
    ingest(first.items);
    const size=first.page_size || first.items.length;
    for(let page=2;active() && size && (page-1)*size<first.total;page++){
      const result=await loaded(()=>request(path+'?page='+page));
      if(result?.items)ingest(result.items);
      else if(result)failures++;
    }
  }
  async function caseList(){
    const first=await request(CASES+'?scope=team&limit=100');
    const cases=Array.isArray(first)?[...first]:[...first.items];
    for(let offset=cases.length;active() && offset<first.total;offset+=100){
      const next=await loaded(()=>request(CASES+'?scope=team&limit=100&offset='+offset));
      if(next)cases.push(...next.items);
    }
    return cases;
  }
  const [accounts,cases,archives]=await Promise.all([
    loaded(()=>request(MONITOR)),loaded(caseList),loaded(()=>request('/api/intelligence/scripts'))
  ]);
  await batch(accounts||[],snapshots);
  for(const entry of archives || []){
    const row=base(entry.video ? key(entry.video) : 'archive:'+entry.id);
    row.account ||= held(entry.account_handle);
    row.description ||= held(entry.description);
    row.published ||= entry.published;
    row.url ||= tikTokUrl(entry.video_url);
    if(row.collected<0) {
      row.metrics=metrics(entry.snapshot);
      row.metric_source='文案档案快照';
    }
    row.category ||= held(entry.product_category);
    row.tags=(entry.tags||[]).filter(tag=>typeof tag==='string');
    row.archive=entry;
    row.transcript=held(entry.transcript_original);
  }
  for(const entry of cases || []){
    const id=entry.video ? held(entry.platform).toLowerCase()+':'+entry.video : 'case:'+entry.id;
    const row=base(id);
    row.case=entry;
    row.account ||= held(entry.handle);
    row.description=held(entry.fields?.title?.value) || row.description;
    row.published ||= entry.source?.published || entry.fields?.published_at?.value;
    row.url ||= tikTokUrl(entry.url);
    row.category ||= held(entry.fields?.category?.value);
    if(entry.cover_url===CASES+'/'+entry.id+'/cover')row.cover=entry.cover_url;
    if(row.metrics.views==null && number(entry.source?.views)!=null){
      row.metrics=metrics(entry.source);row.metric_source='公开视频累计快照';
    }else if(row.metrics.views==null && number(entry.source?.kalodata?.period_views)!=null){
      row.metrics=metrics({...entry.source.kalodata,views:entry.source.kalodata.period_views});
      row.metric_source='Kalodata 区间快照';
    }
    const estimate=entry.metrics?.find(m=>m.key==='gmv');
    if(number(estimate?.value)!=null){
      row.gm=estimate.value;row.currency=held(estimate.currency);row.gm_scope=held(estimate.scope);
    }else gmv(row,entry.source?.kalodata);
  }
  await batch([...items.values()].filter(row=>row.case?.transcript_source || row.case?.ai?.generated_at),async row=>{
    const item=await request(CASES+'/'+encodeURIComponent(row.case.id));
    row.case=item;
    row.transcript=held(item.fields?.transcript?.value) || held(item.transcript) || row.transcript;
    if(item.has_preview)row.preview=CASES+'/'+encodeURIComponent(item.id)+'/preview';
  });
  for(const row of items.values()){
    const full=normalize(row.transcript);
    row.has_transcript=Boolean(row.transcript);
    row.exact_script=full;
    if(full){
      const fields=row.case?.fields || {};
      const candidates=[
        ['opening',fields.hook_example?.value || fields.opening?.value || row.archive?.opening,'opening'],
        ['pain',row.archive?.pain_point,''],
        ['demo',fields.replication_actions?.value,'replication_actions'],
        ['cta',fields.ending?.value || row.archive?.ending,'ending']
      ];
      row.components=candidates.flatMap(([phase,text,field])=>{
        const quote=normalize(text);
        if(!quote || !(' '+full+' ').includes(' '+quote+' '))return [];
        const review=row.case?.clip_reviews?.[field];
        const timing=intervalValid(review) && normalize(review.claim)===quote ? {start:review.start,end:review.end,timing_source:'人工确认区间'} : {};
        return [{phase,text:held(text),source:'已有口播原句',...timing}];
      }).sort((a,b)=>full.indexOf(normalize(a.text))-full.indexOf(normalize(b.text)));
      if(!row.components.length){
        const first=row.transcript.split(/(?<=[.!?。！？])\s+|(?<=[。！？])/u,1)[0].trim();
        if(first.length<=250)row.components=[{phase:'opening',text:first,source:'逐字稿首句'}];
      }
    }
    delete row.case;
    delete row.archive;
    delete row.collected;
  }
  if(!accounts && !cases && !archives)throw Error('现有数据读取失败');
  return {items:[...items.values()],date:new Date().toISOString().slice(0,10),existing:true,failures};
}

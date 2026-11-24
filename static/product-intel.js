(() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const api = '/api/intelligence/goods';
  window.openProductIntel = async (host, focusVideo='') => {
    const view = document.createElement('section');
    host.replaceChildren(view);
    view.className = 'goods-library';
    let data, tab = '商品', selected = '', query = '', message = '', busy = false, relation = '视频', selectedShop = '', shopRelation = '商品', productPage = 1, shopPage = 1;
    const pageSize=12, trail=[], failedCovers=new Set();
    const recordLabels={linked:'已关联',queued:'排队中',claimed:'查询已提交',done:'未查到商品',attention:'需核查',unchecked:'尚未查询'};
    const recordNotes={unchecked:'还未发起关联查询',queued:'等待系统处理',claimed:'已提交，结果待确认',done:'本次查询未返回关联商品，不代表视频一定未带货',attention:'未确认查询结果，当前记录未保存具体原因；可先核对原视频'};
    let recordFilter='', recordQuery='', recordPage=1;
    const coverMarkup=(sources,action='')=>{
      const urls=[...new Set(sources.filter(Boolean))], available=urls.filter(url=>!failedCovers.has(url));
      const [src,fallback]=available;
      return `${src?`<img loading="lazy" data-intel-cover="${esc(src)}" ${fallback?`data-cover-fallback="${esc(fallback)}"`:''} src="${esc(src)}" alt="视频封面">`:''}<span class="gi-cover-fallback" ${src?'hidden':''}><span data-cover-status>${urls.length?'封面加载失败':'暂无封面'}</span>${action?`<strong>${action}</strong>`:''}</span>`;
    };
    view.addEventListener('error',e=>{
      const img=e.target;
      if(!img.matches?.('img[data-intel-cover]'))return;
      failedCovers.add(img.dataset.intelCover);
      const fallback=img.dataset.coverFallback;
      if(fallback&&!failedCovers.has(fallback)){
        delete img.dataset.coverFallback;img.dataset.intelCover=fallback;img.src=fallback;return;
      }
      const placeholder=img.nextElementSibling;
      placeholder.querySelector('[data-cover-status]').textContent='封面加载失败';
      placeholder.hidden=false;img.remove();
    },true);
    let initialized=false, sort='default', filter={author:'',caseType:''};
    const number=v=>((typeof v==='number'||(typeof v==='string'&&v.trim()!==''))&&Number.isFinite(Number(v)))?Number(v):null;
    const group=(rows,key)=>{const m=new Map();for(const row of rows){const k=key(row);if(!m.has(k))m.set(k,[]);m.get(k).push(row)}return m};
    const detail=(kind,id)=>data.details[kind+':'+id];
    const sortRows=(rows,score)=>sort==='default'?rows:[...rows].sort((a,b)=>{const x=score(a),y=score(b);return x===null?(y===null?0:1):y===null?-1:y-x});
    const filterVideos=items=>items.filter(v=>(!filter.author||v.handle===filter.author)&&(!filter.caseType||Boolean(v.case_id)===(filter.caseType==='with')));
    const options=(items,active)=>items.map(([value,label])=>`<option value="${esc(value)}" ${value===active?'selected':''}>${esc(label)}</option>`).join('');
    const rail=(name)=>`<input type="search" aria-label="搜索${name}" placeholder="搜索${name}" value="${esc(query)}"><select data-intel-sort aria-label="${name}排序">${options([['default','默认排序'],['revenue','成交额从高到低'],['sales_volumn','销量从高到低'],['videos','关联视频数从高到低']],sort)}</select>`;
    const filters=(items,topPager='')=>`<div class="gi-filters"><select data-author-filter aria-label="筛选视频作者">${options([['','全部作者'],...[...new Set(items.map(v=>v.handle).filter(Boolean))].sort().map(h=>[h,'@'+h])],filter.author)}</select><select data-case-filter aria-label="筛选案例状态">${options([['','全部案例状态'],['with','已有案例'],['without','暂无案例']],filter.caseType)}</select><small>显示 ${filterVideos(items).length} / ${items.length} 条视频</small>${topPager}</div>`;
    const newCreators=()=>({query:'',order:'desc',page:1,expanded:''});
    let creatorState=newCreators();
    const resetVideos=()=>{filter={author:'',caseType:''};productPage=shopPage=1};
    const resetScope=()=>{resetVideos();creatorState=newCreators()};
    const savePlace=()=>trail.push({tab,selected,selectedShop,query,sort,relation,shopRelation,productPage,shopPage,creatorState:{...creatorState},filter:{...filter},scrolls:[...new Set([document.scrollingElement,...ancestors(view)])].filter(Boolean).map(node=>[node,node.scrollTop]),railTop:view.querySelector('.gi-rail')?.scrollTop||0});
    function* ancestors(node){for(let p=node.parentElement;p;p=p.parentElement)yield p}
    const period=d=>`近30天 · ${d?.end?'截至 '+esc(d.end)+'（UTC）':'截止日期暂无'}`;
    const metricStatus=d=>!d?'暂无采集记录':!['revenue','sales_volumn','unit_price','video_revenue','live_revenue','showcase_revenue'].some(k=>number(d[k])!==null)?'已有详情记录，接口未提供可用指标':'来源：Kalodata · — 表示接口未提供可用数值';
    function pageNumbers(current,pages,button){
      const ns=[...new Set([1,current-1,current,current+1,pages])].filter(n=>n>=1&&n<=pages).sort((a,b)=>a-b);
      return ns.map((n,i)=>(i&&n-ns[i-1]>1?'<span aria-hidden="true">…</span>':'')+button(n)).join('');
    }
    function pagedVideos(items,kind){
      const total=items.length,pages=Math.max(1,Math.ceil(total/pageSize)),current=Math.max(1,Math.min(kind==='product'?productPage:shopPage,pages));
      if(kind==='product')productPage=current;else shopPage=current;
      const start=(current-1)*pageSize;
      const indices=pageNumbers(current,pages,n=>`<button type="button" data-video-page="${kind}" data-page="${n}" aria-label="第 ${n} 页" ${n===current?'aria-current="page"':''}>${n}</button>`);
      const pager=where=>pages>1?`<nav class="gi-pagination" data-pager="${where}" aria-label="${where==='top'?'视频顶部翻页':'视频底部翻页'}"><button type="button" data-video-page="${kind}" data-direction="prev" data-page="${current-1}" ${current===1?'disabled':''}>上一页</button><span tabindex="-1" data-page-summary>第 ${current} / ${pages} 页${where==='bottom'?' · 共 '+total+' 条':''}</span>${indices}<button type="button" data-video-page="${kind}" data-direction="next" data-page="${current+1}" ${current===pages?'disabled':''}>下一页</button></nav>`:'';
      return {items:items.slice(start,start+pageSize),top:pager('top'),pagination:pager('bottom')};
    }
    async function refresh() {
      const res = await fetch(api+(focusVideo?'?video='+encodeURIComponent(focusVideo):''));
      if (!res.ok) throw Error('商品库读取失败');
      const next = await res.json();
      if (!initialized && focusVideo) tab = next.links.some(v=>v.video===focusVideo) ? '商品' : '识别记录';
      initialized=true;
      data=next;
      draw();
    }
    function draw() {
      const scoped=data.goods.filter(g=>!focusVideo||g.id===selected||data.links.some(v=>v.video===focusVideo&&v.product===g.id));
      const productLinks=group(data.links,l=>l.product), storeProducts=group(data.goods.filter(g=>g.shop),g=>g.shop);
      const storeLinks=new Map();
      for(const [id,products] of storeProducts) storeLinks.set(id,[...new Map(products.flatMap(g=>productLinks.get(g.id)||[]).map(l=>[l.video,l])).values()]);
      const matches=(...values)=>values.some(v=>String(v??'').toLowerCase().includes(query.trim().toLowerCase()));
      const goods=sortRows(scoped.filter(g=>matches(g.name,g.id,g.shop_name,g.shop)),g=>sort==='videos'?(productLinks.get(g.id)?.length||0):number(detail('shop',g.id)?.[sort]));
      const shops=[...storeProducts].map(([id,products])=>[id,products.find(g=>g.shop_name)?.shop_name||'店铺名称待补全']);
      const product=tab==='商品'&&(goods.find(g=>g.id===selected)||goods[0]);
      if(product&&product.id!==selected){selected=product.id;resetScope()}
      const videos=[...(product?productLinks.get(product.id)||[]:[])];
      const creators=group(videos,v=>v.handle);
      const actions = (kind,id,title) => `<button type="button" data-lookup="${kind}" data-id="${esc(id)}" ${busy?'disabled':''}>${title}</button>`;
      const recordsByVideo=new Map(data.pending.map(v=>[v.video,v]));
      const linksByVideo=group(data.links,l=>l.video);
      const goodsById=new Map(data.goods.map(g=>[g.id,g]));
      const originalUrl=v=>`https://www.tiktok.com/@${encodeURIComponent(v.handle||'_')}/video/${encodeURIComponent(v.video)}`;
      const video = v => {
        const sources=[v.case_id&&'/api/intelligence/cases/'+encodeURIComponent(v.case_id)+'/cover',v.monitor_cover||recordsByVideo.get(v.video)?.cover];
        return `<article class="gi-film"><a href="${originalUrl(v)}" target="_blank" rel="noopener"><div class="gi-frame">${coverMarkup(sources,'▶ 查看原视频')}</div><strong>@${esc(v.handle||'未知作者')}</strong></a>${v.case_id?`<button data-case="${esc(v.case_id)}">查看案例</button>`:''}</article>`;
      };
      const recordState=v=>linksByVideo.has(v.video)?'linked':!v.state?'unchecked':['queued','claimed','done','attention'].includes(v.state)?v.state:'attention';
      function renderRecords(){
        const keyword=recordQuery.trim().toLowerCase().replace(/^@/,'');
        const rows=data.pending.filter(v=>(!recordFilter||recordState(v)===recordFilter)&&(!keyword||[v.title,v.handle,...(linksByVideo.get(v.video)||[]).map(l=>goodsById.get(l.product)?.name)].some(text=>String(text||'').toLowerCase().includes(keyword))));
        const size=15, pages=Math.max(1,Math.ceil(rows.length/size));
        recordPage=Math.min(recordPage,pages);
        return `<section class="gi-record-panel" aria-labelledby="gi-record-heading"><header class="gi-record-toolbar"><div><h3 id="gi-record-heading">识别记录</h3><small>按采集时间排序 · 匹配 ${rows.length} / ${data.pending.length} 条近期记录</small></div><div class="gi-filters"><input type="search" data-record-search aria-label="搜索识别记录" placeholder="搜索视频、作者或商品" value="${esc(recordQuery)}"><select data-record-filter aria-label="筛选识别状态">${options([['','全部识别状态'],...Object.entries(recordLabels)],recordFilter)}</select></div></header><div class="gi-record-scroll" role="region" tabindex="0" aria-label="识别记录表格"><table class="gi-record-table" aria-labelledby="gi-record-heading"><colgroup><col><col><col><col><col></colgroup><thead><tr>${['视频','来源 / 成员','识别状态','关联商品','操作'].map(label=>`<th scope="col">${label}</th>`).join('')}</tr></thead><tbody>${rows.slice((recordPage-1)*size,recordPage*size).map(v=>{
          const linked=linksByVideo.get(v.video)||[],state=recordState(v),title=v.title||'查看原视频';
          return `<tr><td><div class="gi-record-video"><a class="gi-record-cover" href="${originalUrl(v)}" target="_blank" rel="noopener" aria-label="查看原视频封面及链接">${coverMarkup([v.cover])}</a><div><a class="gi-record-title" title="${esc(title)}" href="${originalUrl(v)}" target="_blank" rel="noopener">${esc(title)}</a><small>@${esc(v.handle||'未知作者')}</small></div></div></td><td>${esc(v.source||'—')}<small>${esc((v.members||[]).join('、')||'—')}</small></td><td><span class="gi-record-state" data-state="${state}">${recordLabels[state]}</span>${recordNotes[state]?`<small>${recordNotes[state]}</small>`:''}</td><td>${linked.length?`<small>${linked.length} 款商品</small>${linked.map(l=>{const name=goodsById.get(l.product)?.name||'查看商品';return `<button type="button" class="gi-record-product" title="${esc(name)}" data-product="${esc(l.product)}">${esc(name)}</button>`}).join('')}`:'<small>—</small>'}</td><td><div class="gi-record-actions"><a href="${originalUrl(v)}" target="_blank" rel="noopener">原视频 ↗</a>${state==='unchecked'?actions('video',v.video,'查询关联商品'):''}</div></td></tr>`;
        }).join('')||`<tr><td colspan="5" class="gi-record-empty">${data.pending.length?'没有符合条件的识别记录':'暂无识别记录'}</td></tr>`}</tbody></table></div>${pages>1?`<nav class="gi-pagination" aria-label="识别记录分页">${pageNumbers(recordPage,pages,n=>`<button type="button" data-record-page="${n}" aria-label="第 ${n} 页" ${n===recordPage?'aria-current="page"':''}>${n}</button>`)}</nav>`:''}</section>`;
      }
      videos.sort((a,b)=>Number(Boolean(b.case_id))-Number(Boolean(a.case_id)));
      const productVideos=tab==='商品'?pagedVideos(filterVideos(videos),'product'):null;
      const amount=(v,money)=>number(v)===null?'—':(money?'$':'')+(Number(v)>=10000?(Number(v)/10000).toFixed(2)+'万':Number(v).toLocaleString(undefined,{maximumFractionDigits:2}));
      const metrics=(kind,id)=>{
        const record=detail(kind,id),d=record||{};
        const channel=(name,key)=>{
          const pct=d.revenue>0&&d[key]!=null?Math.min(100,Math.max(0,100*Number(d[key])/Number(d.revenue))):0;
          return `<div class="gi-bar"><span>${name}</span><i><b style="width:${pct}%"></b></i><small>${amount(d[key],true)}</small></div>`;
        };
        return `<section class="goods-overview"><header><strong>经营概览</strong><small>美国 · ${period(record)} · ${metricStatus(record)}</small></header><div class="gi-stats"><div class="goods-kpis">${Object.entries({revenue:'成交额',sales_volumn:'销量',unit_price:'平均售价',video_revenue:'视频成交额'}).map(([k,n])=>`<div><small>${n}</small><strong>${amount(d[k],k!=='sales_volumn')}</strong></div>`).join('')}</div><div class="gi-chart"><strong>成交渠道对比</strong>${channel('视频','video_revenue')}${channel('直播','live_revenue')}${channel('商品卡','showcase_revenue')}</div></div></section>`;
      };
      const cover = g => {
        const img=data.details['shop:'+g.id]?.master_image_url;
        if(typeof img==='string'&&img.startsWith('https://')) return '<img loading="lazy" referrerpolicy="no-referrer" alt="商品主图" src="'+esc(img)+'">';
        const link=data.links.find(v=>v.product===g.id && v.case_id);
        return link ? '<img loading="lazy" alt="关联视频封面" src="/api/intelligence/cases/'+encodeURIComponent(link.case_id)+'/cover">' : '<span>暂无封面</span>';
      };
      const card = g => {
        const related=productLinks.get(g.id)||[];
        return `<button class="goods-card" aria-pressed="${selected===g.id}" data-product="${esc(g.id)}"><div class="goods-thumb">${cover(g)}</div><div><strong>${esc(g.name||'商品资料待补全')}</strong><small>${esc(g.shop_name||'店铺名称待补全')}</small><small>${related.length} 条视频 · ${new Set(related.map(v=>v.handle).filter(Boolean)).size} 位达人</small></div></button>`;
      };
      function renderCreators(groups,scope){
        const all=[...groups].filter(([h])=>h);
        const keyword=creatorState.query.trim().replace(/^@/,'').toLowerCase();
        const rows=all.filter(([h])=>h.toLowerCase().includes(keyword)).sort(([a,x],[b,y])=>(creatorState.order==='asc'?x.length-y.length:y.length-x.length)||a.localeCompare(b));
        const pages=Math.max(1,Math.ceil(rows.length/pageSize));
        const current=creatorState.page=Math.min(creatorState.page,pages);
        return `<div class="gi-filters"><input type="search" data-creator-search aria-label="搜索达人" placeholder="搜索达人账号" value="${esc(creatorState.query)}"><select data-creator-order aria-label="达人排序">${options([['desc','关联视频数从高到低'],['asc','关联视频数从低到高']],creatorState.order)}</select><small>匹配 ${rows.length} / ${all.length} 位达人</small></div><div class="gi-shop-people">${rows.slice((current-1)*pageSize,current*pageSize).map(([h,items])=>{
          const opened=creatorState.expanded===h;
          return `<article><strong>@${esc(h)}</strong> <small>${items.length} 条关联视频</small><div class="gi-filters"><button type="button" data-expand-creator="${esc(h)}" aria-expanded="${opened}">${opened?'收起':'展开视频'}</button><a href="https://www.tiktok.com/@${encodeURIComponent(h)}" target="_blank" rel="noopener">打开 TikTok ↗</a></div>${opened?`<ul class="gi-creator-preview">${items.slice(0,4).map(v=>`<li><a href="${originalUrl(v)}" target="_blank" rel="noopener">${esc(v.title||'原视频 '+v.video)} ↗</a></li>`).join('')}</ul><button type="button" data-creator="${esc(h)}" data-scope="${scope}">查看全部关联视频</button>`:''}</article>`;
        }).join('')||`<p class="gi-empty">${all.length?'没有匹配的达人':'暂无已关联达人'}</p>`}</div>${pages>1?`<nav class="gi-pagination" aria-label="达人分页">${pageNumbers(current,pages,n=>`<button type="button" data-creator-page="${n}" aria-label="第 ${n} 页" ${n===current?'aria-current="page"':''}>${n}</button>`)}</nav>`:''}`;
      }
      function renderShop() {
        const entries=sortRows(shops.filter(([key,name])=>matches(key,name)),([key])=>sort==='videos'?storeLinks.get(key).length:number(detail('store',key)?.[sort]));
        const active=entries.find(([id])=>id===selectedShop)||entries[0];
        if(!active)return `<div class="gi-workspace gi-shop-workspace"><aside class="gi-rail">${rail('店铺')}</aside><main class="gi-main"><p class="gi-empty">${query?'暂无匹配店铺':'暂无已确认店铺。视频关联到商品和店铺后会自动显示。'}</p></main></div>`;
        if(active[0]!==selectedShop){selectedShop=active[0];resetScope()}
        const [id,name]=active, record=detail('store',id),d=record||{};
        const products=storeProducts.get(id),links=storeLinks.get(id);
        const people=group(links.filter(l=>l.handle),l=>l.handle);
        const shopVideos=pagedVideos(filterVideos(links),'shop');
        const logo=(key,label)=>{const u=data.details['store:'+key]?.master_image_url;return u&&/^https:\/\//.test(u)?`<img loading="lazy" src="${esc(u)}" alt="${esc(label)}">`:`<span>${esc(label.slice(0,1))}</span>`};
        const parts=[['视频','video_revenue'],['直播','live_revenue'],['商品卡','showcase_revenue']];
        const total=Number(d.revenue)||0;
        let cursor=0;const colors=['#8cc8e5','#708b9c','#536878'];
        const stops=parts.map(([,key],i)=>{const from=cursor;cursor=Math.min(100,cursor+(total>0?Math.max(0,Number(d[key])||0)/total*100:0));return `${colors[i]} ${from}% ${cursor}%`});
        const productTiles=products.map(g=>{const m=data.details['shop:'+g.id]||{}, ls=data.links.filter(l=>l.product===g.id);return `<button class="gi-shop-product" data-product="${esc(g.id)}"><div class="gi-product-image">${cover(g)}</div><div class="gi-product-copy"><strong>${esc(g.name||'商品资料待补全')}</strong><div class="gi-product-numbers"><b>${amount(m.unit_price,true)}</b><small>销量 ${amount(m.sales_volumn)}</small></div><small>关联视频 ${ls.length} 条 · 达人 ${new Set(ls.map(l=>l.handle).filter(Boolean)).size} 位</small></div></button>`}).join('');
        return `<div class="gi-workspace gi-shop-workspace"><aside class="gi-rail">${rail('店铺')}${entries.map(([key,label])=>`<button class="gi-shop-choice" data-store="${esc(key)}" aria-pressed="${key===id}"><div class="gi-shop-logo">${logo(key,label)}</div><div><strong>${esc(label)}</strong><small>已关联 ${storeProducts.get(key).length} 款商品</small></div></button>`).join('')}</aside><main class="gi-main gi-shop-main"><section class="gi-shop-heading"><div class="gi-shop-logo">${logo(id,name)}</div><div><h3>${esc(name)}</h3><small>美国 · 店铺详情</small></div></section><section class="gi-shop-kpis">${[['成交额',amount(d.revenue,true)],['销量',amount(d.sales_volumn)],['平均售价',amount(d.unit_price,true)],['已关联达人',people.size.toLocaleString()]].map(([label,value])=>`<div><small>${label}</small><strong>${value}</strong></div>`).join('')}<small>${period(record)}</small></section><p class="gi-data-status">${metricStatus(record)}</p><div class="gi-shop-charts"><section><h4>成交渠道分布</h4><div class="gi-distribution"><div class="gi-donut" style="background:conic-gradient(${stops.join(',')},#394147 ${cursor}% 100%)"><div><strong>${amount(d.revenue,true)}</strong><small>成交额</small></div></div><div>${parts.map(([label,key],i)=>`<div class="gi-channel"><i style="background:${colors[i]}"></i><span>${label}</span><b>${amount(d[key],true)}</b></div>`).join('')}</div></div></section><section><h4>成交额趋势</h4><div class="gi-trend-empty"><span>暂无每日趋势数据</span><small>当前接口返回近30天汇总，不绘制推测曲线</small></div></section></div><section class="gi-shop-content"><nav>${['商品','达人','视频'].map(t=>`<button data-shop-relation="${t}" aria-pressed="${shopRelation===t}">${t==='商品'?'店铺商品':'带货'+t}</button>`).join('')}</nav>${shopRelation==='商品'?`<div class="gi-shop-products">${productTiles}</div>`:shopRelation==='视频'?`${filters(links,shopVideos.top)}<div class="gi-films">${shopVideos.items.map(video).join('')||(links.length?'<p>没有符合筛选条件的视频</p>':'<p>暂无已关联视频</p>')}</div>${shopVideos.pagination}`:renderCreators(people,'shop')}</section></main></div>`;
      }
      const restoreTabFocus=view.querySelector('.gi-tabs')?.contains(document.activeElement);
      view.innerHTML = `<div class="intel-direct-tools"><nav class="gi-tabs" aria-label="商品与店铺子页">${['商品','店铺','识别记录'].map(t=>`<button type="button" data-tab="${t}" aria-pressed="${t===tab}">${t}</button>`).join('')}</nav>${trail.length?'<button type="button" class="intel-direct-action" data-intel-return>返回上一步</button>':''}</div><p role="status">${esc(message)}</p>`+
        (tab==='商品'?`<div class="gi-workspace"><aside class="gi-rail">${rail('商品')}<div>${goods.map(card).join('')||'暂无匹配商品'}</div></aside><main class="gi-main">${product?`<section class="goods-hero"><div class="goods-thumb">${cover(product)}</div><div><small>商品详情</small><h3>${esc(product.name||product.id)}</h3><p>${product.shop?`<button type="button" class="gi-shop-link" data-open-shop="${esc(product.shop)}">${esc(product.shop_name||'店铺名称待补全')} ↗</button>`:'所属店铺尚未建立关联'}</p></div></section>${metrics('shop',selected)}<section class="goods-relations"><header><nav>${['视频','达人'].map(t=>`<button data-relation="${t}" aria-pressed="${relation===t}">带货${t} · ${t==='视频'?videos.length:[...creators.keys()].filter(Boolean).length}</button>`).join('')}</nav>${actions('product',selected,'检查带货关联')}</header>${relation==='视频'?`${filters(videos,productVideos.top)}<div class="gi-films">${productVideos.items.map(video).join('')||(videos.length?'<p>没有符合筛选条件的视频</p>':'<p>暂无已关联视频</p>')}</div>${productVideos.pagination}`:renderCreators(creators,'product')}</section>`:''}</main></div>`:
        tab==='识别记录'?renderRecords():
        renderShop());
      if(restoreTabFocus)view.querySelector('.gi-tabs [aria-pressed="true"]')?.focus({preventScroll:true});
      for(const input of view.querySelectorAll('input[type=search]')){
        const isCreator=input.hasAttribute('data-creator-search');
        const search=()=>{
          const value=input.value;
          if(isCreator){if(creatorState.query===value)return;Object.assign(creatorState,{query:value,page:1,expanded:''})}
          else if(input.hasAttribute('data-record-search')){if(recordQuery===value)return;recordQuery=value;recordPage=1}
          else{if(query===value)return;query=value}
          const selector=isCreator?'[data-creator-search]':input.hasAttribute('data-record-search')?'[data-record-search]':'.gi-rail input[type=search]';
          draw();view.querySelector(selector)?.focus({preventScroll:true});
        };
        input.oninput=e=>{if(!e.isComposing)search()};input.oncompositionend=search;
      }
    }
    view.onchange=e=>{
      const el=e.target;
      if(el.matches('[data-intel-sort]'))sort=el.value;
      else if(el.matches('[data-author-filter]')){filter.author=el.value;productPage=shopPage=1}
      else if(el.matches('[data-case-filter]')){filter.caseType=el.value;productPage=shopPage=1}
      else if(el.matches('[data-creator-order]'))Object.assign(creatorState,{order:el.value,page:1,expanded:''});
      else if(el.matches('[data-record-filter]')){recordFilter=el.value;recordPage=1}
      else return;
      const attribute=['data-intel-sort','data-author-filter','data-case-filter','data-record-filter','data-creator-order'].find(a=>el.hasAttribute(a));
      draw();view.querySelector(`[${attribute}]`)?.focus({preventScroll:true});
    }
    view.onclick = async e => {
      const b=e.target.closest('button');if(!b)return;
      if(b.hasAttribute('data-intel-return')){
        const prev=trail.pop();if(!prev)return;
        ({tab,selected,selectedShop,query,sort,relation,shopRelation,productPage,shopPage,creatorState,filter}=prev);
        draw();const rail=view.querySelector('.gi-rail');if(rail)rail.scrollTop=prev.railTop;
        for(const [node,top] of prev.scrolls)node.scrollTop=top;
        return;
      }
      if(b.dataset.openShop){savePlace();tab='店铺';selectedShop=b.dataset.openShop;shopRelation='商品';query='';sort='default';resetScope();draw();view.querySelector('.gi-shop-heading')?.scrollIntoView({block:'nearest'});return;}
      if(b.dataset.recordPage){
        recordPage=Number(b.dataset.recordPage);draw();
        view.querySelector('.gi-record-toolbar')?.scrollIntoView({block:'nearest'});
        view.querySelector('[data-record-page][aria-current=page]')?.focus({preventScroll:true});return;
      }
      if(b.dataset.creatorPage){creatorState.page=Number(b.dataset.creatorPage);creatorState.expanded='';draw();view.querySelector('[data-creator-search]')?.focus();return;}
      if(b.dataset.expandCreator){const h=b.dataset.expandCreator;creatorState.expanded=creatorState.expanded===h?'':h;draw();[...view.querySelectorAll('[data-expand-creator]')].find(el=>el.dataset.expandCreator===h)?.focus({preventScroll:true});return;}
      if(b.dataset.creator){savePlace();resetScope();filter.author=b.dataset.creator;if(b.dataset.scope==='shop')shopRelation='视频';else relation='视频';draw();view.querySelector('.gi-filters')?.scrollIntoView({block:'nearest'});return;}
      if(b.dataset.videoPage){
        const n=Number(b.dataset.page),where=b.closest('[data-pager]').dataset.pager;
        if(b.dataset.videoPage==='product')productPage=n;else shopPage=n;
        draw();const pager=view.querySelector(`[data-pager="${where}"]`);
        pager?.scrollIntoView({block:'nearest'});
        const focusTarget=b.dataset.direction?pager?.querySelector(`[data-direction="${b.dataset.direction}"]:not(:disabled)`):pager?.querySelector('[aria-current="page"]');
        (focusTarget||pager?.querySelector('[data-page-summary]'))?.focus({preventScroll:true});return;
      }
      if(b.dataset.case){window.dispatchEvent(new CustomEvent('hub-view-video-case',{detail:{id:b.dataset.case}}));return;}
      if(b.dataset.lookup){
        if(busy)return;
        busy=true;message='正在查询…';draw();
        try {
          const res=await fetch(api+'/lookup/'+b.dataset.lookup+'/'+b.dataset.id,{method:'POST',headers:{'X-Hub-Request':'1'}});
          const v=await res.json();if(!res.ok)throw Error(v.detail||'查询失败');
          message='已检查查询队列，相同记录共用查询结果'; await refresh();
        }catch(err){message=err.message}finally{busy=false;draw()}return;
      }
      if(b.dataset.store){if(selectedShop!==b.dataset.store)resetScope();selectedShop=b.dataset.store;draw();return}
      if(b.dataset.shopRelation){shopRelation=b.dataset.shopRelation;draw();return}
      if(b.dataset.relation){relation=b.dataset.relation;draw();return}
      if(b.dataset.tab){if(tab===b.dataset.tab)return;tab=b.dataset.tab;query='';sort='default';resetScope();trail.length=0;if(focusVideo){focusVideo='';await refresh();return}}
      else if(b.dataset.product){if(tab!=='商品'){savePlace();query='';sort='default'}else if(selected===b.dataset.product)return;tab='商品';selected=b.dataset.product;relation='视频';resetScope()}
      else if(b.hasAttribute('data-back'))selected='';
      draw();
    };
    const timer=setInterval(()=>{if(!view.isConnected){clearInterval(timer);return}if(!view.querySelector('details[open]')&&!busy&&!selected&&!query&&!view.contains(document.activeElement))refresh().catch(()=>{})},15000);try{await refresh()}catch(err){view.textContent=err.message}
  };
})();

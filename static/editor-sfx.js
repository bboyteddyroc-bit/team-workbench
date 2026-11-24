/* Built-in royalty-free sound effects tab for the editor audio panel. */
(()=>{
  'use strict';
  const $=id=>document.getElementById(id);
  const el=(tag,text,cls)=>{const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;};
  const icon=(path,size=14)=>{const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 24 24');svg.setAttribute('width',size);svg.setAttribute('height',size);svg.setAttribute('fill','none');svg.setAttribute('stroke','currentColor');svg.setAttribute('stroke-width','2');svg.setAttribute('stroke-linecap','round');svg.setAttribute('stroke-linejoin','round');const p=document.createElementNS('http://www.w3.org/2000/svg','path');p.setAttribute('d',path);svg.append(p);return svg;};
  const PLAY='M8 5v14l11-7z',PAUSE='M9 5v14M15 5v14',STAR='M12 3.5l2.7 5.6 6.1.9-4.4 4.3 1 6.1-5.4-2.9-5.4 2.9 1-6.1L3.2 10l6.1-.9z',SEARCH='M10.5 17a6.5 6.5 0 1 0 0-13 6.5 6.5 0 0 0 0 13zM20 20l-4.2-4.2';

  let mounted=false,loaded=false,loading=false,failure='',items=[],cats=[],license='',source='',cat='',query='';
  let audio=null,playing='',host=null,note=null,listNode=null,chipsNode=null,emptyNode=null,countNode=null;

  const say=message=>{if(typeof note==='function')note(message);};
  const duration=value=>{const d=Number(value)||0;return `${d<10?d.toFixed(2):d.toFixed(1)}s`;};
  const CATEGORY_LABEL=key=>{const hit=cats.find(c=>c.key===key);return hit?hit.label:key;};

  async function json(url,options){
    const r=await fetch(url,{credentials:'same-origin',...options});
    let data={};try{data=await r.json();}catch(e){data={};}
    if(!r.ok)throw Error(data.detail||'音效服务暂时不可用');
    return data;
  }

  function waveform(seed,width=54,height=16){
    let hash=2166136261;for(const ch of String(seed)){hash^=ch.charCodeAt(0);hash=Math.imul(hash,16777619);}
    const bars=13,gap=1.5,bar=(width-gap*(bars-1))/bars;let x=0,sig=hash>>>0;
    const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.setAttribute('width',width);svg.setAttribute('height',height);svg.setAttribute('aria-hidden','true');
    for(let i=0;i<bars;i++){
      sig=(Math.imul(sig^sig>>>15,2246822519)+1013904223)>>>0;
      const ratio=.28+.62*((sig>>>8)%1000)/1000,h=Math.max(2,height*ratio),y=(height-h)/2;
      const rect=document.createElementNS('http://www.w3.org/2000/svg','rect');
      rect.setAttribute('x',x.toFixed(2));rect.setAttribute('y',y.toFixed(2));rect.setAttribute('width',bar.toFixed(2));rect.setAttribute('height',h.toFixed(2));
      rect.setAttribute('rx','0.8');rect.setAttribute('fill','currentColor');svg.append(rect);x+=bar+gap;
    }
    return svg;
  }

  function stopAudio(){
    if(audio){audio.pause();try{audio.currentTime=0;}catch(e){}}
    playing='';
    host?.querySelectorAll('.sfx-row.is-playing').forEach(node=>{
      node.classList.remove('is-playing');
      const button=node.querySelector('.sfx-play');
      if(button){button.replaceChildren(icon(PLAY,13));button.setAttribute('aria-label',`试听 ${node.dataset.name}`);button.setAttribute('aria-pressed','false');}
    });
  }

  function toggle(item,button,row){
    if(playing===item.id){stopAudio();return;}
    stopAudio();
    if(!audio)audio=new Audio();
    audio.src=item.audio_url;
    audio.volume=1;
    audio.onended=()=>stopAudio();
    audio.onerror=()=>{stopAudio();say('试听失败：音效文件无法播放');};
    playing=item.id;
    row.classList.add('is-playing');
    button.replaceChildren(icon(PAUSE,13));button.setAttribute('aria-pressed','true');button.setAttribute('aria-label',`停止试听 ${item.name}`);
    const promise=audio.play();
    if(promise&&promise.catch)promise.catch(()=>{stopAudio();});
  }

  async function insert(item,button){
    if(!window.hubEditor?.insertAudioAsset){say('请先打开剪辑台');return;}
    const row=button.closest('.sfx-row');
    row?.classList.add('is-busy');button.disabled=true;
    try{
      const asset=await json(`/api/editor/sfx/${encodeURIComponent(item.id)}/adopt`,{method:'POST',headers:{'X-Hub-Request':'1'}});
      window.hubEditor.insertAudioAsset({id:asset.id,name:asset.name},Number(asset.duration)||item.duration);
      item.uses=(item.uses||0)+1;
      say(`已把「${item.name}」插入到播放头`);
    }catch(error){
      say(`插入失败：${error.message}`);
    }finally{
      row?.classList.remove('is-busy');button.disabled=false;
    }
  }

  async function favorite(item,button){
    const on=!item.favorite;
    button.disabled=true;
    try{
      const data=await json(`/api/editor/sfx/${encodeURIComponent(item.id)}/favorite`,{method:'POST',headers:{'Content-Type':'application/json','X-Hub-Request':'1'},body:JSON.stringify({on})});
      item.favorite=!!data.favorite;
      button.classList.toggle('is-on',item.favorite);
      button.setAttribute('aria-pressed',String(item.favorite));
      button.replaceChildren(icon(STAR,13));
      button.title=item.favorite?'取消收藏':'收藏';
      say(item.favorite?`已收藏「${item.name}」`:`已取消收藏「${item.name}」`);
    }catch(error){
      say(`收藏失败：${error.message}`);
    }finally{button.disabled=false;}
  }

  function row(item){
    const node=el('div','','sfx-row');node.dataset.id=item.id;node.dataset.name=item.name;node.draggable=true;
    const play=el('button','','sfx-play');play.type='button';play.append(icon(PLAY,13));
    play.setAttribute('aria-pressed','false');play.setAttribute('aria-label',`试听 ${item.name}`);
    play.onclick=()=>toggle(item,play,node);
    const name=el('span',item.name,'sfx-name');
    const star=el('button','','sfx-star');star.type='button';star.append(icon(STAR,12));
    star.setAttribute('aria-pressed',String(item.favorite));
    star.title=item.favorite?'取消收藏':'收藏';star.onclick=()=>favorite(item,star);
    const add=el('button','','sfx-add');add.type='button';add.textContent='插入';
    add.title='复制到我的素材库并插入到播放头';
    add.onclick=()=>insert(item,add);
    const meta=el('div','','sfx-meta');
    const wave=el('span','','sfx-wave');wave.append(waveform(item.id));
    meta.append(wave,el('span',CATEGORY_LABEL(item.category),'sfx-tag'),el('span',duration(item.duration),'sfx-time'));
    if(item.uses)meta.append(el('span',`用过 ${item.uses} 次`,'sfx-uses'));
    node.append(play,name,star,add,meta);
    node.addEventListener('dragstart',event=>{
      if(event.target.closest('button')){event.preventDefault();return;}
      event.dataTransfer.setData('application/x-seedance-audio',`sfx:${item.id}`);
      event.dataTransfer.setData('text/plain',item.name);
      event.dataTransfer.effectAllowed='copy';
      say('拖到时间轴的音频轨道上即可放置');
    });
    return node;
  }

  function paint(){
    if(!listNode)return;
    const needle=query.trim().toLowerCase();
    const visible=items.filter(item=>{
      if(cat&&item.category!==cat)return false;
      if(!needle)return true;
      return `${item.name} ${item.name_en||''} ${CATEGORY_LABEL(item.category)} ${(item.tags||[]).join(' ')}`.toLowerCase().includes(needle);
    });
    stopAudio();
    listNode.replaceChildren(...visible.map(row));
    if(emptyNode){
      emptyNode.hidden=visible.length>0;
      emptyNode.textContent=failure||(loaded?`没有匹配「${query||CATEGORY_LABEL(cat)}」的音效`:'正在载入音效…');
    }
    if(countNode)countNode.textContent=loaded?`${visible.length} / ${items.length} 个音效`:'';
  }

  function chips(){
    if(!chipsNode)return;
    chipsNode.replaceChildren();
    const make=(key,text)=>{const b=el('button',text,'sfx-chip');b.type='button';b.dataset.cat=key;b.setAttribute('aria-pressed',String(cat===key));b.onclick=()=>{cat=key;chips();paint();};return b;};
    chipsNode.append(make('','全部'));
    for(const item of cats)if(item.count)chipsNode.append(make(item.key,`${item.label} ${item.count}`));
  }

  async function load(){
    if(loading)return;
    loading=true;failure='';
    if(emptyNode&&!loaded){emptyNode.hidden=false;emptyNode.textContent='正在载入音效…';}
    try{
      const data=await json('/api/editor/sfx');
      items=data.items||[];cats=data.categories||[];license=data.license||'';source=data.source||'';
      loaded=true;
      if(!items.length)failure='音效库为空，请运行 sfx_seed.py 重新下载';
      chips();paint();
      if(license){
        const from=(source||'mixkit.co').replace(/^https?:\/\//,'').split('/')[0];
        const credit=$('editor-sfx-credit');
        if(credit){credit.textContent=`音效来自 ${from} · 免费可商用、无需署名 · 点“插入”会复制一份到你的素材库`;credit.title=`${license}。来源：${source||'https://mixkit.co/free-sound-effects/'}。点“插入”会复制一份到你的素材库。`;}
      }
    }catch(error){
      failure=`载入失败：${error.message}`;paint();
    }finally{loading=false;}
  }

  function build(container,options){
    host=container;note=options.note;
    const page=el('div','','sfx-page');
    const search=el('label','','sfx-search');
    search.append(icon(SEARCH,14));
    const input=el('input');input.type='search';input.placeholder='搜索音效：转场、打击、提示…';input.setAttribute('aria-label','搜索内置音效');
    input.oninput=()=>{query=input.value;paint();};
    input.onkeydown=event=>{if(event.key==='Escape'){input.value='';query='';paint();}};
    search.append(input);
    const chipBar=el('div','','sfx-chips');chipBar.setAttribute('role','group');chipBar.setAttribute('aria-label','音效分类');
    const list=el('div','','sfx-list');list.id='editor-sfx-list';
    const empty=el('p','正在载入音效…','sfx-empty');
    const credit=el('p','','sfx-credit');credit.id='editor-sfx-credit';
    const counter=el('p','','sfx-count');counter.id='editor-sfx-count';
    page.append(search,chipBar,counter,credit,list,empty);
    container.append(page);
    listNode=list;chipsNode=chipBar;emptyNode=empty;countNode=counter;
    chips();
    if(!loaded)load();
  }

  function mount(){
    if(mounted||!window.hubAudioLibrary?.tab)return;
    const panel=$('editor-tool-audio');
    if(!panel)return;
    const host=window.hubAudioLibrary.tab('sfx','音效',build);
    if(!host)return;
    mounted=true;
    const button=panel.querySelector('button[data-tab="sfx"]');
    if(button)button.addEventListener('click',()=>{if(!loaded&&!loading)load();});
    window.addEventListener('keydown',event=>{if(event.key==='Escape'&&playing)stopAudio();});
  }

  window.addEventListener('hub-editor-shell-ready',mount);
  document.addEventListener('DOMContentLoaded',mount);
  window.addEventListener('hub-project',()=>{if(loaded&&mounted)load();});
  // Small read-only surface for verification scripts and the console.
  window.hubSfx={refresh:load,state:()=>({mounted,loaded,loading,failure,count:items.length,cat,query,playing})};
  mount();
})();

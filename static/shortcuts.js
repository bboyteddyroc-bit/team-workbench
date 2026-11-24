'use strict';
/* Timeline shortcut registry + settings window.
   Defaults follow CapCut (剪映专业版) desktop habits; every row can be rebound,
   given an extra alias, cleared or reset. Bindings live per browser profile. */
window.HubShortcuts=(()=>{
  const STORE='hub-shortcuts.v1';
  const GROUPS=['播放与定位','剪辑','时间轴视图','选择','工程'];
  const CATALOG=[
    {id:'play',group:'播放与定位',label:'播放 / 暂停',keys:['Space'],capcut:true},
    {id:'prevFrame',group:'播放与定位',label:'上一帧',keys:['ArrowLeft'],capcut:true},
    {id:'nextFrame',group:'播放与定位',label:'下一帧',keys:['ArrowRight'],capcut:true},
    {id:'back1s',group:'播放与定位',label:'后退 1 秒',keys:['Shift+ArrowLeft']},
    {id:'fwd1s',group:'播放与定位',label:'前进 1 秒',keys:['Shift+ArrowRight']},
    {id:'prevCut',group:'播放与定位',label:'上一个剪辑点',keys:['ArrowUp']},
    {id:'nextCut',group:'播放与定位',label:'下一个剪辑点',keys:['ArrowDown']},
    {id:'goStart',group:'播放与定位',label:'跳到开头',keys:['Home'],capcut:true},
    {id:'goEnd',group:'播放与定位',label:'跳到结尾',keys:['End'],capcut:true},

    {id:'split',group:'剪辑',label:'在播放头处分割',keys:['Ctrl+B'],capcut:true},
    {id:'deleteSelection',group:'剪辑',label:'删除所选片段',keys:['Delete','Backspace'],capcut:true},
    {id:'remove',group:'剪辑',label:'移除片段（保留源素材）',keys:['Shift+Delete']},
    {id:'copy',group:'剪辑',label:'复制所选',keys:['Ctrl+C'],capcut:true},
    {id:'cut',group:'剪辑',label:'剪切所选',keys:['Ctrl+X'],capcut:true},
    {id:'paste',group:'剪辑',label:'粘贴到播放头',keys:['Ctrl+V'],capcut:true},
    {id:'duplicate',group:'剪辑',label:'再制所选（紧跟其后）',keys:['Ctrl+D']},
    {id:'nudgeLeft',group:'剪辑',label:'所选片段前移 1 帧',keys:['Alt+ArrowLeft']},
    {id:'nudgeRight',group:'剪辑',label:'所选片段后移 1 帧',keys:['Alt+ArrowRight']},
    {id:'nudgeLeftSecond',group:'剪辑',label:'所选片段前移 1 秒',keys:['Alt+Shift+ArrowLeft']},
    {id:'nudgeRightSecond',group:'剪辑',label:'所选片段后移 1 秒',keys:['Alt+Shift+ArrowRight']},
    {id:'mute',group:'剪辑',label:'原声静音 / 恢复',keys:['M'],capcut:true},
    {id:'detach',group:'剪辑',label:'分离音频',keys:['Ctrl+Shift+S']},
    {id:'group',group:'剪辑',label:'成组',keys:['Ctrl+G'],capcut:true},
    {id:'compound',group:'剪辑',label:'合成复合片段',keys:['Alt+G']},
    {id:'ungroup',group:'剪辑',label:'解除组 / 复合',keys:['Ctrl+Shift+G']},
    {id:'speed',group:'剪辑',label:'打开变速面板',keys:['Alt+R']},
    {id:'addCaption',group:'剪辑',label:'添加字幕',keys:['T']},
    {id:'rippleIn',group:'剪辑',label:'波纹裁剪入点（裁到播放头，后面自动前移）',keys:['Q'],capcut:true},
    {id:'rippleOut',group:'剪辑',label:'波纹裁剪出点（裁到播放头，后面自动前移）',keys:['W'],capcut:true},

    {id:'zoomIn',group:'时间轴视图',label:'放大时间轴',keys:['Ctrl+=','Ctrl+Shift+=']},
    {id:'zoomOut',group:'时间轴视图',label:'缩小时间轴',keys:['Ctrl+-','Ctrl+Shift+-']},
    {id:'zoomFit',group:'时间轴视图',label:'时间轴适配宽度',keys:['Shift+Z']},
    {id:'zoomWheel',group:'时间轴视图',label:'滚轮缩放时间轴（以鼠标所在位置为锚点）',keys:['Ctrl+滚轮'],fixed:true},
    {id:'snapToggle',group:'时间轴视图',label:'吸附开关',keys:['N']},
    {id:'magnetToggle',group:'时间轴视图',label:'主轨磁吸开关',keys:['Ctrl+M']},
    {id:'linkToggle',group:'时间轴视图',label:'联动开关',keys:['Alt+L']},

    {id:'selectAll',group:'选择',label:'全选时间轴对象',keys:['Ctrl+A'],capcut:true},
    {id:'deselect',group:'选择',label:'取消选择',keys:['Escape']},

    {id:'undo',group:'工程',label:'撤销',keys:['Ctrl+Z'],capcut:true},
    {id:'redo',group:'工程',label:'重做',keys:['Ctrl+Y','Ctrl+Shift+Z'],capcut:true},
    {id:'save',group:'工程',label:'保存剪辑',keys:['Ctrl+S'],capcut:true},
    {id:'export',group:'工程',label:'导出 MP4',keys:['Ctrl+E'],capcut:true},
    {id:'shortcuts',group:'工程',label:'快捷键设置',keys:['Ctrl+/']}
  ];
  const DEFAULTS=new Map(CATALOG.map(item=>[item.id,[...item.keys]]));
  const ALIAS={'+':'=','_':'-','{':'[','}':']',':':';','"':"'",'<':',','>':'.','?':'/','|':'\\','~':'`','!':'1','@':'2','#':'3','$':'4','%':'5','^':'6','&':'7','*':'8','(':'9',')':'0'};
  const NAMED={' ':'Space',Spacebar:'Space',Esc:'Escape',Del:'Delete'};
  const GLYPH={ArrowLeft:'←',ArrowRight:'→',ArrowUp:'↑',ArrowDown:'↓',Space:'空格',Escape:'Esc',Delete:'Del',Backspace:'⌫',Enter:'Enter',Home:'Home',End:'End',PageUp:'PgUp',PageDown:'PgDn',Tab:'Tab'};
  const MAC=/Mac|iPhone|iPad|iPod/.test(navigator.platform||navigator.userAgent||'');
  const listeners=[];
  const handlers=new Map();

  function keyPart(event){
    let key=event.key;
    if(!key)return '';
    if(ALIAS[key])key=ALIAS[key];
    else if(NAMED[key])key=NAMED[key];
    else if(key.length===1)key=key.toUpperCase();
    return key;
  }
  function comboOf(event){
    const parts=[];
    if(event.ctrlKey||event.metaKey)parts.push('Ctrl');
    if(event.altKey)parts.push('Alt');
    if(event.shiftKey)parts.push('Shift');
    const key=keyPart(event);
    if(!key||['Control','Alt','Shift','Meta'].includes(key))return '';
    parts.push(key);
    return parts.join('+');
  }
  function format(combo){
    if(!combo)return '未设置';
    const parts=combo.split('+').map(part=>{
      if(part==='Ctrl')return MAC?'⌘':'Ctrl';
      if(part==='Alt')return MAC?'⌥':'Alt';
      if(part==='Shift')return MAC?'⇧':'Shift';
      return GLYPH[part]||part;
    });
    return parts.join(MAC?'':'+');
  }
  function formatList(list){return (list||[]).filter(Boolean).map(format).join(' / ')||'未设置';}
  function read(){
    let stored={};
    try{stored=JSON.parse(localStorage.getItem(STORE)||'{}')||{};}catch{stored={};}
    const overrides=stored&&typeof stored.bindings==='object'&&stored.bindings?stored.bindings:{};
    const map=new Map();
    for(const item of CATALOG){
      const custom=overrides[item.id];
      map.set(item.id,Array.isArray(custom)?custom.filter(v=>typeof v==='string'&&v).slice(0,3):[...DEFAULTS.get(item.id)]);
    }
    return map;
  }
  let bindings=read();
  const current=id=>[...(bindings.get(id)||[])];
  const label=id=>formatList(bindings.get(id));
  const isCustom=id=>JSON.stringify(bindings.get(id)||[])!==JSON.stringify(DEFAULTS.get(id)||[]);
  function resolve(event){
    const combo=comboOf(event);
    if(!combo)return null;
    for(const item of CATALOG){if(item.fixed)continue;if((bindings.get(item.id)||[]).includes(combo))return {id:item.id,combo};}
    return null;
  }
  function register(map){
    if(typeof map==='string'){const [,fn]=arguments;handlers.set(map,fn);return;}
    for(const [id,fn]of Object.entries(map||{}))if(typeof fn==='function')handlers.set(id,fn);
  }
  function run(id,event){
    const fn=handlers.get(id);
    if(!fn)return false;
    try{fn(event);}catch(error){window.toast?.(error.message||String(error),true);}
    return true;
  }
  const notify=()=>listeners.forEach(fn=>{try{fn();}catch{}});
  const onChange=fn=>{listeners.push(fn);};

  /* ---------------- settings window ---------------- */
  let dialog=null,bodyEl=null,searchEl=null,statusEl=null,draft=new Map(),recording=null,recordTarget=null;
  const el=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node;};

  function ensureDialog(){
    if(dialog)return dialog;
    dialog=el('dialog','shortcut-dialog');
    dialog.id='shortcut-dialog';
    dialog.setAttribute('aria-label','快捷键设置');
    const head=el('header','sc-head');
    const titles=el('div');
    titles.append(el('h2',null,'快捷键设置'),el('p','fine','时间轴动作已按 CapCut 习惯预设，点任意键位可改成自己的组合。'));
    head.append(titles,el('span','sc-head-badge','CapCut 预设'));
    searchEl=el('input','sc-search');
    searchEl.type='search';
    searchEl.placeholder='搜索功能或当前快捷键';
    searchEl.setAttribute('aria-label','搜索快捷键');
    statusEl=el('span','sc-status');
    statusEl.setAttribute('role','status');
    const tools=el('div','sc-tools');
    tools.append(searchEl,statusEl);
    bodyEl=el('div','sc-body');
    const foot=el('footer','sc-foot');
    const resetAll=el('button','secondary','全部恢复默认');
    resetAll.type='button';
    resetAll.dataset.act='reset-all';
    const spacer=el('span','sc-spacer');
    const cancel=el('button','secondary','取消');
    cancel.type='button';
    cancel.dataset.act='cancel';
    const save=el('button','primary','保存');
    save.type='button';
    save.dataset.act='save';
    foot.append(resetAll,spacer,cancel,save);
    dialog.append(head,tools,bodyEl,foot);
    document.body.append(dialog);
    dialog.dataset.act='close';
    searchEl.addEventListener('input',()=>renderRows());
    dialog.addEventListener('click',event=>{
      const act=event.target.closest('[data-act]')?.dataset.act;
      if(act==='save')return commit();
      if(act==='cancel')return close();
      if(act==='reset-all'){draft=new Map(CATALOG.map(item=>[item.id,[...DEFAULTS.get(item.id)]]));statusEl.textContent='已载入 CapCut 预设，点保存生效';renderRows();return;}
      if(act==='close'&&event.target===dialog)close();
    });
    dialog.addEventListener('cancel',event=>{event.preventDefault();close();});
    return dialog;
  }

  function renderRows(){
    if(!dialog||!bodyEl)return;
    const needle=(searchEl?.value||'').trim().toLowerCase();
    bodyEl.replaceChildren();
    let shown=0;
    for(const group of GROUPS){
      const items=CATALOG.filter(item=>item.group===group);
      const matches=items.filter(item=>!needle||item.label.toLowerCase().includes(needle)||formatList(draft.get(item.id)).toLowerCase().includes(needle));
      if(!matches.length)continue;
      const section=el('section','sc-group');
      section.append(el('h3',null,group));
      const list=el('div','sc-list');
      for(const item of matches){list.append(row(item));shown++;}
      section.append(list);
      bodyEl.append(section);
    }
    if(!shown)bodyEl.append(el('p','sc-empty','没有匹配的功能'));
  }

  function row(item){
    const wrap=el('div','sc-row');
    wrap.dataset.id=item.id;
    if(recording?.id===item.id)wrap.classList.add('is-recording');
    const desc=el('div','sc-desc');
    desc.append(el('strong',null,item.label));
    const tags=el('div','sc-tags');
    if(item.capcut)tags.append(el('span','sc-tag capcut','CapCut'));
    if(item.fixed)tags.append(el('span','sc-tag is-fixed','固定'));
    if(JSON.stringify(draft.get(item.id)||[])!==JSON.stringify(DEFAULTS.get(item.id)||[]))tags.append(el('span','sc-tag changed','已修改'));
    if(tags.childNodes.length)desc.append(tags);
    const keys=el('div','sc-keys');
    if(item.fixed){
      /* 鼠标手势类快捷键没有键位组合，只做说明，不参与录制与改写。 */
      const chip=el('span','sc-chip is-fixed',formatList(item.keys));
      chip.title='鼠标手势固定快捷键，不支持修改';
      keys.append(chip);
      wrap.append(desc,keys);
      return wrap;
    }
    const list=draft.get(item.id)||[];
    const slots=Math.max(list.length,1);
    for(let slot=0;slot<slots;slot++){
      const combo=list[slot]||'';
      const chip=el('button','sc-chip',format(combo));
      chip.type='button';
      chip.dataset.slot=String(slot);
      if(!combo)chip.classList.add('empty');
      if(recording?.id===item.id&&recording.slot===slot)chip.classList.add('recording');
      chip.title=combo?'点击重新录制':'点击录制快捷键';
      chip.onclick=()=>beginRecord(item.id,slot);
      keys.append(chip);
      if(combo&&list.length>1){
        const drop=el('button','sc-chip-drop','×');
        drop.type='button';
        drop.title='删除这个备用快捷键';
        drop.onclick=()=>{const next=[...(draft.get(item.id)||[])];next.splice(slot,1);draft.set(item.id,next);stopRecord();renderRows();};
        keys.append(drop);
      }
    }
    if((draft.get(item.id)||[]).length<3){
      const add=el('button','sc-chip-add','+');
      add.type='button';
      add.title='添加备用快捷键';
      add.onclick=()=>{const next=[...(draft.get(item.id)||[])];next.push('');draft.set(item.id,next);beginRecord(item.id,next.length-1);};
      keys.append(add);
    }
    const reset=el('button','sc-reset','恢复默认');
    reset.type='button';
    reset.disabled=!isCustom(item.id)&&JSON.stringify(draft.get(item.id)||[])===JSON.stringify(DEFAULTS.get(item.id)||[]);
    reset.onclick=()=>{draft.set(item.id,[...DEFAULTS.get(item.id)]);stopRecord();statusEl.textContent='';renderRows();};
    keys.append(reset);
    wrap.append(desc,keys);
    return wrap;
  }

  function beginRecord(id,slot){
    ensureDialog();
    stopRecord();
    recording={id,slot};
    statusEl.textContent='正在录制：按下新的组合键，Esc 取消';
    renderRows();
    recordTarget=bodyEl.querySelector(`.sc-row[data-id="${id}"] .sc-chip[data-slot="${slot}"]`);
    recordTarget?.classList.add('recording');
    window.addEventListener('keydown',recordKey,true);
  }
  function stopRecord(){
    window.removeEventListener('keydown',recordKey,true);
    recording=null;
    recordTarget=null;
  }
  function recordKey(event){
    if(!recording)return;
    if(['Shift','Control','Alt','Meta'].includes(event.key))return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if(event.key==='Escape'){stopRecord();statusEl.textContent='';renderRows();return;}
    const combo=comboOf(event);
    if(!combo)return;
    const owner=CATALOG.find(item=>item.id!==recording.id&&(draft.get(item.id)||[]).includes(combo));
    if(owner){
      statusEl.textContent='「'+format(combo)+'」已被「'+owner.label+'」占用，请先清除那个键位';
      stopRecord();
      renderRows();
      return;
    }
    const list=[...(draft.get(recording.id)||[])];
    list[recording.slot]=combo;
    draft.set(recording.id,list);
    stopRecord();
    statusEl.textContent='已改为 '+format(combo)+'，点保存生效';
    renderRows();
  }

  function openSettings(){
    ensureDialog();
    draft=new Map(CATALOG.map(item=>[item.id,current(item.id)]));
    if(searchEl)searchEl.value='';
    statusEl.textContent='';
    hintShortcutLabels();
    renderRows();
    if(!dialog.open)dialog.showModal();
    setTimeout(()=>searchEl?.focus({preventScroll:true}),0);
  }
  function close(){
    stopRecord();
    statusEl.textContent='';
    if(dialog?.open)dialog.close();
  }
  function commit(){
    const overrides={};
    for(const item of CATALOG){
      if(item.fixed)continue;
      const next=draft.get(item.id)||[];
      if(JSON.stringify(next)!==JSON.stringify(DEFAULTS.get(item.id)||[]))overrides[item.id]=next;
    }
    try{
      if(Object.keys(overrides).length)localStorage.setItem(STORE,JSON.stringify({v:1,bindings:overrides}));
      else localStorage.removeItem(STORE);
    }catch{window.toast?.('浏览器不允许保存设置',true);return;}
    bindings=new Map(CATALOG.map(item=>[item.id,[...(overrides[item.id]||DEFAULTS.get(item.id))]]));
    close();
    notify();
    hintShortcutLabels();
    window.toast?.('快捷键已更新');
  }
  function resetAll(){
    try{localStorage.removeItem(STORE);}catch{}
    bindings=read();
    notify();
    hintShortcutLabels();
  }
  // Any element can show its key with data-shortcut="split"; keep those labels fresh.
  function hintShortcutLabels(){
    for(const node of document.querySelectorAll('[data-shortcut]')){
      const text=label(node.dataset.shortcut);
      if(node.tagName==='KBD'||node.dataset.shortcutInline==='1')node.textContent=text;
      else node.title=label(node.dataset.shortcut);
    }
    window.dispatchEvent(new CustomEvent('hub-shortcuts-changed'));
  }

  return {catalog:CATALOG,groups:GROUPS,defaults:id=>[...(DEFAULTS.get(id)||[])],binding:current,label,formatList,isCustom,resolve,register,run,onChange,openSettings,closeSettings:close,resetAll,hintShortcutLabels,format};
})();

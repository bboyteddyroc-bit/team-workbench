/* AI 配音面板：音色选择、试听、生成、状态。
   复用中台绿色/浅色风格，追加在编辑器的「字幕与配音」区域内。
   明确区分：示例试听 = 播放已有音频；用我的文案试读 = 真实计费调用。 */

(function () {
  'use strict';

  const $ = (id) => document.getElementById(id);
  let voices = [];
  let config = { configured: false, enabled: false, model: 's2.1-pro', format: 'wav' };
  let isAdmin = false;
  let selectedVoice = null;
  let currentJob = null;
  let pollTimer = null;
  let sampleAudio = null;          // 单一示例播放器，避免与编辑器预览叠音
  let previewAudio = null;
  let lastRequestKey = null, lastRequestBody = null;
  const activeRequests=new Set();
  let voicePage=1,hasMore=false,catalogEpoch=0,searchTimer=null,selectedName="",submitting=false;
  const handledReady=new Set();

  function el(tag, text, cls) {
    const n = document.createElement(tag);
    if (text != null) n.textContent = text;
    if (cls) n.className = cls;
    return n;
  }

  async function api(path, options) {
    const epoch=refreshEpoch;
    const controller = new AbortController();activeRequests.add(controller);
    const timer = setTimeout(() => controller.abort(), 30000);
    try { return await fetch(path, Object.assign({
      headers: { 'Content-Type': 'application/json', 'X-Hub-Request':'1' },
      credentials: 'same-origin', signal: controller.signal
    }, options || {})).then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if(epoch!==refreshEpoch)throw new DOMException('Session changed','AbortError');
      if (!r.ok) throw new Error(data.detail || data.error || ('请求失败 ' + r.status));
      return data;
    }); } catch (e) {
      if (e.name === 'AbortError') throw new Error('试听请求超时，未自动重试；提交结果可能仍在处理中，请勿重复提交。');
      throw e;
    } finally { clearTimeout(timer);activeRequests.delete(controller); }
  }

  function stopAllAudio() {
    document.querySelectorAll('audio.hvn-native').forEach(a=>a.pause());
    if (sampleAudio) { sampleAudio.pause(); sampleAudio = null; }
    if (previewAudio) { previewAudio.pause(); previewAudio = null; }
    // 暂停编辑器预览，避免同时出声
    window.hubEditor?.pause();
  }

  function status(text, kind) {
    const box = $('voice-status');
    if (!box) return;
    box.textContent = text || '';
    box.dataset.kind = kind || '';
    box.hidden = !text;
  }

  // ---------------------------------------------------------- 配置提示

  function renderConfigNotice() {
    const box = $('voice-config-notice');
    if (!box) return;
    box.replaceChildren();
    if (!config.configured) {
      box.hidden = false;
      box.append(el('p', 'AI 配音尚未启用：管理员还没有配置 Fish Audio API Key。', 'fine warn'));
      if (isAdmin) box.append(adminConfigButton());
      return;
    }
    if (!config.enabled) {
      box.hidden = false;
      box.append(el('p', 'AI 配音已配置但当前处于停用状态。', 'fine warn'));
      if (isAdmin) box.append(adminConfigButton());
      return;
    }
    box.hidden = !isAdmin;
    if (isAdmin) box.append(adminConfigButton());
  }

  function adminConfigButton() {
    const b = el('button', '配置配音服务', 'text-button');
    b.type = 'button';
    b.onclick = openConfigDialog;
    return b;
  }

  // ---------------------------------------------------------- 音色

  function filteredVoices() {
    const q = ($('voice-search')?.value || '').trim().toLowerCase();
    const onlyFav = $('voice-only-fav')?.checked;
    const lang = $('voice-lang-filter')?.value || '';
    return voices.filter((v) => {
      if (!v.enabled && !isAdmin) return false;
      if (!v.reference_id && !isAdmin) return false;
      if (onlyFav && !v.favorite) return false;
      if (lang && ($('voice-only-fav')?.checked||$('voice-library-source')?.value==='saved') && !(v.languages||[v.language]).some(l=>l.toLowerCase().split('-')[0]===lang)) return false;
      if (q && ($('voice-only-fav')?.checked||$('voice-library-source')?.value==='saved')) {
        const hay = (v.name + ' ' + v.language + ' ' + v.style).toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
  }

  function renderVoices() {
    const list = $('voice-list');
    if (!list) return;
    list.replaceChildren();
    const rows = filteredVoices();
    if (!rows.length) {
      list.append(el('p', '没有匹配的音色。', 'fine'));
      return;
    }
    rows.forEach((v) => {
      const card = el('div', null, 'voice-card' + (selectedVoice === v.id ? ' selected' : ''));
      card.dataset.voiceId = v.id;

      const head = el('div', null, 'voice-card-head');
      const title = el('strong', v.name);
      head.append(title);
      if (v.language) head.append(el('span', v.language, 'voice-tag'));
      if (v.style) head.append(el('span', v.style, 'voice-tag soft'));
      card.append(head);

      if (!v.reference_id) {
        card.append(el('p', '管理员尚未填写真实 reference_id，暂不可用。', 'fine warn'));
      }

      const actions = el('div', null, 'voice-card-actions');

      const listen=el('button','试听文案','secondary');listen.type='button';listen.disabled=!v.usable;
      const player=el('audio');player.controls=true;player.hidden=true;player.preload='none';
      listen.onclick=()=>trialVoice(v,listen,player);actions.append(listen);
      // 选择音色
      const use = el('button', selectedVoice === v.id ? '已选此音色' : '使用此音色', 'secondary');
      use.type = 'button';
      use.disabled = !v.usable;
      use.onclick = () => {
        selectedVoice = v.id;selectedName=v.name;$('voice-selected-name').textContent='已选音色：'+v.name;
        renderVoices();
        updateGenerateButton();
        status('已选择音色：' + v.name, 'ok');
        showWorkspace('compose');
        $('voice-choose')?.focus({preventScroll:true});
      };
      actions.append(use);

      // 收藏
      const fav = el('button', v.favorite ? '★ 已收藏' : '☆ 收藏', 'text-button');
      fav.type = 'button';
      fav.setAttribute('aria-pressed', String(v.favorite));
      fav.onclick = async () => {
        try {
          await api('/api/voice/voices/' + v.id + '/favorite', { method: 'POST' });
          await loadVoices();
        } catch (e) { status(e.message, 'error'); }
      };
      actions.append(fav);

      if (isAdmin && !v.official) {
        const edit = el('button', '编辑', 'text-button');
        edit.type = 'button';
        edit.onclick = () => openVoiceDialog(v);
        actions.append(edit);
      }
      card.append(actions);
      list.append(card);
    });
  }

  let trialBusy=false;
  const trialCache=new Map();
  const trialPending=new Map();
  async function trialVoice(v,button,player){
    const text=currentText(),epoch=refreshEpoch,speed=Number($('voice-speed')?.value||1);
    if(!text){status('请先输入配音文案','error');$('voice-text').focus();return;}
    if(trialBusy){status('正在生成试听，请稍候');return;}
    const cacheKey=JSON.stringify([epoch,v.id,text,speed]);
    trialBusy=true;button.disabled=true;button.textContent='生成试听…';
    try{
      let url=trialCache.get(cacheKey);
      if(!url){
        let pending=trialPending.get(cacheKey);
        if(!pending){pending={key:crypto.randomUUID()};trialPending.set(cacheKey,pending);}
        const data=pending.id ? await api('/api/voice/jobs/'+pending.id) : await api('/api/voice/jobs',{method:'POST',body:JSON.stringify({request_key:pending.key,voice_id:v.id,text,speed,format:'mp3',source:'manual',auto_asset:false,auto_timeline:false})});
        if(epoch!==refreshEpoch)return;
        let job=data.job;
        pending.id=job.id;
        const deadline=Date.now()+240000;
        while(epoch===refreshEpoch&&['queued','running'].includes(job.state)){
          if(Date.now()>deadline)throw Error('试听仍在处理中，已停止等待。再次点击会查询原任务，不会重新生成。');
          status('正在生成文案试听 · 消耗配音额度');await new Promise(resolve=>setTimeout(resolve,2000));
          if(epoch!==refreshEpoch)return;
          job=(await api('/api/voice/jobs/'+job.id)).job;
        }
        if(epoch!==refreshEpoch)return;
        if(job.state!=='ready'){trialPending.delete(cacheKey);throw Error(job.error||'试听生成失败，未自动重试');}
        url=job.audio_url||('/api/voice/jobs/'+job.id+'/audio');trialCache.set(cacheKey,url);
        trialPending.delete(cacheKey);
      }
      if(epoch!==refreshEpoch)return;
      if(!button.isConnected){status('试听已生成，重新点击同一音色可播放','ok');return;}
      stopAllAudio();player.src=url;player.hidden=false;if(!player.isConnected)button.closest('.voice-card').append(player);previewAudio=player;
      try{await player.play();}catch(e){if(e&&e.name==='AbortError')return;status('试听已生成，点击播放即可');return;}
      status('正在试听当前文案','ok');
    }catch(e){if(epoch===refreshEpoch)status(e.message,'error');}
    finally{if(epoch===refreshEpoch){trialBusy=false;button.disabled=!v.usable;button.textContent='试听文案';}}
  }

  async function loadVoices(forceRefresh=false) {
    const token=++catalogEpoch,epoch=refreshEpoch;
    $('voice-list').textContent='正在读取音色库…';
    try {
      const favorites=$('voice-only-fav')?.checked,local=favorites||$('voice-library-source')?.value==='saved';
      const query=new URLSearchParams({title:$('voice-search')?.value||'',language:$('voice-lang-filter')?.value||'',page:String(voicePage)});
      if(forceRefresh===true)query.set('refresh','true');
      const data=await api(local?'/api/voice/voices':'/api/voice/catalog?'+query);
      if(token!==catalogEpoch||epoch!==refreshEpoch)return;
      voices=data.voices||[];hasMore=!local&&!!data.has_more;
      $('voice-page').textContent=local?(favorites?'我的收藏':'已保存音色'):'第 '+voicePage+' 页';
      $('voice-prev').disabled=local||voicePage<=1;$('voice-next').disabled=!hasMore;
      renderVoices();updateGenerateButton();
    }catch(e){if(token!==catalogEpoch||epoch!==refreshEpoch)return;$('voice-list').textContent=e.message;$('voice-next').disabled=true;}
  }

  // ---------------------------------------------------------- 生成

  function voiceCaptions(){
    const all=window.hubEditor?.current()?.body.captions||[];
    const indices=window.hubEditor?.captionSelection()||[];
    return ($('voice-source')?.value==='selected'?all.filter((c,i)=>indices.includes(i)):all).filter(c=>c.text?.trim()).sort((a,b)=>a.start-b.start);
  }
  function currentText() {
    return ($('voice-text')?.value||'').trim();
  }
  function syncCaptionState(){
    $('voice-source').value='manual';const manual=true;$('voice-manual-field').hidden=!manual;
    const text=currentText();$('voice-caption-summary').textContent=manual?text.length+' 字':voiceCaptions().length+' 条字幕 · '+text.length+' 字；字幕修改会直接用于下一次配音';
    updateGenerateButton();
  }

  function updateGenerateButton() {
    const btn = $('voice-generate');
    if (!btn) return;
    const ready = config.configured && config.enabled && !!selectedVoice && !!currentText() && !submitting && !['queued','running'].includes(currentJob?.state);
    btn.disabled = !ready;
    if (!config.configured) btn.title = '管理员尚未配置配音服务';
    else if (!selectedVoice) btn.title = '请先选择音色';
    else if (!currentText()) btn.title = '请填写配音文案';
    else btn.title = '';
  }

  async function generate() {
    if (submitting || currentJob && ['queued', 'running'].includes(currentJob.state)) {
      status('已有配音任务在进行中', 'error');
      return;
    }
    const epoch=refreshEpoch;
    const text = currentText();
    if(!window.hubEditor?.current()){status('请先打开剪辑台','error');return;}
    const insertAt = $('voice-insert-mode')?.value === 'playhead'?Number(window.hubEditor?.position()||0):$('voice-insert-mode')?.value==='caption'?Number(voiceCaptions()[0]?.start||0):0;
    const indices=$('voice-source')?.value==='selected'?(window.hubEditor?.captionSelection()||[]):null;
    if(indices&& !indices.length){status('请先勾选需要配音的字幕','error');return;}
    const fromSubtitles=$('voice-source')?.value!=='manual';
    // 每次点击生成新的 request_key；重复点击由后端幂等 + 前端禁用双重保护
    const key = lastRequestKey || (crypto?.randomUUID ? crypto.randomUUID() : String(Date.now()));
    lastRequestKey = key;
    const btn = $('voice-generate');
    btn.disabled = true;
    submitting=true;status('正在提交…');
    try {
      if(lastRequestKey&&lastRequestBody){
        status('先核对上次提交，不能将修改后的内容当成原请求重试','warn');
        const prior=await api('/api/voice/request-status?request_key='+encodeURIComponent(lastRequestKey));
        if(epoch!==refreshEpoch)return;
        if(!prior.found){status('暂未查到上次任务，可能仍在提交中。保留原请求标识，请稍后再次核对；本次未创建新任务。','warn');return;}
        currentJob=prior.job;pollJob();return;
      }
      const project=await window.hubEditor.save(),current=window.hubEditor.current();
      if(epoch!==refreshEpoch)return;
      if(!project?.id||window.hubEditor.isDirty()||current?.id!==project.id||current?.version!==project.version)throw Error('剪辑已切换或仍有未保存更改，请核对当前项目后再生成配音');
      lastRequestBody={
          request_key: key,
          text: text,
          voice_id: selectedVoice,
          speed: Number($('voice-speed')?.value || 1),
          insert_at: insertAt,
          make_captions:false,format:'mp3',source:fromSubtitles?'subtitles':'manual',caption_indices:indices,project_version:project.version,auto_asset:true,auto_timeline:!!$('voice-auto-timeline')?.checked,
          project_id: project.id
      };
      const data=await api('/api/voice/jobs',{method:'POST',body:JSON.stringify(lastRequestBody)});
      if(epoch!==refreshEpoch)return;
      currentJob = data.job;
      status('已提交，等待上游合成…这是真实调用，会产生 Fish Audio 额度消耗', 'warn');
      pollJob();
    } catch (e) {
      if(epoch===refreshEpoch)status(e.message, 'error');
    } finally {if(epoch===refreshEpoch){submitting=false;updateGenerateButton();}}
  }

  function pollJob() {
    clearTimeout(pollTimer);
    if (!currentJob) return;
    const token=refreshEpoch,id=currentJob.id;
    const tick = async () => {
      try {
        const data = await api('/api/voice/jobs/' + id);
        if(token!==refreshEpoch||currentJob?.id!==id)return;
        currentJob = data.job;
        renderJob();
        if (['queued', 'running'].includes(currentJob.state)||currentJob.state==='ready'&&currentJob.completion_state==='pending') {
          pollTimer = setTimeout(tick, 2000);
        } else {
          lastRequestKey = null;lastRequestBody=null;
          updateGenerateButton();
          await applyReady(currentJob);
        }
      } catch (e) {
        if(token===refreshEpoch)status(e.message, 'error');
      }
    };
    tick();
  }

  async function applyReady(job){
    const epoch=refreshEpoch;
    if(job.state!=='ready'||handledReady.has(job.id)||job.completion_state==='pending')return;
    handledReady.add(job.id);
    window.hubAudioLibrary?.refresh();
    if(job.timeline_status==='added'){
      const current=window.hubEditor?.current();
      if(current?.id===job.project_id&&!window.hubEditor.isDirty()){
        const refreshed=await window.hubEditor.refreshVoiceProject(job.project_id);
        if(epoch!==refreshEpoch)return;
        status(refreshed?'MP3 已保存到素材库，并加入配音轨':'MP3 已加入原剪辑；当前有新编辑，请确认后重新打开剪辑',refreshed?'ok':'warn');
      }else status('MP3 已保存并加入原剪辑；当前有其他编辑内容，请保存或确认后重新打开原剪辑','warn');
    }else if(job.workflow_error)status('MP3 已生成。'+job.workflow_error,'warn');
    else if(job.asset_id)status('MP3 已自动保存到素材库','ok');
  }

  const STATE_TEXT = {
    queued: '排队中', running: '合成中', ready: '已完成', failed: '失败'
  };

  function renderJob() {
    const box = $('voice-result');
    if (!box) return;
    box.replaceChildren();
    if (!currentJob) { box.hidden = true; return; }
    box.hidden = false;

    box.append(el('p', '状态：' + (STATE_TEXT[currentJob.state] || currentJob.state)
      + (currentJob.state === 'ready' ? '（时长 ' + currentJob.duration.toFixed(2) + ' 秒）' : ''), 'fine'));

    if(currentJob.workflow_error)box.append(el('p',currentJob.workflow_error,'fine warn'));
    if(currentJob.asset_id)box.append(el('p','已自动保存到音频素材库','fine'));
    if (currentJob.error) box.append(el('p', currentJob.error, 'fine warn'));
    (currentJob.warnings || []).forEach((w) => box.append(el('p', w, 'fine warn')));

    if (currentJob.state === 'ready') {
      const actions = el('div', null, 'voice-card-actions');

      const preview=el('audio');preview.controls=true;preview.preload='metadata';
      preview.src=currentJob.audio_url;preview.setAttribute('aria-label','试听生成配音');box.append(preview);
      const add = el('button', '加入时间轴', 'secondary');
      add.type = 'button';
      add.onclick = () => addToTimeline(currentJob);
      if(currentJob.timeline_status==='added'){add.textContent='已加入配音轨';add.disabled=true;}
      actions.append(add);
      const format=currentJob.format||'mp3';
      const download=el('a','下载 '+format.toUpperCase(),'secondary');download.href=currentJob.audio_url+'?download=true';download.download='配音.'+format;actions.append(download);
      const asset=el('button','保存到素材库','secondary');asset.type='button';
      const readyJob=currentJob;
      asset.onclick=async()=>{asset.disabled=true;try{await api('/api/voice/jobs/'+readyJob.id+'/asset',{method:'POST',body:'{}'});status('已保存到素材库的音频分类','ok');}catch(e){status(e.message,'error');}finally{asset.disabled=false;}};
      actions.append(asset);

      box.append(actions);

      const capCount = (currentJob.captions || []).length;
      box.append(el('p', capCount
        ? '已生成 ' + capCount + ' 条同步字幕，可选择加入。'
        : '原字幕保持不变；配音按文本顺序连续朗读。', 'fine'));
    }
  }

  function addToTimeline(job) {
    if (!window.hubEditor?.current()) { status('请先打开剪辑台', 'error'); return; }
    const handler = window.hubEditor?.insertVoice;
    if (typeof handler !== 'function') {
      status('剪辑台尚未就绪，请刷新后重试', 'error');
      return;
    }
    try {
      handler(job);
      status('已加入时间轴', 'ok');
    } catch (e) {
      status(e.message, 'error');
    }
  }

  // ---------------------------------------------------------- 管理员对话框

  function openConfigDialog() {
    if (!isAdmin) { status('只有管理员可以配置配音服务', 'error'); return; }
    const dlg = $('voice-config-dialog');
    if (!dlg) return;
    $('voice-cfg-model').value = config.model || 's2.1-pro';
    $('voice-cfg-format').value = config.format || 'wav';
    $('voice-cfg-enabled').checked = !!config.enabled;
    $('voice-cfg-key').value = '';
    $('voice-cfg-note').textContent = config.configured
      ? '已配置密钥（出于安全不回显）。留空表示不修改。'
      : '尚未配置密钥。';
    dlg.hidden = false;
    dlg.showModal();
  }

  async function saveConfig() {
    const epoch=refreshEpoch;
    try {
      const body = {
        model: $('voice-cfg-model').value,
        format: $('voice-cfg-format').value,
        enabled: $('voice-cfg-enabled').checked
      };
      const key = $('voice-cfg-key').value.trim();
      if (key) body.api_key = key;
      const data = await api('/api/voice/config', { method: 'POST', body: JSON.stringify(body) });
      if(epoch!==refreshEpoch)return;
      config = data.config;
      $('voice-cfg-key').value = '';
      $('voice-config-dialog').close();
      renderConfigNotice();
      updateGenerateButton();
      status('配置已保存', 'ok');
    } catch (e) {
      if(epoch===refreshEpoch)$('voice-cfg-note').textContent = e.message;
    }
  }

  function openVoiceDialog(voice) {
    if (!isAdmin) { status('只有管理员可以维护音色', 'error'); return; }
    const dlg = $('voice-edit-dialog');
    if (!dlg) return;
    $('voice-edit-id').value = voice ? voice.id : '';
    $('voice-edit-name').value = voice ? voice.name : '';
    $('voice-edit-ref').value = voice ? voice.reference_id : '';
    $('voice-edit-lang').value = voice ? voice.language : 'zh-CN';
    $('voice-edit-style').value = voice ? voice.style : '';
    $('voice-edit-enabled').checked = voice ? voice.enabled : true;
    $('voice-edit-sample').value = '';
    dlg.hidden = false;
    dlg.showModal();
  }

  async function saveVoice() {
    const epoch=refreshEpoch;
    const id = $('voice-edit-id').value;
    const payload = {
      name: $('voice-edit-name').value,
      reference_id: $('voice-edit-ref').value,
      language: $('voice-edit-lang').value,
      style: $('voice-edit-style').value,
      enabled: $('voice-edit-enabled').checked
    };
    try {
      let vid = id;
      if (id) await api('/api/voice/voices/' + id, { method: 'PUT', body: JSON.stringify(payload) });
      else {
        const data = await api('/api/voice/voices', { method: 'POST', body: JSON.stringify(payload) });
        vid = data.id;
      }
      if(epoch!==refreshEpoch)return;
      const file = $('voice-edit-sample').files[0];
      if (file) {
        const fd = new FormData();
        fd.append('file', file);
        const r = await fetch('/api/voice/voices/' + vid + '/sample', { method: 'POST', headers:{'X-Hub-Request':'1'}, body: fd, credentials: 'same-origin' });
        if(epoch!==refreshEpoch)return;
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          throw new Error(d.detail || '示例音频上传失败');
        }
      }
      $('voice-edit-dialog').close();
      await loadVoices();
      status('音色已保存', 'ok');
    } catch (e) {
      if(epoch===refreshEpoch)$('voice-edit-note').textContent = e.message;
    }
  }

  // ---------------------------------------------------------- 初始化

  let initialized=false,refreshEpoch=0;
  function showWorkspace(name) {
    for (const key of ['compose','library']) {
      const active=key===name, tab=$('voice-tab-'+key);
      if(tab){tab.setAttribute('aria-selected',String(active));tab.classList.toggle('active',active);tab.tabIndex=active?0:-1;}
      if($('voice-'+key)) $('voice-'+key).hidden=!active;
    }
  }
  function bindWorkspace() {
    const tabs=['compose','library'].map(key=>$('voice-tab-'+key));
    tabs.forEach((tab,i)=>{
      if(!tab||tab.dataset.bound)return;
      tab.dataset.bound='1';
      tab.onclick=()=>showWorkspace(i?'library':'compose');
      tab.onkeydown=e=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
        e.preventDefault();e.stopPropagation();
        const next=e.key==='Home'?0:e.key==='End'?1:1-i;
        tabs[next].click();tabs[next].focus();
      };
    });
    if($('voice-choose'))$('voice-choose').onclick=()=>{showWorkspace('library');$('voice-tab-library')?.focus({preventScroll:true});};
  }
  async function refreshJobs(){
    const token=refreshEpoch;
    const data=await api('/api/voice/jobs');if(token!==refreshEpoch)return;
    const jobs=data.jobs||[];
    currentJob=jobs.find(j=>['queued','running'].includes(j.state)||(j.state==='ready'&&j.completion_state==='pending'))||null;
    renderJob();pollJob();
  }
  async function init() {
    if (!$('voice-panel')) return;
    bindWorkspace();
    $('voice-cfg-format')?.querySelector('option[value=pcm]')?.remove();
    const token=refreshEpoch;
    try {
      const cfg = await api('/api/voice/config');
      if(token!==refreshEpoch)return;
      config = cfg.config;
      isAdmin = !!cfg.admin;
      $('voice-new').hidden=!isAdmin;
      renderConfigNotice();
      await loadVoices();
      await refreshJobs();
    } catch (e) {
      if(token===refreshEpoch)status('无法读取配音配置：' + e.message, 'error');
    }

    if(initialized)return;initialized=true;
    $('voice-text')?.addEventListener('input',syncCaptionState);
    $('voice-source')?.addEventListener('change',syncCaptionState);
    window.addEventListener('hub-project',syncCaptionState);
    window.addEventListener('hub-caption-selection',syncCaptionState);
    syncCaptionState();
    // 「读取全部字幕到文案」：切到手动模式并填入全部字幕文本
    $('voice-read-all')?.addEventListener('click', () => {
      const all = window.hubEditor?.current()?.body.captions || [];
      const rows = all.filter(c => c.text && String(c.text).trim()).sort((a, b) => a.start - b.start);
      if (!rows.length) { status('当前工程还没有字幕', 'error'); return; }
      const src = $('voice-source');
      if (src) src.value = 'manual';
      const box = $('voice-text');
      if (box) box.value = rows.map(c => String(c.text).trim()).join('\n');
      syncCaptionState();
      status('已读取 ' + rows.length + ' 条字幕到文案框', 'ok');
    });
    $('voice-generate')?.addEventListener('click', generate);
    $('voice-speed')?.addEventListener('input', () => {
      const v = $('voice-speed').value;
      const out = $('voice-speed-value');
      if (out) out.textContent = Number(v).toFixed(2) + '×';
    });
    $('voice-search')?.addEventListener('input',()=>{clearTimeout(searchTimer);searchTimer=setTimeout(()=>{voicePage=1;loadVoices();},350);});
    $('voice-only-fav')?.addEventListener('change',()=>{voicePage=1;loadVoices();});
    $('voice-lang-filter')?.addEventListener('change',()=>{voicePage=1;loadVoices();});
    $('voice-prev')?.addEventListener('click',()=>{voicePage=Math.max(1,voicePage-1);loadVoices();});
    $('voice-next')?.addEventListener('click',()=>{if(hasMore){voicePage++;loadVoices();}});
    $('voice-library-source')?.addEventListener('change',()=>{voicePage=1;loadVoices();});
    $('voice-refresh')?.addEventListener('click', () => loadVoices(true));
    $('voice-new')?.addEventListener('click', () => openVoiceDialog(null));
    $('voice-config-save')?.addEventListener('click', saveConfig);
    $('voice-edit-save')?.addEventListener('click', saveVoice);

    // 页面卸载时停止音频，避免背景播放
    window.addEventListener('beforeunload', stopAllAudio);
  }

  function reset(){
    refreshEpoch++;catalogEpoch++;
    activeRequests.forEach(c=>c.abort());activeRequests.clear();
    trialBusy=false;submitting=false;trialCache.clear();trialPending.clear();
    clearTimeout(searchTimer);clearTimeout(pollTimer);handledReady.clear();
    currentJob=null;lastRequestKey=null;lastRequestBody=null;voices=[];selectedVoice=null;selectedName='';voicePage=1;hasMore=false;
    isAdmin=false;config={configured:false,enabled:false,model:'s2.1-pro',format:'wav'};
    stopAllAudio();
    for(const id of ['voice-text','voice-search','voice-cfg-key','voice-edit-id','voice-edit-name','voice-edit-ref','voice-edit-style','voice-edit-sample'])if($(id))$(id).value='';
    for(const id of ['voice-cfg-note','voice-edit-note','voice-list','voice-caption-summary'])if($(id))$(id).textContent='';
    for(const id of ['voice-config-dialog','voice-edit-dialog'])if($(id)?.open)$(id).close();
    if($('voice-speed'))$('voice-speed').value='1';if($('voice-speed-value'))$('voice-speed-value').textContent='1.00×';
    if($('voice-source'))$('voice-source').value='manual';if($('voice-insert-mode'))$('voice-insert-mode').value='start';
    for(const id of ['voice-only-fav','voice-auto-timeline','voice-cfg-enabled'])if($(id))$(id).checked=false;
    renderJob();status('');updateGenerateButton();$('voice-job-history')?.replaceChildren();
  }
  window.voicePanel = { init, loadVoices, stopAllAudio, reset, get job() { return currentJob; } };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();


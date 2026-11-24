/* Vanilla adaptation of beUI Streaming Response for the existing hub. */
'use strict';
(()=>{
  const reduced=()=>window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
  const makeAction=(label,icon,handler)=>{
    const button=document.createElement('button');
    button.type='button';button.className='assistant-response-action';
    button.textContent=icon;button.title=label;button.setAttribute('aria-label',label);
    button.addEventListener('click',handler);return button;
  };
  const addActions=(article,text)=>{
    if(article.querySelector('.assistant-response-actions'))return;
    const actions=document.createElement('div');actions.className='assistant-response-actions';
    let copyTimer=0;
    const copy=makeAction('复制回答','□',async()=>{
      try{await navigator.clipboard.writeText(text);copy.textContent='✓';copy.title='已复制';
        clearTimeout(copyTimer);copyTimer=setTimeout(()=>{copy.textContent='□';copy.title='复制回答';},1600);
      }catch{copy.title='复制失败';}
    });
    let rating=null;
    const rate=(value,active,other)=>{rating=rating===value?null:value;active.setAttribute('aria-pressed',String(rating===value));other.setAttribute('aria-pressed','false');};
    const up=makeAction('有帮助','↑',()=>rate('up',up,down));
    const down=makeAction('没有帮助','↓',()=>rate('down',down,up));
    up.setAttribute('aria-pressed','false');down.setAttribute('aria-pressed','false');
    actions.append(copy,up,down);article.append(actions);
    requestAnimationFrame(()=>actions.classList.add('shown'));
  };
  const decorate=(article,animate)=>{
    if(article.dataset.streamingResponse==='ready')return;
    const output=article.querySelector(':scope > p');if(!output)return;
    const text=output.textContent||'';article.dataset.streamingResponse='ready';
    output.classList.add('assistant-response-content');
    if(!animate||reduced()||!text){addActions(article,text);return;}
    article.dataset.responseState='streaming';article.setAttribute('aria-busy','true');
    const started=performance.now(),duration=Math.min(4200,Math.max(550,text.length*13));
    const reveal=now=>{const progress=Math.min(1,(now-started)/duration);output.textContent=text.slice(0,Math.ceil(text.length*progress));
      if(progress<1){requestAnimationFrame(reveal);return;}
      article.dataset.responseState='complete';article.setAttribute('aria-busy','false');addActions(article,text);
    };requestAnimationFrame(reveal);
  };
  const pending=messages=>{
    if(messages.querySelector('.assistant-stream-pending'))return;
    const article=document.createElement('article');article.className='assistant-message assistant-stream-pending';
    article.setAttribute('aria-busy','true');
    const label=document.createElement('small');label.textContent='AI 助理';
    const dots=document.createElement('span');dots.className='assistant-response-typing';dots.setAttribute('role','status');dots.setAttribute('aria-label','AI 正在生成回答');
    dots.append(document.createElement('i'),document.createElement('i'),document.createElement('i'));article.append(label,dots);messages.append(article);messages.scrollTop=messages.scrollHeight;
  };
  const connect=panel=>{
    if(panel.dataset.streamingConnected)return;panel.dataset.streamingConnected='true';
    const messages=panel.querySelector('.assistant-messages'),status=panel.querySelector('.assistant-status');if(!messages||!status)return;
    const composer=panel.querySelector('.assistant-compose'),chooser=composer?.querySelector('input[type="file"]');
    composer?.addEventListener('paste',event=>{
      const pasted=[...(event.clipboardData?.items||[])]
        .filter(item=>item.kind==='file'&&item.type.startsWith('image/'))
        .map(item=>item.getAsFile()).filter(Boolean);
      if(!pasted.length||!chooser)return;
      event.preventDefault();
      const transfer=new DataTransfer();
      pasted.forEach((file,index)=>{
        const extension=(file.type.split('/')[1]||'png').replace('jpeg','jpg');
        const named=/\.[a-z0-9]+$/i.test(file.name||'')?file:new File([file],`剪贴板图片-${Date.now()}-${index+1}.${extension}`,{type:file.type||'image/png'});
        transfer.items.add(named);
      });
      chooser.files=transfer.files;
      chooser.dispatchEvent(new Event('change',{bubbles:true}));
    });
    let animateNext=false;
    new MutationObserver(()=>{if(status.textContent.includes('正在思考')){animateNext=true;pending(messages);}else{messages.querySelector('.assistant-stream-pending')?.remove();animateNext=false;}}).observe(status,{childList:true,subtree:true,characterData:true});
    new MutationObserver(()=>{const replies=[...messages.querySelectorAll('.assistant-message:not(.user-message):not(.assistant-stream-pending)')];
      replies.forEach((article,index)=>decorate(article,animateNext&&index===replies.length-1));if(replies.length)animateNext=false;
    }).observe(messages,{childList:true});
  };
  const scan=()=>document.querySelectorAll('.assistant-panel').forEach(connect);
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',scan,{once:true});else scan();
  new MutationObserver(scan).observe(document.documentElement,{childList:true,subtree:true});
})();

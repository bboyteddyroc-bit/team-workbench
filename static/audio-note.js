/* Original vanilla-JS implementation inspired by Rare UI Voice note.
   Reference: https://www.rareui.com/components/voicenote
   Uses real HTMLMediaElement playback; no simulated audio or waveform. */
(()=>{'use strict';
const players=new Map(),cache=new Map();
const make=(tag,cls,text)=>{const n=document.createElement(tag);n.className=cls;if(text)n.textContent=text;return n;};
const time=n=>Number.isFinite(n)?`${Math.floor(n/60)}:${String(Math.floor(n%60)).padStart(2,'0')}`:'--:--';
function mount(audio){
 if(players.has(audio)||audio.id==='edit-audio'||audio.dataset.timelineAudio||!audio.controls)return;
 const root=make('div','hub-voice-note'),row=make('div','hvn-row'),play=make('button','hvn-play'),wave=make('div','hvn-wave'),seek=make('input','hvn-seek'),speed=make('button','hvn-speed','1×'),stamp=make('span','hvn-time','0:00 / --:--'),error=make('span','hvn-error');
 root.setAttribute('role','group');root.setAttribute('aria-label',audio.getAttribute('aria-label')||'音频播放器');play.type=speed.type='button';play.setAttribute('aria-label','播放音频');play.innerHTML='<span></span><span></span>';speed.setAttribute('aria-label','播放速度 1 倍，点击切换');seek.type='range';seek.min=0;seek.max=1000;seek.step=1;seek.value=0;seek.setAttribute('aria-label','音频播放进度');wave.setAttribute('title','拖动定位；方向键微调');
 const bars=make('div','hvn-bars');for(let i=0;i<40;i++)bars.append(make('i',''));wave.append(bars,seek);row.append(play,wave,speed);error.setAttribute('role','status');root.append(row,stamp,error);audio.after(root);audio.classList.add('hvn-native');
 let source='',epoch=0,loading=false;
 const sync=()=>{const d=audio.duration,t=audio.currentTime,p=Number.isFinite(d)&&d>0?t/d:0;seek.value=Math.round(p*1000);seek.disabled=!Number.isFinite(d)||d<=0;seek.setAttribute('aria-valuetext',`${time(t)} / ${time(d)}`);root.style.setProperty('--progress',`${p*100}%`);root.classList.toggle('is-playing',!audio.paused&&!audio.ended);play.setAttribute('aria-label',audio.paused?'播放音频':'暂停音频');play.setAttribute('aria-pressed',String(!audio.paused));stamp.textContent=`${time(t)} / ${time(d)}`;speed.textContent=audio.playbackRate+'×';};
 async function peaks(){const url=audio.currentSrc||audio.src;if(!url||loading||root.dataset.waveSrc===url)return;loading=true;const ticket=epoch;
 try{let heights=cache.get(url);if(!heights){const u=new URL(url,location.href);if(u.origin!==location.origin)return;const r=await fetch(url,{credentials:'same-origin'});if(!r.ok||Number(r.headers.get('content-length'))>20000000)return;const data=await r.arrayBuffer();if(data.byteLength>20000000)return;const C=window.AudioContext||window.webkitAudioContext;if(!C)return;const ctx=new C();let decoded;try{decoded=await ctx.decodeAudioData(data);}finally{await ctx.close();}const samples=decoded.getChannelData(0),step=Math.ceil(samples.length/40);heights=[];for(let i=0;i<40;i++){let max=0;for(let j=i*step;j<Math.min((i+1)*step,samples.length);j+=Math.max(1,Math.floor(step/1500)))max=Math.max(max,Math.abs(samples[j]));heights.push(max);}const top=Math.max(...heights,.01);heights=heights.map(h=>Math.max(.08,h/top));if(cache.size>=40)cache.delete(cache.keys().next().value);cache.set(url,heights);}if(ticket!==epoch||!audio.isConnected)return;[...bars.children].forEach((b,i)=>b.style.height=`${heights[i]*100}%`);root.dataset.waveSrc=url;}
 catch{wave.title='波形暂不可用，仍可拖动进度播放';}finally{loading=false;}}
 const refresh=()=>{root.hidden=audio.hidden||!(audio.getAttribute('src')||audio.querySelector('source'));const url=audio.getAttribute('src')||'';if(source!==url){source=url;epoch++;loading=false;delete root.dataset.waveSrc;[...bars.children].forEach(b=>b.style.height='18%');error.textContent='';}sync();};
 play.onclick=async()=>{if(!audio.paused){audio.pause();return;}error.textContent='';try{await audio.play();void peaks();}catch(e){if(e&&e.name==='AbortError'){sync();return;}error.textContent='音频暂时无法播放，请重试';sync();}};
 seek.oninput=()=>{if(Number.isFinite(audio.duration))audio.currentTime=Number(seek.value)/1000*audio.duration;sync();};
 speed.onclick=()=>{const speeds=[1,1.25,1.5,2,.75];audio.playbackRate=speeds[(speeds.indexOf(audio.playbackRate)+1)%speeds.length];speed.setAttribute('aria-label',`播放速度 ${audio.playbackRate} 倍，点击切换`);sync();};
 ['timeupdate','loadedmetadata','durationchange','play','pause','ended','ratechange','emptied'].forEach(e=>audio.addEventListener(e,sync));audio.addEventListener('error',()=>{error.textContent='音频加载失败，请稍后重试';sync();});
 const observer=new MutationObserver(refresh);observer.observe(audio,{attributes:true,attributeFilter:['src','hidden'],childList:true});players.set(audio,{root,observer});refresh();
}
function scan(){document.querySelectorAll('audio').forEach(mount);for(const [audio,p]of players){if(!audio.isConnected){audio.pause();p.observer.disconnect();p.root.remove();players.delete(audio);}}}
document.addEventListener('DOMContentLoaded',()=>{scan();new MutationObserver(records=>{if(records.some(r=>[...r.addedNodes,...r.removedNodes].some(n=>n.nodeType===1&&(n.matches?.('audio')||n.querySelector?.('audio')))))scan();}).observe(document.body,{childList:true,subtree:true});});
})();


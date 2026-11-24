/* Native form controls, custom beUI-like unfolding list. */
(function(){
'use strict';
let current=null, serial=0, typed='', typedAt=0;
const eligible=s=>s instanceof HTMLSelectElement&&!s.multiple&&(!s.hasAttribute('size')||s.size<=1)&&!s.disabled;
const nativeOpen=HTMLSelectElement.prototype.showPicker;
if(nativeOpen) HTMLSelectElement.prototype.showPicker=function(){if(eligible(this)){this.focus({preventScroll:true});open(this);}else return nativeOpen.call(this);};
const motion=()=>!matchMedia('(prefers-reduced-motion: reduce)').matches;
function close(refocus=false){
 const c=current;if(!c)return;current=null;
 c.select.setAttribute('aria-expanded','false');c.select.removeAttribute('aria-controls');c.select.removeAttribute('aria-activedescendant');
 c.panel.classList.remove('bs-open'); c.panel.style.pointerEvents='none';
 if(refocus&&c.select.isConnected)c.select.focus({preventScroll:true});
 if(motion())setTimeout(()=>c.panel.remove(),210);else c.panel.remove();
}
function position(c){
 if(!c.select.isConnected||!c.select.getClientRects().length){close();return;}
 const r=c.select.getBoundingClientRect(), p=c.panel;
 const below=innerHeight-r.bottom-8, above=r.top-8, desired=Math.min(300,Math.max(40,p.scrollHeight));
 const top=below<Math.min(desired,160)&&above>below;
 const space=Math.max(45,(top?above:below)-8);
 p.style.maxHeight=Math.min(300,space)+'px';p.style.width=Math.min(Math.max(r.width,160),innerWidth-16)+'px';
 p.style.left=Math.max(8,Math.min(r.left,innerWidth-p.offsetWidth-8))+'px';
 p.classList.toggle('bs-top',top);p.style.top=(top?Math.max(8,r.top-8-p.offsetHeight):r.bottom+8)+'px';
}
function setActive(c,index,scroll=true){
 if(!c.rows.length)return;
 let i=Math.max(0,Math.min(index,c.rows.length-1));
 if(c.rows[i].disabled){const direction=i>=c.index?1:-1;while(i>=0&&i<c.rows.length&&c.rows[i].disabled)i+=direction;if(i<0||i>=c.rows.length)return;}
 c.index=i;c.rows.forEach((r,n)=>r.el.dataset.active=String(n===i));
 c.select.setAttribute('aria-activedescendant',c.rows[i].el.id);
 if(scroll)c.rows[i].el.scrollIntoView({block:'nearest'});
}
function choose(c,i){
 const row=c.rows[i];if(!row||row.disabled)return;
 const s=c.select, changed=s.selectedIndex!==row.option.index;
 s.selectedIndex=row.option.index;close(true);
 if(changed){s.dispatchEvent(new Event('input',{bubbles:true}));s.dispatchEvent(new Event('change',{bubbles:true}));}
}
function open(s){
 if(!eligible(s))return; if(current?.select===s){close(true);return;} close();
 const p=document.createElement('div');p.className='bs-panel';p.id='bs-list-'+(++serial);p.setAttribute('role','listbox');
 p.setAttribute('aria-label',s.getAttribute('aria-label')||s.labels?.[0]?.textContent.trim()||'选择选项');
 const c={select:s,panel:p,rows:[],index:0};current=c;
 for(const node of s.children){
   if(node.tagName==='OPTGROUP'){
     const group=document.createElement('div');group.className='bs-group';group.textContent=node.label;p.append(group);
     for(const o of node.children)if(o.tagName==='OPTION')add(o,node.disabled);
   }else if(node.tagName==='OPTION')add(node,false);
 }
 function add(o,groupDisabled){
   if(o.hidden)return;
   const el=document.createElement('div');el.className='bs-row';el.id=p.id+'-'+c.rows.length;el.setAttribute('role','option');
   el.setAttribute('aria-selected',String(o.selected));const disabled=o.disabled||groupDisabled;el.setAttribute('aria-disabled',String(disabled));
   const text=document.createElement('span');text.textContent=o.label;const check=document.createElement('span');check.className='bs-check';check.textContent='✓';check.setAttribute('aria-hidden','true');el.append(text,check);p.append(el);
   const n=c.rows.length;c.rows.push({el,option:o,disabled});
   el.addEventListener('pointermove',()=>{if(!disabled)setActive(c,n,false)});
   el.addEventListener('pointerdown',e=>{e.preventDefault();if(!disabled)choose(c,n)});
 }
 (s.closest('dialog[open]')||document.body).append(p);s.setAttribute('aria-expanded','true');s.setAttribute('aria-controls',p.id);
 position(c);let idx=c.rows.findIndex(r=>r.option.selected&&!r.disabled);if(idx<0)idx=c.rows.findIndex(r=>!r.disabled);if(idx>=0)setActive(c,idx);
 requestAnimationFrame(()=>{if(current===c)p.classList.add('bs-open')});
}
document.addEventListener('pointerdown',e=>{
 document.documentElement.classList.remove('bs-keyboard');
 const s=e.target.closest?.('select');
 if(eligible(s)&&e.button===0){e.preventDefault();s.focus({preventScroll:true});open(s);return;}
 if(current&&!current.panel.contains(e.target))close();
},true);
document.addEventListener('keydown',e=>{
 if(e.ctrlKey||e.metaKey||e.altKey)return;
 document.documentElement.classList.add('bs-keyboard');
 const s=e.target;if(!eligible(s))return;
 if(!current||current.select!==s){if(['ArrowDown','ArrowUp','Enter',' '].includes(e.key)){e.preventDefault();open(s)}return;}
 const c=current;let n=c.index,handled=true;
 switch(e.key){case 'Escape':close(true);break;case 'Tab':close();handled=false;break;case 'ArrowDown':n++;setActive(c,n);break;case 'ArrowUp':n--;setActive(c,n);break;case 'Home':setActive(c,0);break;case 'End':setActive(c,c.rows.length-1);break;case 'Enter':case ' ':choose(c,n);break;
 default:handled=false;if(e.key.length===1){const now=Date.now();typed=now-typedAt<700?typed+e.key.toLowerCase():e.key.toLowerCase();typedAt=now;const i=c.rows.findIndex(r=>!r.disabled&&r.option.label.toLowerCase().startsWith(typed));if(i>=0)setActive(c,i);handled=true;}}
 if(handled){e.preventDefault();e.stopPropagation();}
},true);
window.addEventListener('resize',()=>{if(current)position(current)});
window.addEventListener('scroll',e=>{if(current&&!current.panel.contains(e.target))position(current)},true);
document.addEventListener('change',e=>{if(current&&e.target===current.select)close()});
})();

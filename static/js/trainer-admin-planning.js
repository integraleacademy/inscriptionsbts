(() => {
  'use strict';
  const app=document.querySelector('[data-admin-trainer-availability]');if(!app)return;
  const $=id=>document.getElementById(id),config=JSON.parse($('tap-availability-config').textContent),selected=new Set();let busy=false,anchor=null,drag=null;
  const days=new Map(config.state.days.map(day=>[day.date,day]));
  const date=value=>new Date(value+'T12:00:00'),label=value=>date(value).toLocaleDateString('fr-FR',{weekday:'long',day:'numeric',month:'long',year:'numeric'});
  const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
  const allowed=key=>days.has(key)&&!days.get(key).public_holiday&&!days.get(key).unavailable;
  function feedback(text,error=false){$('tap-feedback').textContent=text;$('tap-feedback').hidden=!text;$('tap-feedback').classList.toggle('is-error',error);}
  function update(){app.dataset.dirty=String(selected.size>0);$('tap-selection-count').textContent=selected.size?selected.size+' journée(s) sélectionnée(s)':'Aucune date sélectionnée';$('tap-clear').disabled=busy||!selected.size;$('tap-save').disabled=busy||!selected.size;app.querySelectorAll('[data-day]').forEach(b=>{b.classList.toggle('is-selected',selected.has(b.dataset.day));b.setAttribute('aria-pressed',String(selected.has(b.dataset.day)));});}
  function toggle(key,value){if(busy||!allowed(key))return;if(value)selected.add(key);else selected.delete(key);update();}
  for(let month=0;month<12;month++){
    const card=node('section','tap-month'),head=node('h3','',new Date(config.year,month,1).toLocaleDateString('fr-FR',{month:'long'}));card.append(head);
    const grid=node('div','tap-month-grid');['L','M','M','J','V','S','D'].forEach(text=>grid.append(node('span','tap-weekday',text)));
    const first=new Date(config.year,month,1),length=new Date(config.year,month+1,0).getDate();for(let i=0;i<(first.getDay()+6)%7;i++)grid.append(node('span','tap-blank'));
    for(let n=1;n<=length;n++){
      const key=[config.year,String(month+1).padStart(2,'0'),String(n).padStart(2,'0')].join('-'),day=days.get(key);const b=node('button','tap-date',n);b.type='button';b.dataset.day=key;b.disabled=!allowed(key);b.classList.toggle('is-unavailable',!!day.unavailable);b.classList.toggle('is-holiday',!!day.public_holiday);b.classList.toggle('has-course',!!day.course_count);if(day.course_count){const dot=node('span','tap-course-dot');dot.setAttribute('aria-hidden','true');b.append(dot);}b.title=[label(key),day.public_holiday,day.reason,day.course_count?day.course_count+' cours prévu(s)':''].filter(Boolean).join(' · ');b.setAttribute('aria-label',b.title);grid.append(b);
    }card.append(grid);$('tap-months').append(card);
  }
  $('tap-months').addEventListener('click',event=>{const b=event.target.closest('[data-day]');if(!b||busy||b.disabled)return;const key=b.dataset.day;if(event.shiftKey&&anchor){for(const candidate of days.keys())if(candidate>=[key,anchor].sort()[0]&&candidate<=[key,anchor].sort()[1])toggle(candidate,true);}else if(!drag)toggle(key,!selected.has(key));anchor=key;});
  $('tap-months').addEventListener('pointerdown',event=>{if(event.pointerType==='touch'||event.button!==0)return;const b=event.target.closest('[data-day]');if(!b||b.disabled||busy||event.shiftKey)return;drag={value:!selected.has(b.dataset.day)};toggle(b.dataset.day,drag.value);anchor=b.dataset.day;});
  $('tap-months').addEventListener('pointerover',event=>{const b=event.target.closest('[data-day]');if(drag&&b)toggle(b.dataset.day,drag.value);});
  window.addEventListener('pointerup',()=>setTimeout(()=>{drag=null;},0));window.addEventListener('pointercancel',()=>{drag=null;});
  $('tap-clear').addEventListener('click',()=>{selected.clear();anchor=null;update();});
  async function mutate(url,method,payload){if(busy)return;busy=true;app.setAttribute('aria-busy','true');update();try{const response=await fetch(url,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':app.dataset.csrf},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok||result.ok===false){let message=result.message||'La modification n’a pas été enregistrée.';if(result.conflicts)message+='\n'+result.conflicts.map(c=>label(c.date)+' · '+c.start+'–'+c.end+' · '+c.title).join('\n');throw Error(message);}window.location.reload();}catch(error){feedback(error.message,true);}finally{busy=false;app.setAttribute('aria-busy','false');update();}}
  $('tap-save').addEventListener('click',()=>{const reason=$('tap-reason').value.trim();if(!reason){feedback('Précisez le motif de ces indisponibilités.',true);return;}mutate(config.save_url,'POST',{dates:[...selected].sort(),reason,expected_revision:config.state.revision});});
  app.querySelectorAll('[data-remove-block]').forEach(button=>button.addEventListener('click',()=>mutate(config.block_url+encodeURIComponent(button.dataset.removeBlock),'DELETE',{expected_revision:config.state.revision})));
  window.addEventListener('academy:planning-changed',event=>{if(selected.size||busy||drag){event.preventDefault();feedback('Le planning a changé. Votre sélection est conservée ; les cours seront vérifiés à l’enregistrement.');}});
  window.addEventListener('beforeunload',event=>{if(selected.size&&!busy){event.preventDefault();event.returnValue='';}});update();
})();

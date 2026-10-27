(() => {
 'use strict';
 const table=document.getElementById('rooms-calendar'); if(!table)return;
 const $=id=>document.getElementById(id), form=$('rooms-session-form'), csrf=document.querySelector('.catalog-app').dataset.csrf;
 const node=(tag,text,cls)=>{const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;};
 const date=d=>new Date(d+'T12:00:00'), iso=d=>[d.getFullYear(),String(d.getMonth()+1).padStart(2,'0'),String(d.getDate()).padStart(2,'0')].join('-');
 const add=(d,n)=>{const x=date(d);x.setDate(x.getDate()+n);return iso(x);};
 const monday=d=>add(d,-((date(d).getDay()+6)%7));
 const today=()=>new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/Paris'}).format(new Date());
 const label=d=>date(d).toLocaleDateString('fr-FR',{weekday:'short',day:'numeric',month:'short'});
 const error=(id,msg)=>{$(id).textContent=msg||'';$(id).hidden=!msg;};
 const courseDialog=$('rooms-course-dialog'), courseForm=$('rooms-course-form');
 let rooms=[], sessions=[], sequence=0, sessionsPromise=null, editingCourse=null;
 async function request(path,data){const response=await fetch('/admin/planning/api/rooms'+path,{method:data?'POST':'GET',credentials:'same-origin',headers:{Accept:'application/json',...(data?{'Content-Type':'application/json','X-CSRF-Token':csrf}:{})},...(data?{body:JSON.stringify(data)}:{})});const result=await response.json().catch(()=>({}));if(!response.ok || result.ok===false)throw new Error([result.message || 'Chargement impossible.',...(result.conflicts||[]).map(c=>(c.date?c.date+' · ':'')+c.message)].join('\n'));return result;}
 function roomOptions(){const old=form.elements.room_id.value;form.elements.room_id.replaceChildren(new Option('Choisir une salle',''));for(const r of rooms.filter(r=>r.active))form.elements.room_id.add(new Option(r.name,r.id));form.elements.room_id.value=old;}
 async function load(){
  const seq=++sequence,start=monday($('rooms-date').value || today());$('rooms-date').value=start;error('rooms-error','');table.setAttribute('aria-busy','true');
  try{const result=await request('/schedule?'+new URLSearchParams({start,end:add(start,6)}));if(seq!==sequence)return;rooms=result.rooms;roomOptions();table.replaceChildren();const head=node('thead'),row=node('tr');row.append(node('th','Salle'));for(let i=0;i<7;i++)row.append(node('th',label(add(start,i))));head.append(row);table.append(head);const body=node('tbody');
   for(const room of rooms){const row=node('tr');const heading=node('th',room.name+(room.active?'':' · inactive'));heading.scope='row';row.append(heading);for(let i=0;i<7;i++){const cell=node('td'),day=add(start,i),bookings=result.reservations.filter(b=>b.room_id===room.id && b.date===day).sort((a,b)=>a.start_min-b.start_min);for(const b of bookings){const card=node('button',undefined,'room-booking '+b.source+(b.conflict?' conflict':''));card.type='button';card.addEventListener('click',()=>openBooking(b));card.setAttribute('aria-label','Changer la salle · '+b.title+' · '+label(b.date)+' · '+b.start+'–'+b.end);card.append(node('strong',b.start+'–'+b.end),node('span',b.title),node('small',b.source==='session'?'Session de formation':b.source==='event'?'Événement ponctuel':'BTS · '+b.promotion_name));if(b.conflict)card.append(node('b','⚠ Chevauchement à corriger'));if(b.pending)card.append(node('small','Réservation en cours de confirmation'));card.append(node('small','Changer la salle'));cell.append(card);}if(!bookings.length)cell.append(node('span',room.active?'Libre':'—','room-free'));row.append(cell);}body.append(row);}table.append(body);
   const conflicts=result.reservations.filter(b=>b.conflict).length;let status=rooms.length+' salle(s) · '+result.reservations.length+' réservation(s) cette semaine.';
   if(conflicts)status+=' ⚠ '+conflicts+' réservation(s) en chevauchement : réaffectez les créneaux signalés en rouge.';
   if(!result.connected)status+=' Liaison avec les sessions non configurée.';else if(!result.ready)status+=' Première synchronisation des sessions nécessaire.';else status+=' Liaison avec les sessions active.';
   $('rooms-status').textContent=status;$('rooms-status').classList.toggle('rooms-error',Boolean(conflicts || (result.connected && !result.ready)));
  }catch(e){if(seq===sequence)error('rooms-error',e.message);}finally{if(seq===sequence)table.removeAttribute('aria-busy');}
 }
 function selected(){return sessions.find(s=>s.owner===form.elements.owner.value);}
 function details(){const s=selected();$('rooms-session-fallback').hidden=!s || s.generated;error('rooms-session-error','');$('rooms-session-detail').textContent=s?(s.start+' → '+s.end+' · '+(s.generated?s.count+' créneau(x) de présence à réserver.':'Réservation sur les jours et horaires ci-dessous.')):'';form.elements.room_id.value=s?.config?.room_id || '';form.elements.start.value=s?.config?.start || '08:00';form.elements.end.value=s?.config?.end || '18:00';for(const input of form.querySelectorAll('[name=weekdays]'))input.checked=(s?.config?.weekdays || [0,1,2,3,4]).includes(Number(input.value));}
 function loadSessions(){
  if(sessionsPromise)return sessionsPromise;
  sessionsPromise=(async()=>{error('rooms-session-error','');const old=form.elements.owner.value;
   try{const result=await request('/sessions');sessions=result.sessions.filter(s=>s.owner.startsWith('session:')).sort((a,b)=>(b.start || '').localeCompare(a.start || ''));form.elements.owner.replaceChildren(new Option('Choisir une session',''));for(const s of sessions)form.elements.owner.add(new Option(s.title+' · '+(s.assigned?'salle affectée':'À AFFECTER'),s.owner));const requested=new URLSearchParams(location.search).get('session_id');form.elements.owner.value=old || (requested?'session:'+requested:'');details();return true;}
   catch(e){error('rooms-session-error',e.message);return false;}
   finally{sessionsPromise=null;}
  })();return sessionsPromise;
 }
 async function openBooking(booking){
  if(booking.source==='session'){
   $('rooms-session-panel').open=true;
   if(!await loadSessions())return;
   const source=sessions.find(s=>s.owner===booking.owner);
   if(!source){error('rooms-session-error','Cette session n’est plus disponible. Actualisez le calendrier.');return;}
   form.elements.owner.value=source.owner;details();form.elements.room_id.value=source.config?.room_id || booking.room_id;
   $('rooms-session-panel').scrollIntoView({behavior:'smooth',block:'start'});form.elements.room_id.focus({preventScroll:true});return;
  }
  editingCourse=booking;courseDialog._opener=document.activeElement;error('rooms-course-error','');
  $('rooms-course-description').textContent=booking.title+' · '+label(booking.date)+' · '+booking.start+'–'+booking.end;
  $('rooms-course-shared').hidden=!booking.is_shared;
  $('rooms-course-shared').textContent=booking.is_shared?'Ce cours est commun à plusieurs promotions. Le changement de salle s’appliquera à toutes : '+booking.groups.map(g=>g.promotion_name).join(', ')+'.':'';
  courseForm.elements.room_id.replaceChildren(new Option('Sans salle attribuée',''));
  for(const r of rooms.filter(r=>r.active))courseForm.elements.room_id.add(new Option(r.name,r.id));
  courseForm.elements.room_id.value=booking.room_id || '';courseDialog.showModal();courseForm.elements.room_id.focus();
 }
 for(const button of courseDialog.querySelectorAll('[data-room-close]'))button.addEventListener('click',()=>{if(!courseDialog.dataset.busy)courseDialog.close();});
 courseDialog.addEventListener('cancel',e=>{if(courseDialog.dataset.busy)e.preventDefault();});
 courseDialog.addEventListener('close',()=>{(courseDialog._opener?.isConnected?courseDialog._opener:$('rooms-refresh')).focus();});
 courseForm.addEventListener('submit',async e=>{
  e.preventDefault();if(!editingCourse || courseDialog.dataset.busy || !courseForm.reportValidity())return;
  const data={room_id:courseForm.elements.room_id.value,version:editingCourse.version},id=editingCourse.id;
  courseDialog.dataset.busy='1';error('rooms-course-error','');courseDialog.querySelectorAll('button,select').forEach(n=>n.disabled=true);
  try{await request('/courses/'+encodeURIComponent(id)+'/assign',data);courseDialog.close();await load();}
  catch(e){error('rooms-course-error',e.message);}
  finally{delete courseDialog.dataset.busy;courseDialog.querySelectorAll('button,select').forEach(n=>n.disabled=false);}
 });
 $('rooms-session-panel').addEventListener('toggle',()=>{if($('rooms-session-panel').open && !sessions.length)loadSessions();});
 $('rooms-sessions-reload').addEventListener('click',loadSessions);form.elements.owner.addEventListener('change',details);
 form.addEventListener('submit',async e=>{e.preventDefault();const s=selected();if(!s)return;error('rooms-session-error','');const data={owner:s.owner,revision:s.revision,room_id:form.elements.room_id.value,start:form.elements.start.value,end:form.elements.end.value,weekdays:[...form.querySelectorAll('[name=weekdays]:checked')].map(n=>Number(n.value))};const controls=[...form.elements].map(n=>[n,n.disabled]);controls.forEach(([n])=>n.disabled=true);try{const result=await request('/sessions',data);await loadSessions();await load();$('rooms-session-detail').textContent=result.message;}catch(e){error('rooms-session-error',e.message);}finally{controls.forEach(([n,disabled])=>n.disabled=disabled);}});
 $('rooms-prev').addEventListener('click',()=>{$('rooms-date').value=add($('rooms-date').value,-7);load();});$('rooms-next').addEventListener('click',()=>{$('rooms-date').value=add($('rooms-date').value,7);load();});$('rooms-date').addEventListener('change',load);$('rooms-today').addEventListener('click',()=>{$('rooms-date').value=today();load();});$('rooms-refresh').addEventListener('click',load);
 $('rooms-date').value=today();load();if(new URLSearchParams(location.search).has('session_id'))$('rooms-session-panel').open=true;
 setInterval(()=>{if(!document.hidden && !document.querySelector('dialog[open]') && !$('rooms-session-panel').open)load();},60000);
})();

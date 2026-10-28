(() => {
  'use strict';
  const api = window.AcademyPlanning;
  if (!api) return;
  const $ = id => document.getElementById(id), ef = $('planning-event-form'), bf = $('planning-bulk-room-form');
  const node = (tag, text, cls) => {const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n;};
  const options = (select, items, empty) => {select.replaceChildren(new Option(empty, '')); for (const [id, name] of items) select.add(new Option(name, id));};
  const error = (form, value) => {const n=form.querySelector('.planning-form-error'); n.textContent=value || ''; n.hidden=!value;};
  const dateLabel = d => new Date(d+'T12:00:00').toLocaleDateString('fr-FR');
  const hours = m => (m / 60).toLocaleString('fr-FR', {maximumFractionDigits: 2})+' h';
  let eventCourse=null, candidates=[], selected=new Set(), token=null;
  let roomSequence=0, roomController=null, roomKey=null, roomPhase='empty', preferredRoom='';
  async function work(form, operation) {
    const dialog=form.closest('dialog'); if (dialog.dataset.busy) return;
    dialog.dataset.busy='1'; error(form,'');
    const controls=[...form.querySelectorAll('button,input,select')].map(n=>[n,n.disabled]); controls.forEach(([n])=>n.disabled=true);
    try {await operation();} catch(e) {error(form,e.message);} finally {delete dialog.dataset.busy; controls.forEach(([n,disabled])=>n.disabled=disabled); if (form===bf) roomControls();}
  }
  function openEvent(course=null) {
    const state=api.getState(), data=state.data; if(!data?.promotion) return;
    eventCourse=course; ef.reset(); error(ef,'');
    options(ef.elements.room_id, data.rooms.filter(r=>r.active).map(r=>[r.id,r.name]),'Sans salle');
    options(ef.elements.trainer_id, data.trainers.map(t=>[t.id, [t.prenom,t.nom].filter(Boolean).join(' ')]),'Sans intervenant');
    for (const name of ['title','date','start','end','room_id','trainer_id']) ef.elements[name].value=course?.[name] || '';
    if(!course) {ef.elements.date.value=state.slot?.date || state.week; ef.elements.start.value=state.slot?.start || '09:00'; ef.elements.end.value=state.slot?.end || '10:00';}
    ef.elements.date.min=data.period?.start_date || data.promotion.date_debut; ef.elements.date.max=data.period?.end_date || data.promotion.date_fin;
    if(ef.elements.date.value<ef.elements.date.min || ef.elements.date.value>ef.elements.date.max) ef.elements.date.value=ef.elements.date.min;
    $('planning-event-delete').hidden=!course; $('planning-event-heading').textContent=course?'Modifier l’événement':'Événement ponctuel';
    $('planning-event-dialog').showModal(); ef.elements.title.focus();
  }
  window.AcademyPlanningExtras={openEvent};
  $('planning-add-event').addEventListener('click',()=>openEvent());
  ef.addEventListener('submit',e=>{e.preventDefault(); if(!ef.reportValidity())return; const data=Object.fromEntries(new FormData(ef)); Object.assign(data,{kind:'event',promotion_id:api.promotionId(),...(eventCourse?{version:eventCourse.version}:{})}); work(ef,async()=>{await api.request('/courses'+(eventCourse?'/'+encodeURIComponent(eventCourse.id):''),{method:eventCourse?'PUT':'POST',data}); $('planning-event-dialog').close(); api.notice('Événement enregistré.'); await api.refresh();});});
  $('planning-event-delete').addEventListener('click',()=>{if(!eventCourse || !window.confirm('Supprimer « '+eventCourse.title+' » du planning ?'))return; work(ef,async()=>{await api.request('/courses/'+encodeURIComponent(eventCourse.id),{method:'DELETE',data:{version:eventCourse.version}}); $('planning-event-dialog').close(); await api.refresh();});});
  function budget(data) {
    const banner=$('planning-budget-alert'); banner.replaceChildren();
    const reached=(data?.subjects || []).filter(s=>s.budget_configured && s.remaining_minutes<=0);
    banner.hidden=!reached.length; banner.classList.toggle('over',reached.some(s=>s.remaining_minutes<0));
    if(!reached.length)return;
    banner.append(node('strong',reached.some(s=>s.remaining_minutes<0)?'⚠ Volume annuel dépassé — corrigez les cours concernés':'Volume annuel atteint — aucun ajout possible'));
    const list=node('ul'); for(const s of reached)list.append(node('li',s.name+' : '+hours(s.scheduled_minutes)+' planifiées / '+hours(s.planned_minutes)+' prévues'+(s.remaining_minutes<0?' · dépassement de '+hours(-s.remaining_minutes):' · volume complet'))); banner.append(list,node('p','Tout ajout qui dépasserait le volume annuel est bloqué, y compris les imports et les duplications.'));
  }
  window.addEventListener('academy:planning-state',e=>budget(e.detail)); budget(api.getState().data);
  function invalidate(){token=null; $('planning-bulk-room-save').disabled=true; $('planning-bulk-room-preview').hidden=true;}
  function selectionPayload(){return {promotion_id:api.promotionId(),period_id:api.getState().periodId,
    courses:candidates.filter(c=>selected.has(c.id)).map(c=>({id:c.id,version:c.version}))};}
  function roomControls(){
    const busy=!!$('planning-bulk-room-dialog').dataset.busy;
    bf.elements.room_id.disabled=busy || roomPhase!=='ready' || bf.elements.room_id.options.length<2;
    $('planning-bulk-room-check').disabled=busy || roomPhase!=='ready' || !bf.elements.room_id.value;
    $('planning-bulk-room-save').disabled=busy || !token;
  }
  async function loadRoomChoices(){
    const sequence=++roomSequence; roomController?.abort(); invalidate(); roomKey=null;
    const payload=selectionPayload(), key=JSON.stringify(payload), status=$('planning-bulk-room-status');
    options(bf.elements.room_id,[],'Choisir une salle disponible'); $('planning-bulk-room-retry').hidden=true;
    if(!payload.courses.length){roomPhase='empty';preferredRoom='';status.textContent='Cochez les créneaux pour voir les salles disponibles.';roomControls();return;}
    roomPhase='loading';status.textContent='Recherche des salles libres sur tous les créneaux cochés…';roomControls();
    roomController=new AbortController();
    try {
      const result=await api.request('/rooms/bulk-available',{method:'POST',data:payload,signal:roomController.signal});
      if(sequence!==roomSequence || !$('planning-bulk-room-dialog').open || key!==JSON.stringify(selectionPayload()))return;
      options(bf.elements.room_id,result.rooms.map(r=>[r.id,r.name]),'Choisir une salle disponible');
      if(!result.rooms.some(r=>r.id===preferredRoom))preferredRoom='';
      bf.elements.room_id.value=preferredRoom;roomKey=key;roomPhase='ready';
      status.textContent=result.rooms.length?'Salles libres sur les '+payload.courses.length+' créneau(x) cochés.':'Aucune salle n’est libre pour tous les créneaux cochés. Réduisez la sélection pour les affecter en plusieurs fois.';
    } catch(e){
      if(sequence!==roomSequence || e.name==='AbortError')return;
      roomPhase='error';status.textContent='Impossible de vérifier les salles. '+e.message;$('planning-bulk-room-retry').hidden=false;
    } finally {if(sequence===roomSequence)roomControls();}
  }
  $('planning-bulk-room-retry').addEventListener('click',loadRoomChoices);
  $('planning-bulk-room-dialog').addEventListener('close',()=>{roomSequence++;roomController?.abort();roomKey=null;roomPhase='empty';invalidate();roomControls();});
  function visible(){return candidates.filter(c=>(!bf.elements.unassigned.checked || !c.room_id) && (!bf.elements.subject.value || (bf.elements.subject.value==='event'?c.kind==='event':c.display_subject_id===bf.elements.subject.value)));}
  function renderRows(){
    const list=$('planning-bulk-room-list'); list.replaceChildren(); const rows=visible(); selected=new Set([...selected].filter(id=>rows.some(c=>c.id===id)));
    for(const c of rows){const label=node('label',undefined,'bulk-room-row'),input=node('input'); input.type='checkbox'; input.value=c.id; input.checked=selected.has(c.id); input.addEventListener('change',()=>{input.checked?selected.add(c.id):selected.delete(c.id); count(); loadRoomChoices();}); label.append(input,node('span',dateLabel(c.date)+' · '+c.start+'–'+c.end),node('span',c.display_subject_name || c.subject_name),node('small',(c.room_name || 'Sans salle')+(c.is_shared?' · cours commun':''))); list.append(label);}
    if(!rows.length)list.append(node('p','Aucun créneau ne correspond à ces filtres.')); count(); loadRoomChoices();
  }
  function count(){$('planning-bulk-room-count').textContent=selected.size+' créneau(x) sélectionné(s)';}
  async function loadRows(){invalidate();candidates=[];selected.clear();renderRows(); const params=new URLSearchParams({promotion_id:api.promotionId(),start:bf.elements.from.value,end:bf.elements.to.value}); const data=await api.request('/rooms/courses?'+params); candidates=data.courses; selected=new Set(); renderRows();}
  $('planning-bulk-rooms').addEventListener('click',()=>{
    const state=api.getState(), data=state.data;if(!data?.period)return; bf.reset(); error(bf,''); candidates=[];selected.clear();invalidate();
    bf.elements.from.value=data.period.start_date; bf.elements.to.value=data.period.end_date;
    for(const name of ['from','to']){bf.elements[name].min=data.period.start_date;bf.elements[name].max=data.period.end_date;}
    preferredRoom='';loadRoomChoices();
    options(bf.elements.subject,[...data.subjects.map(s=>[s.id,s.name]),['event','Événements ponctuels']],'Tous les créneaux');
    $('planning-bulk-room-dialog').showModal(); work(bf,loadRows);
  });
  $('planning-bulk-room-load').addEventListener('click',()=>work(bf,loadRows));
  ['from','to'].forEach(name=>bf.elements[name].addEventListener('change',()=>{candidates=[];selected.clear();invalidate();renderRows();}));
  ['subject','unassigned'].forEach(name=>bf.elements[name].addEventListener('change',()=>{invalidate();renderRows();}));
  bf.elements.room_id.addEventListener('change',()=>{preferredRoom=bf.elements.room_id.value;invalidate();roomControls();});
  $('planning-bulk-room-all').addEventListener('click',()=>{selected=new Set(visible().map(c=>c.id));invalidate();renderRows();});
  $('planning-bulk-room-none').addEventListener('click',()=>{selected.clear();invalidate();renderRows();});
  bf.addEventListener('submit',e=>{e.preventDefault();if(roomPhase!=='ready' || roomKey!==JSON.stringify(selectionPayload())){error(bf,$('planning-bulk-room-status').textContent);return;}if(!bf.reportValidity())return;work(bf,async()=>{invalidate();const data={...selectionPayload(),room_id:bf.elements.room_id.value};const result=await api.request('/rooms/bulk-preview',{method:'POST',data});token=result.token;$('planning-bulk-room-preview').textContent=result.count+' créneau(x) vérifié(s).'+(result.shared?' Dont '+result.shared+' cours commun(s) : toutes leurs promotions seront concernées.':'')+' Vous pouvez confirmer l’affectation.';$('planning-bulk-room-preview').hidden=false;});});
  $('planning-bulk-room-save').addEventListener('click',()=>{if(!token)return;work(bf,async()=>{const result=await api.request('/rooms/bulk-commit',{method:'POST',data:{token}});invalidate();$('planning-bulk-room-dialog').close();api.notice(result.message);await api.refresh();});});
})();

(() => {
  'use strict';
  const root = document.querySelector('#ap-workspace,#ap-candidate');
  if (!root) return;
  const $ = id => document.getElementById(id), dialog = $('ap-dialog'), small = $('ap-small-dialog');
  // Native modal top layer must be outside the candidate sheet's hidden tab and forms.
  document.body.append(dialog, small, $('ap-toast'));
  const candidateId = root.dataset.candidateId, isDues = root.dataset.view === 'dues';
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const money = value => typeof value === 'number' ? value.toLocaleString('fr-FR', {style:'currency', currency:'EUR'}) : 'Non communiqué';
  const date = value => /^\d{4}-\d{2}-\d{2}/.test(value || '') ? String(value).slice(0,10).split('-').reverse().join('/') : 'À préciser';
  const stamp = value => {const d = new Date(value); return Number.isNaN(d.getTime()) ? '' : d.toLocaleString('fr-FR', {timeZone:'Europe/Paris',dateStyle:'short',timeStyle:'short'});};
  const initials = name => String(name || '').split(/\s+/).filter(Boolean).slice(0,2).map(x => x[0]).join('').toUpperCase();
  const get = (o,path) => path.split('.').reduce((v,k) => v?.[k],o);
  const set = (o,path,value) => {const keys=path.split('.'); const last=keys.pop(); for(const k of keys) o=o[k] ||= {}; o[last]=value;};
  const badge = (text,state='') => `<span class="ap-badge ${esc(state)}">${esc(text)}</span>`;
  const providerName = p => config?.providers[p] || p || 'OPCO';
  const dueStates = {due:'À facturer',upcoming:'À venir',pending:'En attente de règlement',paid:'Réglée',unknown:'Règlement non communiqué'};
  let config, current, rows=[], visible=[], activeTab='tracking', dirty=false, busy=false, page=1, previousFocus, toastTimer;
  let creationKey = crypto.randomUUID();

  async function api(path, options={}) {
    const headers = {'Accept':'application/json','X-CSRF-Token':root.dataset.csrf,...options.headers};
    if (options.body && !(options.body instanceof FormData)) {headers['Content-Type']='application/json'; options.body=JSON.stringify(options.body);}
    const response=await fetch('/admin/apprentissage'+path,{credentials:'same-origin',...options,headers});
    const result=await response.json().catch(()=>({ok:false,message:response.status===409?'Le dossier a changé. Fermez puis rouvrez-le pour récupérer la dernière version.':'La session a expiré ou le serveur est indisponible. Rechargez la page.'}));
    if(!response.ok || !result.ok) {const error=new Error(result.message || 'Opération interrompue.');error.errors=result.errors;throw error;}
    return result;
  }
  function toast(message) {clearTimeout(toastTimer);$('ap-toast').textContent=message;$('ap-toast').hidden=false;toastTimer=setTimeout(()=>$('ap-toast').hidden=true,5500);}
  function alert(message) {$('ap-dialog-alert').textContent=message || '';$('ap-dialog-alert').hidden=!message;}
  async function run(task) {
    if(busy)return;busy=true;
    const controls=[...document.querySelectorAll('.ap-dialog button,.ap-small-dialog button,[data-ap-create]')];
    const disabled=controls.map(x=>x.disabled);controls.forEach(x=>x.disabled=true);
    try {await task();}
    catch(e) {if(small.open){let node=small.querySelector('.ap-small-error');if(!node){node=document.createElement('p');node.className='ap-small-error';$('ap-small-body').prepend(node);}node.textContent=e.message;}else if(dialog.open){alert(e.message);if(e.errors)markErrors(e.errors);}else toast(e.message);}
    finally {controls.forEach((x,i)=>{if(x.isConnected)x.disabled=disabled[i];});busy=false;if(current&&dialog.open)$('ap-save').disabled=current.locked;}
  }
  function markErrors(errors) {
    for(const e of errors){const input=[...dialog.querySelectorAll('[data-ap-field]')].find(x=>x.dataset.apField===e.path);if(input){input.closest('.ap-field').classList.add('invalid');input.closest('.ap-field').querySelector('.ap-field-error').textContent=e.message;}}
  }
  function empty(title,text) {return `<div class="ap-empty"><span class="ap-empty-icon">▤</span><h3>${esc(title)}</h3><p>${esc(text)}</p></div>`;}
  function folder(row) {
    const attr=row.source==='local'?`data-ap-open="${esc(row.id)}"`:`href="/admin/candidat/${encodeURIComponent(row.candidate_id)}#contrat-apprentissage"`;
    const tag=row.source==='local'?'button':'a';
    return `<${tag} class="ap-folder" ${attr}><div class="ap-folder-top"><span class="ap-avatar">${esc(initials(row.name))}</span><div><h3>${esc(row.name)}</h3><small>#${esc(row.id)}${row.source==='opco'?' · Relevé OPCO':''}</small></div></div><div class="ap-actions">${badge(row.state_label,row.state)}${row.environment==='recette'?badge('Recette · test','ap-test'):''}</div><div class="ap-folder-meta"><div>▤ &nbsp; <b>${esc(row.training)}</b>${row.promotion?`<br><span>${esc(row.promotion)}</span>`:''}</div><div>◇ &nbsp; ${esc(row.employer || 'Entreprise à compléter')}</div><div>◷ &nbsp; ${date(row.start)} → ${date(row.end)}</div></div><div class="ap-folder-footer"><span>${row.source==='local'?'Dossier Intégrale Academy':'Consulter la synthèse'} ↗</span><strong>${esc(providerName(row.provider))}</strong></div></${tag}>`;
  }
  function selectOptions(id, values, first) {
    const el=$(id);if(!el)return;const selected=el.value;
    el.innerHTML=`<option value="">${first}</option>`+[...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b,'fr')).map(x=>`<option>${esc(x)}</option>`).join('');
    if([...el.options].some(o=>o.value===selected))el.value=selected;
  }
  async function loadRows() {
    if(candidateId){rows=(await api('/dossiers?candidate_id='+encodeURIComponent(candidateId))).dossiers;$('ap-candidate-count').textContent=rows.length||'';$('ap-candidate-results').innerHTML=rows.length?rows.map(folder).join(''):empty('Son premier contrat commence ici','Créez un dossier pour préparer le CERFA et la convention de formation.');return;}
    const data=await api(isDues?'/echeances':'/dossiers');rows=isDues?data.dues:data.dossiers;
    selectOptions('ap-training',rows.map(r=>r.training),'Toutes les formations');selectOptions('ap-promotion',rows.map(r=>r.promotion),'Toutes les promotions');
    const old=$('ap-state').value;const states=isDues?dueStates:config.states;
    $('ap-state').innerHTML='<option value="">Tous les statuts</option>'+Object.entries(states).map(([key,label])=>`<option value="${esc(key)}">${esc(label)}</option>`).join('');$('ap-state').value=old;
    if(isDues){$('ap-training').parentElement.hidden=true;$('ap-promotion').parentElement.hidden=true;}
    renderRows();
  }
  function renderRows() {
    const q=$('ap-search').value.toLocaleLowerCase('fr');
    visible=rows.filter(r=>['training','promotion','state','provider','environment','payer'].every(key=>!$('ap-'+key)?.value || $('ap-'+key).value===r[key]) && [r.name,r.employer,r.id,r.reference,r.invoice,r.training].join(' ').toLocaleLowerCase('fr').includes(q));
    const kpis=isDues?[
      ['Montant des échéances',money(visible.reduce((s,r)=>s+r.amount,0)),'€'],['À facturer',money(visible.filter(r=>r.state==='due').reduce((s,r)=>s+r.amount-(r.paid||0),0)),'◷'],
      ['En attente',money(visible.filter(r=>r.state==='pending').reduce((s,r)=>s+r.amount-(r.paid||0),0)),'↗'],['Règlements connus',money(visible.reduce((s,r)=>s+(r.paid||0),0)),'✓']]:[
      ['Dossiers',visible.length,'▤'],['À préparer',visible.filter(r=>['draft','ready'].includes(r.state)).length,'◷'],['Transmis / en instruction',visible.filter(r=>['sent','pending','sending','pendingAcceptation'].includes(r.state)).length,'↗'],['Engagés / soldés',visible.filter(r=>['accepted','completed'].includes(r.state)).length,'✓']];
    $('ap-kpis').innerHTML=kpis.map(([label,value,icon])=>`<div class="ap-kpi"><div><span>${label}</span><strong>${esc(value)}</strong></div><i>${icon}</i></div>`).join('');
    $('ap-result-count').textContent=`${visible.length} ${isDues?'échéance(s)':'dossier(s)'}${isDues?' · Les relevés OPCO et les prévisions saisies restent identifiés.':''}`;
    page=Math.min(page,Math.max(1,Math.ceil(visible.length/24)));const displayed=visible.slice((page-1)*24,page*24);
    let content=visible.length?(isDues?duesTable(displayed):`<div class="ap-folder-grid">${displayed.map(folder).join('')}</div>`):empty(isDues?'Aucune échéance pour ces filtres':'Aucun dossier pour ces filtres',isDues?'Les échéances apparaissent après récupération auprès de l’OPCO ou saisie dans un dossier.':'Créez un dossier ou ajustez les filtres.');
    if(visible.length>24)content+=`<div class="ap-pager"><button class="ap-icon-button" data-ap-page="-1" ${page===1?'disabled':''}>‹</button><span>${page} / ${Math.ceil(visible.length/24)}</span><button class="ap-icon-button" data-ap-page="1" ${page*24>=visible.length?'disabled':''}>›</button></div>`;
    $('ap-results').innerHTML=(isDues&&visible.length?chart(visible):'')+content;
  }
  function chart(items) {
    const monthly=new Map();items.forEach(r=>{if(/^\d{4}-\d{2}/.test(r.due_date)){const key=r.due_date.slice(0,7);monthly.set(key,(monthly.get(key)||0)+r.amount);}});
    const points=[...monthly].sort(([a],[b])=>a.localeCompare(b)).slice(-12);if(!points.length)return '';
    const max=Math.max(1,...points.map(([,v])=>v));
    return `<div class="ap-chart" role="img" aria-label="Montant total des échéances par mois : ${esc(points.map(([k,v])=>k+' '+money(v)).join(', '))}">${points.map(([k,v])=>`<div class="ap-chart-col" title="${k} : ${money(v)}"><span>${money(v)}</span><div class="ap-chart-bar" style="height:${Math.round(v/max*85)}px"></div><small>${k.slice(5)}/${k.slice(2,4)}</small></div>`).join('')}</div>`;
  }
  function duesTable(items) {
    return `<div class="ap-table-wrap"><table class="ap-table"><thead><tr><th>ÉTUDIANT / DOSSIER</th><th>ÉCHÉANCE</th><th>FINANCEUR</th><th class="ap-money">MONTANT</th><th class="ap-money">RÉGLÉ</th><th>STATUT</th><th></th></tr></thead><tbody>${items.map(r=>`<tr><td>${esc(r.name)}<small>#${esc(r.reference)}</small></td><td>${esc(r.label)}<small>${date(r.due_date)}${r.start?' · '+date(r.start)+' au '+date(r.end):''}</small></td><td>${esc(r.payer==='OPCO'?providerName(r.provider):r.payer)}<small>${r.source==='manual'?'Prévision saisie':'Relevé OPCO'}${r.environment==='recette'?' · RECETTE':''}</small></td><td class="ap-money">${money(r.amount)}</td><td class="ap-money">${money(r.paid)}</td><td>${badge(dueStates[r.state]||r.state,r.state)}</td><td>${r.source==='manual'?`<button class="ap-button ap-secondary" data-ap-edit-due="${esc(r.id)}">Modifier</button>`:r.dossier_id?`<button class="ap-icon-button" data-ap-open="${esc(r.dossier_id)}" aria-label="Ouvrir le dossier">↗</button>`:`<a class="ap-icon-button" href="/admin/candidat/${encodeURIComponent(r.candidate_id)}#contrat-apprentissage" aria-label="Ouvrir la fiche">↗</a>`}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function inputField(f,value,disabled=false,extra='') {
    const common=`data-ap-field="${esc(f.path)}" ${disabled?'disabled':''} ${extra}`;
    let input;
    if(f.type==='boolean'||f.type==='select'){
      const options=f.type==='boolean'?[{value:true,label:'Oui'},{value:false,label:'Non'}]:f.options;
      input=`<select ${common} data-value-type="${f.type==='boolean'?'boolean':options.some(o=>typeof o.value==='number')?'number':'string'}"><option value="">À renseigner</option>${options.map(o=>`<option value="${esc(o.value)}" ${String(o.value)===String(value)?'selected':''}>${esc(o.label)}</option>`).join('')}</select>`;
    }else input=`<input ${common} type="${f.type}" value="${esc(f.type==='date'?String(value||'').slice(0,10):value)}" ${f.type==='number'?`min="0" step="${f.integer?'1':'0.01'}"`:`maxlength="${f.maxLength||500}"`} autocomplete="off">`;
    return `<label class="ap-field"><span>${esc(f.label)} ${f.required?'<em>•</em>':''}</span>${input}<small class="ap-field-error"></small></label>`;
  }
  function detailField(key,wide=false) {
    const value=current.details[key]||'',disabled=current.locked?'disabled':'';
    return `<label class="ap-field ${wide?'wide':''}"><span>${esc(config.details[key])}</span>${wide?`<textarea rows="4" data-ap-detail="${key}" ${disabled}>${esc(value)}</textarea>`:`<input data-ap-detail="${key}" value="${esc(value)}" ${disabled}>`}</label>`;
  }
  function renderEditor() {
    const d=current;$('ap-reference').textContent='#'+d.id;$('ap-dialog-title').textContent=d.name||'Nouveau dossier';
    $('ap-avatar').textContent=initials(d.name);$('ap-dialog-subtitle').textContent=[d.training,d.promotion].filter(Boolean).join(' · ');
    $('ap-save').disabled=d.locked;$('ap-save-state').textContent=d.locked?'Dossier figé':'Modifications enregistrées';
    for(const tab of ['student','contract','company','management']){
      let html=tab==='student'?'<p class="ap-inline-hint">Les données de la fiche étudiant sont préremplies à la création. Les corrections apportées ici concernent ce contrat. Les points • signalent les champs attendus par Convergence.</p>':'';
      if(tab==='management')html+=`<div class="ap-card ap-form-card"><h3>Organisation du dossier</h3><div class="ap-form-grid ap-note-block"><label class="ap-field"><span>OPCO destinataire</span><select id="ap-edit-provider" ${d.locked?'disabled':''}>${Object.entries(config.providers).map(([v,t])=>`<option value="${v}" ${v===d.provider?'selected':''}>${t}</option>`).join('')}</select></label><label class="ap-field"><span>Environnement de transmission</span><select id="ap-edit-environment" ${d.locked?'disabled':''}><option value="recette" ${d.environment==='recette'?'selected':''}>Recette · dossiers de test uniquement</option><option value="production" ${d.environment==='production'?'selected':''}>Production · dépôt réel</option></select></label>${detailField('owner')}${detailField('promotion')}${detailField('nda')}${detailField('cfa_signer')}${detailField('employer_signer')}</div></div>`;
      for(const [i,g] of config.groups.filter(g=>g.tab===tab).entries()) html+=`<details class="ap-card ap-form-card" data-ap-group="${esc(g.path)}" ${i===0?'open':''}><summary>${esc(g.title)}</summary><div class="ap-form-grid">${g.fields.map(f=>inputField(f,get(d.payload,f.path),d.locked)).join('')}</div></details>`;
      if(tab==='contract')html+=`<div class="ap-card ap-form-card"><div class="ap-section-title"><div><h3>Calendrier de rémunération</h3><p>Renseignez les périodes et taux convenus. Aucun salaire n’est calculé automatiquement.</p></div>${!d.locked?'<button type="button" class="ap-button ap-secondary" data-ap-add-period>+ Période</button>':''}</div><div id="ap-periods">${(get(d.payload,'cerfa.contrat.remunerationsAnnuelles')||[]).map(periodHTML).join('')}</div><div class="ap-form-grid ap-note-block">${detailField('job_title')}${detailField('missions',true)}</div></div>`;
      if(tab==='management')html+=`<details class="ap-card ap-form-card" data-ap-group="details" open><summary>Contenu de la convention de formation</summary><div class="ap-form-grid">${['objectives','organization','assessment','payment_terms','terms'].map(k=>detailField(k,true)).join('')}${detailField('vat')}</div></details><div class="ap-card ap-form-card"><h3>Notes internes</h3><div class="ap-form-grid ap-note-block">${detailField('notes',true)}</div></div><div class="ap-card"><div class="ap-section-title"><div><h3>Échéancier complémentaire</h3><p>Prévisions OPCO ou entreprise, distinctes des montants retournés par l’API.</p></div><button type="button" class="ap-button ap-secondary" data-ap-add-due ${d.state==='archived'?'disabled':''}>+ Échéance</button></div><a href="/admin/contrats-apprentissage/echeances" class="ap-button ap-secondary">Ouvrir le suivi des échéances ↗</a><div class="ap-section-divider"></div><div class="ap-section-title"><div><h3>Archiver le dossier</h3><p>L’archivage conserve l’historique et n’annule pas le contrat auprès de l’OPCO.</p></div><button type="button" class="ap-button ap-danger" data-ap-archive ${['archived','sending','uncertain'].includes(d.state)?'disabled':''}>Archiver</button></div></div>`;
      $('ap-panel-'+tab).innerHTML=html;
    }
    renderTracking();activateTab(activeTab);dirty=false;alert(d.error|| (d.state==='sending'?'Une transmission a été lancée. Si cet état persiste, faites vérifier la réception par l’OPCO avant toute nouvelle opération.':''));
  }
  function periodHTML(p={},i=0) {
    return `<div class="ap-pay-period" data-ap-period>${config.remuneration.map(f=>inputField({...f,path:f.path.replace('period.','')},p[f.path.split('.').pop()],current.locked,'data-period-field="true"')).join('')}${!current.locked?'<button type="button" class="ap-icon-button" data-ap-remove-period aria-label="Supprimer cette période">✕</button>':''}</div>`;
  }
  function renderTracking() {
    const d=current,documents=d.documents.filter(x=>x.revision===d.revision),signed=documents.filter(x=>x.signed);
    const errors=d.errors,complete=errors.length===0;
    const needs=errors.slice(0,40).map(e=>`<li><button type="button" data-ap-issue="${esc(e.path)}">${esc(e.label)}<small>${esc(e.message)}</small></button></li>`).join('');
    const docs=d.documents.slice(0,12).map(doc=>`<div class="ap-document"><span class="ap-doc-icon">PDF</span><div><b>${doc.kind==='cerfa'?'CERFA':'Convention'} ${doc.signed?'signé(e)':''}</b><small>Version ${doc.revision}${doc.revision!==d.revision?' · Archive':''} · ${stamp(doc.created_at)}</small></div><a target="_blank" rel="noopener" href="/admin/apprentissage/documents/${encodeURIComponent(doc.id)}" aria-label="Ouvrir ${doc.kind}">Ouvrir ↗</a></div>`).join('');
    const facts=(items)=>`<dl class="ap-context-facts">${items.map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(v||'À compléter')}</dd>`).join('')}</dl>`;
    $('ap-panel-tracking').innerHTML=`<div class="ap-tracking-grid"><div class="ap-stack"><section class="ap-card ap-progress-card"><div class="ap-progress-top"><div><h3>${d.opco_ref?'Votre dossier est chez l’OPCO':complete?'Tout est prêt pour la transmission':'Préparation du contrat'}</h3><p>${d.opco_ref?'Retrouvez le statut et les échéances communiqués par votre OPCO.':`${errors.length} point(s) à vérifier avant l’envoi. Complétez les informations, relisez les documents et ajoutez les versions signées.`}</p></div><div class="ap-progress-number">${d.completion}%</div></div><div class="ap-progress-track"><span style="width:${d.completion}%"></span></div></section>
      <section class="ap-card"><div class="ap-section-title"><h3>Avancée du dossier</h3><div class="ap-actions">${badge(d.state_label,d.state)}${badge(d.environment==='recette'?'RECETTE · TEST':'PRODUCTION',d.environment==='recette'?'ap-test':'accepted')}</div></div>
      <div class="ap-step ${d.completion===100?'done':''}"><span class="ap-step-icon">1</span><div><h4>Compléter les informations</h4><p>Étudiant, formation, contrat et entreprise : un dossier prérempli et modifiable.</p><button type="button" class="ap-button ap-secondary" data-ap-goto="student">${d.locked?'Consulter':'Compléter'} le dossier</button></div></div>
      <div class="ap-step ${documents.some(x=>!x.signed)?'done':''}"><span class="ap-step-icon">2</span><div><h4>Relire le CERFA et la convention</h4><p>Générez les PDF à partir de la version enregistrée. Les champs encore manquants restent à compléter avant signature.</p><div class="ap-actions"><button type="button" class="ap-button ap-secondary" data-ap-generate="cerfa">Générer le CERFA</button><button type="button" class="ap-button ap-secondary" data-ap-generate="convention">Générer la convention</button></div></div></div>
      <div class="ap-step ${new Set(signed.map(x=>x.kind)).size===2?'done':''}"><span class="ap-step-icon">3</span><div><h4>Rassembler les documents signés</h4><p>Ajoutez les PDF signés par les parties, puis confirmez les attestations dans Gestion.</p><div class="ap-actions"><button type="button" class="ap-button ap-secondary" data-ap-upload="cerfa" ${d.locked?'disabled':''}>+ CERFA signé</button><button type="button" class="ap-button ap-secondary" data-ap-upload="convention" ${d.locked?'disabled':''}>+ Convention signée</button><button type="button" class="ap-button ap-secondary" data-ap-goto="management">Attestations</button></div></div></div>
      <div class="ap-step ${d.opco_ref?'done':''}"><span class="ap-step-icon">4</span><div><h4>Transmettre à ${esc(providerName(d.provider))}</h4><p>${d.environment==='recette'?'Environnement de test : cette transmission ne vaut pas dépôt de production.':'Dépôt réel du CERFA dématérialisé et de la convention signée auprès de l’OPCO.'}</p><div class="ap-actions"><button type="button" class="ap-button ap-primary" data-ap-transmit ${!complete||d.locked?'disabled':''}>Télétransmettre le dossier</button><button type="button" class="ap-button ap-secondary" data-ap-retrieve ${(d.state==='sending'&&!d.recoverable)||d.state==='archived'?'disabled':''}>${d.opco_ref?'Actualiser le suivi OPCO':'Récupérer un dossier OPCO'}</button></div></div></div></section>
      ${!d.opco_ref&&errors.length?`<section class="ap-card"><div class="ap-section-title"><h3>À vérifier avant transmission</h3>${badge(errors.length+' points','draft')}</div><ul class="ap-issues">${needs}</ul>${errors.length>40?'<p class="ap-muted">Les autres champs à compléter apparaîtront au fil de votre saisie.</p>':''}</section>`:''}
      <section class="ap-card"><h3>Historique du dossier</h3><ol class="ap-event-list ap-note-block">${d.events.map(e=>`<li>${esc(e.message)}<small>${stamp(e.created_at)} · ${esc(e.actor)}</small></li>`).join('')}</ol></section></div>
      <aside class="ap-stack"><section class="ap-card"><div class="ap-context-title"><span class="ap-context-icon">▤</span><h3>Intégrale Academy</h3></div>${facts([['Dossier interne','#'+d.id],['Version',d.revision],['Formation',d.training],['Contrat',date(d.start)+' → '+date(d.end)]])}</section>
      <section class="ap-card"><div class="ap-context-title"><span class="ap-context-icon" style="background:#ffeaf0;color:#c6778d">◇</span><h3>${esc(d.employer)}</h3></div>${facts([['OPCO',providerName(d.provider)],['Maître d’apprentissage',[get(d.payload,'cerfa.maitre1.prenom'),get(d.payload,'cerfa.maitre1.nom')].filter(Boolean).join(' ')],['Dossier OPCO',d.external_ref||d.opco_ref],['Dernière lecture',d.last_sync?stamp(d.last_sync):'Pas encore effectuée']])}</section>
      <section class="ap-card"><div class="ap-context-title"><span class="ap-context-icon" style="background:#ece7ff;color:#8872bc">◎</span><h3>${esc(d.name)}</h3></div>${facts([['Promotion',d.promotion],['Responsable',d.details.owner]])}<a class="ap-button ap-secondary ap-note-block" href="/admin/candidat/${encodeURIComponent(d.candidate_id)}#contrat-apprentissage">Fiche étudiant ↗</a></section>
      <section class="ap-card"><h3>Documents du dossier</h3><div class="ap-note-block">${docs||'<p class="ap-muted">Vos documents apparaîtront ici après leur génération ou leur ajout.</p>'}</div></section>
      ${d.remote.echeances?.length?`<section class="ap-card"><h3>Financement OPCO</h3><div class="ap-note-block">${facts([['Engagement',money(d.remote.engagement)],['Échéances',d.remote.echeances.length]])}<p class="ap-muted">${d.remote.schedule_missing?'Dernier échéancier conservé : non communiqué lors de la dernière lecture.':''}</p><a class="ap-button ap-secondary" href="/admin/contrats-apprentissage/echeances">Voir les échéances ↗</a></div></section>`:''}</aside></div>`;
  }
  function activateTab(key,focus=false) {
    activeTab=key;
    dialog.querySelectorAll('[data-ap-tab]').forEach(t=>{const active=t.dataset.apTab===key;t.setAttribute('aria-selected',active);t.tabIndex=active?0:-1;if(active&&focus)t.focus();});
    dialog.querySelectorAll('.ap-tab-panel').forEach(x=>x.hidden=x.id!=='ap-panel-'+key);
  }
  async function open(did) {
    const d=(await api('/dossiers/'+encodeURIComponent(did))).dossier;current=d;activeTab='tracking';renderEditor();
    if(!dialog.open){previousFocus=document.activeElement;dialog.showModal();document.body.style.overflow='hidden';}$('ap-modal-scroll').scrollTop=0;
  }
  function close() {
    if(busy)return;if(dirty&&!window.confirm('Fermer sans enregistrer vos modifications ?'))return;
    dialog.close();document.body.style.overflow='';dirty=false;current=null;previousFocus?.focus();
  }
  function changed() {dirty=true;$('ap-save-state').textContent='Modifications à enregistrer';}
  function fieldValue(input) {
    if(input.value==='')return undefined;
    if(input.dataset.valueType==='boolean')return input.value==='true';
    if(input.type==='number'||input.dataset.valueType==='number')return Number(input.value);
    return input.value;
  }
  async function save() {
    if(!dirty||current.locked)return;
    const payload={cerfa:{versionCERFA:'10103*14'},convention:{}};
    dialog.querySelectorAll('[data-ap-field]:not([data-period-field])').forEach(input=>{const value=fieldValue(input);if(value!==undefined)set(payload,input.dataset.apField,value);});
    const periods=[...dialog.querySelectorAll('[data-ap-period]')].map(row=>{const p={};row.querySelectorAll('[data-period-field]').forEach(input=>{const v=fieldValue(input);if(v!==undefined)p[input.dataset.apField]=v;});return p;});
    if(periods.length)set(payload,'cerfa.contrat.remunerationsAnnuelles',periods);
    const details={};dialog.querySelectorAll('[data-ap-detail]').forEach(input=>details[input.dataset.apDetail]=input.value);
    const d=(await api('/dossiers/'+current.id,{method:'PUT',body:{version:current.version,payload,details,provider:$('ap-edit-provider').value,environment:$('ap-edit-environment').value}})).dossier;
    current=d;renderEditor();toast('Dossier enregistré');await loadRows();
  }
  function showSmall(title,html) {$('ap-small-title').textContent=title;$('ap-small-body').innerHTML=html;if(!small.open)small.showModal();}
  function smallForm(title,html,handler,submit='Enregistrer') {
    showSmall(title,`<form id="ap-small-form">${html}<div class="ap-actions"><button type="button" class="ap-button ap-secondary" data-ap-small-close>Annuler</button><button class="ap-button ap-primary" type="submit">${submit}</button></div></form>`);
    $('ap-small-form').addEventListener('submit',e=>{e.preventDefault();run(()=>handler(new FormData(e.currentTarget)));});
  }
  async function createFor(cid) {
    const data=await api('/dossiers',{method:'POST',body:{candidate_id:cid,creation_key:creationKey}});creationKey=crypto.randomUUID();small.close();await loadRows();await open(data.dossier.id);
  }
  async function createChoice() {
    if(candidateId)return createFor(candidateId);
    showSmall('Créer un dossier d’apprentissage','<p>Sélectionnez l’étudiant. Ses informations disponibles seront préremplies.</p><label class="ap-field"><span>Rechercher un étudiant</span><input id="ap-student-search" type="search" placeholder="Nom ou prénom" autocomplete="off"></label><div id="ap-student-choices"></div>');
    let seq=0,timer;
    async function search(){const n=++seq;const result=await api('/etudiants?q='+encodeURIComponent($('ap-student-search').value));if(n!==seq||!$('ap-student-choices'))return;$('ap-student-choices').innerHTML=result.students.map(p=>`<button type="button" class="ap-choose-student" data-ap-choose="${esc(p.id)}"><span class="ap-avatar">${esc(initials(p.prenom+' '+p.nom))}</span><div><b>${esc(p.prenom+' '+p.nom)}</b><small>${esc(p.bts)}</small></div></button>`).join('')||'<p>Aucun étudiant trouvé.</p>';}
    $('ap-student-search').addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>search().catch(e=>toast(e.message)),220);});await search();
  }
  async function generate(kind) {
    await save();const result=await api('/dossiers/'+current.id+'/documents',{method:'POST',body:{kind,version:current.version}});current=result.dossier;renderEditor();
    showSmall(kind==='cerfa'?'Votre CERFA est prêt':'Votre convention est prête',`<p>Relisez le document avant signature. Les informations encore manquantes doivent être complétées.</p><a class="ap-button ap-primary" href="${result.document_url}" target="_blank" rel="noopener">Ouvrir le PDF ↗</a><a class="ap-button ap-secondary" href="${result.document_url}?download=1">Télécharger</a>`);
  }
  async function upload(kind) {
    await save();smallForm('Ajouter '+(kind==='cerfa'?'le CERFA signé':'la convention signée'),`<p>Version ${current.revision} du dossier #${current.id}. Toute modification ultérieure du dossier nécessitera une nouvelle version signée.</p><label class="ap-field"><span>Document PDF · 8 Mo maximum</span><input type="file" name="file" accept="application/pdf" required></label><label class="ap-checkbox"><input type="checkbox" name="confirmed" required><span>Ce document correspond à la version enregistrée et comporte les signatures requises.</span></label>`,async form=>{form.set('kind',kind);form.set('version',current.version);form.set('confirmed','true');current=(await api('/dossiers/'+current.id+'/documents-signes',{method:'POST',body:form})).dossier;small.close();renderEditor();toast('Document signé enregistré');await loadRows();},'Ajouter le document');
  }
  async function transmit() {
    await save();smallForm('Confirmer la télétransmission',`<p>Dossier <b>#${current.id}</b> de <b>${esc(current.name)}</b>, à destination de <b>${esc(providerName(current.provider))}</b>.</p><p>${current.environment==='production'?'<strong>Dépôt réel en production.</strong> Le CERFA dématérialisé et la convention signée seront transmis à l’OPCO.':'<strong>Recette : test uniquement.</strong> Ce dépôt ne constitue pas une transmission de production.'}</p><label class="ap-field"><span>Recopiez le numéro ${current.id} pour confirmer</span><input name="confirm" required pattern="${current.id}" autocomplete="off"></label>`,async form=>{try {current=(await api('/dossiers/'+current.id+'/transmettre',{method:'POST',body:{version:current.version,environment:current.environment,confirm:form.get('confirm')}})).dossier;} catch(error) {current=(await api('/dossiers/'+current.id)).dossier;small.close();renderEditor();await loadRows();throw error;} small.close();renderEditor();await loadRows();toast('Accusé de réception OPCO enregistré');},'Transmettre à l’OPCO');
  }
  async function retrieve() {
    await save();
    const fetchDossier=async fields=>{current=(await api('/dossiers/'+current.id+'/recuperer',{method:'POST',body:{version:current.version,...fields}})).dossier;small.close();renderEditor();await loadRows();toast('Statut et échéances récupérés');};
    if(current.opco_ref)return fetchDossier({});
    smallForm('Récupérer un dossier OPCO',`<p>Lecture auprès de ${esc(providerName(current.provider))} en <b>${current.environment}</b>. L’identité et la date de naissance seront vérifiées avant tout rattachement. Les informations disponibles seront récupérées dans ce dossier.</p><div class="ap-form-grid"><label class="ap-field wide"><span>Numéro interne technique attribué par l’OPCO</span><input name="reference" placeholder="À distinguer du numéro Intégrale Academy"></label><div class="ap-field wide"><span>Ou renseignez les deux références suivantes :</span></div><label class="ap-field"><span>Numéro de dossier OPCO</span><input name="external"></label><label class="ap-field"><span>Numéro DECA</span><input name="deca"></label></div>`,form=>fetchDossier(Object.fromEntries(form)),'Récupérer le dossier');
  }
  function dueForm(existing) {
    const d=existing||{},did=d.dossier_id||current.id;
    smallForm(d.id?'Modifier l’échéance':'Ajouter une échéance',`<p>Cette saisie constitue votre suivi interne. Les échéances retournées par l’OPCO restent en lecture seule.</p><div class="ap-form-grid"><label class="ap-field wide"><span>Libellé</span><input name="label" value="${esc(d.label)}" required></label><label class="ap-field"><span>Date d’échéance</span><input type="date" name="due_date" value="${esc(d.due_date)}" required></label><label class="ap-field"><span>Financeur</span><select name="payer"><option ${d.payer==='OPCO'?'selected':''}>OPCO</option><option ${d.payer==='Entreprise'?'selected':''}>Entreprise</option></select></label><label class="ap-field"><span>Montant (€)</span><input type="number" min="0.01" step="0.01" name="amount" value="${d.amount||''}" required></label><label class="ap-field"><span>Montant réglé (€)</span><input type="number" min="0" step="0.01" name="paid" value="${d.paid||0}" required></label><label class="ap-field wide"><span>Référence de facture · si facturée</span><input name="invoice" value="${esc(d.invoice)}"></label></div>`,async form=>{const values=Object.fromEntries(form);values.amount_cents=Math.round(Number(values.amount)*100);values.paid_cents=Math.round(Number(values.paid)*100);if(d.id){values.id=d.id;values.version=d.version;}await api('/dossiers/'+did+'/echeances',{method:'POST',body:values});small.close();await loadRows();toast('Échéance enregistrée');});
  }
  async function connections() {
    const result=await api('/connexions');
    smallForm('Connexions Convergence',`<div class="ap-connections-list">${result.connections.map(c=>badge(providerName(c.provider)+' · '+c.environment,'accepted')).join('')||'<p>Aucune connexion enregistrée.</p>'}</div><p>La clé AKTO de recette reste disponible dans <a href="/admin/parametres#akto-convergence">les paramètres existants</a>. Pour les autres accès, renseignez les informations d’accrochage fournies par l’OPCO. Les secrets ne sont jamais réaffichés.</p><div class="ap-form-grid"><label class="ap-field"><span>OPCO</span><select name="provider">${Object.entries(config.providers).map(([v,t])=>`<option value="${v}">${t}</option>`).join('')}</select></label><label class="ap-field"><span>Environnement</span><select name="environment"><option value="production">Production</option><option value="recette">Recette</option></select></label>${[['api','URL de base API','url'],['token','URL d’authentification','url'],['client_id','Identifiant logiciel','text'],['client_secret','Secret logiciel','password'],['key','Clé CFA','password'],['scope','Portée (scope)','text']].map(([k,t,type])=>`<label class="ap-field ${['api','token','key'].includes(k)?'wide':''}"><span>${t}</span><input type="${type}" name="${k}" ${k==='scope'?'':'required'} autocomplete="off"></label>`).join('')}<label class="ap-field"><span>Authentification du logiciel</span><select name="auth_mode"><option value="basic">HTTP Basic (AKTO)</option><option value="body">Dans le corps du formulaire</option></select></label></div>`,async form=>{const r=await api('/connexions',{method:'POST',body:Object.fromEntries(form)});small.close();toast(r.message);});
  }
  function exportCSV() {
    const cols=isDues?['name','reference','label','payer','provider','environment','due_date','amount','paid','state']:['id','name','training','promotion','employer','provider','environment','state_label','start','end'];
    const cell=v=>{let s=String(v??'');if(/^[=+@\-\t\r]/.test(s))s="'"+s;return '"'+s.replace(/"/g,'""')+'"';};
    const text='\uFEFF'+[cols,...visible.map(r=>cols.map(k=>r[k]))].map(row=>row.map(cell).join(';')).join('\r\n');
    const url=URL.createObjectURL(new Blob([text],{type:'text/csv;charset=utf-8;'})),link=document.createElement('a');link.href=url;link.download=isDues?'echeances-apprentissage.csv':'dossiers-apprentissage.csv';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  document.addEventListener('click',e=>{
    const b=e.target.closest('button,[data-ap-open]');if(!b||b.disabled)return;
    if(b.hasAttribute('data-ap-small-close')){if(!busy)small.close();return;}
    if(b.dataset.apTab){activateTab(b.dataset.apTab);return;}
    if(b.dataset.apGoto){activateTab(b.dataset.apGoto,true);return;}
    if(b.dataset.apSubtab){root.querySelectorAll('[data-ap-subtab]').forEach(x=>x.setAttribute('aria-pressed',x===b));root.querySelectorAll('[data-ap-subpanel]').forEach(x=>x.hidden=x.dataset.apSubpanel!==b.dataset.apSubtab);return;}
    if(b.dataset.apPage){page+=Number(b.dataset.apPage);renderRows();return;}
    if(b.dataset.apIssue){const path=b.dataset.apIssue,g=[...config.groups].sort((a,b)=>b.path.length-a.path.length).find(x=>path.startsWith(x.path+'.')),tab=path.startsWith('details.')?'management':g?.tab||'tracking';activateTab(tab,true);const input=[...dialog.querySelectorAll('[data-ap-field]')].find(x=>x.dataset.apField===path);if(input){const group=input.closest('details');if(group)group.open=true;input.focus();input.scrollIntoView({block:'center',behavior:'smooth'});}return;}
    if(b.hasAttribute('data-ap-add-period')){if($('ap-periods').children.length>=8){toast('Huit périodes maximum.');return;}$('ap-periods').insertAdjacentHTML('beforeend',periodHTML());changed();return;}
    if(b.hasAttribute('data-ap-remove-period')){b.closest('[data-ap-period]').remove();changed();return;}
    if(b.hasAttribute('data-ap-create'))run(createChoice);
    else if(b.dataset.apChoose)run(()=>createFor(b.dataset.apChoose));
    else if(b.dataset.apOpen)run(()=>open(b.dataset.apOpen));
    else if(b.dataset.apGenerate)run(()=>generate(b.dataset.apGenerate));
    else if(b.dataset.apUpload)run(()=>upload(b.dataset.apUpload));
    else if(b.hasAttribute('data-ap-transmit'))run(transmit);
    else if(b.hasAttribute('data-ap-retrieve'))run(retrieve);
    else if(b.hasAttribute('data-ap-connections'))run(connections);
    else if(b.hasAttribute('data-ap-refresh'))run(loadRows);
    else if(b.hasAttribute('data-ap-export'))exportCSV();
    else if(b.hasAttribute('data-ap-add-due'))dueForm();
    else if(b.dataset.apEditDue)dueForm(rows.find(r=>r.id===b.dataset.apEditDue));
    else if(b.hasAttribute('data-ap-archive'))smallForm('Archiver ce dossier',`<p>Le dossier #${current.id} sera archivé localement. Aucun message ni annulation ne sera envoyé à l’OPCO.</p>`,async()=>{current=(await api('/dossiers/'+current.id+'/archiver',{method:'POST',body:{version:current.version}})).dossier;small.close();renderEditor();await loadRows();},'Archiver');
  });
  $('ap-close').addEventListener('click',close);dialog.addEventListener('cancel',e=>{e.preventDefault();close();});
  small.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
  $('ap-save').addEventListener('click',()=>run(save));$('ap-editor').addEventListener('submit',e=>{e.preventDefault();run(save);});
  $('ap-editor').addEventListener('input',e=>{if(e.target.matches('input,select,textarea'))changed();});
  $('ap-editor').addEventListener('change',e=>{if(e.target.matches('input,select,textarea'))changed();});
  dialog.addEventListener('keydown',e=>{const tab=e.target.closest('[data-ap-tab]');if(!tab||!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;e.preventDefault();const tabs=[...dialog.querySelectorAll('[data-ap-tab]')];const index=e.key==='Home'?0:e.key==='End'?tabs.length-1:(tabs.indexOf(tab)+(e.key==='ArrowRight'?1:-1)+tabs.length)%tabs.length;activateTab(tabs[index].dataset.apTab,true);});
  window.addEventListener('beforeunload',e=>{if(dirty){e.preventDefault();e.returnValue='';}});
  root.querySelectorAll('.ap-filters input,.ap-filters select').forEach(el=>el.addEventListener(el.tagName==='INPUT'?'input':'change',()=>{page=1;if(el.id==='ap-training')selectOptions('ap-promotion',rows.filter(r=>!el.value||r.training===el.value).map(r=>r.promotion),'Toutes les promotions');renderRows();}));
  run(async()=>{config=await api('/config');await loadRows();const id=new URLSearchParams(location.search).get('dossier');if(id&&/^[a-f0-9]{6}$/.test(id))await open(id);});
})();

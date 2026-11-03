(() => {
  const form = document.getElementById('application-form');
  if (!form) return;
  const steps = [...form.querySelectorAll('.application-step')];
  const nav = [...document.querySelectorAll('#step-navigation button')];
  const guide = document.getElementById('application-guide');
  const catalog = document.getElementById('choix-formation');
  const journey = document.getElementById('application-journey');
  const previewSelect = document.getElementById('preview-step');
  const activeSteps = () => steps.filter(step => step.dataset.available !== 'false');
  const positionOfField = name => steps.findIndex(step => step.querySelector(`[name="${name}"]`));
  const previous = document.getElementById('previous-step');
  const next = document.getElementById('next-step');
  const send = document.getElementById('send-application');
  const save = document.getElementById('save-application');
  const error = document.getElementById('application-error');
  const notice = document.getElementById('application-notice');
  const preview = form.dataset.preview === 'true';
  const titleJourney = form.dataset.titleJourney === 'true';
  const distanceInfo = document.getElementById('infosDistanciel');
  const enforce = () => !preview || !!document.getElementById('preview-validation')?.checked;
  let index = 0, furthest = 0, submitting = false, started = false;
  // Read checked values even while a conditional field is disabled so returning
  // to MOS restores its dependent panels in the same change event.
  const value = name => form.elements.namedItem(name)?.value || '';
  const showMessage = (message, failure = true) => { const el = failure ? error : notice; el.textContent = message; el.hidden = false; };
  function formatName(input) {
    if (!['nom', 'prenom', 'resp_nom', 'resp_prenom'].includes(input.name)) return;
    const clean = input.value.trim().replace(/\s+/g, ' ');
    input.value = ['nom', 'resp_nom'].includes(input.name) ? clean.toLocaleUpperCase('fr') : clean.toLocaleLowerCase('fr').replace(/(^|[\s’'\-])(\p{L})/gu, (_, separator, letter) => separator + letter.toLocaleUpperCase('fr'));
  }
  function normalizeNames() { [...form.elements].forEach(formatName); }
  form.addEventListener('focusout', event => formatName(event.target));
  const sessionChoice = document.getElementById('title-session');
  function syncTitleSession() {
    const radio = form.querySelector('[name="bts"]:checked');
    const options = [...sessionChoice.options].slice(1);
    const matches = options.filter(option => option.dataset.title === radio?.value);
    options.forEach(option => { option.hidden = option.disabled = !matches.includes(option); });
    if (!matches.includes(sessionChoice.selectedOptions[0])) sessionChoice.value = '';
    if (matches.length === 1) sessionChoice.value = matches[0].value;
    const session = sessionChoice.selectedOptions[0];
    document.getElementById('title-session-field').hidden = !matches.length;
    sessionChoice.required = matches.length > 0;
    document.getElementById('recap-title-name').textContent = radio?.closest('label').querySelector('b').textContent || 'choisi';
    if (!preview) {
      form.action = session?.dataset.submit || location.pathname;
      form.dataset.draftUrl = session?.dataset.draft || '';
      form.elements.title_promotion_id.value = session?.value || '';
      form.elements.submission_token.value = session?.dataset.token || '';
      save.disabled = !session?.dataset.draft;
    }
    const year = session?.dataset.year || form.elements.rentree_annee.dataset.defaultYear;
    form.elements.rentree_annee.value = year;
    const expectedBac = form.elements.baccalaureat.querySelector('[value^="Prévu en"]');
    expectedBac.value = 'Prévu en ' + year;
    expectedBac.textContent = 'Je le prépare en ' + year;
  }
  function conditional() {
    const birth = value('date_naissance');
    const today = new Date();
    const parts = birth.split('-').map(Number);
    const age = today.getFullYear() - parts[0] - ((today.getMonth() + 1 < parts[1] || (today.getMonth() + 1 === parts[1] && today.getDate() < parts[2])) ? 1 : 0);
    const selectedBts = value('bts');
    const formationInfo = document.getElementById('formation-info');
    const trainingPanels = [...form.querySelectorAll('[data-training-info]')];
    trainingPanels.forEach(panel => { panel.hidden = panel.dataset.trainingInfo !== selectedBts; });
    if (formationInfo) formationInfo.hidden = !trainingPanels.some(panel => !panel.hidden);
    const mos = selectedBts === 'MOS';
    const aps = mos && value('mos_parcours') === 'autre';
    const conditions = {mos, aps, 'aps-yes': aps && value('aps_souhaitee') === 'oui', 'aps-no': aps && value('aps_souhaitee') === 'non', minor: !!birth && age < 18, 'bac-other': value('bac_type') === 'Autre', idf: value('cherche_idf') === 'oui'};
    form.querySelectorAll('[data-condition]').forEach(block => { block.hidden = !conditions[block.dataset.condition]; });
    steps.forEach(step => { step.dataset.available = String(!step.dataset.stepCondition || !!conditions[step.dataset.stepCondition]); });
    // Hide irrelevant questions from validation and payload, keeping their answers
    // in memory in case the applicant changes the earlier choice again.
    form.querySelectorAll('input,select,textarea').forEach(input => {
      input.disabled = input.hasAttribute('data-unavailable') || !!input.closest('[data-condition][hidden], [data-available="false"]');
    });
    if (previewSelect) {
      previewSelect.querySelectorAll('option[data-question]').forEach(option => {
        option.hidden = steps[Number(option.value)].dataset.available === 'false';
        option.disabled = option.hidden;
      });
    }
    updateProgress();
  }
  function validate(step) {
    normalizeNames();
    conditional();
    if (titleJourney && step === 0 && !preview && !form.dataset.draftUrl) {
      showMessage(document.getElementById('title-intake-notice')?.textContent || 'Choisis un titre et une session ouverte pour continuer.'); return false;
    }
    if (!enforce() || steps[step].dataset.available === 'false') return true;
    const fields = [...steps[step].querySelectorAll('input,select,textarea')].filter(x => !x.disabled);
    for (const field of fields) {
      field.setCustomValidity('');
      if (field.type === 'email') field.value = field.value.trim();
      if (field.name === 'email_confirm' && field.value.toLowerCase() !== value('email').toLowerCase()) field.setCustomValidity('Les deux adresses e-mail doivent être identiques.');
      if (field.name === 'num_secu') {const result=AdmissionValidation.nir(field.value,value('date_naissance'),value('sexe'));field.setCustomValidity(result.ok?'':result.message);}
      if (field.name === 'date_naissance' && field.value >= new Date().toLocaleDateString('en-CA')) field.setCustomValidity('Vérifie ta date de naissance.');
      if (field.type === 'file' && field.files[0]) {
        const file = field.files[0];
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (['carte_vitale','cv','lm'].includes(field.name) && file.size < 10*1024) field.setCustomValidity('Ce PDF semble vide ou incomplet (moins de 10 Ko). Ajoute un document lisible.');
        if (!field.accept.split(',').includes(ext) || file.size > 8 * 1024 * 1024 || file.size === 0) field.setCustomValidity('Vérifie le format et la taille du fichier (8 Mo maximum).');
      }
      if (!field.checkValidity()) {
        field.classList.add('invalid'); field.setAttribute('aria-invalid','true');
        if (!steps[step].hidden) field.reportValidity();
        showMessage(field.validationMessage); return false;
      }
      field.classList.remove('invalid'); field.removeAttribute('aria-invalid');
    }
    for(const group of steps[step].querySelectorAll('[data-required-group]')) {
      if(!group.querySelector('input:checked')) {showMessage('Choisis au moins une réponse pour cette question.');group.querySelector('input').focus();return false;}
    }
    return true;
  }
  function nirFeedback() {
    const input=form.elements.num_secu, help=document.getElementById('numSecuHelp');
    const result=AdmissionValidation.nir(input.value,value('date_naissance'),value('sexe'));
    help.textContent=input.value?result.message:'15 caractères, avec la clé de contrôle. Vérification automatique pendant la saisie.';
    help.dataset.state=input.value?(result.ok?'valid':'invalid'):'';
    input.setCustomValidity(input.value&&!result.ok?result.message:'');
    input.classList.toggle('invalid',!!input.value&&!result.ok);input.setAttribute('aria-invalid',String(!!input.value&&!result.ok));
    return result.ok;
  }
  window.verifierNumSecu=nirFeedback;
  function recap() {
    const container = document.getElementById('application-recap'); container.replaceChildren();
    const chapters = new Map();
    const radioLabels = {bts:'Formation', mode:'Format des cours', mos_parcours:'Situation', aps_souhaitee:'Formation APS', permis_b:'Permis B', entreprise_trouvee:'Entreprise', recherches_commencees:'Recherche', cherche_idf:'Zone de recherche'};
    function addAnswer(list, label, answer, missing = 'À compléter') {
      const dt = document.createElement('dt'), dd = document.createElement('dd');
      dt.textContent = label.replace(/\s*\*$/, ''); dd.textContent = answer || missing;
      if (!answer) dd.className = 'recap-missing';
      list.append(dt, dd);
    }
    activeSteps().slice(0,-1).forEach(step => {
      const group = Number(step.dataset.group);
      if (!chapters.has(group)) {
        const card = document.createElement('section'); card.className = 'review-card';
        const header = document.createElement('header'), title = document.createElement('h3');
        title.textContent = nav[group].querySelector('span:nth-child(2)').textContent;
        const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'text-link'; edit.textContent = 'Modifier';
        edit.setAttribute('aria-label','Modifier : '+title.textContent);
        edit.addEventListener('click', () => show(steps.indexOf(step)));
        const list = document.createElement('dl'); header.append(title,edit); card.append(header,list);
        container.append(card); chapters.set(group,list);
      }
      const list = chapters.get(group), seen = new Set();
      step.querySelectorAll('input,select,textarea').forEach(field => {
        if (!field.name || field.disabled || seen.has(field.name) || field.name === 'email_confirm') return;
        seen.add(field.name);
        const label = field.closest('label');
        let name = field.dataset.label || label?.querySelector('span')?.textContent || step.dataset.title;
        let answer = field.value;
        if (field.type === 'radio' || field.type === 'checkbox') {
          name = radioLabels[field.name] || step.dataset.title;
          answer = [...step.querySelectorAll('input:checked')].filter(item => item.name === field.name)
            .map(item => { const option = item.closest('label'); return (option.querySelector('b') || option).textContent.trim(); }).join(', ');
        } else if (field.type === 'file') { answer = field.files[0]?.name; }
        else if (field.name === 'num_secu' && answer) { answer = '•••••••••••' + answer.slice(-4); }
        else if (field.type === 'date' && answer) { answer = answer.split('-').reverse().join('/'); }
        else if (field.tagName === 'SELECT' && answer) { answer = field.selectedOptions[0].textContent; }
        addAnswer(list,name,answer,field.type === 'file' ? (field.required ? 'Pièce à joindre' : 'Facultatif') : 'À compléter');
      });
      if (titleJourney && step.dataset.stepId === 'formation') {
        addAnswer(list,'Lieu des cours','À l’école à Puget-sur-Argens, Côte d’Azur');
        if (sessionChoice.value) addAnswer(list,'Session',sessionChoice.selectedOptions[0].textContent);
      }
    });
  }
  function updateProgress() {
    const active = activeSteps(), current = steps[index], position = active.indexOf(current);
    const group = Number(current.dataset.group);
    nav.forEach(button => {
      const chapter = Number(button.dataset.groupNav);
      const target = steps.findIndex(step => Number(step.dataset.group) === chapter && step.dataset.available !== 'false');
      button.disabled = enforce() && target > furthest;
      button.classList.toggle('active', chapter === group);
      button.classList.toggle('done', chapter < group);
      if (chapter === group) button.setAttribute('aria-current','step'); else button.removeAttribute('aria-current');
    });
    document.getElementById('step-label').textContent = `ÉTAPE ${position+1} SUR ${active.length} · ${nav[group].querySelector('span:nth-child(2)').textContent.toUpperCase()}`;
    document.getElementById('step-percent').textContent = `${Math.round(position / (active.length - 1) * 100)} %`;
    document.getElementById('application-progress').value = position;
    document.getElementById('application-progress').max = active.length - 1;
    previous.setAttribute('aria-label', position === 0 ? 'Revenir au choix de formation' : 'Revenir à l’étape précédente');
    next.hidden = current === active.at(-1); send.hidden = !next.hidden;
    if (previewSelect && started && !journey.hidden) previewSelect.value = String(index);
  }
  function focusHeading(heading, region) {
    heading.focus({preventScroll:true});
    region.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'});
  }
  function showGuide(focus = true) {
    if (catalog) catalog.hidden = true;
    journey.hidden = true; guide.hidden = false;
    document.body.dataset.applicationView = 'guide';
    if (previewSelect) previewSelect.value = 'guide';
    const label = document.querySelector('[data-start-label]');
    label.textContent = started ? 'Reprendre ma pré-inscription ' : 'Commencer ma pré-inscription ';
    if (focus) focusHeading(document.getElementById('preparation-title'),guide);
  }
  function show(step, focus = true) {
    if (steps[step]?.dataset.available === 'false' || !steps[step]) return;
    index = step; started = true;
    if (catalog) catalog.hidden = true;
    guide.hidden = true; journey.hidden = false;
    document.body.dataset.applicationView = 'form';
    document.body.dataset.applicationStep = steps[index].dataset.stepId;
    const current = steps[index];
    current.classList.remove('step-enter'); void current.offsetWidth; current.classList.add('step-enter');
    furthest = Math.max(furthest,index); error.hidden = true; notice.hidden = true;
    steps.forEach((section,i) => { section.hidden = i !== index; });
    updateProgress();
    if (current.dataset.stepId === 'recap') recap();
    if (focus) focusHeading(current.querySelector('h2'),document.querySelector('.application-main'));
  }
  function navigateTo(target) {
    if (target > index && enforce()) {
      for (const step of activeSteps()) {
        const position = steps.indexOf(step);
        if (position >= index && position < target && !validate(position)) {show(position); validate(position); return;}
      }
    }
    show(target);
  }
  function advance() {
    if (!validate(index)) return;
    const active = activeSteps(), nextStep = active[active.indexOf(steps[index])+1];
    if (nextStep) show(steps.indexOf(nextStep));
  }
  previous.addEventListener('click', () => {
    const active = activeSteps(), position = active.indexOf(steps[index]);
    if (position > 0) show(steps.indexOf(active[position-1])); else if (titleJourney) location.assign(previous.dataset.orientationUrl); else if (catalog) showChoice(); else showGuide();
  });
  next.addEventListener('click', advance);
  nav.forEach(button => button.addEventListener('click', () => {
    const target = steps.findIndex(step => step.dataset.group === button.dataset.groupNav && step.dataset.available !== 'false');
    navigateTo(target);
  }));
  function showChoice() {
    guide.hidden = true; journey.hidden = true; catalog.hidden = false;
    document.body.dataset.applicationView = 'choice';
    if (previewSelect) previewSelect.value = 'choice';
    focusHeading(document.getElementById('catalog-title'), catalog);
  }
  document.getElementById('start-application').addEventListener('click', () => {
    if (started || titleJourney) show(index);
    else showChoice();
  });
  document.getElementById('start-bts')?.addEventListener('click', () => show(index));
  document.getElementById('choice-back')?.addEventListener('click', () => showGuide());
  document.getElementById('review-preparation').addEventListener('click', () => showGuide());
  function openLinkedSection() {
    if (location.hash === '#titres-professionnels') {
      location.replace(document.getElementById('choose-titles').href);
    } else if (location.hash === '#choix-formation') {
      showChoice();
    }
  }
  if (catalog) window.addEventListener('hashchange', openLinkedSection);
  document.querySelectorAll('[data-prepared]').forEach(input => input.addEventListener('change', () => {
    const count = document.querySelectorAll('[data-prepared]:checked').length;
    document.getElementById('preparation-count').textContent = `${count} / 5 pièces préparées`;
  }));
  if (previewSelect) {
    steps.forEach((step,i) => {
      const option = document.createElement('option'); option.value = String(i); option.dataset.question = '';
      option.textContent = step.dataset.title; previewSelect.append(option);
    });
    previewSelect.addEventListener('change', () => { if (previewSelect.value === 'guide') showGuide(); else if (previewSelect.value === 'choice') showChoice(); else navigateTo(Number(previewSelect.value)); });
    document.getElementById('preview-validation').addEventListener('change', updateProgress);
  }
  form.addEventListener('change', event=>{if (sessionChoice && (event.target.name === 'bts' || event.target === sessionChoice)) syncTitleSession(); conditional();if(event.target.name==='mode' && distanceInfo)distanceInfo.open=value('mode')==='distanciel';if(['num_secu','date_naissance','sexe'].includes(event.target.name))nirFeedback();});
  form.addEventListener('input', event => {
    const input = event.target; input.setCustomValidity?.(''); input.classList.remove('invalid'); input.removeAttribute('aria-invalid');
    if (input.type === 'tel') input.value = input.value.replace(/\D/g,'');
    if (input.name === 'num_secu') input.value = input.value.toUpperCase().replace(/[^0-9AB]/g,'').slice(0,15);
    if(['num_secu','date_naissance','sexe'].includes(input.name))nirFeedback();
  });
  form.querySelectorAll('input[type="file"]').forEach(input => input.addEventListener('change', () => {
    const state = input.closest('label').querySelector('.file-state'); const file = input.files[0]; state.textContent = file ? `${file.name} · ${(file.size/1024/1024).toFixed(1)} Mo` : 'Choisir un fichier'; input.closest('label').classList.toggle('has-file',!!file);
  }));
  form.addEventListener('keydown', event => { if(!event.defaultPrevented && event.key==='Enter' && event.target.tagName==='INPUT' && !['file','checkbox','radio','submit'].includes(event.target.type)) { event.preventDefault(); if(index<steps.length-1) advance(); } });
  save.addEventListener('click', async () => {
    if(preview || (titleJourney && !form.dataset.draftUrl)) return;
    const email = form.elements.email;
    if(!email.value || !email.checkValidity()) { show(positionOfField('email')); email.focus(); showMessage('Indique ton e-mail pour recevoir un lien de reprise.'); return; }
    normalizeNames();
    save.disabled=true; save.textContent='Enregistrement…';
    const full_form={}; new FormData(form).forEach((val,key) => { if(val instanceof File) return; if(key.endsWith('[]')) (full_form[key] ||= []).push(val); else full_form[key]=val; });
    try { const res=await fetch(form.dataset.draftUrl || '/save_draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({full_form})}); const data=await res.json(); if(!res.ok || !data.success) throw new Error(data.error || 'Impossible d’enregistrer le dossier.'); showMessage('Ton brouillon est enregistré. Un lien de reprise a été envoyé à ton adresse e-mail. Pense à sélectionner à nouveau tes fichiers lors de la reprise.',false); }
    catch(err){showMessage(err.message);} finally{save.disabled=false;save.textContent='Enregistrer et reprendre plus tard';}
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if(submitting || form.dataset.preview==='true') return;
    if(steps[index].dataset.stepId!=='recap') { advance(); return; }
    for(let i=0;i<steps.length;i++){if(!validate(i)){show(i);validate(i);return;}}
    submitting=true;document.body.classList.add('application-sending');send.disabled=true;save.disabled=true;previous.disabled=true;send.textContent='Envoi de ta candidature…';form.setAttribute('aria-busy','true');
    try{const res=await fetch(form.action,{method:'POST',headers:{Accept:'application/json'},body:new FormData(form)}); const type=res.headers.get('content-type') || ''; if(!type.includes('application/json')) throw new Error('L’envoi n’a pas pu être confirmé. Réessaie ou contacte notre équipe.'); const data=await res.json();if(!res.ok || !data.ok)throw new Error(data.error || 'Impossible de transmettre ta candidature.');document.body.classList.remove('application-sending'); if(window.BTSAdmissionCelebration) await window.BTSAdmissionCelebration.show(data.redirect); else window.location.assign(data.redirect);}
    catch(err){showMessage(err.message);document.body.classList.remove('application-sending');submitting=false;send.disabled=false;save.disabled=false;previous.disabled=false;send.textContent='Envoyer ma candidature';form.removeAttribute('aria-busy');}
  });
  const saved=JSON.parse(document.getElementById('saved-application').textContent || 'null');
  if(saved) Object.entries(saved).forEach(([key,val]) => { [...form.elements].filter(x=>x.name===key&&x.type!=='file').forEach(input=>{if(['radio','checkbox'].includes(input.type))input.checked=Array.isArray(val)?val.includes(input.value):input.value===String(val);else input.value=val;}); });
  if (sessionChoice) syncTitleSession();
  normalizeNames();conditional();if(distanceInfo)distanceInfo.open=value('mode')==='distanciel';nirFeedback();
  if(saved) { show(0,false); showMessage('Ton brouillon est chargé. Vérifie les étapes, puis ajoute à nouveau tes justificatifs.',false); } else if (titleJourney) show(0,false); else { showGuide(false); openLinkedSection(); }
})();

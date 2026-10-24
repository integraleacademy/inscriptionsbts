(() => {
  const form = document.getElementById('application-form');
  if (!form) return;
  const steps = [...form.querySelectorAll('.application-step')];
  const nav = [...document.querySelectorAll('#step-navigation button')];
  const previous = document.getElementById('previous-step');
  const next = document.getElementById('next-step');
  const send = document.getElementById('send-application');
  const save = document.getElementById('save-application');
  const error = document.getElementById('application-error');
  const notice = document.getElementById('application-notice');
  let index = 0, furthest = 0, submitting = false;
  const value = name => new FormData(form).get(name) || '';
  const showMessage = (message, failure = true) => { const el = failure ? error : notice; el.textContent = message; el.hidden = false; };
  function conditional() {
    const birth = value('date_naissance');
    const today = new Date();
    const parts = birth.split('-').map(Number);
    const age = today.getFullYear() - parts[0] - ((today.getMonth() + 1 < parts[1] || (today.getMonth() + 1 === parts[1] && today.getDate() < parts[2])) ? 1 : 0);
    const mos = value('bts') === 'MOS';
    const aps = mos && value('mos_parcours') === 'autre';
    const conditions = {mos, aps, 'aps-no': aps && value('aps_souhaitee') === 'non', minor: !!birth && age < 18, 'bac-other': value('bac_type') === 'Autre', idf: value('cherche_idf') === 'oui'};
    form.querySelectorAll('[data-condition]').forEach(block => { block.hidden = !conditions[block.dataset.condition]; });
    form.querySelectorAll('[data-condition] input, [data-condition] textarea, [data-condition] select').forEach(input => { input.disabled = !!input.closest('[data-condition][hidden]'); });
  }
  function validate(step) {
    conditional();
    const fields = [...steps[step].querySelectorAll('input,select,textarea')].filter(x => !x.disabled);
    for (const field of fields) {
      field.setCustomValidity('');
      if (field.type === 'email') field.value = field.value.trim();
      if (field.name === 'email_confirm' && field.value.toLowerCase() !== value('email').toLowerCase()) field.setCustomValidity('Les deux adresses e-mail doivent être identiques.');
      if (field.name === 'date_naissance' && field.value >= new Date().toLocaleDateString('en-CA')) field.setCustomValidity('Vérifie ta date de naissance.');
      if (field.type === 'file' && field.files[0]) {
        const file = field.files[0];
        const ext = '.' + file.name.split('.').pop().toLowerCase();
        if (!field.accept.split(',').includes(ext) || file.size > 8 * 1024 * 1024 || file.size === 0) field.setCustomValidity('Vérifie le format et la taille du fichier (8 Mo maximum).');
      }
      if (!field.checkValidity()) {
        field.classList.add('invalid'); field.setAttribute('aria-invalid','true'); field.reportValidity();
        showMessage(field.validationMessage); return false;
      }
      field.classList.remove('invalid'); field.removeAttribute('aria-invalid');
    }
    return true;
  }
  function recap() {
    const container = document.getElementById('application-recap'); container.replaceChildren();
    steps.slice(0,-1).forEach((step,i) => {
      const block = document.createElement('section'); block.className = 'recap-section';
      const header = document.createElement('div'); const title = document.createElement('h3'); title.textContent = step.dataset.title;
      const edit = document.createElement('button'); edit.type = 'button'; edit.className = 'text-link'; edit.textContent = 'Modifier'; edit.addEventListener('click', () => show(i)); header.append(title,edit); block.append(header);
      const dl = document.createElement('dl'); const used = new Set();
      step.querySelectorAll('input,select,textarea').forEach(input => {
        if (input.disabled || !input.name || used.has(input.name) || ((input.type === 'checkbox' || input.type === 'radio') && !input.checked)) return;
        let content = input.type === 'file' ? input.files[0]?.name : input.value;
        if (input.type === 'radio' || input.type === 'checkbox') content = [...step.querySelectorAll(`input[name="${input.name}"]:checked`)].map(x => x.closest('label').textContent.trim()).join(', ');
        if (!content) return;
        used.add(input.name);
        const dt = document.createElement('dt'); const dd = document.createElement('dd');
        dt.textContent = input.type === 'radio' ? ({bts:'Formation',mode:'Format',mos_parcours:'Situation MOS',aps_souhaitee:'Formation APS',entreprise_trouvee:'Entreprise',recherches_commencees:'Recherches',cherche_idf:'Île-de-France',souhaite_accompagnement:'Accompagnement'}[input.name] || input.name) : (input.dataset.label || input.closest('label')?.querySelector('span')?.textContent || input.name.replace('[]',''));
        dd.textContent = input.name === 'num_secu' ? '•••••••••••' + content.slice(-4) : content;
        dl.append(dt,dd);
      }); block.append(dl); container.append(block);
    });
  }
  function show(step, focus = true) {
    index = step; furthest = Math.max(furthest,index); error.hidden = true; notice.hidden = true;
    steps.forEach((section,i) => { section.hidden = i !== index; });
    nav.forEach((button,i) => { button.disabled = i > furthest; button.classList.toggle('active',i===index); button.classList.toggle('done',i<index); if (i===index) button.setAttribute('aria-current','step'); else button.removeAttribute('aria-current'); });
    document.getElementById('step-label').textContent = `ÉTAPE ${index+1} SUR ${steps.length} · ${steps[index].dataset.title.toUpperCase()}`;
    document.getElementById('step-percent').textContent = `${Math.round(index / (steps.length - 1) * 100)} %`;
    document.getElementById('application-progress').value = index;
    document.getElementById('application-progress').max = steps.length-1;
    previous.hidden = index===0; next.hidden = index===steps.length-1; send.hidden = index!==steps.length-1;
    if (index===steps.length-1) recap();
    if (focus) { steps[index].querySelector('h2').focus({preventScroll:true}); document.querySelector('.application-main').scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'start'}); }
  }
  previous.addEventListener('click', () => show(index-1));
  next.addEventListener('click', () => { if (validate(index)) show(index+1); });
  nav.forEach((button,i) => button.addEventListener('click', () => { if(i<=index || validate(index)) show(i); }));
  form.addEventListener('change', conditional);
  form.addEventListener('input', event => {
    const input = event.target; input.setCustomValidity?.(''); input.classList.remove('invalid'); input.removeAttribute('aria-invalid');
    if (input.type === 'tel') input.value = input.value.replace(/\D/g,'');
    if (input.name === 'num_secu') input.value = input.value.toUpperCase().replace(/[^0-9AB]/g,'');
  });
  form.querySelectorAll('input[type="file"]').forEach(input => input.addEventListener('change', () => {
    const state = input.closest('label').querySelector('.file-state'); const file = input.files[0]; state.textContent = file ? `${file.name} · ${(file.size/1024/1024).toFixed(1)} Mo` : 'Choisir un fichier'; input.closest('label').classList.toggle('has-file',!!file);
  }));
  form.addEventListener('keydown', event => { if(event.key==='Enter' && event.target.tagName==='INPUT' && !['file','checkbox','radio','submit'].includes(event.target.type)) { event.preventDefault(); if(index<steps.length-1 && validate(index)) show(index+1); } });
  save.addEventListener('click', async () => {
    if(form.dataset.preview==='true') return;
    const email = form.elements.email;
    if(!email.value || !email.checkValidity()) { show(2); email.focus(); showMessage('Indique ton e-mail pour recevoir un lien de reprise.'); return; }
    save.disabled=true; save.textContent='Enregistrement…';
    const full_form={}; new FormData(form).forEach((val,key) => { if(val instanceof File) return; if(key.endsWith('[]')) (full_form[key] ||= []).push(val); else full_form[key]=val; });
    try { const res=await fetch('/save_draft',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({full_form})}); const data=await res.json(); if(!res.ok || !data.success) throw new Error(data.error || 'Impossible d’enregistrer le dossier.'); showMessage('Ton brouillon est enregistré. Un lien de reprise a été envoyé à ton adresse e-mail. Pense à sélectionner à nouveau tes fichiers lors de la reprise.',false); }
    catch(err){showMessage(err.message);} finally{save.disabled=false;save.textContent='Enregistrer et reprendre plus tard';}
  });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if(submitting || form.dataset.preview==='true') return;
    for(let i=0;i<steps.length;i++){if(!validate(i)){show(i);validate(i);return;}}
    submitting=true;send.disabled=true;save.disabled=true;previous.disabled=true;send.textContent='Envoi de ta candidature…';form.setAttribute('aria-busy','true');
    try{const res=await fetch(form.action,{method:'POST',headers:{Accept:'application/json'},body:new FormData(form)}); const type=res.headers.get('content-type') || ''; if(!type.includes('application/json')) throw new Error('L’envoi n’a pas pu être confirmé. Réessaie ou contacte notre équipe.'); const data=await res.json();if(!res.ok || !data.ok)throw new Error(data.error || 'Impossible de transmettre ta candidature.');window.location.assign(data.redirect);}
    catch(err){showMessage(err.message);submitting=false;send.disabled=false;save.disabled=false;previous.disabled=false;send.textContent='Envoyer ma candidature ↗';form.removeAttribute('aria-busy');}
  });
  const saved=JSON.parse(document.getElementById('saved-application').textContent || 'null');
  if(saved) Object.entries(saved).forEach(([key,val]) => { [...form.elements].filter(x=>x.name===key&&x.type!=='file').forEach(input=>{if(['radio','checkbox'].includes(input.type))input.checked=Array.isArray(val)?val.includes(input.value):input.value===String(val);else input.value=val;}); });
  conditional();show(0,false);
  if(saved)showMessage('Ton brouillon est chargé. Vérifie les étapes, puis ajoute à nouveau tes justificatifs.',false);
})();

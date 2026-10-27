/* Dedicated Academy catalogs. Course assignments remain controlled by the planning API. */
(() => {
  'use strict';
  const app = document.querySelector('.catalog-app');
  if (!app) return;
  const $ = id => document.getElementById(id), isSubjects = app.dataset.kind === 'subjects';
  const API = '/admin/planning/api', form = $('catalog-form'), editor = $('catalog-editor'), confirm = $('catalog-confirm');
  const state = {data: null, editing: null, deleting: null, loading: true, sequence: 0};
  const active = value => ![false, 0, '0', 'false'].includes(value);
  const ready = promotion => !!promotion && active(promotion.active) && !!promotion.date_debut && !!promotion.date_fin;
  const normal = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr');
  const safeColor = value => /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#66764e';
  const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = String(text); return node; };
  const number = value => new Intl.NumberFormat('fr-FR', {maximumFractionDigits: 2}).format(value);
  const minuteValue = (item, prefix) => {
    const minutes = item[prefix + '_minutes'];
    if (minutes !== null && minutes !== undefined && Number.isFinite(Number(minutes))) return Math.round(Number(minutes));
    const hours = item[prefix + '_hours'];
    return hours === null || hours === undefined || hours === '' || !Number.isFinite(Number(hours)) ? null : Math.round(Number(hours) * 60);
  };
  const duration = minutes => { if (minutes === null || minutes === undefined) return 'À définir'; const amount = Math.max(0, Math.round(minutes)); const h = Math.floor(amount / 60), m = amount % 60; return m ? (h ? number(h) + ' h ' : '') + m + ' min' : number(h) + ' h'; };
  const budget = item => item.budget_configured !== false && (minuteValue(item, 'planned') || 0) > 0;
  const promotionOf = item => state.data?.promotions.find(promotion => String(promotion.id) === String(item.promotion_id));
  const trainerName = trainer => AcademyNames.fullName(trainer.nom, trainer.prenom);
  const icon = name => { const template = document.querySelector('[data-catalog-create] svg') || document.querySelector('.catalog-stat-icon svg'); if (!template) return el('span'); const svg = template.cloneNode(true); if (name === 'person') { svg.replaceChildren(); for (const [tag, attrs] of [['circle', {cx: 12, cy: 7, r: 4}], ['path', {d: 'M4 21v-2a8 8 0 0 1 16 0v2'}]]) { const part = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const [key, value] of Object.entries(attrs)) part.setAttribute(key, value); svg.append(part); } } return svg; };
  function action(label, handler, cls = '') { const node = el('button', 'catalog-button ' + cls, label); node.type = 'button'; node.addEventListener('click', handler); return node; }
  function notice(message, error = false) { const node = $('catalog-notice'); node.textContent = message || ''; node.hidden = !message; node.classList.toggle('error', error); }
  function errorAt(id, message) { const node = $(id); node.textContent = message || ''; node.hidden = !message; }
  function failureText(data) { return [data.message || data.error || '', ...(data.conflicts || []).map(item => item.message)].filter(Boolean).filter((value, index, list) => list.indexOf(value) === index).join('\n') || 'L’action n’a pas abouti. Réessayez dans un instant.'; }
  async function request(path, method = 'GET', data) {
    const response = await fetch(API + path, {method, credentials: 'same-origin', headers: {Accept: 'application/json', ...(method !== 'GET' ? {'Content-Type': 'application/json', 'X-CSRF-Token': app.dataset.csrf} : {})}, ...(method !== 'GET' ? {body: JSON.stringify(data || {})} : {})});
    const result = await response.json().catch(() => { throw new Error('La connexion a expiré ou le service est indisponible. Rechargez la page avant de réessayer.'); });
    if (!response.ok || result.ok === false) throw new Error(failureText(result));
    return result;
  }
  function busy(dialog, value) {
    dialog.dataset.busy = value ? '1' : '';
    dialog.setAttribute('aria-busy', String(value));
    dialog.querySelectorAll('button,input,select,textarea').forEach(control => {
      if (value) { control.dataset.previousDisabled = control.disabled ? '1' : '0'; control.disabled = true; }
      else if (control.dataset.previousDisabled !== undefined) { control.disabled = control.dataset.previousDisabled === '1'; delete control.dataset.previousDisabled; }
    });
  }
  function show(dialog, focus) { dialog._opener = document.activeElement; dialog.showModal(); focus?.focus(); }
  for (const dialog of [editor, confirm]) {
    dialog.querySelectorAll('[data-catalog-close]').forEach(button => button.addEventListener('click', () => { if (!dialog.dataset.busy) dialog.close(); }));
    dialog.addEventListener('cancel', event => { if (dialog.dataset.busy) event.preventDefault(); });
    dialog.addEventListener('close', () => { if (dialog._opener?.isConnected) dialog._opener.focus(); });
  }
  function setLoading(value) { state.loading = value; app.setAttribute('aria-busy', String(value)); app.querySelectorAll('[data-catalog-create]').forEach(button => { button.disabled = value || !state.data || (isSubjects && !state.data.promotions.some(ready)); }); app.querySelectorAll('[data-catalog-edit]').forEach(button => { button.disabled = value; }); }
  function optionList(select, items, label, empty, selected = '') { select.replaceChildren(new Option(empty, '')); for (const item of items) select.add(new Option(label(item), String(item.id))); select.value = String(selected || ''); }
  async function load(message = '') {
    const sequence = ++state.sequence; setLoading(true); $('catalog-load-error').hidden = true;
    try {
      const data = await request('/catalog');
      if (sequence !== state.sequence) return;
      if (!['promotions', 'subjects', 'trainers', 'rooms'].every(key => Array.isArray(data[key]))) throw new Error('Le catalogue reçu est incomplet. Réessayez dans un instant.');
      state.data = data;
      if (isSubjects) {
        const select = $('catalog-promotion-filter'), selected = select.value || app.dataset.selectedPromotion || '';
        optionList(select, data.promotions, item => item.nom + (!active(item.active) ? ' · Archivée' : ''), 'Toutes les promotions', selected);
        app.dataset.selectedPromotion = '';
      }
      render(); notice(message);
    } catch (failure) {
      if (sequence !== state.sequence) return;
      state.data = null; $('catalog-grid').replaceChildren(); $('catalog-empty').hidden = true; $('catalog-load-error').hidden = false; $('catalog-count').textContent = 'Catalogue indisponible';
      ['one', 'two', 'three'].forEach(key => { $('catalog-stat-' + key).textContent = '—'; });
      notice((message ? message + ' L’actualisation du catalogue a toutefois échoué. ' : '') + failure.message, true);
    } finally { if (sequence === state.sequence) setLoading(false); }
  }
  function subjectCard(item) {
    const card = el('article', 'catalog-subject-card'); card.style.setProperty('--catalog-accent', safeColor(item.color));
    const promotion = promotionOf(item), planned = minuteValue(item, 'planned'), scheduled = minuteValue(item, 'scheduled') || 0, configured = budget(item), remaining = configured ? Math.max(0, planned - scheduled) : null;
    const top = el('div', 'catalog-card-top'); top.append(el('span', 'catalog-promotion', item.promotion_name || promotion?.nom || 'Promotion'));
    if (promotion && !active(promotion.active)) top.append(el('span', 'catalog-state inactive', 'Archivée'));
    card.append(top, el('h3', '', item.name));
    if (item.exam_unit || item.coefficient !== null && item.coefficient !== undefined) card.append(el('span', 'subject-reference-badge', [item.exam_unit, item.coefficient !== null && item.coefficient !== undefined ? 'Coefficient ' + number(item.coefficient) : '', item.optional ? 'Facultative' : ''].filter(Boolean).join(' · ')));
    const teacher = el('p', 'catalog-teacher'); teacher.append(icon('person'), el('span', '', item.trainer_name || 'Formateur à définir')); card.append(teacher);
    const metrics = el('div', 'catalog-hour-metrics');
    for (const [label, value, cls] of [['Prévues sur l’année', planned, ''], ['Planifiées', scheduled, ''], ['Restantes', remaining, 'remaining']]) { const part = el('div', cls); part.append(el('span', '', label), el('b', '', configured || label === 'Planifiées' ? duration(value) : 'À définir')); metrics.append(part); }
    card.append(metrics);
    if (configured) { const progress = el('progress', 'catalog-hour-progress'); progress.max = planned; progress.value = Math.min(planned, scheduled); progress.setAttribute('aria-label', duration(scheduled) + ' planifiées sur ' + duration(planned)); card.append(progress); }
    else card.append(el('p', 'catalog-card-note', 'Renseignez le volume annuel pour suivre le reste à planifier.'));
    if (configured && scheduled > planned) card.append(el('p', 'catalog-card-note', duration(scheduled - planned) + ' au-delà du volume annuel. Ajustez le volume ou le planning.'));
    const bottom = el('div', 'catalog-card-actions'), edit = action('Modifier la matière', () => openEditor(item)); edit.dataset.catalogEdit = item.id; edit.setAttribute('aria-label', 'Modifier la matière ' + item.name);
    const link = el('a', 'catalog-text-link', 'Voir le planning'); link.href = '/admin/planning?promotion_id=' + encodeURIComponent(item.promotion_id); bottom.append(edit, link); card.append(bottom); return card;
  }
  function roomCard(item) {
    const enabled = active(item.active), card = el('article', 'catalog-room-card' + (enabled ? '' : ' inactive'));
    const top = el('div', 'catalog-card-top'), symbol = el('span', 'catalog-room-icon'); symbol.append(icon()); top.append(symbol, el('span', 'catalog-state' + (enabled ? '' : ' inactive'), enabled ? 'Active' : 'Inactive'));
    card.append(top, el('h3', '', item.name), el('p', 'catalog-room-description', enabled ? 'Proposée pour les nouveaux créneaux de toutes les promotions.' : 'Conservée dans le répertoire, sans être proposée pour les nouveaux créneaux.'));
    const edit = action('Modifier la salle', () => openEditor(item)); edit.dataset.catalogEdit = item.id; edit.setAttribute('aria-label', 'Modifier la salle ' + item.name); card.append(edit); return card;
  }
  function render() {
    if (!state.data) return;
    const query = normal($('catalog-search').value); let items;
    if (isSubjects) {
      const promotion = $('catalog-promotion-filter').value;
      items = state.data.subjects.filter(item => (!promotion || String(item.promotion_id) === promotion) && normal([item.name, item.trainer_name, item.promotion_name].join(' ')).includes(query));
      const missing = items.filter(item => !budget(item)).length;
      const planned = items.reduce((total, item) => total + (budget(item) ? minuteValue(item, 'planned') : 0), 0), scheduled = items.reduce((total, item) => total + (minuteValue(item, 'scheduled') || 0), 0), remaining = items.reduce((total, item) => total + (budget(item) ? Math.max(0, minuteValue(item, 'planned') - (minuteValue(item, 'scheduled') || 0)) : 0), 0);
      $('catalog-stat-one').textContent = items.length && missing === items.length ? 'À définir' : duration(planned);
      $('catalog-stat-two').textContent = duration(scheduled); $('catalog-stat-three').textContent = items.length && missing === items.length ? 'À définir' : duration(remaining);
      $('catalog-stat-one-note').textContent = missing ? missing + ' volume' + (missing > 1 ? 's' : '') + ' à compléter' : items.length + ' matière' + (items.length > 1 ? 's' : '') + ' affichée' + (items.length > 1 ? 's' : '');
      $('catalog-stat-three-note').textContent = missing ? 'Hors matières dont le volume reste à définir' : 'Selon les volumes annuels renseignés';
      const note = $('catalog-budget-note'); note.hidden = !missing; note.textContent = missing + ' matière' + (missing > 1 ? 's n’ont' : ' n’a') + ' pas encore de volume annuel. Complétez ce volume avant de planifier de nouveaux cours.';
    } else {
      const filter = $('catalog-room-filter').value;
      items = state.data.rooms.filter(item => normal(item.name).includes(query) && (!filter || active(item.active) === (filter === 'active')));
      $('catalog-stat-one').textContent = number(state.data.rooms.length); $('catalog-stat-two').textContent = number(state.data.rooms.filter(item => active(item.active)).length); $('catalog-stat-three').textContent = number(state.data.rooms.filter(item => !active(item.active)).length);
    }
    const singular = isSubjects ? 'matière' : 'salle'; $('catalog-count').textContent = items.length + ' ' + singular + (items.length === 1 ? '' : 's') + ' affichée' + (items.length === 1 ? '' : 's');
    $('catalog-grid').replaceChildren(...items.map(isSubjects ? subjectCard : roomCard));
    const empty = $('catalog-empty'); empty.hidden = !!items.length;
    const hasItems = (isSubjects ? state.data.subjects : state.data.rooms).length > 0;
    $('catalog-empty-title').textContent = hasItems ? 'Aucun résultat pour ces filtres.' : (isSubjects ? 'Tout commence par une matière.' : 'Votre première salle, ici.');
    $('catalog-empty-text').textContent = hasItems ? 'Modifiez la recherche ou le filtre pour retrouver les éléments du catalogue.' : (isSubjects ? 'Ajoutez les matières de vos promotions, leurs formateurs et les volumes à planifier.' : 'Donnez un nom à chaque lieu de formation pour le retrouver facilement dans les plannings.');
    if (isSubjects && !state.data.promotions.some(ready)) { $('catalog-empty-text').textContent = 'Créez une promotion active et complétez ses dates avant d’ajouter une matière.'; if (!empty.querySelector('.catalog-promotion-link')) { const link = el('a', 'catalog-button catalog-promotion-link', 'Gérer les promotions'); link.href = '/admin/promotions'; empty.append(link); } }
    else empty.querySelector('.catalog-promotion-link')?.remove();
  }
  function populateTrainers(selected = '') {
    const promotionId = form.elements.promotion_id.value;
    const trainers = state.data.trainers.filter(trainer => active(trainer.active) && (trainer.promotion_ids || []).some(id => String(id) === promotionId));
    optionList(form.elements.trainer_id, trainers, trainerName, promotionId ? 'Choisir un formateur' : 'Choisir d’abord une promotion', selected);
    const imported = !!state.editing?.import_id;
    if (imported) form.elements.trainer_id.options[0].textContent = 'À attribuer plus tard';
    form.elements.trainer_id.required = !imported;
    form.elements.trainer_id.disabled = !trainers.length && !imported;
    $('catalog-trainer-help').textContent = !promotionId ? 'Choisissez une promotion pour voir ses formateurs.' : !trainers.length ? 'Aucun formateur actif n’est affecté à cette promotion. Ajoutez une affectation dans Formateurs.' : selected && !trainers.some(trainer => String(trainer.id) === String(selected)) ? 'L’ancien formateur n’est plus disponible. Choisissez un formateur actif affecté à la promotion.' : 'Seuls les formateurs actifs affectés à la promotion sont proposés.';
    const promotion = state.data.promotions.find(item => String(item.id) === promotionId);
    $('catalog-save').disabled = imported ? !promotion || !active(promotion.active) : !ready(promotion) || !trainers.length;
    const guard = $('catalog-form-guard'); guard.hidden = imported || !promotion || ready(promotion); guard.textContent = 'Cette promotion est archivée ou ses dates sont incomplètes. Rendez-la active et complétez ses dates dans Promotions avant de modifier ses matières.';
  }
  function openEditor(item = null) {
    if (state.loading || !state.data) return;
    state.editing = item; form.reset(); errorAt('catalog-form-error', ''); $('catalog-delete').hidden = !item;
    $('catalog-editor-title').textContent = (item ? 'Modifier la ' : 'Ajouter une ') + (isSubjects ? 'matière' : 'salle');
    $('catalog-save').textContent = item ? 'Enregistrer les modifications' : 'Créer la ' + (isSubjects ? 'matière' : 'salle');
    $('catalog-save').disabled = false; form.elements.name.value = item?.name || '';
    if (isSubjects) {
      const selected = item?.promotion_id || $('catalog-promotion-filter').value;
      const select = form.elements.promotion_id; select.disabled = false; optionList(select, state.data.promotions, promotion => promotion.nom + (!active(promotion.active) ? ' · Archivée' : !ready(promotion) ? ' · Dates à compléter' : ''), 'Choisir une promotion', selected);
      for (const option of select.options) if (option.value && !ready(state.data.promotions.find(promotion => String(promotion.id) === option.value))) option.disabled = true;
      select.disabled = !!item;
      $('catalog-promotion-help').textContent = item ? 'La promotion d’une matière existante ne peut pas être changée.' : 'La matière appartient à cette promotion.';
      populateTrainers(item?.trainer_id);
      form.elements.planned_hours.required = !item?.import_id;
      form.elements.planned_hours.value = item?.planned_hours ?? (minuteValue(item || {}, 'planned') !== null ? minuteValue(item, 'planned') / 60 : '');
      const scheduled = item ? minuteValue(item, 'scheduled') || 0 : 0;
      form.elements.planned_hours.min = String(Math.max(1 / 60, scheduled / 60));
      form.elements.planned_hours.setCustomValidity('');
      form.elements.color.querySelector('[data-existing-color]')?.remove();
      const color = safeColor(item?.color); if (![...form.elements.color.options].some(option => option.value.toLowerCase() === color.toLowerCase())) { const option = new Option('Couleur actuelle', color); option.dataset.existingColor = '1'; form.elements.color.add(option); } form.elements.color.value = [...form.elements.color.options].find(option => option.value.toLowerCase() === color.toLowerCase()).value;
      fillReferenceFields(item);
      $('catalog-existing-hours').hidden = !item; $('catalog-existing-hours').textContent = duration(scheduled) + ' déjà planifiées. Le volume annuel doit couvrir au moins ces heures.'; $('catalog-course-note').hidden = !item;
    } else form.elements.active.checked = item ? active(item.active) : true;
    show(editor, isSubjects && !item && !form.elements.promotion_id.value ? form.elements.promotion_id : form.elements.name);
  }
  function fillReferenceFields(item) {
    for (const key of ['exam_unit', 'objectives', 'curriculum_topics', 'pedagogical_content', 'exam_format', 'review_note', 'coefficient', 'weekly_hours_first', 'weekly_hours_second']) if (form.elements[key]) form.elements[key].value = item?.[key] ?? '';
    if (form.elements.optional) form.elements.optional.checked = !!item?.optional;
    const panel = $('subject-reference-fields'); if (panel) panel.open = !!item?.import_id;
    const source = $('subject-reference-provenance'); if (!source) return;
    source.replaceChildren(); source.hidden = !item?.source_url;
    if (item?.source_url) {
      try {
        const url = new URL(item.source_url); if (url.protocol !== 'https:') return;
        const link = el('a', '', item.source_label || 'Consulter le référentiel officiel'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; source.append(link);
        for (const value of [item.reference_title, item.reference_version, item.evidence]) if (value) source.append(el('p', '', value));
        const full = {...(item.reference_full_text || {}), ...(item.full_text || {})};
        if (Object.keys(full).length) {
          const details = el('details', 'reference-full-text');
          details.append(el('summary', '', 'Textes intégraux conservés à l’import'));
          for (const [label, value] of Object.entries(full)) details.append(el('strong', '', label), el('p', 'reference-full-paragraph', value));
          source.append(details);
        }
      } catch (_) { source.hidden = true; }
    }
  }
  window.addEventListener('catalog:reload', event => {
    if (isSubjects && event.detail?.promotion_id) { $('catalog-promotion-filter').value = event.detail.promotion_id; rootPromotion(event.detail.promotion_id); }
    load(event.detail?.message || 'Catalogue actualisé.');
  });
  function rootPromotion(value) { app.dataset.selectedPromotion = value; }
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (editor.dataset.busy || !state.data) return;
    errorAt('catalog-form-error', ''); let payload;
    if (isSubjects) {
      const value = Number(form.elements.planned_hours.value), scheduled = state.editing ? minuteValue(state.editing, 'scheduled') || 0 : 0;
      form.elements.planned_hours.setCustomValidity(state.editing?.import_id && !form.elements.planned_hours.value && !scheduled ? '' : !Number.isFinite(value) || value <= 0 ? 'Renseignez un volume annuel supérieur à zéro.' : Math.abs(value * 60 - Math.round(value * 60)) > 1e-7 ? 'Le volume doit correspondre à un nombre entier de minutes, par exemple 1,5 h pour 1 h 30.' : value * 60 + 1e-7 < scheduled ? 'Le volume annuel ne peut pas être inférieur aux ' + duration(scheduled) + ' déjà planifiées.' : '');
      if ($('catalog-save').disabled) return;
      payload = {promotion_id: state.editing?.promotion_id || form.elements.promotion_id.value, name: form.elements.name.value.trim(), trainer_id: form.elements.trainer_id.value, planned_hours: state.editing?.import_id && !form.elements.planned_hours.value ? null : value, color: form.elements.color.value};
      for (const key of ['exam_unit', 'objectives', 'curriculum_topics', 'pedagogical_content', 'exam_format', 'review_note']) if (form.elements[key]) payload[key] = form.elements[key].value;
      for (const key of ['coefficient', 'weekly_hours_first', 'weekly_hours_second']) if (form.elements[key]) payload[key] = form.elements[key].value === '' ? null : Number(form.elements[key].value);
      if (form.elements.optional) payload.optional = form.elements.optional.checked;
    } else payload = {name: form.elements.name.value.trim(), active: form.elements.active.checked};
    if (!form.reportValidity()) return;
    busy(editor, true);
    try { const result = await request('/' + (isSubjects ? 'subjects' : 'rooms') + (state.editing ? '/' + encodeURIComponent(state.editing.id) : ''), state.editing ? 'PUT' : 'POST', payload); editor.close(); if (!isSubjects) window.dispatchEvent(new CustomEvent('academy:rooms-changed', {detail: {origin: 'catalog'}})); await load(result.message || (isSubjects ? 'Matière enregistrée.' : 'Salle enregistrée.')); }
    catch (failure) { errorAt('catalog-form-error', failure.message); }
    finally { busy(editor, false); }
  });
  if (isSubjects) { form.elements.promotion_id.addEventListener('change', () => populateTrainers()); form.elements.planned_hours.addEventListener('input', () => form.elements.planned_hours.setCustomValidity('')); }
  $('catalog-delete').addEventListener('click', () => {
    if (!state.editing || editor.dataset.busy) return; state.deleting = state.editing; errorAt('catalog-confirm-error', '');
    $('catalog-confirm-text').textContent = 'Supprimer « ' + state.deleting.name + ' » ? ' + (isSubjects ? 'Une matière utilisée par des cours ne peut pas être supprimée. Les cours doivent d’abord être supprimés ou réaffectés depuis le planning.' : 'Une salle utilisée par des cours ne peut pas être supprimée. Réaffectez d’abord ces cours depuis le planning.');
    show(confirm, confirm.querySelector('footer [data-catalog-close]'));
  });
  $('catalog-confirm-action').addEventListener('click', async () => {
    if (!state.deleting || confirm.dataset.busy) return; busy(confirm, true); errorAt('catalog-confirm-error', '');
    try { const result = await request('/' + (isSubjects ? 'subjects' : 'rooms') + '/' + encodeURIComponent(state.deleting.id), 'DELETE'); confirm.close(); editor.close(); if (!isSubjects) window.dispatchEvent(new CustomEvent('academy:rooms-changed', {detail: {origin: 'catalog'}})); await load(result.message || 'Suppression enregistrée.'); }
    catch (failure) { errorAt('catalog-confirm-error', failure.message); }
    finally { busy(confirm, false); }
  });
  app.querySelectorAll('[data-catalog-create]').forEach(button => button.addEventListener('click', () => openEditor()));
  $('catalog-search').addEventListener('input', render);
  if (isSubjects) $('catalog-promotion-filter').addEventListener('change', () => { const url = new URL(location.href); const value = $('catalog-promotion-filter').value; if (value) url.searchParams.set('promotion_id', value); else url.searchParams.delete('promotion_id'); history.replaceState(null, '', url); render(); });
  else $('catalog-room-filter').addEventListener('change', render);
  $('catalog-retry').addEventListener('click', () => load());
  load();
})();

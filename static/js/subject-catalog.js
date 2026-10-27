/* One subject definition, several diplomas, independent timetable allocations. */
(() => {
  'use strict';
  const root = document.querySelector('.catalog-app[data-kind="subjects"]');
  if (!root) return;
  const $ = id => document.getElementById(id), form = $('catalog-form'), editor = $('catalog-editor'), confirm = $('catalog-confirm');
  const state = {data: null, loading: true, sequence: 0, editing: null, drafts: {}, detail: '', allocationDrafts: {}};
  const textFields = ['exam_unit', 'objectives', 'curriculum_topics', 'pedagogical_content', 'exam_format', 'review_note'];
  const numberFields = ['coefficient', 'weekly_hours_first', 'weekly_hours_second', 'annual_hours_first', 'annual_hours_second'];
  const annualField = year => ({1: 'annual_hours_first', 2: 'annual_hours_second'})[year];
  const normal = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr');
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const safeColor = value => /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#2563eb';
  const compare = (a, b) => a.localeCompare(b, 'fr', {sensitivity: 'base', numeric: true});
  const number = value => new Intl.NumberFormat('fr-FR', {maximumFractionDigits: 2}).format(value);
  function alert(id, message) { $(id).textContent = message || ''; $(id).hidden = !message; }
  async function api(path, method = 'GET', data) {
    const response = await fetch('/admin/planning/api' + path, {method, credentials: 'same-origin',
      headers: {Accept: 'application/json', ...(method !== 'GET' ? {'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.csrf} : {})},
      ...(method !== 'GET' ? {body: JSON.stringify(data || {})} : {})});
    const result = await response.json().catch(() => { throw new Error('La connexion a expiré. Rechargez la page avant de réessayer.'); });
    if (!response.ok || result.ok === false) { const error = new Error(result.message || 'Cette action n’a pas abouti.'); error.result = result; throw error; }
    return result;
  }
  function busy(dialog, value) {
    dialog.dataset.busy = value ? '1' : '';
    dialog.setAttribute('aria-busy', String(value));
    dialog.querySelectorAll('button,input,select,textarea').forEach(input => {
      if (value) { input.dataset.previousDisabled = String(input.disabled); input.disabled = true; }
      else if (input.dataset.previousDisabled !== undefined) { input.disabled = input.dataset.previousDisabled === 'true'; delete input.dataset.previousDisabled; }
    });
  }
  function show(dialog) { dialog._opener = document.activeElement; dialog.showModal(); }
  for (const dialog of [editor, confirm]) {
    dialog.querySelectorAll('[data-catalog-close]').forEach(button => button.addEventListener('click', () => { if (!dialog.dataset.busy) dialog.close(); }));
    dialog.addEventListener('cancel', event => { if (dialog.dataset.busy) event.preventDefault(); });
    dialog.addEventListener('close', () => dialog._opener?.isConnected && dialog._opener.focus());
  }
  function loading(value) {
    state.loading = value; root.setAttribute('aria-busy', String(value));
    root.querySelectorAll('[data-catalog-create],[data-catalog-edit]').forEach(button => { button.disabled = value || !state.data; });
  }
  function filterUrl() {
    const url = new URL(location.href), code = $('catalog-diploma-filter').value, sort = $('catalog-sort').value;
    url.searchParams.delete('promotion_id');
    if (code) url.searchParams.set('diploma', code); else url.searchParams.delete('diploma');
    if (sort !== 'name') url.searchParams.set('sort', sort); else url.searchParams.delete('sort');
    history.replaceState(null, '', url);
  }
  async function load(message = '') {
    const sequence = ++state.sequence; loading(true); $('catalog-load-error').hidden = true;
    try {
      const data = await api('/catalog');
      if (sequence !== state.sequence) return;
      if (!Array.isArray(data.subject_catalog) || !data.diplomas) throw new Error('Le catalogue reçu est incomplet. Rechargez la page.');
      state.data = data;
      const select = $('catalog-diploma-filter');
      const selected = select.value || root.dataset.selectedDiploma || data.promotions?.find(p => p.id === root.dataset.legacyPromotion)?.bts || '';
      select.replaceChildren(new Option('Tous les diplômes', ''));
      for (const [code, label] of Object.entries(data.diplomas)) { const option = new Option('BTS ' + code, code); option.title = label; select.add(option); }
      select.value = selected; root.dataset.selectedDiploma = ''; root.dataset.legacyPromotion = '';
      filterUrl(); render(); alert('catalog-notice', message);
    } catch (error) {
      if (sequence !== state.sequence) return;
      state.data = null; $('catalog-grid').replaceChildren(); $('catalog-empty').hidden = true; $('catalog-load-error').hidden = false;
      $('catalog-count').textContent = 'Catalogue indisponible';
      for (const key of ['one', 'two', 'three']) $('catalog-stat-' + key).textContent = '—';
      alert('catalog-notice', (message ? message + ' ' : '') + error.message);
    } finally { if (sequence === state.sequence) loading(false); }
  }
  function card(item, filter) {
    const article = node('article', 'catalog-subject-card subject-catalog-card'); article.style.setProperty('--catalog-accent', safeColor(item.color));
    const tags = node('div', 'subject-diploma-tags');
    for (const code of item.diploma_codes) { const tag = node('span', 'subject-diploma-tag' + (code === filter ? ' selected' : ''), 'BTS ' + code); tag.title = state.data.diplomas[code] || code; tags.append(tag); }
    article.append(tags, node('h3', '', item.name));
    const curricula = node('ul', 'subject-curricula');
    for (const code of item.diploma_codes.filter(code => !filter || code === filter)) {
      const data = item.diploma_details[code] || {}, row = node('li');
      const info = [data.exam_unit, data.coefficient !== null && data.coefficient !== undefined ? 'Coefficient ' + number(data.coefficient) : 'Coefficient à renseigner', data.optional ? 'Facultative' : ''].filter(Boolean).join(' · ');
      const description = node('span', '', info);
      const volumes = [1, 2].map(year => (year === 1 ? '1re' : '2e') + ' année : ' + (data[annualField(year)] == null ? 'à renseigner' : number(data[annualField(year)]) + ' h'));
      description.append(node('small', 'subject-annual-summary', volumes.join(' · ')));
      row.append(node('b', '', 'BTS ' + code), description); curricula.append(row);
    }
    article.append(curricula, node('p', 'subject-catalog-use', item.planning_count ? 'Préparée dans ' + item.planning_count + ' planning' + (item.planning_count > 1 ? 's' : '') + '.' : 'Disponible pour les plannings des diplômes cochés.'));
    const actions = node('div', 'catalog-card-actions'), edit = node('button', 'catalog-button', 'Modifier la matière'); edit.type = 'button'; edit.dataset.catalogEdit = item.id;
    edit.setAttribute('aria-label', 'Modifier la matière ' + item.name); edit.addEventListener('click', () => openEditor(item));
    const planning = node('a', 'catalog-text-link', 'Préparer les cours'); planning.href = '/admin/planning?catalog_subject_id=' + encodeURIComponent(item.id);
    actions.append(edit, planning); article.append(actions); return article;
  }
  function render() {
    if (!state.data) return;
    const filter = $('catalog-diploma-filter').value, query = normal($('catalog-search').value).trim(), sort = $('catalog-sort').value;
    const items = state.data.subject_catalog.filter(item => (!filter || item.diploma_codes.includes(filter)) && normal([
      item.name, ...item.diploma_codes.map(code => 'BTS ' + code + ' ' + state.data.diplomas[code]), ...Object.values(item.diploma_details).map(data => data.exam_unit || '')
    ].join(' ')).includes(query));
    items.sort((a, b) => {
      if (sort === 'name-desc') return compare(b.name, a.name);
      if (sort === 'shared' && a.diploma_codes.length !== b.diploma_codes.length) return b.diploma_codes.length - a.diploma_codes.length;
      if (sort === 'diploma') { const diff = compare(a.diploma_codes.join(' '), b.diploma_codes.join(' ')); if (diff) return diff; }
      return compare(a.name, b.name);
    });
    $('catalog-stat-one').textContent = number(items.length);
    $('catalog-stat-two').textContent = number(new Set(items.flatMap(item => item.diploma_codes)).size);
    $('catalog-stat-three').textContent = number(items.filter(item => item.diploma_codes.length > 1).length);
    $('catalog-count').textContent = items.length + ' matière' + (items.length > 1 ? 's' : '') + ' affichée' + (items.length > 1 ? 's' : '');
    $('catalog-grid').replaceChildren(...items.map(item => card(item, filter))); $('catalog-empty').hidden = !!items.length;
    $('catalog-empty-title').textContent = state.data.subject_catalog.length ? 'Aucune matière pour ces filtres.' : 'Tout commence par une matière.';
    $('catalog-empty-text').textContent = state.data.subject_catalog.length ? 'Modifiez la recherche ou le diplôme pour retrouver vos matières.' : 'Créez une matière et cochez ses diplômes, ou importez un référentiel officiel.';
  }
  const checkedCodes = () => [...$('catalog-diploma-choices').querySelectorAll('input:checked')].map(input => input.value);
  function editable(data) {
    const result = {};
    for (const key of textFields) result[key] = data[key] || '';
    for (const key of numberFields) result[key] = data[key] ?? null;
    result.optional = !!data.optional; return result;
  }
  function saveDetail() {
    if (!state.detail) return;
    const values = {};
    for (const key of textFields) values[key] = form.elements[key].value;
    for (const key of numberFields) values[key] = form.elements[key].value === '' ? null : Number(form.elements[key].value);
    values.optional = form.elements.optional.checked;
    state.drafts[state.detail] = {...(state.drafts[state.detail] || {}), ...values};
  }
  function renderDetail() {
    const item = state.drafts[state.detail] || {};
    for (const key of [...textFields, ...numberFields]) form.elements[key].value = item[key] ?? '';
    form.elements.optional.checked = !!item.optional;
    renderAllocations(); alert('catalog-hours-status', '');
    const source = $('subject-reference-provenance'); source.replaceChildren(); source.hidden = !item.source_url;
    if (item.source_url) {
      try {
        const url = new URL(item.source_url);
        if (url.protocol !== 'https:') { source.hidden = true; return; }
        const link = node('a', '', item.source_label || 'Consulter la source officielle'); link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer'; source.append(link);
        for (const value of [item.reference_title, item.reference_version, item.evidence]) if (value) source.append(node('p', '', value));
        const full = {...(item.reference_full_text || {}), ...(item.full_text || {})};
        if (Object.keys(full).length) {
          const details = node('details', 'reference-full-text'); details.append(node('summary', '', 'Textes intégraux conservés à l’import'));
          for (const [label, value] of Object.entries(full)) details.append(node('strong', '', label), node('p', 'reference-full-paragraph', value));
          source.append(details);
        }
      } catch (_) { source.hidden = true; }
    }
  }
  function allocations(code = state.detail) {
    return (state.data?.subjects || []).filter(item => state.editing && item.catalog_subject_id === state.editing.id && item.diploma_code === code);
  }
  function renderAllocations() {
    const items = allocations(), container = $('catalog-allocations'); container.replaceChildren();
    $('catalog-allocation-section').hidden = !items.length;
    $('catalog-apply-hours').disabled = !items.some(item => item.promotion_active && annualField(item.study_year));
    for (const item of items) {
      const row = node('div', 'subject-allocation'), description = node('div');
      const period = [item.period_start, item.period_end].filter(Boolean).map(value => value.split('-').reverse().join('/')).join(' – ');
      description.append(node('strong', '', item.promotion_name), node('small', '', 'Année ' + item.study_year + (period ? ' · ' + period : '') + (item.promotion_active ? '' : ' · Archivée')),
        node('small', '', number(item.scheduled_hours) + ' h déjà planifiées'));
      const label = node('label', 'catalog-field', 'Volume annuel · h'), input = node('input');
      input.type = 'number'; input.min = String(Math.max(item.scheduled_hours || 0, 1 / 60)); input.max = '5000'; input.step = 'any';
      input.value = state.allocationDrafts[item.id] ?? item.planned_hours ?? ''; input.dataset.allocationId = item.id;
      input.disabled = !item.promotion_active; input.placeholder = 'À renseigner';
      input.setAttribute('aria-label', 'Volume annuel · ' + item.promotion_name + ' · année ' + item.study_year);
      input.addEventListener('input', () => { state.allocationDrafts[item.id] = input.value; alert('catalog-hours-status', ''); });
      label.append(input); row.append(description, label); container.append(row);
    }
  }
  $('catalog-apply-hours').addEventListener('click', () => {
    saveDetail(); let count = 0;
    for (const item of allocations()) {
      const value = state.drafts[state.detail]?.[annualField(item.study_year)];
      if (item.promotion_active && value != null && Number.isFinite(value) && value > 0) { state.allocationDrafts[item.id] = String(value); count++; }
    }
    renderAllocations();
    alert('catalog-hours-status', count ? 'Volumes reportés dans ' + count + ' planning(s). Enregistrez les modifications pour les appliquer.' : 'Renseignez le volume de l’année concernée avant de l’appliquer.');
  });
  function updateDiplomas() {
    saveDetail(); const codes = checkedCodes(), select = $('catalog-detail-diploma');
    if (!codes.includes(state.detail)) state.detail = codes.includes($('catalog-diploma-filter').value) ? $('catalog-diploma-filter').value : codes[0] || '';
    select.replaceChildren(...codes.map(code => new Option('BTS ' + code, code))); select.value = state.detail;
    $('catalog-diploma-programme').hidden = !codes.length; renderDetail();
  }
  function openEditor(item = null) {
    if (state.loading || !state.data) return;
    state.editing = item; state.drafts = JSON.parse(JSON.stringify(item?.diploma_details || {})); state.detail = ''; state.allocationDrafts = {};
    form.reset(); alert('catalog-form-error', ''); $('catalog-delete').hidden = !item;
    $('catalog-editor-title').textContent = item ? 'Modifier la matière' : 'Ajouter une matière';
    $('catalog-save').textContent = item ? 'Enregistrer les modifications' : 'Créer la matière'; form.elements.name.value = item?.name || '';
    const choices = $('catalog-diploma-choices'); choices.replaceChildren();
    for (const [code, label] of Object.entries(state.data.diplomas)) {
      const wrap = node('label', 'subject-diploma-choice'), input = node('input'); input.type = 'checkbox'; input.name = 'diploma_codes'; input.value = code;
      input.checked = item ? item.diploma_codes.includes(code) : $('catalog-diploma-filter').value === code;
      wrap.title = label; wrap.append(input, document.createTextNode('BTS ' + code)); input.addEventListener('change', updateDiplomas); choices.append(wrap);
    }
    form.elements.color.querySelector('[data-existing-color]')?.remove();
    const color = safeColor(item?.color);
    if (![...form.elements.color.options].some(option => option.value === color)) { const option = new Option('Couleur actuelle', color); option.dataset.existingColor = '1'; form.elements.color.add(option); }
    form.elements.color.value = color; updateDiplomas(); $('subject-reference-fields').open = false;
    show(editor); form.elements.name.focus();
  }
  $('catalog-detail-diploma').addEventListener('change', () => { saveDetail(); state.detail = $('catalog-detail-diploma').value; renderDetail(); });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (editor.dataset.busy) return; alert('catalog-form-error', '');
    const codes = checkedCodes();
    if (!codes.length) { alert('catalog-form-error', 'Cochez au moins un diplôme pour cette matière.'); $('catalog-diploma-choices').querySelector('input')?.focus(); return; }
    if (!form.reportValidity()) return; saveDetail(); busy(editor, true);
    try {
      const payload = {name: form.elements.name.value.trim(), color: form.elements.color.value, diploma_codes: codes,
        diploma_details: Object.fromEntries(codes.map(code => [code, editable(state.drafts[code] || {})])), ...(state.editing ? {version: state.editing.version} : {}),
        planning_allocations: (state.data.subjects || []).filter(item => item.catalog_subject_id === state.editing?.id && item.promotion_active &&
          Object.hasOwn(state.allocationDrafts, item.id) && (state.allocationDrafts[item.id] === '' ? null : Number(state.allocationDrafts[item.id])) !== item.planned_hours)
          .map(item => ({id: item.id, previous_planned_hours: item.planned_hours, planned_hours: state.allocationDrafts[item.id] === '' ? null : Number(state.allocationDrafts[item.id])}))};
      const result = await api('/subject-catalog' + (state.editing ? '/' + encodeURIComponent(state.editing.id) : ''), state.editing ? 'PUT' : 'POST', payload);
      editor.close(); await load(result.message);
    } catch (error) { alert('catalog-form-error', error.message); }
    finally { busy(editor, false); }
  });
  $('catalog-delete').addEventListener('click', () => {
    if (!state.editing || editor.dataset.busy) return;
    alert('catalog-confirm-error', ''); $('catalog-confirm-links').replaceChildren(); $('catalog-confirm-links').hidden = true;
    $('catalog-confirm-text').textContent = 'Supprimer « ' + state.editing.name + ' » du catalogue et de tous ses diplômes ? Ses rattachements aux plannings sans cours seront retirés automatiquement. La suppression reste bloquée si des cours, des devoirs ou des évaluations existent.';
    show(confirm);
  });
  $('catalog-confirm-action').addEventListener('click', async () => {
    if (!state.editing || confirm.dataset.busy) return; busy(confirm, true);
    try { const result = await api('/subject-catalog/' + encodeURIComponent(state.editing.id), 'DELETE', {version: state.editing.version}); confirm.close(); editor.close(); await load(result.message); }
    catch (error) {
      alert('catalog-confirm-error', error.message); const links = $('catalog-confirm-links'); links.replaceChildren();
      for (const issue of error.result?.conflicts || []) {
        if (issue.type !== 'subject_used' || typeof issue.promotion_id !== 'string') continue;
        const row = node('li'), link = node('a', 'catalog-text-link', (issue.promotion_name || 'Ouvrir le planning') + ' · année ' + issue.study_year + ' · ' + issue.course_count + ' cours');
        const params = new URLSearchParams({promotion_id: issue.promotion_id}); if (issue.period_id) params.set('period_id', issue.period_id);
        link.href = '/admin/planning?' + params; link.target = '_blank'; link.rel = 'noopener noreferrer'; row.append(link); links.append(row);
      }
      links.hidden = !links.children.length;
    }
    finally { busy(confirm, false); }
  });
  root.querySelectorAll('[data-catalog-create]').forEach(button => button.addEventListener('click', () => openEditor()));
  $('catalog-search').addEventListener('input', render);
  for (const id of ['catalog-diploma-filter', 'catalog-sort']) $(id).addEventListener('change', () => { filterUrl(); render(); });
  $('catalog-retry').addEventListener('click', () => load());
  window.addEventListener('catalog:reload', event => {
    if (event.detail?.diploma_code) { $('catalog-diploma-filter').value = event.detail.diploma_code; root.dataset.selectedDiploma = event.detail.diploma_code; filterUrl(); }
    load(event.detail?.message || 'Catalogue actualisé.');
  });
  const sort = new URL(location.href).searchParams.get('sort'); if (['name', 'name-desc', 'diploma', 'shared'].includes(sort)) $('catalog-sort').value = sort;
  load();
})();

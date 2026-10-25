/* Reference imports are previews until the selected, edited rows are committed. */
(() => {
  'use strict';
  const root = document.querySelector('.catalog-app[data-kind="subjects"]');
  if (!root) return;
  const $ = id => document.getElementById(id), dialog = $('reference-dialog');
  const state = {catalog: null, settings: null, job: null, rows: [], timer: null, polling: false, saving: false, opening: false};
  const API = '/admin/planning/api/references';
  const textFields = ['exam_unit', 'objectives', 'pedagogical_content', 'exam_format', 'review_note'];
  const numericFields = ['coefficient', 'weekly_hours_first', 'weekly_hours_second'];
  const normal = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr').trim().replace(/\s+/g, ' ');
  const node = (tag, cls, text) => { const n = document.createElement(tag); if (cls) n.className = cls; if (text !== undefined) n.textContent = text; return n; };
  const number = value => value === null || value === undefined || value === '' ? null : Number(String(value).replace(',', '.'));
  const fmt = value => value === null || value === undefined ? 'À vérifier' : new Intl.NumberFormat('fr-FR', {maximumFractionDigits: 2}).format(value);
  function alert(message, target = 'reference-alert') { const n = $(target); n.textContent = message || ''; n.hidden = !message; }
  async function api(path, method = 'GET', payload) {
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 28000);
    try {
      const response = await fetch(API + path, {method, credentials: 'same-origin', signal: controller.signal,
        headers: {Accept: 'application/json', ...(method !== 'GET' ? {'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.csrf} : {})},
        ...(method !== 'GET' ? {body: JSON.stringify(payload || {})} : {})});
      const data = await response.json().catch(() => { throw new Error('La session a expiré ou le service est indisponible. Rechargez la page.'); });
      if (!response.ok || data.ok === false) throw new Error(data.message || 'Cette action n’a pas abouti.');
      return data;
    } catch (error) { if (error.name === 'AbortError') throw new Error('Le serveur met trop de temps à répondre. Rouvrez l’import pour retrouver l’analyse éventuelle.'); throw error; }
    finally { clearTimeout(timeout); }
  }
  async function catalog() {
    const response = await fetch('/admin/planning/api/catalog', {credentials: 'same-origin', headers: {Accept: 'application/json'}});
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error('Impossible de charger le catalogue des diplômes. Rechargez la page.');
    state.catalog = data;
  }
  function showStep(name) {
    for (const key of ['source', 'progress', 'review', 'done']) $('reference-' + key + '-step').hidden = key !== name;
    document.querySelectorAll('[data-reference-step]').forEach(n => {
      if (n.dataset.referenceStep === (name === 'progress' ? 'source' : name)) n.setAttribute('aria-current', 'step'); else n.removeAttribute('aria-current');
    });
    $('reference-import').hidden = name !== 'review';
    $('reference-footer-note').textContent = name === 'review' ? 'Aucune matière ajoutée avant votre validation.' : '';
  }
  function connectionStatus() {
    const enabled = state.settings?.configured;
    $('reference-connection-state').textContent = enabled ? 'Analyse des référentiels disponible' : 'Configurez OpenAI dans les paramètres pour activer la recherche';
    $('reference-analyze').disabled = !enabled;
    $('reference-settings-link').hidden = !!enabled;
  }
  function chooseDiploma() {
    const code = $('reference-diploma-code').value;
    $('reference-qualification').value = state.settings.bts_options[code] || '';
    $('reference-url').value = state.settings.suggested_urls[code] || '';
    if (!$('reference-exam-year').value) $('reference-exam-year').value = new Date().getFullYear() + 2;
  }
  function populate() {
    const selected = $('catalog-diploma-filter').value || $('reference-diploma-code').value;
    const select = $('reference-diploma-code'); select.replaceChildren(new Option('Choisir un diplôme', ''));
    for (const [code, label] of Object.entries(state.settings.bts_options)) select.add(new Option(label + ' (' + code + ')', code));
    if ([...select.options].some(o => o.value === selected)) select.value = selected;
    else if (select.options.length === 2) select.selectedIndex = 1;
    chooseDiploma(); connectionStatus();
  }
  async function open() {
    if (state.opening) return;
    state.opening = true; $('reference-open').disabled = true; $('reference-analyze').disabled = true;
    if (!dialog.open) dialog.showModal();
    alert('');
    try {
      const [, settings] = await Promise.all([catalog(), api('/settings')]);
      state.settings = settings; populate();
      if (state.job && state.rows.length && state.job.status === 'ready') { showStep('review'); selection(); return; }
      const latest = await api('/latest');
      if (latest.job?.recoverable) {
        showStep('progress');
        handleJob(await api('/' + encodeURIComponent(latest.job.job_id) + '/recover', 'POST', {}));
      } else if (latest.job && !['failed', 'imported'].includes(latest.job.status)) handleJob(latest.job);
      else { showStep('source'); $('reference-diploma-code').focus(); }
    } catch (error) { alert(error.message); }
    finally { state.opening = false; $('reference-open').disabled = false; }
  }
  function savedDraft() {
    try { return JSON.parse(sessionStorage.getItem('bts-reference-draft:' + state.job.job_id) || 'null'); } catch (_) { return null; }
  }
  function persistDraft() {
    if (!state.job) return;
    try { sessionStorage.setItem('bts-reference-draft:' + state.job.job_id, JSON.stringify(state.rows.map(r => ({...readRow(r), selected: r.check.checked})))); } catch (_) { /* Private browsing may disallow session storage. */ }
  }
  function readRow(row) {
    const out = {row_id: row.original.row_id, name: row.fields.name.value.trim(), optional: row.fields.optional.checked};
    for (const key of textFields) out[key] = row.fields[key].value;
    for (const key of numericFields) out[key] = number(row.fields[key].value);
    return out;
  }
  function sourceLink(row) {
    const source = node('div', 'reference-source');
    const link = node('a', '', row.source_label || 'Consulter la source officielle');
    try {
      const url = new URL(row.source_url);
      if (url.protocol !== 'https:') return source;
      link.href = url.href; link.target = '_blank'; link.rel = 'noopener noreferrer';
    } catch (_) { return source; }
    source.append(link);
    if (row.evidence) source.append(node('p', '', row.evidence));
    return source;
  }
  function fullTextDetails(texts) {
    const details = node('details', 'reference-full-text');
    details.append(node('summary', '', 'Consulter les textes intégraux'));
    details.append(node('p', 'reference-help', 'Ces textes ont été abrégés dans les champs. La version intégrale ci-dessous sera conservée avec la matière.'));
    for (const [label, value] of Object.entries(texts || {})) {
      details.append(node('strong', '', label), node('p', 'reference-full-paragraph', value));
    }
    return details;
  }
  function field(row, label, key, type = 'text', max = null) {
    const wrap = node('label', 'catalog-field', label);
    const input = node(type === 'textarea' ? 'textarea' : 'input');
    if (type !== 'textarea') input.type = type;
    input.dataset.field = key;
    if (type === 'number') { input.min = 0; input.max = max || 100; input.step = 'any'; input.placeholder = 'À compléter'; }
    if (type === 'textarea') input.rows = key === 'pedagogical_content' ? 5 : 3;
    if (type === 'text' || type === 'textarea') input.maxLength = max || 2000;
    input.value = row.value[key] ?? '';
    row.fields[key] = input; wrap.append(input); return wrap;
  }
  function buildRow(original, draft) {
    const value = {...original, ...(draft || {})}, row = {original, value, fields: {}};
    const card = node('article', 'reference-subject'), head = node('div', 'reference-subject-head');
    const checkLabel = node('label', 'reference-row-choice');
    row.check = node('input'); row.check.type = 'checkbox'; row.check.setAttribute('aria-label', 'Importer ' + value.name);
    row.check.checked = original.importable !== false && (draft ? !!draft.selected : !value.optional);
    row.title = node('strong', '', value.name); checkLabel.append(row.check, row.title);
    row.badge = node('span', 'reference-coefficient', 'Coefficient ' + fmt(value.coefficient)); head.append(checkLabel, row.badge); card.append(head);
    if (original.source_issue) card.append(node('p', 'reference-source-issue', original.source_issue));
    row.duplicate = node('p', 'reference-duplicate'); row.duplicate.hidden = true; card.append(row.duplicate);
    const detail = node('details', 'reference-edit'); detail.append(node('summary', '', 'Vérifier et modifier cette matière'));
    const content = node('div', 'reference-edit-content');
    content.append(field(row, 'Nom de la matière', 'name', 'text', 120)); row.fields.name.required = true;
    const exam = node('div', 'catalog-form-row'); exam.append(field(row, 'Unité / épreuve', 'exam_unit', 'text', 80), field(row, 'Coefficient d’examen', 'coefficient', 'number')); content.append(exam);
    const optional = node('label', 'reference-check'); row.fields.optional = node('input'); row.fields.optional.type = 'checkbox'; row.fields.optional.checked = !!value.optional; optional.append(row.fields.optional, document.createTextNode(' Enseignement / épreuve facultative')); content.append(optional);
    const hours = node('div', 'catalog-form-row'); hours.append(field(row, 'Horaire scolaire · 1re année (h/semaine)', 'weekly_hours_first', 'number', 80), field(row, 'Horaire scolaire · 2e année (h/semaine)', 'weekly_hours_second', 'number', 80)); content.append(hours);
    content.append(field(row, 'Objectifs et compétences', 'objectives', 'textarea', 12000), field(row, 'Contenu pédagogique / savoirs associés', 'pedagogical_content', 'textarea', 20000), field(row, 'Modalités d’examen', 'exam_format', 'textarea', 2000), field(row, 'Points à vérifier / notes', 'review_note', 'textarea', 2000), sourceLink(original));
    if (Object.keys(original.full_text || {}).length) content.append(fullTextDetails(original.full_text));
    if (original.review_note) card.append(node('p', 'reference-row-note', original.review_note));
    detail.append(content); card.append(detail); row.card = card; row.detail = detail;
    card.addEventListener('input', () => { $('reference-reviewed').checked = false; row.title.textContent = row.fields.name.value || 'Matière sans nom'; row.badge.textContent = 'Coefficient ' + fmt(number(row.fields.coefficient.value)); selection(); persistDraft(); });
    card.addEventListener('change', () => { $('reference-reviewed').checked = false; selection(); persistDraft(); });
    return row;
  }
  function selection() {
    const code = state.job?.diploma_code || state.job?.query?.bts_code;
    const existing = new Set((state.catalog.subject_catalog || []).filter(s => s.diploma_codes.includes(code)).map(s => normal(s.name)));
    for (const row of state.rows) {
      const duplicate = existing.has(normal(row.fields.name.value));
      const blocked = row.original.importable === false;
      row.check.disabled = duplicate || blocked || state.saving;
      if (duplicate || blocked) row.check.checked = false;
      row.duplicate.hidden = !duplicate;
      row.duplicate.textContent = 'Déjà présente pour le BTS ' + code + ' : laissée de côté. Vous pouvez modifier son nom si vous souhaitez créer une autre matière.';
    }
    const count = state.rows.filter(r => r.check.checked).length;
    $('reference-selection-count').textContent = count + ' matière' + (count > 1 ? 's' : '') + ' sélectionnée' + (count > 1 ? 's' : '');
    $('reference-import').textContent = state.saving ? 'Import en cours…' : 'Importer ' + count + ' matière' + (count > 1 ? 's' : '');
    $('reference-import').disabled = !count || !$('reference-reviewed').checked || state.saving;
  }
  function review(job) {
    const preview = job.preview; if (!preview) throw new Error('L’aperçu est incomplet. Relancez l’analyse.');
    const code = job.diploma_code || job.query?.bts_code;
    $('reference-destination').textContent = 'Catalogue · BTS ' + code;
    $('reference-diploma').textContent = preview.qualification;
    $('reference-version').textContent = [preview.reference_title, preview.reference_version].filter(Boolean).join(' · ');
    $('reference-warnings').replaceChildren(...preview.warnings.map(w => node('p', 'reference-caution', w)));
    const complete = $('reference-complete-text'); complete.replaceChildren();
    if (Object.keys(preview.full_text || {}).length) complete.append(fullTextDetails(preview.full_text));
    const draft = savedDraft();
    state.rows = preview.subjects.map(row => buildRow(row, Array.isArray(draft) ? draft.find(d => d.row_id === row.row_id) : null));
    $('reference-subjects').replaceChildren(...state.rows.map(r => r.card));
    $('reference-reviewed').checked = false; showStep('review'); selection();
  }
  function handleJob(job) {
    state.job = job; clearTimeout(state.timer);
    if (job.status === 'ready') { review(job); return; }
    if (job.status === 'imported') { showStep('done'); $('reference-success-title').textContent = job.receipt?.message || 'Import terminé.'; return; }
    if (job.status === 'failed') { showStep('source'); alert(job.message || 'L’analyse n’a pas abouti. Relancez-la.'); return; }
    showStep('progress'); $('reference-retry-poll').hidden = true;
    state.timer = setTimeout(poll, 2500);
  }
  async function poll() {
    if (state.polling || !state.job) return;
    state.polling = true;
    try { const job = await api('/' + encodeURIComponent(state.job.job_id)); alert(''); handleJob(job); }
    catch (error) { alert(error.message); $('reference-retry-poll').hidden = false; }
    finally { state.polling = false; }
  }
  $('reference-open').addEventListener('click', open);
  $('reference-diploma-code').addEventListener('change', chooseDiploma);
  $('reference-search-form').addEventListener('submit', async event => {
    event.preventDefault(); if ($('reference-analyze').disabled || state.saving) return;
    if (!event.target.reportValidity()) return;
    alert(''); $('reference-analyze').disabled = true;
    try {
      const job = await api('/analyze', 'POST', {diploma_code: $('reference-diploma-code').value,
        qualification: $('reference-qualification').value.trim(), source_url: $('reference-url').value.trim(), exam_year: Number($('reference-exam-year').value)});
      state.rows = []; handleJob(job);
    } catch (error) { alert(error.message); }
    finally { connectionStatus(); }
  });
  $('reference-retry-poll').addEventListener('click', poll);
  $('reference-restart').addEventListener('click', () => { state.job = null; state.rows = []; alert(''); showStep('source'); });
  $('reference-select-all').addEventListener('click', () => { state.rows.forEach(r => { if (!r.check.disabled) r.check.checked = true; }); $('reference-reviewed').checked = false; selection(); persistDraft(); });
  $('reference-select-none').addEventListener('click', () => { state.rows.forEach(r => { r.check.checked = false; }); $('reference-reviewed').checked = false; selection(); persistDraft(); });
  $('reference-reviewed').addEventListener('change', selection);
  $('reference-import').addEventListener('click', async () => {
    if (state.saving || $('reference-import').disabled) return;
    const rows = state.rows.filter(r => r.check.checked);
    for (const row of rows) for (const input of Object.values(row.fields)) if (!input.checkValidity()) { row.detail.open = true; input.reportValidity(); return; }
    state.saving = true; selection(); alert('');
    dialog.querySelectorAll('button,input,textarea,select').forEach(n => { n.dataset.wasDisabled = String(n.disabled); n.disabled = true; });
    try {
      const receipt = await api('/' + encodeURIComponent(state.job.job_id) + '/import', 'POST', {reviewed: true, subjects: rows.map(readRow)});
      state.job.status = 'imported'; state.rows = [];
      try { sessionStorage.removeItem('bts-reference-draft:' + state.job.job_id); } catch (_) {}
      $('reference-success-title').textContent = receipt.count + ' matière' + (receipt.count > 1 ? 's' : '') + ' importée' + (receipt.count > 1 ? 's' : '') + '.'; showStep('done');
      window.dispatchEvent(new CustomEvent('catalog:reload', {detail: {diploma_code: receipt.diploma_code, message: receipt.message}}));
    } catch (error) { alert(error.message); await catalog().catch(() => {}); }
    finally { state.saving = false; dialog.querySelectorAll('[data-was-disabled]').forEach(n => { n.disabled = n.dataset.wasDisabled === 'true'; delete n.dataset.wasDisabled; }); if (state.rows.length) selection(); }
  });
  for (const id of ['reference-close', 'reference-bottom-close']) $(id).addEventListener('click', () => { if (!state.saving) dialog.close(); });
  dialog.addEventListener('cancel', event => { if (state.saving) event.preventDefault(); });
  dialog.addEventListener('close', () => { $('reference-open').focus(); });
})();

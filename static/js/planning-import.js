(() => {
  'use strict';
  const root = document.querySelector('.planning-import');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = String(text); if (cls) n.className = cls; return n; };
  const day = value => new Date(value + 'T12:00:00').toLocaleDateString('fr-FR');
  const duration = minutes => Math.floor(minutes / 60) + ' h' + (minutes % 60 ? ' ' + String(minutes % 60).padStart(2, '0') : '');
  let extracted = null, preview = null, working = false;
  function message(text = '', error = false) { $('pi-message').textContent = text; $('pi-message').hidden = !text; $('pi-message').classList.toggle('error', error); }
  function step(value) { window.scrollTo(0, 0); document.querySelectorAll('.pi-steps li').forEach((n, i) => { if (i + 1 === value) n.setAttribute('aria-current', 'step'); else n.removeAttribute('aria-current'); }); }
  function busy(value) {
    working = value; root.setAttribute('aria-busy', String(value));
    root.querySelectorAll('button,input,select').forEach(n => {
      if (value) { n.dataset.disabledBefore = n.disabled ? '1' : '0'; n.disabled = true; }
      else if (n.dataset.disabledBefore !== undefined) { n.disabled = n.dataset.disabledBefore === '1'; delete n.dataset.disabledBefore; }
    });
  }
  async function api(path, body) {
    const multipart = body instanceof FormData;
    const response = await fetch('/admin/planning/api/import/' + path, {method: 'POST', credentials: 'same-origin',
      headers: {'X-CSRF-Token': root.dataset.csrf, Accept: 'application/json', ...(multipart ? {} : {'Content-Type': 'application/json'})},
      body: multipart ? body : JSON.stringify(body)});
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error([data.message || 'L’opération n’a pas abouti. Rechargez la page et réessayez.', ...(data.conflicts || []).map(c => (c.date ? day(c.date) + ' : ' : '') + c.message)].join('\n'));
    return data;
  }
  function stats(target, entries) {
    $(target).replaceChildren(...entries.map(([value, label, tone]) => {
      const card = node('div', undefined, 'pi-stat'); if (tone) card.dataset.tone = tone;
      card.append(node('strong', value), node('small', label)); return card;
    }));
  }
  function mappingField(source, kind, title, choices, suggestion, placeholder) {
    const field = node('label', undefined, 'pi-map-field'), select = node('select');
    field.append(node('span', title)); select.required = true; select.dataset.source = source; select.dataset.mapping = kind;
    select.setAttribute('aria-label', title + ' · ' + source);
    select.append(new Option(placeholder, ''));
    choices.forEach(c => select.append(new Option(c.name || [c.prenom, c.nom].filter(Boolean).join(' '), c.id)));
    select.value = suggestion || ''; field.append(select); return field;
  }
  function correspondences() {
    $('pi-subjects').replaceChildren(...Object.entries(extracted.mappings.subjects).map(([source, suggestion]) => {
      const row = node('div', undefined, 'pi-subject-row');
      const trainers = [...new Set(extracted.document.rows.filter(r => r.subject_key === source).map(r => r.trainer))];
      const subject = mappingField(source, 'subjects', source, extracted.subjects, suggestion, 'Choisir une matière de cette année');
      const trainer = mappingField(source, 'subject_trainers', 'Formateur pour cette matière', extracted.trainers,
        extracted.mappings.subject_trainers[source], 'Choisir un formateur');
      trainer.append(node('small', 'Dans le PDF : ' + trainers.join(' · ')));
      if (trainers.length > 1) trainer.append(node('small', 'Plusieurs formateurs dans le PDF : le choix ci-dessus les remplacera pour cette matière.', 'pi-map-notice'));
      row.append(subject, trainer); return row;
    }));
  }
  function mapping() {
    return Object.fromEntries(['subjects', 'subject_trainers'].map(kind => [kind,
      Object.fromEntries([...$('pi-subjects').querySelectorAll('select[data-mapping="' + kind + '"]')].map(n => [n.dataset.source, n.value]))]));
  }
  function invalidate() { preview = null; $('pi-preview-section').hidden = true; $('pi-commit').disabled = true; }
  $('pi-upload-form').addEventListener('submit', async event => {
    event.preventDefault(); if (working || !event.target.reportValidity()) return;
    const file = $('pi-file').files[0]; if (!file || file.size > 10 * 1024 * 1024) return message('Choisissez un PDF de 10 Mo maximum.', true);
    const data = new FormData(); data.append('file', file); data.append('promotion_id', root.dataset.promotion); data.append('period_id', root.dataset.period);
    busy(true); invalidate(); message('Lecture des pages et vérification des durées… Cela peut prendre quelques secondes.');
    try {
      extracted = await api('analyze', data); const doc = extracted.document;
      correspondences();
      $('pi-room').replaceChildren(new Option('Salle à compléter après l’import', ''), ...extracted.rooms.map(r => new Option(r.name, r.id)));
      stats('pi-document-summary', [[doc.rows.length, 'cours repérés'], [duration(doc.minutes), 'volume dans le PDF'], [doc.pages, 'semaines vérifiées'], [Object.keys(extracted.mappings.subjects).length, 'matières à associer']]);
      $('pi-source').textContent = 'Groupe du PDF : ' + doc.group + ' · Cours du ' + day(doc.first_date) + ' au ' + day(doc.last_date) + '.';
      $('pi-upload-section').hidden = true; $('pi-mapping-section').hidden = false; step(2); message();
    } catch (error) { message(error.message, true); }
    finally { busy(false); }
  });
  $('pi-new-file').addEventListener('click', () => { invalidate(); extracted = null; $('pi-mapping-section').hidden = true; $('pi-upload-section').hidden = false; message(); step(1); });
  $('pi-mapping-form').addEventListener('change', invalidate);
  function selection() { return [...$('pi-courses').querySelectorAll('input:checked')].map(n => n.value); }
  function selectedCount() {
    const chosen = selection(), ready = preview?.items.filter(r => r.status === 'ready') || [];
    $('pi-selected-count').textContent = chosen.length + ' cours sélectionné(s) · ' + duration(ready.filter(r => chosen.includes(r.key)).reduce((n, r) => n + r.duration_minutes, 0));
    $('pi-commit').disabled = !chosen.length;
    $('pi-select-all').checked = ready.length > 0 && ready.length === chosen.length;
    $('pi-select-all').indeterminate = chosen.length > 0 && chosen.length < ready.length;
  }
  function renderPreview() {
    const sum = preview.summary;
    stats('pi-preview-summary', [[sum.ready, 'prêts à importer'], [sum.duplicate, 'doublons ignorés', 'duplicate'], [sum.blocked, 'cours à vérifier', 'blocked'], [duration(sum.minutes), 'volume prêt à ajouter']]);
    $('pi-calendar').hidden = !preview.calendar_changes.length;
    $('pi-calendar-title').textContent = preview.calendar_changes.length + ' journée(s) à définir comme école';
    $('pi-calendar-list').replaceChildren(...preview.calendar_changes.map(c => node('li', day(c.date) + ' : ' + c.previous + ' → École')));
    const trainerNames = new Map(extracted.trainers.map(t => [t.id, [t.prenom, t.nom].filter(Boolean).join(' ')]));
    const statuses = {ready: 'Prêt à importer', duplicate: 'Déjà présent', blocked: 'À vérifier'};
    $('pi-courses').replaceChildren(...preview.items.map(item => {
      const row = node('tr'), selectCell = node('td'), dateCell = node('td'), subjectCell = node('td'), trainerCell = node('td'), checkCell = node('td');
      if (item.status === 'ready') { const box = node('input'); box.type = 'checkbox'; box.value = item.key; box.checked = true; box.setAttribute('aria-label', 'Importer le cours du ' + day(item.date) + ' à ' + item.start); box.addEventListener('change', selectedCount); selectCell.append(box); }
      else selectCell.textContent = '—';
      dateCell.append(node('strong', day(item.date)), node('small', item.start + ' – ' + item.end), node('small', 'PDF · page ' + item.page));
      subjectCell.append(node('strong', item.subject_name || item.subject), node('small', item.subject));
      trainerCell.append(node('span', trainerNames.get(item.trainer_id) || item.trainer), node('small', item.trainer));
      checkCell.append(node('span', statuses[item.status], 'pi-status ' + item.status));
      if (item.issues.length) checkCell.append(node('p', item.issues.join(' '), 'pi-issues'));
      row.append(selectCell, dateCell, subjectCell, trainerCell, checkCell); return row;
    }));
    $('pi-preview-section').hidden = false; $('pi-mapping-section').hidden = true; step(3); selectedCount();
  }
  $('pi-mapping-form').addEventListener('submit', async event => {
    event.preventDefault(); if (working || !extracted || !event.target.reportValidity()) return;
    busy(true); message('Vérification des doublons, des disponibilités et des volumes annuels…');
    try {
      preview = await api('preview', {source_token: extracted.source_token, mappings: mapping(), school_days: $('pi-school-days').checked, room_id: $('pi-room').value || null});
      renderPreview(); message();
    } catch (error) { message(error.message, true); }
    finally { busy(false); if (preview) selectedCount(); }
  });
  $('pi-select-all').addEventListener('change', event => { $('pi-courses').querySelectorAll('input').forEach(n => { n.checked = event.target.checked; }); selectedCount(); });
  $('pi-back').addEventListener('click', () => { invalidate(); $('pi-mapping-section').hidden = false; step(2); message(); });
  $('pi-commit').addEventListener('click', async () => {
    if (working || !preview) return;
    const selected = selection(); if (!selected.length) return;
    busy(true); message('Enregistrement des cours sélectionnés…');
    try {
      const result = await api('commit', {preview_token: preview.preview_token, selected_keys: selected});
      $('pi-preview-section').hidden = true; $('pi-success').hidden = false; $('pi-success-message').textContent = result.message; preview = null; message();
    } catch (error) { message(error.message, true); }
    finally { busy(false); }
  });
  window.addEventListener('beforeunload', event => { if (working) { event.preventDefault(); event.returnValue = ''; } });
})();

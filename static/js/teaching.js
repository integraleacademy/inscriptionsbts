(() => {
  'use strict';
  const root = document.querySelector('[data-teaching-course]');
  if (!root) return;
  const $ = id => document.getElementById(id);
  let state = JSON.parse($('teaching-state').textContent);
  const teacher = state.role === 'trainer', base = '/formateur/cours/' + encodeURIComponent(state.course.id);
  const dirty = new Set();
  let busy = false, editingHomework = null, gradingHomework = null;
  let clockOffset = Date.parse(state.window.server_now) - Date.now();
  function message(text, error = false) {
    const node = $('teach-feedback'); node.textContent = text; node.hidden = false;
    node.className = 'teach-feedback ' + (error ? 'error' : 'success');
  }
  function tab(name, focus = false) {
    const target = root.querySelector('[data-tab="' + name + '"]');
    if (!target) return;
    root.querySelectorAll('[data-tab]').forEach(button => {
      const active = button === target;
      button.setAttribute('aria-selected', String(active)); button.tabIndex = active ? 0 : -1;
      $('panel-' + button.dataset.tab).hidden = !active;
    });
    if (focus) target.focus();
  }
  const tabs = [...root.querySelectorAll('[data-tab]')];
  tabs.forEach((button, index) => {
    button.addEventListener('click', () => { tab(button.dataset.tab); history.replaceState(null, '', '#' + button.dataset.tab); });
    button.addEventListener('keydown', event => {
      const next = event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : null;
      if (next !== null) { event.preventDefault(); tab(tabs[next].dataset.tab, true); }
    });
  });
  const initial = location.hash.slice(1);
  tab(tabs.some(t => t.dataset.tab === initial) ? initial : teacher ? 'appel' : 'cahier');
  if (!teacher) return;

  root.querySelectorAll('form').forEach(form => {
    form.addEventListener('input', () => dirty.add(form.id));
    form.addEventListener('change', () => dirty.add(form.id));
  });
  window.addEventListener('beforeunload', event => { if (dirty.size) { event.preventDefault(); event.returnValue = ''; } });
  async function api(action, data, multipart = false) {
    const options = {method:'POST', credentials:'same-origin', cache:'no-store', headers:{'X-CSRF-Token':root.dataset.csrf, Accept:'application/json'}};
    if (multipart) options.body = data;
    else { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(data); }
    const response = await fetch(base + '/' + action, options);
    const value = await response.json().catch(() => ({}));
    if (!response.ok || !value.ok) throw new Error(value.message || 'Impossible d’enregistrer. Vérifiez votre connexion et réessayez.');
    return value;
  }
  async function task(button, operation) {
    if (busy) return;
    busy = true;
    const text = button?.textContent;
    if (button) { button.disabled = true; button.textContent = 'En cours…'; }
    try { await operation(); }
    catch (error) { message(error.message, true); }
    finally { busy = false; if (button) { button.disabled = false; button.textContent = text; if (button.isConnected && button.offsetParent) button.focus({preventScroll:true}); } updateWindow(); }
  }
  function syncClock(answer) { if (answer.window) { state.window = answer.window; clockOffset = Date.parse(answer.window.server_now) - Date.now(); } }
  function updateWindow() {
    const now = Date.now() + clockOffset, start = Date.parse(state.window.start_at), end = Date.parse(state.window.end_at);
    const open = now >= start && now < end;
    $('teach-attendance-fields').disabled = !open || busy;
    $('teach-course-phase').textContent = open ? 'En cours' : now < start ? 'À venir' : 'Cours terminé';
    $('teach-window-message').textContent = open
      ? 'L’appel est ouvert jusqu’à ' + state.course.end + '. Pensez à le valider, même si tout le monde est présent.'
      : now < start ? 'L’appel ouvrira au début du cours, le ' + state.course.date.split('-').reverse().join('/') + ' à ' + state.course.start + ' (heure de Paris).'
      : 'L’appel est fermé depuis ' + state.course.end + '. Pour une correction après le cours, contactez l’équipe pédagogique.';
  }
  updateWindow(); setInterval(updateWindow, 1000);
  // Resync without replacing any draft. Server enforcement remains authoritative.
  setInterval(async () => {
    if (document.hidden || busy) return;
    try {
      const response = await fetch(base + '/state', {credentials:'same-origin', cache:'no-store'});
      if (response.ok) syncClock(await response.json());
    } catch (_) { /* Drafts remain editable; a save will surface a connection error. */ }
  }, 60000);
  function refreshAttendance() {
    const counts = {present:0, late:0, absent:0};
    root.querySelectorAll('[data-attendance-row]').forEach(row => {
      const select = row.querySelector('[data-status]'), minutes = row.querySelector('[data-minutes]');
      const late = select.value === 'late'; counts[select.value]++;
      select.className = 'teach-status ' + select.value;
      minutes.parentElement.hidden = !late; minutes.required = late; minutes.disabled = !late;
    });
    $('teach-attendance-count').textContent = counts.present + ' présent' + (counts.present > 1 ? 's' : '') + ' · ' + counts.late + ' retard' + (counts.late > 1 ? 's' : '') + ' · ' + counts.absent + ' absent' + (counts.absent > 1 ? 's' : '');
  }
  root.querySelectorAll('[data-status]').forEach(select => select.addEventListener('change', () => {
    refreshAttendance(); if (select.value === 'late') select.closest('[data-attendance-row]').querySelector('[data-minutes]').focus();
  }));
  refreshAttendance();
  $('teach-attendance-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget;
    if (!form.reportValidity() || $('teach-attendance-fields').disabled) return;
    const students = [...root.querySelectorAll('[data-attendance-row]')].map(row => {
      const status = row.querySelector('[data-status]').value;
      return {id:row.dataset.studentId, status, late_minutes:status === 'late' ? Number(row.querySelector('[data-minutes]').value) : 0};
    });
    task(event.submitter, async () => {
      const answer = await api('appel', {version:state.attendance.version, students});
      state.attendance = answer.attendance; syncClock(answer); dirty.delete(form.id);
      $('teach-call-indicator').textContent = '✓'; $('teach-call-summary').textContent = 'Appel validé. Vous pouvez le corriger jusqu’à la fin du cours.';
      message('L’appel a bien été enregistré.');
    });
  });
  const selectedTopics = () => [...root.querySelectorAll('input[name=topics]:checked')].map(input => input.value);
  $('teach-journal-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget;
    task(event.submitter, async () => {
      const answer = await api('cahier', {version:state.journal.version, content:$('teach-journal-content').value, topics:selectedTopics()});
      state.journal = answer.journal; dirty.delete(form.id); $('teach-journal-saved').textContent = 'Enregistré à l’instant';
      message('Cahier de texte enregistré et disponible dans l’espace étudiant.');
    });
  });
  $('teach-ai-journal').addEventListener('click', event => task(event.currentTarget, async () => {
    const answer = await api('assistant', {task:'journal', notes:$('teach-journal-content').value, topics:selectedTopics()});
    $('teach-ai-output').value = answer.draft; $('teach-ai-draft').hidden = false;
    message('Proposition prête : relisez-la avant de l’utiliser.');
  }));
  $('teach-use-ai').addEventListener('click', () => {
    if ($('teach-journal-content').value.trim() && !window.confirm('Remplacer le texte actuel par cette proposition ?')) return;
    $('teach-journal-content').value = $('teach-ai-output').value; dirty.add('teach-journal-form'); $('teach-ai-draft').hidden = true;
  });
  $('teach-dismiss-ai').addEventListener('click', () => { $('teach-ai-draft').hidden = true; });

  function el(tag, text, className) {
    const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (className) node.className = className; return node;
  }
  function renderDocuments() {
    const list = $('teach-document-list'); list.replaceChildren(); $('teach-document-count').textContent = state.documents.length;
    if (!state.documents.length) list.append(el('p', 'Aucun document partagé pour le moment.', 'teach-empty'));
    state.documents.forEach(doc => {
      const row = el('div', undefined, 'teach-document-row'), link = el('a', doc.filename);
      link.href = '/formateur/documents/' + encodeURIComponent(doc.id);
      const remove = el('button', 'Retirer', 'teach-button subtle'); remove.type = 'button'; remove.dataset.deleteDocument = doc.id;
      row.append(link, el('small', Math.round(doc.size / 1024) + ' Ko'), remove); list.append(row);
    });
  }
  $('teach-document-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget;
    if (!form.reportValidity()) return;
    const file = form.querySelector('input[type=file]').files[0];
    if (file.size > 20 * 1024 * 1024) { message('Le fichier dépasse 20 Mo.', true); return; }
    const body = new FormData(form);
    task(event.submitter, async () => {
      const added = await api('documents', body, true);
      state.documents.push({id:added.id, filename:added.filename, size:file.size}); renderDocuments(); form.reset(); dirty.delete(form.id);
      message('Document ajouté au cours.');
    });
  });
  $('teach-document-list').addEventListener('click', event => {
    const button = event.target.closest('[data-delete-document]');
    if (!button || !window.confirm('Retirer ce document du cours ?')) return;
    task(button, async () => {
      await api('document-supprimer', {id:button.dataset.deleteDocument});
      state.documents = state.documents.filter(d => d.id !== button.dataset.deleteDocument); renderDocuments(); message('Document retiré.');
    });
  });
  function renderHomework() {
    const list = $('teach-homework-list'); list.replaceChildren();
    if (!state.homework.length) list.append(el('p', 'Aucun devoir pour ce cours. Créez le premier devoir.', 'teach-empty'));
    state.homework.forEach(hw => {
      const item = el('article', undefined, 'teach-homework'), heading = el('div', undefined, 'teach-section-heading');
      heading.append(el('h3', hw.title), el('span', hw.published ? 'Publié' : 'Brouillon', 'teach-tag'));
      item.append(heading, el('div', hw.instructions, 'teach-read-content'), el('p', 'Pour le ' + hw.due_date.split('-').reverse().join('/') + ' · Sur ' + hw.scale + ' · Coefficient ' + hw.coefficient));
      const actions = el('div', undefined, 'teach-inline');
      const edit = el('button', 'Modifier le devoir', 'teach-button'); edit.type = 'button'; edit.addEventListener('click', () => openHomework(hw));
      const grades = el('button', 'Saisir les notes', 'teach-button primary'); grades.type = 'button'; grades.addEventListener('click', () => openGrades(hw));
      actions.append(edit, grades); item.append(actions); list.append(item);
    });
  }
  function canDiscard(id) { return !dirty.has(id) || window.confirm('Abandonner les modifications non enregistrées de ce formulaire ?'); }
  function openHomework(hw = null) {
    if (!canDiscard('teach-homework-form')) return;
    dirty.delete('teach-homework-form'); editingHomework = hw ? {id:hw.id, version:hw.version} : null;
    $('teach-homework-form').hidden = false; $('teach-homework-editor-title').textContent = hw ? 'Modifier le devoir' : 'Nouveau devoir';
    $('teach-homework-id').value = hw?.id || ''; $('teach-homework-title').value = hw?.title || '';
    $('teach-homework-instructions').value = hw?.instructions || ''; $('teach-homework-due').value = hw?.due_date || state.course.date;
    $('teach-homework-scale').value = hw?.scale || 20; $('teach-homework-coefficient').value = hw?.coefficient || 1;
    $('teach-homework-published').checked = hw?.published === 1; $('teach-homework-ai-draft').hidden = true;
    $('teach-homework-title').focus();
  }
  $('teach-new-homework').addEventListener('click', () => openHomework());
  $('teach-close-homework').addEventListener('click', () => { if (canDiscard('teach-homework-form')) { dirty.delete('teach-homework-form'); $('teach-homework-form').hidden = true; } });
  $('teach-homework-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget;
    if (!form.reportValidity()) return;
    task(event.submitter, async () => {
      const answer = await api('devoir', {id:editingHomework?.id || null, version:editingHomework?.version || 0,
        title:$('teach-homework-title').value, instructions:$('teach-homework-instructions').value,
        due_date:$('teach-homework-due').value, scale:$('teach-homework-scale').value,
        coefficient:$('teach-homework-coefficient').value, published:$('teach-homework-published').checked});
      state.homework = answer.homework; dirty.delete(form.id); form.hidden = true; renderHomework(); message('Devoir enregistré.');
    });
  });
  $('teach-ai-homework').addEventListener('click', event => task(event.currentTarget, async () => {
    const notes = [$('teach-homework-title').value, $('teach-homework-instructions').value, $('teach-journal-content').value].filter(Boolean).join('\n\n');
    const answer = await api('assistant', {task:'homework', topics:selectedTopics(), notes:notes.slice(0, 12000)});
    $('teach-homework-ai-output').value = answer.draft; $('teach-homework-ai-draft').hidden = false;
    message('Consignes proposées : relisez-les avant de les utiliser.');
  }));
  $('teach-use-homework-ai').addEventListener('click', () => {
    if ($('teach-homework-instructions').value.trim() && !window.confirm('Remplacer les consignes actuelles par cette proposition ?')) return;
    $('teach-homework-instructions').value = $('teach-homework-ai-output').value; $('teach-homework-ai-draft').hidden = true; dirty.add('teach-homework-form');
  });
  function openGrades(hw) {
    if (!canDiscard('teach-grades-form')) return;
    dirty.delete('teach-grades-form'); gradingHomework = {id:hw.id, version:hw.version, scale:hw.scale};
    $('teach-grades-form').hidden = false; $('teach-grades-title').textContent = hw.title + ' · Notes sur ' + hw.scale;
    const rows = $('teach-grades-rows'); rows.replaceChildren();
    state.attendance.students.forEach(student => {
      const grade = hw.grades.find(g => g.candidate_id === student.id), row = el('div', undefined, 'teach-grade-row');
      row.dataset.gradeStudent = student.id; const name = el('strong', student.prenom + ' ' + student.nom.toUpperCase()); name.append(el('small', student.promotion_name));
      const statusLabel = el('label', 'Statut'), status = document.createElement('select'); status.dataset.gradeStatus = '';
      [['pending','Non noté'],['graded','Noté'],['absent','Absent'],['exempt','Dispensé']].forEach(([value,label]) => { const option = el('option', label); option.value = value; status.append(option); });
      status.value = grade?.status || 'pending'; statusLabel.append(status);
      const scoreLabel = el('label', 'Sur ' + hw.scale), score = document.createElement('input'); score.type = 'number'; score.min = '0'; score.max = hw.scale; score.step = '.01'; score.dataset.gradeScore = ''; score.value = grade?.score ?? ''; scoreLabel.append(score);
      const commentLabel = el('label', 'Appréciation'), comment = document.createElement('input'); comment.type = 'text'; comment.maxLength = 2000; comment.dataset.gradeComment = ''; comment.value = grade?.comment || ''; commentLabel.append(comment);
      const refresh = () => { score.disabled = ['absent', 'exempt'].includes(status.value); score.required = status.value === 'graded'; updateAverage(); };
      status.addEventListener('change', refresh); score.addEventListener('input', () => { if (score.value !== '') status.value = 'graded'; else if (status.value === 'graded') status.value = 'pending'; refresh(); });
      row.append(name, statusLabel, scoreLabel, commentLabel); rows.append(row); refresh();
    });
    updateAverage(); $('teach-grades-title').scrollIntoView({block:'start', behavior:'smooth'});
  }
  function updateAverage() {
    let sum = 0, count = 0;
    root.querySelectorAll('[data-grade-student]').forEach(row => {
      const score = row.querySelector('[data-grade-score]');
      if (row.querySelector('[data-grade-status]').value === 'graded' && score.value !== '' && Number.isFinite(Number(score.value))) { sum += Number(score.value); count++; }
    });
    $('teach-grades-average').textContent = count ? 'Moyenne du devoir : ' + (sum/count).toLocaleString('fr-FR', {maximumFractionDigits:2}) + ' / ' + gradingHomework.scale + ' · ' + count + ' notes' : 'Aucune note saisie';
  }
  $('teach-close-grades').addEventListener('click', () => { if (canDiscard('teach-grades-form')) { dirty.delete('teach-grades-form'); $('teach-grades-form').hidden = true; } });
  $('teach-grades-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget;
    if (!form.reportValidity() || !gradingHomework) return;
    const students = [...root.querySelectorAll('[data-grade-student]')].map(row => ({id:row.dataset.gradeStudent,
      status:row.querySelector('[data-grade-status]').value, score:row.querySelector('[data-grade-score]').value, comment:row.querySelector('[data-grade-comment]').value}));
    task(event.submitter, async () => {
      const answer = await api('notes', {id:gradingHomework.id, version:gradingHomework.version, students});
      state.homework = answer.homework; gradingHomework.version = state.homework.find(hw => hw.id === gradingHomework.id).version;
      dirty.delete(form.id); renderHomework(); message('Notes et appréciations enregistrées.');
    });
  });
  renderHomework();
})();

(() => {
  'use strict';
  const root = document.querySelector('[data-teaching-course]');
  if (!root) return;
  const $ = id => document.getElementById(id);
  let state = JSON.parse($('teaching-state').textContent);
  const teacher = state.role === 'trainer', base = '/formateur/cours/' + encodeURIComponent(state.course.id);
  const dirty = new Set();
  let busy = false;
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
})();

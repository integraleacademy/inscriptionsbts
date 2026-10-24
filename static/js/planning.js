/* Academy planning: explicit saves, server-checked availability, no third-party calendar. */
(() => {
  'use strict';
  const app = document.querySelector('.planning-app');
  if (!app) return;
  const $ = id => document.getElementById(id), API = '/admin/planning/api';
  const kinds = {school: 'À l’école', company: 'En entreprise', holiday: 'Vacances', closed: 'Fermé', unconfigured: 'À définir'};
  const weekdays = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];
  const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = String(text); return node; };
  const button = (text, cls, action) => { const node = el('button', cls || 'planning-button', text); node.type = 'button'; if (action) node.addEventListener('click', action); return node; };
  const parseDate = value => new Date(String(value).slice(0, 10) + 'T12:00:00');
  const dateString = date => [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
  const addDays = (value, days) => { const date = parseDate(value); date.setDate(date.getDate() + days); return dateString(date); };
  const monday = value => { const date = parseDate(value); return addDays(value, -(date.getDay() + 6) % 7); };
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  const formatDate = (value, options = {day: 'numeric', month: 'long'}) => parseDate(value).toLocaleDateString('fr-FR', options);
  const minutes = value => { const [h, m] = String(value || '00:00').split(':').map(Number); return h * 60 + m; };
  const timeString = value => String(Math.floor(value / 60)).padStart(2, '0') + ':' + String(value % 60).padStart(2, '0');
  const hours = value => new Intl.NumberFormat('fr-FR', {maximumFractionDigits: 1}).format(Number(value) || 0) + ' h';
  const normal = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr');
  const courseDuration = course => Number(course.duration_minutes) || minutes(course.end) - minutes(course.start);
  const safeColor = value => /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#66764e';
  const state = {data: null, year: null, week: monday(today()), view: 'week', subject: '', availability: new Map(), availabilityReady: false, availabilitySeq: 0, loadSeq: 0, dragCourse: null, gridStart: 420, gridEnd: 1260, subjectEdit: null, ruleEdit: null, exceptionEdit: null, courseEdit: null, roomEdit: null, batch: null, busy: false, loading: false};
  const promotionId = () => $('planning-promotion').value;
  const currentSubject = () => state.data?.subjects?.find(subject => String(subject.id) === state.subject);
  function notice(text, failure = false) { const node = $('planning-notice'); node.textContent = text || ''; node.hidden = !text; node.classList.toggle('error', failure); }
  function formError(form, message) { const node = form.querySelector('.planning-form-error'); if (node) { node.textContent = message || ''; node.hidden = !message; } }
  function failureText(result) { return [result.message || result.error || '', ...(result.conflicts || []).map(conflict => (conflict.date ? formatDate(conflict.date) + ' : ' : '') + conflict.message)].filter(Boolean).join('\n') || 'L’action n’a pas abouti. Rechargez la page puis réessayez.'; }
  async function request(path, {method = 'GET', data, signal} = {}) {
    const response = await fetch(path.startsWith('/admin/') ? path : API + path, {method, signal, credentials: 'same-origin', headers: {Accept: 'application/json', ...(method !== 'GET' ? {'Content-Type': 'application/json', 'X-CSRF-Token': app.dataset.csrf} : {})}, ...(method !== 'GET' ? {body: JSON.stringify(data || {})} : {})});
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) { const failure = new Error(failureText(result)); failure.result = result; throw failure; }
    return result;
  }
  function openDialog(id, focus) {
    const dialog = $(id); dialog._opener = document.activeElement; dialog.querySelectorAll('.planning-form-error').forEach(node => { node.hidden = true; node.textContent = ''; }); dialog.showModal();
    (focus || dialog.querySelector('input,select,button:not(.planning-dialog-close)'))?.focus();
  }
  document.querySelectorAll('.planning-dialog').forEach(dialog => {
    dialog.querySelectorAll('[data-close-dialog]').forEach(control => control.addEventListener('click', () => { if (!dialog.dataset.busy) dialog.close(); }));
    dialog.addEventListener('cancel', event => { if (dialog.dataset.busy) event.preventDefault(); });
    dialog.addEventListener('close', () => dialog._opener?.focus());
  });
  function busyDialog(dialog, value) {
    if (value) dialog.dataset.busy = '1'; else delete dialog.dataset.busy;
    dialog.setAttribute('aria-busy', String(value));
    dialog.querySelectorAll('button,input,select').forEach(node => { if (value) { node.dataset.wasDisabled = node.disabled ? '1' : '0'; node.disabled = true; } else if (node.dataset.wasDisabled !== undefined) { node.disabled = node.dataset.wasDisabled === '1'; delete node.dataset.wasDisabled; } });
  }
  async function saveForm(form, task, success, keepOpen = false) {
    const dialog = form.closest('dialog'); if (dialog.dataset.busy || !form.reportValidity()) return;
    formError(form, ''); busyDialog(dialog, true);
    try { await task(); if (!keepOpen) dialog.close(); notice(success); await loadState(); }
    catch (failure) { formError(form, failure.message); }
    finally { busyDialog(dialog, false); }
  }
  function populate(select, items, label, blank = null, selected = '') {
    select.replaceChildren(); if (blank !== null) select.add(new Option(blank, ''));
    for (const item of items || []) select.add(new Option(label(item), String(item.id)));
    select.value = String(selected || '');
  }
  function courseName(course) { return course.title || course.subject_name || state.data?.subjects?.find(subject => String(subject.id) === String(course.subject_id))?.name || 'Cours'; }
  async function loadState({initial = false} = {}) {
    const id = promotionId(); const seq = ++state.loadSeq; state.loading = true; state.availabilitySeq++; state.availabilityReady = false; state.availability.clear();
    $('planning-selected').hidden = !id; $('planning-unselected').hidden = !!id; $('planning-export-open').disabled = !id;
    if (!id) { state.data = null; state.loading = false; app.setAttribute('aria-busy', 'false'); return; }
    app.setAttribute('aria-busy', 'true'); $('planning-save-state').textContent = 'Chargement du planning…';
    try {
      const result = await request('/state?' + new URLSearchParams({promotion_id: id, start: state.week, end: addDays(state.week, 6)}));
      if (seq !== state.loadSeq || id !== promotionId()) return;
      state.data = result; state.year = null;
      const promotion = result.promotion;
      if (initial && promotion.date_debut && promotion.date_fin && (today() < promotion.date_debut || today() > promotion.date_fin)) { state.week = monday(promotion.date_debut); return loadState(); }
      if (!(result.subjects || []).some(subject => String(subject.id) === state.subject)) state.subject = '';
      renderPromotion(); renderSubjects(); renderCalendar(); renderRules();
      if (state.view === 'year') await renderYear();
      if (state.subject) await loadAvailability();
    } catch (failure) { if (seq === state.loadSeq) { state.data = null; $('planning-selected').hidden = true; notice(failure.message, true); } }
    finally { if (seq === state.loadSeq) { state.loading = false; app.setAttribute('aria-busy', 'false'); $('planning-save-state').textContent = 'Chaque action est enregistrée'; } }
  }
  function renderPromotion() {
    const {promotion, subjects = [], courses = []} = state.data;
    const details = $('planning-promotion-details'); details.replaceChildren(el('b', '', promotion.nom), el('span', '', 'BTS ' + promotion.bts + ' · ' + (promotion.niveau ? (Number(promotion.niveau) === 1 ? '1re année' : '2e année') : 'Niveau à compléter') + (promotion.date_debut && promotion.date_fin ? ' · ' + formatDate(promotion.date_debut) + ' au ' + formatDate(promotion.date_fin, {day: 'numeric', month: 'long', year: 'numeric'}) : ' · Dates à compléter dans Promotions')));
    $('planning-calendar-progress').textContent = state.data.calendar_configured ? 'En place' : 'À préparer';
    $('planning-subject-progress').textContent = subjects.length ? subjects.length + ' matière' + (subjects.length > 1 ? 's' : '') : 'À préparer';
    $('planning-course-progress').textContent = courses.length ? courses.length + ' cours cette semaine' : 'À composer';
    const room = $('planning-room'), selected = room.value; populate(room, (state.data.rooms || []).filter(item => item.active !== false && item.active !== 0), item => item.name, 'Sans salle attribuée', selected);
    $('planning-range-title').textContent = formatDate(state.week, {day: 'numeric', month: 'short'}) + ' — ' + formatDate(addDays(state.week, 6), {day: 'numeric', month: 'short', year: 'numeric'});
    $('planning-week-hours').textContent = hours(courses.reduce((sum, course) => sum + courseDuration(course), 0) / 60) + ' planifiées · ' + courses.length + ' cours';
    $('planning-date').value = state.week;
  }
  function renderSubjects() {
    const container = $('planning-subjects'); container.replaceChildren();
    const query = normal($('planning-subject-search').value);
    for (const subject of (state.data?.subjects || []).filter(item => normal(item.name + ' ' + (item.trainer_name || '')).includes(query))) {
      const card = el('article', 'planning-subject-card' + (state.subject === String(subject.id) ? ' selected' : '')); card.style.setProperty('--subject-color', safeColor(subject.color));
      const choose = button('', 'planning-subject-pick', () => chooseSubject(subject.id)); choose.draggable = true; choose.setAttribute('aria-pressed', String(state.subject === String(subject.id))); choose.append(el('b', '', subject.name), el('span', '', subject.trainer_name || 'Formateur à définir'));
      choose.append(el('small', '', hours(subject.scheduled_hours) + ' planifiées' + (subject.planned_hours !== null && subject.planned_hours !== undefined ? ' / ' + hours(subject.planned_hours) + ' prévues' : '')));
      choose.addEventListener('dragstart', event => { state.dragCourse = null; chooseSubject(subject.id); event.dataTransfer.setData('text/plain', 'subject:' + subject.id); event.dataTransfer.effectAllowed = 'copy'; });
      const edit = button('Modifier', 'planning-text-button', () => openSubject(subject)); edit.setAttribute('aria-label', 'Modifier la matière ' + subject.name); card.append(choose, edit); container.append(card);
    }
    if (!container.children.length) container.append(el('p', 'planning-palette-empty', state.data?.subjects?.length ? 'Aucune matière pour cette recherche.' : 'Créez votre première matière pour commencer à composer le planning.'));
    $('planning-selection-clear').hidden = !state.subject;
  }
  async function chooseSubject(id) { if (state.loading || !state.data) return; state.subject = String(id); state.availabilityReady = false; state.availability.clear(); renderSubjects(); renderAvailability(); await loadAvailability(); }
  function availabilityOptions() {
    const course = state.dragCourse, subject = currentSubject();
    return {promotion_id: promotionId(), subject_id: state.subject, trainer_id: course?.trainer_id || subject?.trainer_id || '', room_id: course ? (course.room_id || '') : ($('planning-room').value || ''), duration: course ? courseDuration(course) : Number($('planning-duration').value), start: state.week, end: addDays(state.week, 6), day_start: timeString(state.gridStart), day_end: timeString(state.gridEnd), step_minutes: 30, ...(course ? {exclude_course_id: course.id} : {})};
  }
  async function loadAvailability() {
    const seq = ++state.availabilitySeq; if (!state.subject || !state.data) { state.availability.clear(); state.availabilityReady = false; renderAvailability(); return; }
    state.availabilityReady = false; $('planning-placement-help').textContent = 'Vérification des disponibilités…'; renderAvailability();
    try {
      const result = await request('/availability?' + new URLSearchParams(availabilityOptions()));
      if (seq !== state.availabilitySeq) return;
      state.availability = new Map((result.slots || []).map(slot => [slot.date + '|' + slot.start, slot])); state.availabilityReady = true; renderAvailability();
    } catch (failure) { if (seq === state.availabilitySeq) notice(failure.message, true); }
  }
  function dayInfo(date) { return (state.data?.days || []).find(day => day.date === date) || {date, kind: 'unconfigured', label: ''}; }
  function renderCalendar() {
    const courses = state.data.courses || []; const startValues = courses.map(course => minutes(course.start)), endValues = courses.map(course => minutes(course.end));
    state.gridStart = Math.max(0, Math.min(420, ...startValues.map(value => Math.floor(value / 60) * 60))); state.gridEnd = Math.min(1440, Math.max(1260, ...endValues.map(value => Math.ceil(value / 60) * 60)));
    const calendar = $('planning-calendar'); calendar.replaceChildren(); calendar.style.setProperty('--calendar-height', (state.gridEnd - state.gridStart) * 1.1 + 'px');
    const head = el('div', 'planning-week-head'); head.append(el('span', 'planning-time-corner', 'Paris'));
    for (let day = 0; day < 7; day++) {
      const date = addDays(state.week, day), info = dayInfo(date); const header = button('', 'planning-day-heading kind-' + info.kind + (date === today() ? ' is-today' : ''), () => openException(date)); header.append(el('span', '', weekdays[day]), el('b', '', formatDate(date, {day: 'numeric', month: 'short'})), el('small', '', info.label || kinds[info.kind] || 'À définir')); header.setAttribute('aria-label', formatDate(date, {weekday: 'long', day: 'numeric', month: 'long'}) + ', ' + (info.label || kinds[info.kind]) + '. Modifier cette journée.'); head.append(header);
    }
    calendar.append(head); const grid = el('div', 'planning-calendar-grid'); const timeAxis = el('div', 'planning-times');
    for (let minute = state.gridStart; minute < state.gridEnd; minute += 60) { const tick = el('span', '', timeString(minute)); tick.style.top = ((minute - state.gridStart) * 1.1) + 'px'; timeAxis.append(tick); } grid.append(timeAxis);
    for (let day = 0; day < 7; day++) {
      const date = addDays(state.week, day), info = dayInfo(date); const column = el('div', 'planning-day-column kind-' + info.kind); column.setAttribute('role', 'group'); column.setAttribute('aria-label', weekdays[day] + ' ' + formatDate(date));
      for (let minute = state.gridStart; minute < state.gridEnd; minute += 30) {
        const start = timeString(minute); const slot = button('', 'planning-slot' + (minute % 60 === 0 ? ' whole-hour' : ''), () => placeAt(date, start)); slot.dataset.date = date; slot.dataset.start = start; slot.style.top = (minute - state.gridStart) * 1.1 + 'px'; slot.style.height = '33px';
        slot.addEventListener('dragover', event => { if (state.subject) { event.preventDefault(); event.dataTransfer.dropEffect = state.dragCourse ? 'move' : 'copy'; slot.classList.add('drag-over'); } }); slot.addEventListener('dragleave', () => slot.classList.remove('drag-over')); slot.addEventListener('drop', event => { event.preventDefault(); slot.classList.remove('drag-over'); placeAt(date, start); });
        slot.addEventListener('keydown', event => { let targetDate = date, targetMinute = minute; if (event.key === 'ArrowDown') targetMinute += 30; else if (event.key === 'ArrowUp') targetMinute -= 30; else if (event.key === 'ArrowRight') targetDate = addDays(date, 1); else if (event.key === 'ArrowLeft') targetDate = addDays(date, -1); else return; const target = calendar.querySelector('[data-date="' + targetDate + '"][data-start="' + timeString(targetMinute) + '"]'); if (target) { event.preventDefault(); target.focus(); } }); column.append(slot);
      }
      for (const course of courses.filter(item => item.date === date)) {
        const event = button('', 'planning-event' + (courseDuration(course) <= 45 ? ' is-short' : ''), () => openCourse(course)); event.draggable = true; event.style.top = (minutes(course.start) - state.gridStart) * 1.1 + 'px'; event.style.height = Math.max(30, courseDuration(course) * 1.1 - 3) + 'px'; event.style.setProperty('--subject-color', safeColor(course.color)); event.append(el('small', 'planning-event-time', course.start + ' – ' + course.end), el('b', '', courseName(course)), el('span', '', course.trainer_name || 'Formateur'), el('small', '', course.room_name || 'Sans salle')); event.title = [courseName(course),course.start + ' – ' + course.end,course.trainer_name,course.room_name].filter(Boolean).join(' · ');
        event.addEventListener('dragstart', drag => { state.dragCourse = course; state.subject = String(course.subject_id); renderSubjects(); loadAvailability(); drag.dataTransfer.setData('text/plain', 'course:' + course.id); drag.dataTransfer.effectAllowed = 'move'; });
        event.addEventListener('dragend', () => { state.dragCourse = null; loadAvailability(); }); column.append(event);
      } grid.append(column);
    } calendar.append(grid); renderAvailability();
  }
  function renderAvailability() {
    const subject = currentSubject();
    $('planning-calendar').querySelectorAll('.planning-slot').forEach(slot => {
      const info = state.availability.get(slot.dataset.date + '|' + slot.dataset.start); const day = dayInfo(slot.dataset.date);
      slot.classList.toggle('is-available', !!subject && state.availabilityReady && !!info?.available); slot.classList.toggle('is-unavailable', !!subject && state.availabilityReady && !info?.available);
      const reason = info?.conflicts?.map(conflict => conflict.message).join(' · ') || (day.kind !== 'school' ? day.label || kinds[day.kind] : 'Durée incompatible avec la plage horaire affichée.');
      const text = formatDate(slot.dataset.date, {weekday: 'long', day: 'numeric', month: 'long'}) + ', ' + slot.dataset.start + (subject ? ', ' + (state.availabilityReady ? (info?.available ? 'Disponible pour ' + subject.name : 'Indisponible : ' + reason) : 'Vérification en cours') : ', sélectionner une matière pour vérifier la disponibilité'); slot.title = text; slot.setAttribute('aria-label', text);
    });
    if (subject && state.availabilityReady) $('planning-placement-help').textContent = subject.name + ' · ' + (state.dragCourse ? 'Déplacez le cours vers un créneau disponible.' : 'Cliquez ou déposez sur un créneau vert.');
    else if (!subject) $('planning-placement-help').textContent = 'Choisissez une matière pour afficher les disponibilités.';
  }
  async function placeAt(date, start) {
    if (state.loading || !state.data) return;
    if (!state.subject) { notice('Sélectionnez d’abord une matière dans la colonne de gauche.'); $('planning-subject-search').focus(); return; }
    const moving = state.dragCourse, subjectId = state.subject, roomId = moving ? (moving.room_id || '') : $('planning-room').value, sequence = state.loadSeq;
    const options = availabilityOptions();
    let slot = state.availabilityReady ? state.availability.get(date + '|' + start) : null;
    if (!state.availabilityReady || moving) {
      try { const result = await request('/availability?' + new URLSearchParams(options)); slot = (result.slots || []).find(item => item.date === date && item.start === start); }
      catch (failure) { notice(failure.message, true); return; }
    }
    if (sequence !== state.loadSeq || options.promotion_id !== promotionId()) return;
    if (!slot?.available) { notice(slot?.conflicts?.map(conflict => conflict.message).join(' · ') || 'Ce créneau n’est pas disponible pour cette matière et cette durée.', true); return; }
    notice(''); openCourse(moving || null, {date, start, end: slot.end, subject_id: subjectId, room_id: roomId});
  }
  function selectView(view) { state.view = view; $('planning-week-view').hidden = view !== 'week'; $('planning-year-view').hidden = view !== 'year'; $('planning-view-week').setAttribute('aria-pressed', String(view === 'week')); $('planning-view-year').setAttribute('aria-pressed', String(view === 'year')); if (view === 'year' && state.data) renderYear(); }
  async function renderYear() {
    const id = promotionId(); if (!id || !state.data) return;
    const promotion = state.data.promotion, start = promotion.date_debut || state.week.slice(0, 4) + '-01-01', end = promotion.date_fin || state.week.slice(0, 4) + '-12-31';
    try {
      if (!state.year) { const sequence = state.loadSeq; const result = await request('/state?' + new URLSearchParams({promotion_id: id, start, end})); if (id !== promotionId() || sequence !== state.loadSeq) return; state.year = result; }
      if (id !== promotionId()) return;
      const map = new Map((state.year.days || []).map(day => [day.date, day])); const container = $('planning-months'); container.replaceChildren();
      const cursor = parseDate(start); cursor.setDate(1); const endDate = parseDate(end);
      for (let index = 0; cursor <= endDate && index < 36; index++, cursor.setMonth(cursor.getMonth() + 1)) {
        const year = cursor.getFullYear(), month = cursor.getMonth(), monthNode = el('article', 'planning-month'); monthNode.append(el('h3', '', cursor.toLocaleDateString('fr-FR', {month: 'long', year: 'numeric'}))); const days = el('div', 'planning-month-grid');
        for (const day of ['L', 'M', 'M', 'J', 'V', 'S', 'D']) days.append(el('span', 'planning-month-weekday', day));
        const offset = (cursor.getDay() + 6) % 7; for (let i = 0; i < offset; i++) days.append(el('span', 'planning-month-blank'));
        const last = new Date(year, month + 1, 0).getDate();
        for (let day = 1; day <= last; day++) { const date = dateString(new Date(year, month, day, 12)), info = map.get(date); const cell = button(String(day), 'planning-month-day kind-' + (info?.kind || 'closed'), () => openException(date)); cell.disabled = date < start || date > end; cell.title = formatDate(date) + ' · ' + (info?.label || kinds[info?.kind || 'closed']); cell.setAttribute('aria-label', cell.title + '. Modifier cette journée.'); if ((state.year.courses || []).some(course => course.date === date)) cell.classList.add('has-courses'); days.append(cell); }
        monthNode.append(days); container.append(monthNode);
      } renderRules();
    } catch (failure) { notice(failure.message, true); }
  }
  function renderRules() {
    const rules = $('planning-rules'), exceptions = $('planning-exceptions'); rules.replaceChildren(); exceptions.replaceChildren();
    for (const rule of state.data.rules || []) { const card = el('article', 'planning-rule kind-' + rule.kind); card.append(el('b', '', rule.label || kinds[rule.kind]), el('span', '', formatDate(rule.start_date) + ' — ' + formatDate(rule.end_date)), el('small', '', (rule.weekdays || []).map(day => weekdays[day]?.slice(0, 3)).join(' · ')), button('Modifier', 'planning-text-button', () => openPeriod(rule))); rules.append(card); }
    if (!rules.children.length) rules.append(el('p', 'planning-muted', 'Aucune période définie.'));
    for (const exception of state.data.exceptions || []) { const card = el('article', 'planning-rule kind-' + exception.kind); card.append(el('b', '', exception.label || kinds[exception.kind]), el('span', '', formatDate(exception.date)), button('Modifier', 'planning-text-button', () => openException(exception.date))); exceptions.append(card); }
    if (!exceptions.children.length) exceptions.append(el('p', 'planning-muted', 'Aucune exception.'));
  }
  const trainerName = trainer => trainer.name || trainer.trainer_name || [trainer.prenom, trainer.nom].filter(Boolean).join(' ');
  function openSubject(subject = null) {
    if (!state.data || state.loading) return; state.subjectEdit = subject; const form = $('planning-subject-form'); form.reset();
    form.elements.name.value = subject?.name || ''; form.elements.planned_hours.value = subject?.planned_hours ?? ''; form.elements.color.value = safeColor(subject?.color);
    if (!form.elements.color.value) { form.elements.color.add(new Option('Couleur actuelle', safeColor(subject?.color))); form.elements.color.value = safeColor(subject?.color); }
    populate(form.elements.trainer_id, state.data.trainers || [], trainerName, 'Choisir un formateur', subject?.trainer_id);
    $('planning-subject-delete').hidden = !subject; openDialog('planning-subject-dialog', form.elements.name);
    if (!state.data.trainers?.length) formError(form, 'Aucun formateur n’est affecté à cette promotion. Ajoutez une affectation depuis la page Formateurs.');
  }
  $('planning-subject-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget; const data = {promotion_id: promotionId(), name: form.elements.name.value.trim(), trainer_id: form.elements.trainer_id.value, color: form.elements.color.value, planned_hours: form.elements.planned_hours.value === '' ? null : Number(form.elements.planned_hours.value)};
    saveForm(form, () => request('/subjects' + (state.subjectEdit ? '/' + encodeURIComponent(state.subjectEdit.id) : ''), {method: state.subjectEdit ? 'PUT' : 'POST', data}), 'Matière enregistrée.');
  });
  function dateLimits(form) { const promotion = state.data.promotion; for (const input of form.querySelectorAll('input[type=date]')) { input.min = promotion.date_debut || ''; input.max = promotion.date_fin || ''; } }
  function setWeekdays(form, values) { form.querySelectorAll('input[name=weekdays]').forEach(input => { input.checked = values.includes(Number(input.value)); }); }
  const selectedWeekdays = form => [...form.querySelectorAll('input[name=weekdays]:checked')].map(input => Number(input.value));
  function openPeriod(rule = null) {
    if (!state.data || state.loading) return; state.ruleEdit = rule; const form = $('planning-period-form'); form.reset(); dateLimits(form);
    form.elements.kind.value = rule?.kind || 'school'; form.elements.label.value = rule?.label || ''; form.elements.start_date.value = rule?.start_date || state.data.promotion.date_debut || state.week; form.elements.end_date.value = rule?.end_date || state.data.promotion.date_fin || addDays(state.week, 6); setWeekdays(form, rule?.weekdays || [0, 1, 2, 3, 4]); $('planning-period-delete').hidden = !rule; openDialog('planning-period-dialog', form.elements.kind);
  }
  $('planning-period-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget; const weekdays = selectedWeekdays(form);
    if (!weekdays.length) { formError(form, 'Sélectionnez au moins un jour de la semaine.'); return; }
    if (form.elements.start_date.value > form.elements.end_date.value) { formError(form, 'La date de fin doit suivre la date de début.'); return; }
    const data = {promotion_id: promotionId(), start_date: form.elements.start_date.value, end_date: form.elements.end_date.value, weekdays, kind: form.elements.kind.value, label: form.elements.label.value.trim()};
    saveForm(form, () => request('/calendar/rules' + (state.ruleEdit ? '/' + encodeURIComponent(state.ruleEdit.id) : ''), {method: state.ruleEdit ? 'PUT' : 'POST', data}), 'Période enregistrée.');
  });
  function openException(date = state.week) {
    if (!state.data || state.loading) return; const exception = (state.data.exceptions || []).find(item => item.date === date), info = (state.year?.days || state.data.days || []).find(item => item.date === date); state.exceptionEdit = exception || null;
    const form = $('planning-exception-form'); form.reset(); dateLimits(form); form.elements.date.value = date; form.elements.date.readOnly = !!exception; form.elements.kind.value = exception?.kind || (info?.kind !== 'unconfigured' ? info?.kind : 'school') || 'school'; form.elements.label.value = exception?.label || ''; $('planning-exception-delete').hidden = !exception; openDialog('planning-exception-dialog', form.elements.kind);
  }
  $('planning-exception-form').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; const data = {promotion_id: promotionId(), date: form.elements.date.value, kind: form.elements.kind.value, label: form.elements.label.value.trim()}; saveForm(form, () => request('/calendar/exceptions', {method: 'PUT', data}), 'Exception enregistrée.'); });
  function openCourse(course = null, overrides = {}) {
    if (state.loading || !state.data) return;
    if (!state.data?.subjects?.length) { notice('Préparez une matière avant de créer un cours.'); openSubject(); return; }
    state.courseEdit = course; const form = $('planning-course-form'); form.reset(); dateLimits(form);
    const values = {...(course || {}), ...overrides}; const subjectId = values.subject_id || state.subject || '';
    populate(form.elements.subject_id, state.data.subjects, item => item.name, 'Choisir une matière', subjectId);
    const subject = state.data.subjects.find(item => String(item.id) === String(subjectId));
    populate(form.elements.trainer_id, state.data.trainers || [], trainerName, 'Choisir un formateur', values.trainer_id || subject?.trainer_id);
    populate(form.elements.room_id, state.data.rooms || [], item => item.name + (item.active === false || item.active === 0 ? ' · Inactive' : ''), 'Sans salle attribuée', Object.prototype.hasOwnProperty.call(values, 'room_id') ? (values.room_id || '') : $('planning-room').value);
    form.elements.date.value = values.date || state.week; form.elements.start.value = values.start || '09:00'; form.elements.end_at_midnight.checked = values.end === '24:00'; form.elements.end.value = values.end === '24:00' ? '23:59' : values.end || '11:00'; form.elements.end.disabled = form.elements.end_at_midnight.checked; form.elements.end.required = !form.elements.end_at_midnight.checked; form.elements.title.value = values.title || '';
    $('planning-course-delete').hidden = !course; $('planning-course-repeat').hidden = !course; $('planning-course-repeat').disabled = false; openDialog('planning-course-dialog', form.elements.subject_id);
  }
  $('planning-course-form').addEventListener('input', () => { $('planning-course-repeat').disabled = true; $('planning-course-repeat').title = 'Enregistrez les modifications du cours avant de le répéter.'; });
  $('planning-course-form').elements.subject_id.addEventListener('change', event => { const subject = state.data.subjects.find(item => String(item.id) === event.target.value); if (subject) $('planning-course-form').elements.trainer_id.value = subject.trainer_id; });
  $('planning-course-form').elements.end_at_midnight.addEventListener('change', event => { const input = $('planning-course-form').elements.end; input.disabled = event.target.checked; input.required = !event.target.checked; });
  const courseValues = form => ({promotion_id: promotionId(), subject_id: form.elements.subject_id.value, trainer_id: form.elements.trainer_id.value, room_id: form.elements.room_id.value || null, date: form.elements.date.value, start: form.elements.start.value, end: form.elements.end_at_midnight.checked ? '24:00' : form.elements.end.value, title: form.elements.title.value.trim()});
  $('planning-course-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget; const data = courseValues(form); if (state.courseEdit) data.version = state.courseEdit.version;
    if (data.start >= data.end) { formError(form, 'L’heure de fin doit suivre l’heure de début.'); return; }
    saveForm(form, () => request('/courses' + (state.courseEdit ? '/' + encodeURIComponent(state.courseEdit.id) : ''), {method: state.courseEdit ? 'PUT' : 'POST', data}), state.courseEdit ? 'Cours mis à jour.' : 'Cours ajouté au planning.');
  });
  function confirmAction(text, action, success, closeDialog = null, after = null) {
    $('planning-confirm-text').textContent = text; const dialog = $('planning-confirm-dialog'); openDialog('planning-confirm-dialog', $('planning-confirm-action'));
    $('planning-confirm-action').onclick = async () => {
      if (dialog.dataset.busy) return; busyDialog(dialog, true); const error = dialog.querySelector('.planning-form-error'); error.hidden = true;
      try { await action(); dialog.close(); if (closeDialog) $(closeDialog).close(); notice(success); await loadState(); if (after) after(); }
      catch (failure) { error.textContent = failure.message; error.hidden = false; }
      finally { busyDialog(dialog, false); }
    };
  }
  $('planning-subject-delete').addEventListener('click', () => { if (state.subjectEdit) confirmAction('Supprimer la matière « ' + state.subjectEdit.name + ' » ? Une matière déjà utilisée dans un cours ne peut pas être supprimée.', () => request('/subjects/' + encodeURIComponent(state.subjectEdit.id), {method: 'DELETE'}), 'Matière supprimée.', 'planning-subject-dialog'); });
  $('planning-period-delete').addEventListener('click', () => { if (state.ruleEdit) confirmAction('Supprimer cette période ? Les jours concernés retrouveront le rythme des autres règles, ou deviendront non définis. Les cours existants seront vérifiés avant toute modification.', () => request('/calendar/rules/' + encodeURIComponent(state.ruleEdit.id), {method: 'DELETE'}), 'Période supprimée.', 'planning-period-dialog'); });
  $('planning-exception-delete').addEventListener('click', () => { if (state.exceptionEdit) confirmAction('Retirer cette exception ? La journée retrouvera le rythme habituel de la promotion.', () => request('/calendar/exceptions/' + encodeURIComponent(promotionId()) + '/' + encodeURIComponent(state.exceptionEdit.date), {method: 'DELETE'}), 'Exception retirée.', 'planning-exception-dialog'); });
  $('planning-course-delete').addEventListener('click', () => { if (state.courseEdit) confirmAction('Supprimer le cours « ' + courseName(state.courseEdit) + ' » du ' + formatDate(state.courseEdit.date) + ' à ' + state.courseEdit.start + ' ? Cette suppression concerne uniquement ce créneau.', () => request('/courses/' + encodeURIComponent(state.courseEdit.id), {method: 'DELETE', data: {version: state.courseEdit.version}}), 'Cours supprimé.', 'planning-course-dialog'); });
  function openBatch(course = null) {
    if (!state.data || state.loading) return; if (!course && !state.data.courses?.length) { notice('Cette semaine ne contient aucun cours à dupliquer.'); return; }
    state.batch = {mode: course ? 'repeat' : 'duplicate', course, preview: null}; const form = $('planning-batch-form'); form.reset(); dateLimits(form);
    $('planning-batch-repeat-fields').hidden = !course; $('planning-batch-duplicate-fields').hidden = !!course;
    $('planning-batch-repeat-fields').querySelectorAll('input,select').forEach(input => { input.disabled = !course; }); $('planning-batch-duplicate-fields').querySelectorAll('input,select').forEach(input => { input.disabled = !!course; });
    form.elements.start_date.required = form.elements.end_date.required = !!course; form.elements.target_start.required = !course;
    form.elements.start_date.value = course ? addDays(course.date, 7) : state.week; form.elements.end_date.value = state.data.promotion.date_fin || addDays(state.week, 35); form.elements.target_start.value = addDays(state.week, 7);
    setWeekdays(form, course ? [(parseDate(course.date).getDay() + 6) % 7] : []);
    $('planning-batch-source').textContent = course ? courseName(course) + ' · ' + course.start + ' – ' + course.end + ' · ' + (course.trainer_name || 'Formateur affecté') : 'Dupliquer tous les cours du ' + formatDate(state.week) + ' au ' + formatDate(addDays(state.week, 6)) + '. Le décalage conserve les jours et les horaires.';
    $('planning-batch-results').hidden = true; $('planning-batch-commit').disabled = true; $('planning-batch-skip').checked = false;
    openDialog('planning-batch-dialog', course ? form.elements.start_date : form.elements.target_start);
  }
  function invalidateBatch() { if (state.batch) state.batch.preview = null; $('planning-batch-results').hidden = true; $('planning-batch-commit').disabled = true; $('planning-batch-skip').checked = false; }
  $('planning-batch-form').addEventListener('input', event => { if (!event.target.closest('#planning-batch-results')) invalidateBatch(); });
  $('planning-batch-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, dialog = form.closest('dialog'); if (dialog.dataset.busy || !form.reportValidity() || !state.batch) return; formError(form, '');
    const data = {promotion_id: promotionId(), mode: state.batch.mode};
    if (state.batch.mode === 'repeat') {
      const course = state.batch.course; Object.assign(data, {start_date: form.elements.start_date.value, end_date: form.elements.end_date.value, weekdays: selectedWeekdays(form), interval_weeks: Number(form.elements.interval_weeks.value), template: {subject_id: course.subject_id, trainer_id: course.trainer_id, room_id: course.room_id || null, start: course.start, end: course.end, title: course.title || ''}});
      if (!data.weekdays.length) { formError(form, 'Sélectionnez au moins un jour à répéter.'); return; }
    } else Object.assign(data, {source_start: state.week, source_end: addDays(state.week, 6), target_start: form.elements.target_start.value});
    busyDialog(dialog, true); invalidateBatch();
    try {
      const preview = await request('/courses/preview', {method: 'POST', data}); state.batch.preview = preview; renderBatchPreview(preview);
    } catch (failure) { formError(form, failure.message); }
    finally { busyDialog(dialog, false); updateBatchCommit(); }
  });
  function renderBatchPreview(preview) {
    const container = $('planning-batch-items'); container.replaceChildren(); let conflicts = 0;
    for (const item of preview.items || []) {
      const course = item.course, label = el('label', 'planning-batch-item' + (!item.valid ? ' has-conflict' : '')); const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.value = String(item.key); checkbox.checked = !!item.valid; checkbox.disabled = !item.valid; checkbox.addEventListener('change', updateBatchCommit);
      const detail = el('span'); detail.append(el('b', '', formatDate(course.date, {weekday: 'short', day: 'numeric', month: 'short', year: 'numeric'}) + ' · ' + course.start + ' – ' + course.end), el('small', '', item.valid ? courseName(course) + ' · Disponible' : (item.conflicts || []).map(conflict => conflict.message).join(' · ')));
      if (!item.valid) conflicts++; label.append(checkbox, detail); container.append(label);
    }
    $('planning-batch-summary').textContent = (preview.items || []).length + ' occurrence(s) vérifiée(s) · ' + conflicts + ' en conflit'; $('planning-batch-conflict-consent').hidden = conflicts === 0; $('planning-batch-skip').checked = false; $('planning-batch-results').hidden = false; updateBatchCommit();
  }
  function updateBatchCommit() {
    const preview = state.batch?.preview; const selected = $('planning-batch-items').querySelectorAll('input:checked:not(:disabled)').length; const conflicts = preview?.items?.some(item => !item.valid);
    $('planning-batch-commit').disabled = !preview || selected === 0 || (!!conflicts && !$('planning-batch-skip').checked); $('planning-batch-commit').textContent = 'Créer ' + selected + ' occurrence' + (selected !== 1 ? 's' : '') + ' sélectionnée' + (selected !== 1 ? 's' : '');
  }
  $('planning-batch-skip').addEventListener('change', updateBatchCommit);
  $('planning-batch-commit').addEventListener('click', async () => {
    const preview = state.batch?.preview, dialog = $('planning-batch-dialog'), form = $('planning-batch-form'); if (!preview || dialog.dataset.busy || $('planning-batch-commit').disabled) return;
    const selected_keys = [...$('planning-batch-items').querySelectorAll('input:checked:not(:disabled)')].map(input => input.value); busyDialog(dialog, true); formError(form, '');
    try { const result = await request('/courses/batch', {method: 'POST', data: {preview_token: preview.preview_token, selected_keys}}); dialog.close(); if ($('planning-course-dialog').open) $('planning-course-dialog').close(); notice(result.message || 'Les occurrences sélectionnées ont été créées.'); await loadState(); }
    catch (failure) { formError(form, failure.message + '\nVérifiez à nouveau les créneaux avant de réessayer.'); invalidateBatch(); }
    finally { busyDialog(dialog, false); updateBatchCommit(); }
  });
  function renderRooms() {
    const list = $('planning-rooms-list'); list.replaceChildren();
    for (const room of state.data.rooms || []) {
      const row = el('div', 'planning-room-row'); row.append(el('b', '', room.name + (room.active === false || room.active === 0 ? ' · Inactive' : ''))); const actions = el('div'); actions.append(button('Modifier', 'planning-text-button', () => { state.roomEdit = room; $('planning-room-form').elements.name.value = room.name; $('planning-room-save').textContent = 'Enregistrer'; $('planning-room-cancel').hidden = false; $('planning-room-form').elements.name.focus(); }), button('Supprimer', 'planning-text-button danger', () => confirmAction('Supprimer la salle « ' + room.name + ' » ? Une salle utilisée dans des cours ne peut pas être supprimée.', () => request('/rooms/' + encodeURIComponent(room.id), {method: 'DELETE'}), 'Salle supprimée.', null, renderRooms))); row.append(actions); list.append(row);
    } if (!list.children.length) list.append(el('p', 'planning-muted', 'Aucune salle pour le moment.'));
  }
  function resetRoom() { state.roomEdit = null; $('planning-room-form').reset(); $('planning-room-save').textContent = 'Ajouter la salle'; $('planning-room-cancel').hidden = true; formError($('planning-room-form'), ''); }
  $('planning-room-cancel').addEventListener('click', resetRoom);
  $('planning-room-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, dialog = form.closest('dialog'); if (dialog.dataset.busy || !form.reportValidity()) return; const room = state.roomEdit, data = {name: form.elements.name.value.trim(), active: room ? room.active : true}; formError(form, ''); busyDialog(dialog, true);
    try { await request('/rooms' + (room ? '/' + encodeURIComponent(room.id) : ''), {method: room ? 'PUT' : 'POST', data}); await loadState(); resetRoom(); renderRooms(); notice('Salle enregistrée.'); } catch (failure) { formError(form, failure.message); } finally { busyDialog(dialog, false); }
  });
  $('planning-promotion').addEventListener('change', () => { notice(''); state.subject = ''; state.availability.clear(); state.availabilityReady = false; state.week = monday(today()); const url = new URL(location.href); if (promotionId()) url.searchParams.set('promotion_id', promotionId()); else url.searchParams.delete('promotion_id'); url.searchParams.delete('promotion'); history.replaceState(null, '', url); loadState({initial: true}); });
  $('planning-view-week').addEventListener('click', () => selectView('week')); $('planning-view-year').addEventListener('click', () => selectView('year'));
  $('planning-step-calendar').addEventListener('click', () => { selectView('year'); if (!state.data?.rules?.length) openPeriod(); }); $('planning-step-subjects').addEventListener('click', () => { selectView('week'); openSubject(); }); $('planning-step-courses').addEventListener('click', () => { selectView('week'); openCourse(); });
  $('planning-prev').addEventListener('click', () => { state.week = addDays(state.week, -7); selectView('week'); loadState(); }); $('planning-next').addEventListener('click', () => { state.week = addDays(state.week, 7); selectView('week'); loadState(); }); $('planning-today').addEventListener('click', () => { state.week = monday(today()); selectView('week'); loadState(); }); $('planning-date').addEventListener('change', event => { if (event.target.value) { state.week = monday(event.target.value); selectView('week'); loadState(); } });
  $('planning-subject-search').addEventListener('input', renderSubjects); $('planning-subject-new').addEventListener('click', () => openSubject()); $('planning-duration').addEventListener('change', loadAvailability); $('planning-room').addEventListener('change', loadAvailability); $('planning-selection-clear').addEventListener('click', () => { state.subject = ''; state.availabilitySeq++; state.availability.clear(); state.availabilityReady = false; renderSubjects(); renderAvailability(); });
  $('planning-period-new').addEventListener('click', () => openPeriod()); $('planning-exception-open').addEventListener('click', () => openException()); $('planning-course-new').addEventListener('click', () => openCourse()); $('planning-duplicate-week').addEventListener('click', () => openBatch()); $('planning-course-repeat').addEventListener('click', () => { if (state.courseEdit) openBatch(state.courseEdit); });
  $('planning-rooms-open').addEventListener('click', () => { if (!state.data || state.loading) return; resetRoom(); renderRooms(); openDialog('planning-rooms-dialog', $('planning-room-form').elements.name); });
  $('planning-export-open').addEventListener('click', () => { if (!promotionId()) return; const form = $('planning-export-form'); form.elements.view.value = state.view === 'year' ? 'annual' : 'weekly'; form.elements.start.value = state.view === 'year' ? state.data.promotion.date_debut || state.week : state.week; form.elements.end.value = state.view === 'year' ? state.data.promotion.date_fin || addDays(state.week, 6) : addDays(state.week, 6); openDialog('planning-export-dialog', form.elements.start); });
  $('planning-export-form').elements.view.addEventListener('change', event => { const form = $('planning-export-form'), annual = event.target.value === 'annual'; form.elements.start.value = annual ? state.data.promotion.date_debut || state.week : state.week; form.elements.end.value = annual ? state.data.promotion.date_fin || addDays(state.week, 6) : addDays(state.week, 6); });
  $('planning-export-form').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; if (!form.reportValidity()) return; if (form.elements.start.value > form.elements.end.value) { formError(form, 'La date de fin doit suivre la date de début.'); return; } const query = new URLSearchParams({promotion_id: promotionId(), start: form.elements.start.value, end: form.elements.end.value, view: form.elements.view.value}); window.open('/admin/planning/export.pdf?' + query, '_blank', 'noopener'); });
  loadState({initial: true});
})();

/* Academy planning: explicit saves, server-checked availability, no third-party calendar. */
(() => {
  'use strict';
  const app = document.querySelector('.planning-app');
  if (!app) return;
  const $ = id => document.getElementById(id), API = '/admin/planning/api';
  const kinds = {school: 'À l’école', company: 'En entreprise', holiday: 'Vacances', closed: 'Fermé', public_holiday: 'Jour férié', unconfigured: 'À définir'};
  const weekdays = ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'];
  const el = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = String(text); return node; };
  const button = (text, cls, action) => { const node = el('button', cls || 'planning-button', text); node.type = 'button'; if (action) node.addEventListener('click', action); return node; };
  const parseDate = value => new Date(String(value).slice(0, 10) + 'T12:00:00');
  const dateString = date => [date.getFullYear(), String(date.getMonth() + 1).padStart(2, '0'), String(date.getDate()).padStart(2, '0')].join('-');
  const addDays = (value, days) => { const date = parseDate(value); date.setDate(date.getDate() + days); return dateString(date); };
  const monday = value => { const date = parseDate(value); return addDays(value, -(date.getDay() + 6) % 7); };
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date());
  const formatDate = (value, options = {day: 'numeric', month: 'long'}) => parseDate(value).toLocaleDateString('fr-FR', options);
  const fullDate = value => formatDate(value, {day: 'numeric', month: 'long', year: 'numeric'}).replace(/^1 /, '1er ');
  const yearLabel = period => period ? 'Année ' + period.number + ' · Du ' + fullDate(period.start_date) + ' au ' + fullDate(period.end_date) : 'Dates à compléter';
  const minutes = value => { const [h, m] = String(value || '00:00').split(':').map(Number); return h * 60 + m; };
  const timeString = value => String(Math.floor(value / 60)).padStart(2, '0') + ':' + String(value % 60).padStart(2, '0');
  const minuteLabel = value => { const total = Math.max(0, Math.round(Number(value) || 0)), h = Math.floor(total / 60), m = total % 60; return h ? h + ' h' + (m ? ' ' + String(m).padStart(2, '0') : '') : m + ' min'; };
  const hours = value => minuteLabel(Number(value) * 60);
  const normal = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr');
  const courseDuration = course => Number(course.duration_minutes) || minutes(course.end) - minutes(course.start);
  const safeColor = value => /^#[0-9a-f]{6}$/i.test(value || '') ? value : '#66764e';
  const state = {data: null, year: null, week: monday(today()), view: 'week', subject: '', availability: new Map(), availabilityReady: false, availabilitySeq: 0, loadSeq: 0, dragCourse: null, gridStart: 420, gridEnd: 1260, subjectEdit: null, ruleEdit: null, exceptionEdit: null, courseEdit: null, roomEdit: null, batch: null, busy: false, loading: false, slot: null, slotAnchor: null, slotGesture: null, slotChecks: new Map(), slotCheckSeq: 0, quickBusy: false, quickShared: [], courseShared: [], paintKind: 'school', paintDraft: new Map(), paintRevision: null, paintStale: false, paintBusy: false, paintAnchor: null, paintGesture: null, paintSkipped: 0};
  const promotionId = () => $('planning-promotion').value;
  const currentSubject = () => state.data?.subjects?.find(subject => String(subject.id) === state.subject);
  function notice(text, failure = false) { const node = $('planning-notice'); node.textContent = text || ''; node.hidden = !text; node.classList.toggle('error', failure); }
  function formError(form, message) { const node = form.querySelector('.planning-form-error'); if (node) { node.textContent = message || ''; node.hidden = !message; } }
  function failureText(result) { return [result.message || result.error || '', ...(result.conflicts || []).map(conflict => (conflict.date ? formatDate(conflict.date) + ' : ' : '') + conflict.message)].filter(Boolean).join('\n') || 'L’action n’a pas abouti. Rechargez la page puis réessayez.'; }
  async function request(path, {method = 'GET', data, signal} = {}) {
    const response = await fetch(path.startsWith('/admin/') ? path : API + path, {method, signal, credentials: 'same-origin', headers: {Accept: 'application/json', ...(state.periodId ? {'X-Planning-Period': state.periodId, 'X-Planning-Promotion': promotionId()} : {}), ...(method !== 'GET' ? {'Content-Type': 'application/json', 'X-CSRF-Token': app.dataset.csrf} : {})}, ...(method !== 'GET' ? {body: JSON.stringify(data || {})} : {})});
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
  function setPlanningFullscreen(enabled) {
    state.fullscreen = !!enabled; document.body.classList.toggle('planning-is-fullscreen', state.fullscreen);
    $('planning-fullscreen').setAttribute('aria-pressed', String(state.fullscreen));
    $('planning-fullscreen-label').textContent = state.fullscreen ? 'Quitter le plein écran' : 'Plein écran';
    $('planning-fullscreen').title = state.fullscreen ? 'Quitter le plein écran (Échap)' : 'Agrandir le planning sur tout l’écran';
    if (!state.fullscreen) { state.nativeFullscreen = false; $('planning-fullscreen').focus({preventScroll: true}); }
  }
  async function togglePlanningFullscreen() {
    if (state.fullscreen) {
      setPlanningFullscreen(false);
      if (document.fullscreenElement) { try { await document.exitFullscreen(); } catch (_) { /* The in-page mode has already closed. */ } }
      return;
    }
    setPlanningFullscreen(true);
    if (!document.fullscreenElement && document.documentElement.requestFullscreen) {
      try { await document.documentElement.requestFullscreen(); state.nativeFullscreen = true; }
      catch (_) { /* In-page fullscreen is retained where the browser disallows its native API. */ }
    }
    $('planning-fullscreen').focus({preventScroll: true});
  }
  $('planning-fullscreen').addEventListener('click', togglePlanningFullscreen);
  document.addEventListener('fullscreenchange', () => { if (state.nativeFullscreen && !document.fullscreenElement) setPlanningFullscreen(false); });
  document.addEventListener('keydown', event => { if (event.key === 'Escape' && state.fullscreen && !document.querySelector('dialog[open]')) { event.preventDefault(); togglePlanningFullscreen(); } });
  function populate(select, items, label, blank = null, selected = '') {
    select.replaceChildren(); if (blank !== null) select.add(new Option(blank, ''));
    for (const item of items || []) select.add(new Option(label(item), String(item.id)));
    select.value = String(selected || '');
  }
  const isPublicHoliday = day => day?.kind === 'public_holiday' || day?.public_holiday === true;
  const knownDay = date => (state.year?.days || []).find(day => day.date === date) || (state.data?.days || []).find(day => day.date === date);
  function courseWarnings(course) {
    const warnings = [...(course.warning_labels || []), ...(course.warnings || []).map(item => typeof item === 'string' ? item : item.message)].filter(Boolean);
    if (!course.room_id && !warnings.some(text => /salle/i.test(text))) warnings.push('Salle à affecter.');
    return [...new Set(warnings)];
  }
  function courseName(course) { return course.title || course.display_subject_name || course.subject_name || state.data?.subjects?.find(subject => String(subject.id) === String(course.subject_id))?.name || 'Cours'; }
  async function loadState({initial = false, fromSync = false} = {}) {
    const id = promotionId(); const seq = ++state.loadSeq; state.loading = true; state.slotCheckSeq++; state.availabilitySeq++; state.availabilityReady = false; state.availability.clear();
    $('planning-selected').hidden = !id; $('planning-unselected').hidden = !!id; $('planning-export-open').disabled = !id;
    if (!id) { state.data = null; state.loading = false; app.setAttribute('aria-busy', 'false'); return true; }
    app.setAttribute('aria-busy', 'true'); $('planning-save-state').textContent = 'Chargement du planning…';
    try {
      const result = await request('/state?' + new URLSearchParams({promotion_id: id, start: state.week, end: addDays(state.week, 6)}));
      if (seq !== state.loadSeq || id !== promotionId()) return false;
      // Recheck after every background fetch: editing can begin while the request is in flight.
      if (fromSync && !planningSyncSafe({ignoreLoading: true})) return false;
      let syncedYear = null;
      if (fromSync && state.view === 'year') {
        const annual = result.promotion;
        syncedYear = await request('/state?' + new URLSearchParams({promotion_id: id, start: annual.date_debut || state.week.slice(0, 4) + '-01-01', end: annual.date_fin || state.week.slice(0, 4) + '-12-31'}));
        if (seq !== state.loadSeq || id !== promotionId() || !planningSyncSafe({ignoreLoading: true})) return false;
      }
      state.data = result; state.year = syncedYear; state.periodId = result.period?.id || '';
      const promotion = result.promotion;
      if (promotion.date_debut && promotion.date_fin && (addDays(state.week, 6) < promotion.date_debut || state.week > promotion.date_fin)) { state.week = monday(promotion.date_debut); return loadState(); }
      if (!(result.subjects || []).some(subject => String(subject.id) === state.subject)) state.subject = '';
      renderPromotion(); renderSharedRows($('planning-quick-shared'), state.quickShared, promotionId(), onQuickSharedChange); renderSubjects(); renderCalendar(); renderRules(); renderSlotSelection();
      if (state.view === 'year') await renderYear();
      if (state.subject) await loadAvailability(); if (state.slot) await checkSelectedSlot();
      return true;
    } catch (failure) { if (seq === state.loadSeq) { if (!fromSync) { state.data = null; $('planning-selected').hidden = true; } notice(failure.message, true); } return false; }
    finally { if (seq === state.loadSeq) { state.loading = false; app.setAttribute('aria-busy', 'false'); $('planning-save-state').textContent = 'Chaque action est enregistrée'; openRequestedSubject(); } }
  }
  function planningSyncSafe({ignoreLoading = false} = {}) {
    return (ignoreLoading || !state.loading) && !state.busy && !state.quickBusy && !state.paintBusy && !state.paintDraft.size && !state.slotFormDirty && !document.activeElement?.closest('#planning-slot-form') && !state.slotGesture && !state.paintGesture && !state.dragCourse && !document.querySelector('dialog[open]');
  }
  async function refreshChangedPlanning() {
    clearTimeout(state.syncTimer); if (!state.syncPending) return;
    if (!planningSyncSafe()) { state.syncTimer = setTimeout(refreshChangedPlanning, 2000); return; }
    const version = state.syncVersion || 0, applied = await loadState({fromSync: true});
    if (applied && version === (state.syncVersion || 0)) { state.syncPending = false; $('planning-sync-notice').hidden = true; }
    else { state.syncPending = true; state.syncTimer = setTimeout(refreshChangedPlanning, state.data ? 2000 : 10000); }
  }
  window.addEventListener('academy:planning-changed', event => {
    event.preventDefault(); state.syncVersion = (state.syncVersion || 0) + 1; state.syncPending = true; $('planning-sync-notice').hidden = false; refreshChangedPlanning();
  });
  $('planning-sync-refresh').addEventListener('click', () => {
    if (!planningSyncSafe()) { notice('Terminez ou annulez l’action en cours avant d’actualiser. Vos modifications ne seront pas perdues.'); return; }
    state.syncPending = true; refreshChangedPlanning();
  });
  function renderPromotion() {
    const {subjects = [], courses = []} = state.data, promotion = state.data.cohort || state.data.promotion;
    const details = $('planning-promotion-details'); details.replaceChildren(el('b', '', promotion.nom), el('span', '', 'BTS ' + promotion.bts + ' · ' + (promotion.niveau ? (Number(promotion.niveau) === 1 ? '1re année' : '2e année') : 'Niveau à compléter') + (promotion.date_debut && promotion.date_fin ? ' · Du ' + fullDate(promotion.date_debut) + ' au ' + fullDate(promotion.date_fin) : ' · Dates à compléter dans Promotions')));
    populate($('planning-school-year'), state.data.periods || [], yearLabel, null, state.periodId);
    $('planning-school-year').disabled = !(state.data.periods || []).length;
    $('planning-delete-open').disabled = !state.periodId;
    $('planning-prev').disabled = state.week <= monday(state.data.promotion.date_debut || state.week);
    $('planning-next').disabled = addDays(state.week, 7) > (state.data.promotion.date_fin || state.week);
    $('planning-today').disabled = today() < state.data.promotion.date_debut || today() > state.data.promotion.date_fin;
    const outside = state.data.outside_courses || []; $('planning-outside').hidden = !outside.length;
    $('planning-outside-summary').textContent = outside.length + ' cours existant(s) hors des périodes annuelles';
    $('planning-outside-courses').replaceChildren(...outside.map(course => button(fullDate(course.date) + ' · ' + courseName(course), 'planning-text-button', () => openCourse(course))));
    $('planning-calendar-progress').textContent = state.data.calendar_configured ? 'En place' : 'À préparer';
    $('planning-subject-progress').textContent = subjects.length ? subjects.length + ' matière' + (subjects.length > 1 ? 's' : '') : 'À préparer';
    $('planning-course-progress').textContent = courses.length ? courses.length + ' cours cette semaine' : 'À composer';
    const room = $('planning-room'), selected = room.value; populate(room, (state.data.rooms || []).filter(item => item.active !== false && item.active !== 0), item => item.name, 'Sans salle attribuée', selected);
    $('planning-range-title').textContent = formatDate(state.week, {day: 'numeric', month: 'short'}) + ' — ' + formatDate(addDays(state.week, 6), {day: 'numeric', month: 'short', year: 'numeric'});
    $('planning-week-hours').textContent = hours(courses.reduce((sum, course) => sum + courseDuration(course), 0) / 60) + ' planifiées · ' + courses.length + ' cours';
    window.dispatchEvent(new CustomEvent('academy:planning-state', {detail: state.data}));
    $('planning-date').value = state.week;
    $('planning-date-label').textContent = formatDate(state.week, {day: '2-digit', month: '2-digit', year: 'numeric'});
  }
  function scheduledDates() {
    const dates = new Map();
    for (const day of state.data?.scheduled_days || []) {
      if (!state.subject || String(day.subject_id) === state.subject) dates.set(day.date, (dates.get(day.date) || 0) + Number(day.count));
    }
    return dates;
  }
  function shiftPickerMonth(delta) {
    const date = parseDate(state.dateMonth); date.setMonth(date.getMonth() + delta);
    const target = dateString(date).slice(0, 7) + '-01';
    if (target.slice(0, 7) < state.data.promotion.date_debut?.slice(0, 7) || target.slice(0, 7) > state.data.promotion.date_fin?.slice(0, 7)) return;
    state.dateMonth = target; renderDatePicker();
  }
  function pickPlanningDate(date) {
    $('planning-date-dialog').close(); goToWeek(date);
  }
  function renderDatePicker(focusDate) {
    const month = parseDate(state.dateMonth), year = month.getFullYear(), monthNumber = month.getMonth();
    const dates = scheduledDates(), ordered = [...dates.keys()].sort();
    $('planning-date-subject').textContent = currentSubject()?.name || 'Toutes les matières de la promotion';
    $('planning-month').replaceChildren(...Array.from({length: 12}, (_, index) => new Option(new Date(2026, index, 1).toLocaleDateString('fr-FR', {month: 'long'}), String(index))));
    $('planning-month').value = String(monthNumber);
    const years = [year, Number(state.week.slice(0, 4)), Number(today().slice(0, 4)), ...ordered.map(date => Number(date.slice(0, 4))), ...[state.data.promotion.date_debut, state.data.promotion.date_fin].filter(Boolean).map(date => Number(date.slice(0, 4)))];
    const firstYear = Number(state.data.promotion.date_debut?.slice(0, 4)) || Math.min(...years), lastYear = Number(state.data.promotion.date_fin?.slice(0, 4)) || Math.max(...years);
    $('planning-month-year').replaceChildren(...Array.from({length: lastYear - firstYear + 1}, (_, index) => new Option(String(firstYear + index), String(firstYear + index))));
    $('planning-month-year').value = String(year);
    const grid = $('planning-mini-days'); grid.replaceChildren();
    grid.setAttribute('aria-label', month.toLocaleDateString('fr-FR', {month: 'long', year: 'numeric'}));
    for (let i = 0; i < (month.getDay() + 6) % 7; i++) grid.append(el('span'));
    const lastDay = new Date(year, monthNumber + 1, 0).getDate();
    let monthCount = 0;
    for (let day = 1; day <= lastDay; day++) {
      const date = dateString(new Date(year, monthNumber, day, 12)), count = dates.get(date) || 0;
      monthCount += count;
      const control = button(String(day), 'planning-mini-day' + (count ? ' has-course' : '') + (date >= state.week && date <= addDays(state.week, 6) ? ' in-week' : ''), () => pickPlanningDate(date));
      control.dataset.date = date;
      control.disabled = date < state.data.promotion.date_debut || date > state.data.promotion.date_fin;
      const label = formatDate(date, {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'}) + (count ? ' · ' + count + ' cours programmé' + (count > 1 ? 's' : '') : ' · Aucun cours programmé');
      control.setAttribute('aria-label', label); control.title = label;
      if (date === today()) control.setAttribute('aria-current', 'date');
      if (count) { const dot = el('i', 'planning-course-dot'); dot.setAttribute('aria-hidden', 'true'); control.append(dot); }
      grid.append(control);
    }
    const monthEnd = dateString(new Date(year, monthNumber, lastDay, 12));
    $('planning-month-prev').disabled = state.dateMonth.slice(0, 7) <= state.data.promotion.date_debut?.slice(0, 7);
    $('planning-month-next').disabled = state.dateMonth.slice(0, 7) >= state.data.promotion.date_fin?.slice(0, 7);
    const previous = ordered.filter(date => date < state.dateMonth).at(-1), next = ordered.find(date => date > monthEnd);
    for (const [id, date] of [['planning-course-prev', previous], ['planning-course-next', next]]) {
      const control = $(id); control.disabled = !date; control.dataset.date = date || '';
      control.title = date ? 'Ouvrir la semaine du ' + formatDate(date, {day: 'numeric', month: 'long', year: 'numeric'}) : 'Aucun autre cours';
    }
    $('planning-date-summary').textContent = monthCount ? monthCount + ' cours programmé' + (monthCount > 1 ? 's' : '') + ' ce mois-ci.' : ordered.length ? 'Aucun cours ce mois-ci. Utilisez les flèches ci-dessous pour en retrouver un.' : 'Aucun cours programmé' + (state.subject ? ' pour cette matière.' : ' dans cette promotion.');
    if (focusDate) grid.querySelector('[data-date="' + focusDate + '"]')?.focus();
  }
  function openDatePicker() {
    if (!state.data || state.loading) return;
    state.dateMonth = (state.week < state.data.promotion.date_debut ? state.data.promotion.date_debut : state.week).slice(0, 7) + '-01'; renderDatePicker();
    openDialog('planning-date-dialog', $('planning-mini-days').querySelector('[data-date="' + state.week + '"]') || $('planning-month'));
  }
  function subjectBudget(subject) {
    const configured = subject?.budget_configured !== false && subject?.planned_hours !== null && subject?.planned_hours !== undefined && Number(subject?.planned_minutes ?? Number(subject?.planned_hours) * 60) > 0;
    const annual = Math.round(Number(subject?.planned_minutes ?? Number(subject?.planned_hours) * 60) || 0);
    const scheduled = Math.round(Number(subject?.scheduled_minutes ?? Number(subject?.scheduled_hours) * 60) || 0);
    return {configured, annual, scheduled, remaining: Math.round(Number(subject?.remaining_minutes ?? annual - scheduled))};
  }
  function budgetProblem(subject, duration = 0) {
    const budget = subjectBudget(subject);
    if (!budget.configured) return 'Volume annuel à renseigner avant de programmer cette matière.';
    if (budget.remaining < 0) return 'Volume annuel dépassé de ' + minuteLabel(-budget.remaining) + '. Ajustez les cours ou le volume.';
    if (budget.remaining === 0) return 'Volume annuel entièrement planifié.';
    if (duration > budget.remaining) return 'Il reste ' + minuteLabel(budget.remaining) + ' ; ce créneau demande ' + minuteLabel(duration) + '.';
    return '';
  }
  const catalogSubjects = () => (state.data?.catalog?.subjects || state.data?.subjects || []).filter(subject => !subject.period_start || !state.data?.period || (subject.promotion_id === promotionId() ? subject.period_id === state.periodId : subject.period_start <= state.data.period.end_date && subject.period_end >= state.data.period.start_date));
  const catalogPromotions = () => (state.data?.catalog?.promotions || (state.data?.promotion ? [state.data.promotion] : [])).map(item => state.data?.period ? {...item, date_debut: item.date_debut > state.data.period.start_date ? item.date_debut : state.data.period.start_date, date_fin: item.date_fin < state.data.period.end_date ? item.date_fin : state.data.period.end_date} : item);
  function cleanShared(values, primary) {
    const used = new Set([String(primary)]);
    return values.map(item => {
      if (!item.promotion_id || !item.subject_id) throw Error('Choisissez une promotion et sa matière pour chaque promotion qui suit ce cours.');
      if (used.has(String(item.promotion_id))) throw Error('Une promotion ne peut apparaître qu’une fois dans le même cours.');
      used.add(String(item.promotion_id));
      const subject = catalogSubjects().find(subject => String(subject.id) === String(item.subject_id) && String(subject.promotion_id) === String(item.promotion_id));
      if (!subject) throw Error('La matière sélectionnée ne correspond pas à cette promotion.');
      return {promotion_id: String(item.promotion_id), subject_id: String(item.subject_id)};
    });
  }
  function renderSharedRows(container, values, primary, change) {
    container.replaceChildren();
    values.forEach((value, index) => {
      const row = el('div', 'planning-shared-row'), promotionLabel = el('label', '', 'Promotion'), subjectLabel = el('label', '', 'Matière à décompter');
      const promotion = el('select'), subject = el('select'); promotion.required = subject.required = true;
      populate(promotion, catalogPromotions().filter(item => String(item.id) !== String(primary) && item.active !== false && item.active !== 0), item => item.nom || item.name, 'Choisir une promotion', value.promotion_id);
      populate(subject, catalogSubjects().filter(item => String(item.promotion_id) === String(value.promotion_id)), item => item.name + (item.period_start ? ' · ' + item.period_start.slice(0, 4) + '–' + item.period_end.slice(0, 4) : ''), 'Choisir sa matière', value.subject_id);
      promotion.addEventListener('change', () => { values[index] = {promotion_id: promotion.value, subject_id: ''}; renderSharedRows(container, values, primary, change); change(); });
      subject.addEventListener('change', () => { value.subject_id = subject.value; change(); });
      promotionLabel.append(promotion); subjectLabel.append(subject); const remove = button('×', 'planning-shared-remove', () => { values.splice(index, 1); renderSharedRows(container, values, primary, change); change(); }); remove.setAttribute('aria-label', 'Retirer cette promotion du cours'); row.append(promotionLabel, subjectLabel, remove);
      const mapped = catalogSubjects().find(item => String(item.id) === String(value.subject_id));
      if (mapped) { const budget = subjectBudget(mapped); row.append(el('small', '', budget.configured ? minuteLabel(budget.remaining) + ' restantes sur ' + minuteLabel(budget.annual) : 'Volume annuel à compléter.')); }
      container.append(row);
    });
  }
  function onQuickSharedChange() {
    state.slotCheckSeq++; state.availabilitySeq++; state.availabilityReady = false;
    const error = $('planning-quick-shared-error'); error.hidden = true;
    try { cleanShared(state.quickShared, promotionId()); } catch (failure) { error.textContent = failure.message; error.hidden = false; }
    if (state.slot) checkSelectedSlot(); else if (state.subject) loadAvailability();
  }
  function renderSubjects() {
    const container = $('planning-subjects'); container.replaceChildren();
    const query = normal($('planning-subject-search').value), duration = state.slot ? minutes(state.slot.end) - minutes(state.slot.start) : 0;
    for (const subject of (state.data?.subjects || []).filter(item => normal(item.name + ' ' + (item.trainer_name || '')).includes(query))) {
      const budget = subjectBudget(subject), problem = budgetProblem(subject, duration), check = state.slotChecks.get(String(subject.id));
      const unavailable = state.slot && (!!problem || check?.status !== 'available');
      const card = el('article', 'planning-subject-card' + (budget.configured && budget.remaining <= 0 ? budget.remaining < 0 ? ' budget-exceeded' : ' budget-complete' : '') + (state.subject === String(subject.id) ? ' selected' : '') + (state.slot && check?.status === 'available' && !problem ? ' slot-available' : '') + (problem || check?.status === 'blocked' ? ' slot-unavailable' : '')); card.style.setProperty('--subject-color', safeColor(subject.color));
      const choose = button('', 'planning-subject-pick', () => chooseSubject(subject.id)); choose.draggable = !problem && !state.quickBusy; choose.disabled = !!unavailable || state.quickBusy; choose.setAttribute('aria-pressed', String(state.subject === String(subject.id))); choose.append(el('b', '', subject.name), el('span', '', subject.trainer_name || 'Formateur à définir'));
      const metrics = el('span', 'planning-subject-budget'); for (const [label, value] of [['Annuel', budget.configured ? minuteLabel(budget.annual) : 'À définir'], ['Planifié', minuteLabel(budget.scheduled)], [budget.remaining < 0 ? 'Dépassement' : 'Restant', budget.configured ? minuteLabel(Math.abs(budget.remaining)) : '—']]) { const metric = el('span'); metric.append(el('small', '', label), el('strong', '', value)); metrics.append(metric); } choose.append(metrics); if (budget.configured) { const progress = el('progress', 'planning-budget-progress'); progress.max = budget.annual; progress.value = budget.scheduled; progress.setAttribute('aria-label', 'Volume annuel utilisé'); choose.append(progress); }
      choose.addEventListener('dragstart', event => { state.dragCourse = null; chooseSubject(subject.id, true); event.dataTransfer.setData('text/plain', 'subject:' + subject.id); event.dataTransfer.effectAllowed = 'copy'; });
      const status = problem || (state.slot ? check?.status === 'available' ? 'Ajouter sur ce créneau' : check?.reason || 'Vérification des disponibilités…' : state.subject === String(subject.id) ? 'Ouvrez le calendrier pour retrouver ses cours, ou choisissez un créneau.' : 'Cliquez pour retrouver les cours de cette matière.'); card.append(choose, el('p', 'planning-subject-result', status));
      const edit = button(budget.configured ? 'Modifier' : 'Définir le volume annuel', 'planning-text-button', () => openSubject(subject)); edit.setAttribute('aria-label', 'Modifier la matière ' + subject.name);
      const dates = button('Voir les dates', 'planning-text-button', () => { if (state.loading || state.quickBusy) return; state.subject = String(subject.id); state.availabilityReady = false; state.availability.clear(); renderSubjects(); renderAvailability(); openDatePicker(); loadAvailability(); }); dates.setAttribute('aria-label', 'Voir les dates de ' + subject.name);
      const removeCourses = button('Supprimer des cours', 'planning-text-button', () => openDeletion(subject.id)); removeCourses.setAttribute('aria-label', 'Supprimer des cours de ' + subject.name); removeCourses.disabled = !budget.scheduled;
      const actions = el('div', 'planning-subject-actions'); actions.append(edit, dates, removeCourses); card.append(actions); container.append(card);
    }
    if (!container.children.length) container.append(el('p', 'planning-palette-empty', state.data?.subjects?.length ? 'Aucune matière pour cette recherche.' : 'Choisissez une matière du catalogue, son formateur et son volume annuel pour préparer ce planning.'));
    const prepared = new Set((state.data?.subjects || []).map(item => item.catalog_subject_id));
    const available = (state.data?.catalog?.subject_catalog || []).filter(item => item.diploma_codes.includes(state.data?.promotion?.bts) && !prepared.has(item.id));
    if (available.length) container.append(button('Préparer une matière du catalogue (' + available.length + ')', 'planning-button planning-full', () => openSubject()));
    $('planning-selection-clear').hidden = !state.subject;
  }
  async function chooseSubject(id, dragging = false) {
    if (state.loading || state.quickBusy || !state.data) return;
    if (state.slot && !dragging) { await createInSelectedSlot(String(id)); return; }
    state.subject = String(id); state.availabilityReady = false; state.availability.clear(); renderSubjects(); renderAvailability(); await loadAvailability();
  }
  function setSlot(date, start, end, check = true) {
    if (state.loading || state.quickBusy || !state.data || minutes(end) <= minutes(start)) return;
    const day = knownDay(date); if (isPublicHoliday(day)) { notice((day.label || 'Jour férié') + ' : aucun cours ne peut être planifié.', true); return; }
    if (!check && state.slot?.date === date && state.slot.start === start && state.slot.end === end) return;
    state.slot = {promotion_id: promotionId(), date, start, end}; state.subject = ''; state.availabilitySeq++; state.availabilityReady = false; state.slotCheckSeq++; state.slotChecks.clear(); renderSlotSelection(); renderAvailability(); renderSubjects();
    if (check) checkSelectedSlot();
  }
  function clearSlot() { state.slot = null; state.slotAnchor = null; state.slotGesture = null; state.slotChecks.clear(); state.slotCheckSeq++; renderSlotSelection(); renderSubjects(); renderAvailability(); }
  function renderSlotSelection() {
    const slot = state.slot, form = $('planning-slot-form'); state.slotFormDirty = false;
    if (state.data) dateLimits(form);
    if (slot) { form.elements.date.value = slot.date; form.elements.start.value = slot.start; form.elements.end.value = slot.end === '24:00' ? '23:59' : slot.end; }
    else { form.elements.date.value = state.week < state.data?.promotion.date_debut ? state.data.promotion.date_debut : state.week; form.elements.start.value = '08:00'; form.elements.end.value = '12:00'; }
    $('planning-slot-summary').textContent = slot ? formatDate(slot.date, {weekday: 'long', day: 'numeric', month: 'long'}) + ' · ' + slot.start + ' – ' + slot.end + ' · ' + minuteLabel(minutes(slot.end) - minutes(slot.start)) + ' sélectionnées. Cliquez sur une matière verte pour créer le cours.' : 'Glissez dans une journée pour sélectionner plusieurs heures, ou utilisez les champs ci-dessus.';
    $('planning-slot-clear').hidden = !slot;
    $('planning-calendar').querySelectorAll('.planning-slot').forEach(cell => { const selected = !!slot && cell.dataset.date === slot.date && minutes(cell.dataset.start) >= minutes(slot.start) && minutes(cell.dataset.start) < minutes(slot.end); cell.classList.toggle('is-time-selected', selected); cell.setAttribute('aria-pressed', String(selected)); });
  }
  async function checkSelectedSlot() {
    const slot = state.slot; const seq = ++state.slotCheckSeq; if (!slot || !state.data) return;
    let shared; try { shared = cleanShared(state.quickShared, promotionId()); } catch (failure) { state.slotChecks = new Map((state.data.subjects || []).map(subject => [String(subject.id), {status: 'blocked', reason: failure.message}])); renderSubjects(); return; }
    const room = $('planning-room').value, duration = minutes(slot.end) - minutes(slot.start), loadSeq = state.loadSeq;
    state.slotChecks.clear(); renderSubjects();
    await Promise.all((state.data.subjects || []).map(async subject => {
      const id = String(subject.id), problem = budgetProblem(subject, duration);
      if (problem) { state.slotChecks.set(id, {status: 'blocked', reason: problem}); return; }
      try {
        const result = await request('/availability?' + new URLSearchParams({promotion_id: slot.promotion_id, subject_id: id, trainer_id: subject.trainer_id, room_id: room, duration, start: slot.date, end: slot.date, day_start: slot.start, day_end: slot.end, step_minutes: 30, shared: JSON.stringify(shared)}));
        if (seq !== state.slotCheckSeq || loadSeq !== state.loadSeq || state.slot !== slot) return;
        const availability = (result.slots || []).find(item => item.date === slot.date && item.start === slot.start);
        state.slotChecks.set(id, {status: availability?.available ? 'available' : 'blocked', reason: availability?.conflicts?.map(item => item.message).join(' · ') || 'Créneau indisponible.'});
      } catch (failure) { if (seq === state.slotCheckSeq && loadSeq === state.loadSeq) state.slotChecks.set(id, {status: 'blocked', reason: failure.message}); }
      if (seq === state.slotCheckSeq) renderSubjects();
    }));
    if (seq === state.slotCheckSeq) renderSubjects();
  }
  async function createInSelectedSlot(subjectId, explicitSlot = null) {
    const slot = explicitSlot || state.slot, subject = state.data?.subjects?.find(item => String(item.id) === subjectId);
    if (!slot || !subject || state.quickBusy || state.loading || slot.promotion_id !== promotionId()) return;
    const problem = budgetProblem(subject, minutes(slot.end) - minutes(slot.start)); if (problem) { notice(problem, true); return; }
    if (!explicitSlot && state.slotChecks.get(subjectId)?.status !== 'available') return;
    let shared; try { shared = cleanShared(state.quickShared, promotionId()); } catch (failure) { notice(failure.message, true); return; }
    const data = {promotion_id: slot.promotion_id, subject_id: subjectId, trainer_id: subject.trainer_id, room_id: $('planning-room').value || null, date: slot.date, start: slot.start, end: slot.end, shared};
    state.quickBusy = true; renderSubjects(); $('planning-slot-summary').textContent = 'Ajout du cours en cours…';
    try { await request('/courses', {method: 'POST', data}); clearSlot(); notice(subject.name + ' ajouté le ' + formatDate(slot.date) + ', de ' + slot.start + ' à ' + slot.end + (shared.length ? ' · Cours commun avec ' + shared.length + ' autre(s) promotion(s).' : '.')); await loadState(); }
    catch (failure) { notice(failure.message, true); state.slotChecks.set(subjectId, {status: 'blocked', reason: failure.message}); renderSlotSelection(); }
    finally { state.quickBusy = false; renderSubjects(); }
  }
  function availabilityOptions() {
    const course = state.dragCourse, subject = currentSubject();
    return {promotion_id: course?.promotion_id || promotionId(), subject_id: course?.subject_id || state.subject, trainer_id: course?.trainer_id || subject?.trainer_id || '', room_id: course ? (course.room_id || '') : ($('planning-room').value || ''), duration: course ? courseDuration(course) : Number($('planning-duration').value), start: state.week, end: addDays(state.week, 6), day_start: timeString(state.gridStart), day_end: timeString(state.gridEnd), step_minutes: 30, shared: JSON.stringify(course ? (course.shared || []) : cleanShared(state.quickShared, promotionId())), ...(course ? {exclude_course_id: course.id} : {})};
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
      const date = addDays(state.week, day), info = dayInfo(date); const header = button('', 'planning-day-heading kind-' + info.kind + (date === today() ? ' is-today' : ''), () => openException(date)); header.append(el('span', '', weekdays[day]), el('b', '', formatDate(date, {day: 'numeric', month: 'short'})), el('small', '', info.label || kinds[info.kind] || 'À définir')); header.disabled = isPublicHoliday(info); header.setAttribute('aria-label', formatDate(date, {weekday: 'long', day: 'numeric', month: 'long'}) + ', ' + (info.label || kinds[info.kind]) + (isPublicHoliday(info) ? '. Jour férié verrouillé, aucun cours possible.' : '. Modifier cette journée.')); head.append(header);
    }
    calendar.append(head); const grid = el('div', 'planning-calendar-grid'); const timeAxis = el('div', 'planning-times');
    for (let minute = state.gridStart; minute < state.gridEnd; minute += 60) { const tick = el('span', '', timeString(minute)); tick.style.top = ((minute - state.gridStart) * 1.1) + 'px'; timeAxis.append(tick); } grid.append(timeAxis);
    for (let day = 0; day < 7; day++) {
      const date = addDays(state.week, day), info = dayInfo(date); const column = el('div', 'planning-day-column kind-' + info.kind); column.setAttribute('role', 'group'); column.setAttribute('aria-label', weekdays[day] + ' ' + formatDate(date));
      for (let minute = state.gridStart; minute < state.gridEnd; minute += 30) {
        const start = timeString(minute); const slot = button('', 'planning-slot' + (minute % 60 === 0 ? ' whole-hour' : ''), event => slotClick(date, start, event)); slot.dataset.date = date; slot.dataset.start = start; slot.disabled = isPublicHoliday(info); slot.style.top = (minute - state.gridStart) * 1.1 + 'px'; slot.style.height = '33px';
        slot.addEventListener('dragover', event => { if (state.subject && !slot.disabled) { event.preventDefault(); event.dataTransfer.dropEffect = state.dragCourse ? 'move' : 'copy'; slot.classList.add('drag-over'); } }); slot.addEventListener('dragleave', () => slot.classList.remove('drag-over')); slot.addEventListener('drop', event => { event.preventDefault(); slot.classList.remove('drag-over'); if (!slot.disabled) placeAt(date, start); });
        slot.addEventListener('pointerdown', event => beginSlot(date, start, event)); slot.addEventListener('pointerenter', () => extendSlot(date, start)); slot.addEventListener('keydown', event => slotKey(date, start, event)); column.append(slot);
      }
      for (const course of courses.filter(item => item.date === date)) {
        const warnings = courseWarnings(course); const event = button('', 'planning-event' + (courseDuration(course) <= 45 ? ' is-short' : '') + (warnings.length ? ' is-incomplete' : ''), () => openCourse(course)); event.draggable = course.kind !== 'event'; if (course.kind === 'event') event.classList.add('is-school-event'); event.style.top = (minutes(course.start) - state.gridStart) * 1.1 + 'px'; event.style.height = Math.max(30, courseDuration(course) * 1.1 - 3) + 'px'; event.style.setProperty('--subject-color', safeColor(course.display_color || course.color)); event.append(el('small', 'planning-event-time', course.start + ' – ' + course.end), el('b', '', courseName(course)), el('span', '', course.trainer_name || 'Formateur'), el('small', '', course.room_name || 'Sans salle')); if (warnings.length) { const alert = el('span', 'planning-event-warning', '⚠︎'); alert.setAttribute('aria-hidden', 'true'); event.append(alert); } if (course.is_shared) event.append(el('small', 'planning-shared-badge', 'Commun · ' + (course.groups || []).length + ' promos')); event.title = [courseName(course),course.start + ' – ' + course.end,course.trainer_name,course.room_name, ...(course.groups || []).map(group => group.promotion_name), ...warnings].filter(Boolean).join(' · '); event.setAttribute('aria-label', event.title + (warnings.length ? ' · Cours à compléter.' : ''));
        event.addEventListener('dragstart', drag => { state.dragCourse = course; state.subject = String(course.display_subject_id || course.groups?.find(group => String(group.promotion_id) === promotionId())?.subject_id || course.subject_id); renderSubjects(); loadAvailability(); drag.dataTransfer.setData('text/plain', 'course:' + course.id); drag.dataTransfer.effectAllowed = 'move'; });
        event.addEventListener('dragend', () => { state.dragCourse = null; loadAvailability(); }); column.append(event);
      } grid.append(column);
    } calendar.append(grid); renderAvailability(); renderSlotSelection();
  }
  function renderAvailability() {
    const subject = currentSubject();
    $('planning-calendar').querySelectorAll('.planning-slot').forEach(slot => {
      const info = state.availability.get(slot.dataset.date + '|' + slot.dataset.start); const day = dayInfo(slot.dataset.date);
      slot.classList.toggle('is-available', !!subject && state.availabilityReady && !!info?.available); slot.classList.toggle('is-unavailable', !!subject && state.availabilityReady && !info?.available);
      const reason = info?.conflicts?.map(conflict => conflict.message).join(' · ') || (day.kind !== 'school' ? day.label || kinds[day.kind] : 'Durée incompatible avec la plage horaire affichée.');
      const text = formatDate(slot.dataset.date, {weekday: 'long', day: 'numeric', month: 'long'}) + ', ' + slot.dataset.start + (isPublicHoliday(day) ? ', jour férié : ' + day.label + ', aucun cours possible' : subject ? ', ' + (state.availabilityReady ? (info?.available ? 'Disponible pour ' + subject.name : 'Indisponible : ' + reason) : 'Vérification en cours') : ', sélectionner le début d’un créneau ; glisser ou utiliser Maj pour étendre'); slot.title = text; slot.setAttribute('aria-label', text);
    });
    if (subject && state.availabilityReady) $('planning-placement-help').textContent = subject.name + ' · ' + (state.dragCourse ? 'Déplacez le cours vers un créneau disponible.' : 'Cliquez ou déposez sur un créneau vert.');
    else if (!subject) $('planning-placement-help').textContent = state.slot ? 'Créneau sélectionné : cliquez sur une matière disponible pour ajouter le cours.' : 'Sélectionnez un créneau, puis cliquez sur une matière disponible.';
  }
  async function placeAt(date, start) {
    if (state.loading || !state.data) return;
    if (isPublicHoliday(knownDay(date))) { notice('Ce jour férié est verrouillé. Aucun cours ne peut y être planifié.', true); return; }
    if (!state.subject) { notice('Sélectionnez d’abord une matière dans la colonne de gauche.'); $('planning-subject-search').focus(); return; }
    const moving = state.dragCourse, viewedPromotion = promotionId(), subjectId = moving?.subject_id || state.subject, roomId = moving ? (moving.room_id || '') : $('planning-room').value, sequence = state.loadSeq;
    let options; try { options = availabilityOptions(); } catch (failure) { notice(failure.message, true); return; }
    let slot = state.availabilityReady ? state.availability.get(date + '|' + start) : null;
    if (!state.availabilityReady || moving) {
      try { const result = await request('/availability?' + new URLSearchParams(options)); slot = (result.slots || []).find(item => item.date === date && item.start === start); }
      catch (failure) { notice(failure.message, true); return; }
    }
    if (sequence !== state.loadSeq || viewedPromotion !== promotionId()) return;
    if (!slot?.available) { notice(slot?.conflicts?.map(conflict => conflict.message).join(' · ') || 'Ce créneau n’est pas disponible pour cette matière et cette durée.', true); return; }
    notice(''); if (moving) openCourse(moving, {date, start, end: slot.end, subject_id: subjectId, room_id: roomId}); else await createInSelectedSlot(subjectId, {promotion_id: promotionId(), date, start, end: slot.end});
  }
  function slotClick(date, start, event) {
    if (state.slotClickSuppressed || state.loading || state.quickBusy || isPublicHoliday(knownDay(date))) return;
    if (event.shiftKey && state.slotAnchor?.date === date) { const first = Math.min(minutes(state.slotAnchor.start), minutes(start)), last = Math.max(minutes(state.slotAnchor.start), minutes(start)) + 30; setSlot(date, timeString(first), timeString(last)); }
    else { state.slotAnchor = {date, start}; setSlot(date, start, timeString(Math.min(state.gridEnd, minutes(start) + Number($('planning-duration').value)))); }
  }
  function beginSlot(date, start, event) {
    if (event.button !== 0 || state.loading || state.quickBusy || isPublicHoliday(knownDay(date))) return;
    event.preventDefault(); event.currentTarget.focus({preventScroll: true}); state.slotClickSuppressed = true;
    if (event.shiftKey && state.slotAnchor?.date === date) { const first = Math.min(minutes(state.slotAnchor.start), minutes(start)), last = Math.max(minutes(state.slotAnchor.start), minutes(start)) + 30; setSlot(date, timeString(first), timeString(last)); return; }
    state.slotAnchor = {date, start}; state.slotGesture = {date, start, moved: false}; setSlot(date, start, timeString(minutes(start) + 30), false);
  }
  function extendSlot(date, start) {
    const gesture = state.slotGesture; if (!gesture || gesture.date !== date || state.quickBusy) return;
    gesture.moved = gesture.moved || start !== gesture.start; const first = Math.min(minutes(start), minutes(gesture.start)), last = Math.max(minutes(start), minutes(gesture.start)) + 30; setSlot(date, timeString(first), timeString(last), false);
  }
  function slotKey(date, start, event) {
    let targetDate = date, targetMinute = minutes(start);
    if (event.key === 'ArrowDown') targetMinute += 30; else if (event.key === 'ArrowUp') targetMinute -= 30; else if (event.key === 'ArrowRight') targetDate = addDays(date, 1); else if (event.key === 'ArrowLeft') targetDate = addDays(date, -1); else return;
    const target = $('planning-calendar').querySelector('[data-date="' + targetDate + '"][data-start="' + timeString(targetMinute) + '"]'); if (!target) return; event.preventDefault(); target.focus();
    if (event.shiftKey && targetDate === date) { if (!state.slotAnchor || state.slotAnchor.date !== date) state.slotAnchor = {date, start}; const first = Math.min(minutes(state.slotAnchor.start), targetMinute), last = Math.max(minutes(state.slotAnchor.start), targetMinute) + 30; setSlot(date, timeString(first), timeString(last)); }
  }
  function annualKey(date, event) {
    const shifts = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7}; if (!(event.key in shifts)) return;
    let targetDate = addDays(date, shifts[event.key]);
    for (let step = 0; step < 741; step++, targetDate = addDays(targetDate, shifts[event.key])) {
      const target = $('planning-months').querySelector('[data-paint-date="' + targetDate + '"]'); if (!target) return;
      if (!target.disabled) { event.preventDefault(); target.focus(); if (event.shiftKey) { if (!state.paintAnchor) state.paintAnchor = date; applyPaintRange(state.paintAnchor, targetDate); } return; }
    }
  }
  document.addEventListener('pointermove', event => {
    if (!state.slotGesture && !state.paintGesture && !state.batch?.dateGesture && !state.batch?.weekGesture) return;
    const target = document.elementFromPoint(event.clientX, event.clientY);
    const batchWeek = target?.closest('[data-batch-week]'); if (batchWeek && !batchWeek.disabled) extendBatchWeek(batchWeek.dataset.batchWeek);
    const batchDay = target?.closest('[data-batch-date]'); if (batchDay && !batchDay.disabled) extendBatchDate(batchDay.dataset.batchDate);
    const cell = target?.closest('[data-paint-date]'); if (cell && !cell.disabled) extendPaint(cell.dataset.paintDate);
    const slot = target?.closest('.planning-slot'); if (slot) extendSlot(slot.dataset.date, slot.dataset.start);
  });
  document.addEventListener('pointerup', () => {
    if (state.slotGesture) { const gesture = state.slotGesture; state.slotGesture = null; if (!gesture.moved) setSlot(gesture.date, gesture.start, timeString(Math.min(state.gridEnd, minutes(gesture.start) + Number($('planning-duration').value)))); else checkSelectedSlot(); }
    state.paintGesture = null; if (state.batch) { state.batch.dateGesture = null; state.batch.weekGesture = null; } setTimeout(() => { if (state.batch) { state.batch.dateClickSuppressed = false; state.batch.weekClickSuppressed = false; } state.slotClickSuppressed = false; state.paintClickSuppressed = false; }, 0);
  });
  document.addEventListener('pointercancel', () => { if (state.batch) { state.batch.dateGesture = null; state.batch.dateClickSuppressed = false; state.batch.weekGesture = null; state.batch.weekClickSuppressed = false; } state.slotGesture = null; state.paintGesture = null; state.slotClickSuppressed = false; state.paintClickSuppressed = false; if (state.slot) checkSelectedSlot(); });
  function annualDay(date) { return (state.year?.days || []).find(day => day.date === date); }
  function paintDate(date, kind = state.paintKind) {
    const original = annualDay(date); if (!original || isPublicHoliday(original) || original.locked) return;
    if (state.paintRevision === null) state.paintRevision = state.year?.calendar_revision ?? state.data?.calendar_revision;
    if (original.kind === kind) state.paintDraft.delete(date); else state.paintDraft.set(date, {date, kind, label: kinds[kind]});
  }
  function applyPaintRange(start, end, base = null) {
    if (state.loading || state.paintBusy || !state.year) return;
    if (base) state.paintDraft = new Map(base);
    const first = start < end ? start : end, last = start < end ? end : start;
    state.paintSkipped = 0; let date = first; for (let count = 0; date <= last && count < 741; count++, date = addDays(date, 1)) { if (isPublicHoliday(annualDay(date))) state.paintSkipped++; else paintDate(date); }
    renderPaintDraft();
  }
  function renderPaintDraft() {
    $('planning-months').querySelectorAll('[data-paint-date]').forEach(cell => {
      const date = cell.dataset.paintDate, original = annualDay(date), pending = state.paintDraft.get(date), day = pending || original;
      for (const kind of Object.keys(kinds)) cell.classList.toggle('kind-' + kind, day?.kind === kind);
      cell.classList.toggle('is-painted', !!pending); cell.setAttribute('aria-pressed', String(!!pending));
      cell.title = formatDate(date) + ' · ' + (day?.label || kinds[day?.kind] || 'À définir') + (pending ? ' · Modification non enregistrée (actuellement : ' + (kinds[original?.kind] || 'À définir') + ')' : '');
      cell.setAttribute('aria-label', cell.title + (isPublicHoliday(original) ? '. Jour férié verrouillé.' : '. Peindre en ' + kinds[state.paintKind] + '.'));
    });
    const skipped = $('planning-paint-locked-status'); skipped.hidden = !state.paintSkipped; skipped.textContent = state.paintSkipped ? state.paintSkipped + ' jour' + (state.paintSkipped > 1 ? 's fériés exclus' : ' férié exclu') + ' de la coloration : ces dates restent verrouillées en rouge.' : '';
    const count = state.paintDraft.size; $('planning-paint-savebar').hidden = count === 0;
    $('planning-paint-count').textContent = count + ' jour' + (count !== 1 ? 's' : '') + ' modifié' + (count !== 1 ? 's' : '');
    if (!state.paintStale) $('planning-paint-status').textContent = state.paintBusy ? 'Enregistrement de tous les jours en cours…' : 'Vos modifications ne sont pas encore enregistrées.';
    $('planning-paint-save').disabled = !count || state.paintBusy || state.paintStale; $('planning-paint-cancel').disabled = state.paintBusy; $('planning-paint-refresh').hidden = !state.paintStale; $('planning-paint-refresh').disabled = state.paintBusy;
    $('planning-period-new').disabled = count > 0; $('planning-exception-open').disabled = count > 0; $('planning-export-open').disabled = count > 0; $('planning-export-open').title = count ? 'Enregistrez ou annulez le brouillon avant d’exporter le calendrier.' : '';
  }
  function cancelPaint() { state.paintSkipped = 0; state.paintDraft.clear(); state.paintRevision = null; state.paintStale = false; state.paintGesture = null; renderPaintDraft(); }
  function annualClick(date, event) {
    if (state.loading || state.paintBusy || state.paintClickSuppressed) return;
    if (event.shiftKey && state.paintAnchor) applyPaintRange(state.paintAnchor, date); else { paintDate(date); renderPaintDraft(); state.paintAnchor = date; }
  }
  function beginPaint(date, event) {
    if (event.button !== 0 || state.loading || state.paintBusy || !annualDay(date) || isPublicHoliday(annualDay(date))) return;
    if (event.shiftKey && state.paintAnchor) { event.preventDefault(); applyPaintRange(state.paintAnchor, date); state.paintClickSuppressed = true; return; }
    event.preventDefault(); event.currentTarget.focus({preventScroll: true}); state.paintAnchor = date; state.paintGesture = {anchor: date, base: new Map(state.paintDraft)}; state.paintClickSuppressed = true; applyPaintRange(date, date, state.paintGesture.base);
  }
  function extendPaint(date) { if (state.paintGesture && !state.paintBusy && state.paintGesture.last !== date) { state.paintGesture.last = date; applyPaintRange(state.paintGesture.anchor, date, state.paintGesture.base); } }
  async function savePaint() {
    if (!state.paintDraft.size || state.paintBusy || state.paintStale || state.loading) return;
    const data = {promotion_id: promotionId(), expected_revision: state.paintRevision, days: [...state.paintDraft.values()].sort((a, b) => a.date.localeCompare(b.date))}; state.paintBusy = true; renderPaintDraft();
    try { await request('/calendar/bulk', {method: 'POST', data}); state.paintDraft.clear(); state.paintSkipped = 0; state.paintRevision = null; state.paintStale = false; notice(data.days.length + ' jour(s) du calendrier enregistrés ensemble.'); await loadState(); }
    catch (failure) { state.paintStale = failure.result?.conflicts?.some(item => item.type === 'calendar_stale') || failure.result?.code === 'calendar_stale' || failure.result?.error === 'calendar_stale'; $('planning-paint-status').textContent = failure.message + (state.paintStale ? ' Rechargez les données pour revoir votre brouillon avant un nouvel enregistrement.' : ' Aucun jour n’a été enregistré. Votre brouillon est conservé.'); notice(failure.message, true); }
    finally { state.paintBusy = false; const failureStatus = $('planning-paint-status').textContent; renderPaintDraft(); if (state.paintDraft.size && failureStatus.includes('Aucun jour')) $('planning-paint-status').textContent = failureStatus; }
  }
  async function refreshPaint() {
    if (state.paintBusy || !state.data) return; state.paintBusy = true; renderPaintDraft(); const promotion = state.data.promotion;
    try {
      const old = new Map((state.year?.days || []).map(day => [day.date, day.kind]));
      const fresh = await request('/state?' + new URLSearchParams({promotion_id: promotionId(), start: promotion.date_debut, end: promotion.date_fin}));
      let changed = 0; for (const day of fresh.days || []) { if (state.paintDraft.has(day.date) && old.get(day.date) !== day.kind) changed++; if (state.paintDraft.get(day.date)?.kind === day.kind) state.paintDraft.delete(day.date); }
      state.year = fresh; state.data.calendar_revision = fresh.calendar_revision; state.data.rules = fresh.rules; state.data.exceptions = fresh.exceptions; state.data.days = fresh.days.filter(day => day.date >= state.week && day.date <= addDays(state.week, 6)); renderCalendar(); state.paintRevision = fresh.calendar_revision; state.paintStale = false; await renderYear();
      notice('Calendrier rechargé. Votre brouillon est conservé.' + (changed ? ' ' + changed + ' jour(s) ont aussi été modifiés par une autre personne : vérifiez les couleurs et les infobulles avant d’enregistrer.' : ' Vérifiez-le puis cliquez sur Enregistrer.'));
    } catch (failure) { notice(failure.message, true); }
    finally { state.paintBusy = false; renderPaintDraft(); }
  }
  function navigatePlanning(action) {
    if (state.quickBusy || state.paintBusy) { notice('Attendez la fin de l’enregistrement en cours.'); return; }
    if (!state.paintDraft.size) { action(); return; }
    $('planning-confirm-text').textContent = state.paintDraft.size + ' jour(s) ont été modifiés sans être enregistrés. Abandonner ce brouillon pour continuer ?'; const dialog = $('planning-confirm-dialog'); openDialog('planning-confirm-dialog');
    $('planning-confirm-action').textContent = 'Abandonner le brouillon'; $('planning-confirm-action').onclick = () => { cancelPaint(); dialog.close(); action(); };
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
        for (let day = 1; day <= last; day++) { const date = dateString(new Date(year, month, day, 12)), info = map.get(date); const cell = button(String(day), 'planning-month-day kind-' + (info?.kind || 'closed'), event => annualClick(date, event)); cell.dataset.paintDate = date; cell.addEventListener('pointerdown', event => beginPaint(date, event)); cell.addEventListener('pointerenter', () => extendPaint(date)); cell.addEventListener('keydown', event => annualKey(date, event)); cell.disabled = date < start || date > end || isPublicHoliday(info) || !!info?.locked; cell.title = formatDate(date) + ' · ' + (info?.label || kinds[info?.kind || 'closed']); cell.setAttribute('aria-label', cell.title + (isPublicHoliday(info) ? '. Jour férié verrouillé.' : '. Modifier cette journée.')); if ((state.year.courses || []).some(course => course.date === date)) cell.classList.add('has-courses'); days.append(cell); }
        monthNode.append(days); container.append(monthNode);
      } renderRules(); renderPaintDraft(); const range = $('planning-paint-range'); for (const input of range.querySelectorAll('input')) { input.min = start; input.max = end; }
    } catch (failure) { notice(failure.message, true); }
  }
  function renderRules() {
    const rules = $('planning-rules'), exceptions = $('planning-exceptions'); rules.replaceChildren(); exceptions.replaceChildren();
    for (const rule of state.data.rules || []) { const card = el('article', 'planning-rule kind-' + rule.kind); card.append(el('b', '', rule.label || kinds[rule.kind]), el('span', '', formatDate(rule.start_date) + ' — ' + formatDate(rule.end_date)), el('small', '', (rule.weekdays || []).map(day => weekdays[day]?.slice(0, 3)).join(' · ')), button('Modifier', 'planning-text-button', () => openPeriod(rule))); rules.append(card); }
    if (!rules.children.length) rules.append(el('p', 'planning-muted', 'Aucune période définie.'));
    $('planning-exception-count').textContent = '(' + (state.data.exceptions || []).length + ')'; $('planning-exception-overflow').hidden = (state.data.exceptions || []).length <= 12;
    for (const exception of (state.data.exceptions || []).slice(0, 12)) { const day = knownDay(exception.date), locked = isPublicHoliday(day), card = el('article', 'planning-rule kind-' + (locked ? 'public_holiday' : exception.kind)); card.append(el('b', '', locked ? day.label + ' · Férié verrouillé' : exception.label || kinds[exception.kind]), el('span', '', formatDate(exception.date))); if (locked) card.append(el('small', '', 'L’ancienne couleur est ignorée : aucun cours ne peut être placé.')); else card.append(button('Modifier', 'planning-text-button', () => openException(exception.date))); exceptions.append(card); }
    if (!exceptions.children.length) exceptions.append(el('p', 'planning-muted', 'Aucune exception.'));
  }
  const trainerName = trainer => trainer.name || trainer.trainer_name || AcademyNames.fullName(trainer.nom, trainer.prenom);
  function prefillSubjectHours() {
    if (state.subjectEdit || !state.data) return;
    const form = $('planning-subject-form'), entry = (state.data.catalog?.subject_catalog || []).find(item => item.id === form.elements.catalog_subject_id.value);
    const field = ({1: 'annual_hours_first', 2: 'annual_hours_second'})[state.data.study_year];
    const value = field ? entry?.diploma_details?.[state.data.promotion.bts]?.[field] : null;
    form.elements.planned_hours.value = value ?? '';
    $('planning-subject-hours-help').textContent = value == null ? 'Vous pouvez définir les volumes annuels dans la fiche matière du catalogue.' : 'Volume repris de la fiche matière pour cette année. Vous pouvez l’adapter à cette promotion.';
  }
  $('planning-subject-form').elements.catalog_subject_id.addEventListener('change', prefillSubjectHours);
  function openSubject(subject = null, requested = '') {
    if (!state.data || state.loading || state.quickBusy) return; state.subjectEdit = subject; const form = $('planning-subject-form'); form.reset();
    const code = state.data.promotion.bts, prepared = new Set((state.data.subjects || []).map(item => item.catalog_subject_id));
    const entries = (state.data.catalog?.subject_catalog || []).filter(item => item.diploma_codes.includes(code) && (subject ? item.id === subject.catalog_subject_id : !prepared.has(item.id)));
    populate(form.elements.catalog_subject_id, entries, item => item.name, 'Choisir une matière', subject?.catalog_subject_id || requested);
    form.elements.catalog_subject_id.disabled = !!subject;
    form.elements.planned_hours.value = subject?.planned_hours ?? '';
    $('planning-subject-hours-help').textContent = 'Ce volume concerne uniquement l’année de ce planning.';
    prefillSubjectHours();
    $('planning-subject-diploma-help').textContent = 'Matières rattachées au BTS ' + code + '. Les autres diplômes se gèrent depuis le catalogue.';
    $('planning-subject-catalog-link').href = '/admin/matieres?diploma=' + encodeURIComponent(code);
    populate(form.elements.trainer_id, state.data.trainers || [], trainerName, 'Choisir un formateur', subject?.trainer_id);
    form.querySelector('button[type=submit]').disabled = !entries.length || !state.data.trainers?.length;
    $('planning-subject-delete').hidden = !subject; openDialog('planning-subject-dialog', subject ? form.elements.trainer_id : form.elements.catalog_subject_id);
    if (!entries.length) formError(form, 'Toutes les matières de ce BTS sont déjà préparées, ou son catalogue est vide. Ajoutez une matière depuis le catalogue.');
    else if (!state.data.trainers?.length) formError(form, 'Aucun formateur n’est affecté à cette promotion. Ajoutez une affectation depuis la page Formateurs.');
  }
  function openRequestedSubject() {
    const requested = new URL(location.href).searchParams.get('catalog_subject_id');
    if (!requested || !state.data || !planningSyncSafe()) return;
    const entry = (state.data.catalog?.subject_catalog || []).find(item => item.id === requested);
    if (!entry || !entry.diploma_codes.includes(state.data.promotion.bts)) { notice('Choisissez une promotion correspondant aux diplômes de cette matière.'); return; }
    const existing = (state.data.subjects || []).find(item => item.catalog_subject_id === requested);
    const url = new URL(location.href); url.searchParams.delete('catalog_subject_id'); history.replaceState(null, '', url);
    openSubject(existing || null, requested);
  }
  $('planning-subject-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget; const data = {promotion_id: promotionId(), catalog_subject_id: form.elements.catalog_subject_id.value, trainer_id: form.elements.trainer_id.value, planned_hours: form.elements.planned_hours.value === '' ? null : Number(form.elements.planned_hours.value)};
    saveForm(form, () => request('/subjects' + (state.subjectEdit ? '/' + encodeURIComponent(state.subjectEdit.id) : ''), {method: state.subjectEdit ? 'PUT' : 'POST', data}), 'Matière enregistrée.');
  });
  function dateLimits(form) { const promotion = state.data.promotion; for (const input of form.querySelectorAll('input[type=date]')) { input.min = promotion.date_debut || ''; input.max = promotion.date_fin || ''; } }
  function setWeekdays(form, values) { form.querySelectorAll('input[name=weekdays]').forEach(input => { input.checked = values.includes(Number(input.value)); }); }
  const selectedWeekdays = form => [...form.querySelectorAll('input[name=weekdays]:checked')].map(input => Number(input.value));
  function openPeriod(rule = null) {
    if (!state.data || state.loading || state.paintDraft.size) { if (state.paintDraft.size) notice('Enregistrez ou annulez les couleurs du calendrier avant de modifier une période.'); return; } state.ruleEdit = rule; const form = $('planning-period-form'); form.reset(); dateLimits(form);
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
    if (isPublicHoliday(knownDay(date))) { notice('Ce jour férié est verrouillé et ne peut pas devenir une journée école.', true); return; }
    if (!state.data || state.loading || state.paintDraft.size) { if (state.paintDraft.size) notice('Enregistrez ou annulez les couleurs du calendrier avant de modifier une exception.'); return; } const exception = (state.data.exceptions || []).find(item => item.date === date), info = (state.year?.days || state.data.days || []).find(item => item.date === date); state.exceptionEdit = exception || null;
    const form = $('planning-exception-form'); form.reset(); dateLimits(form); form.elements.date.value = date; form.elements.date.readOnly = !!exception; form.elements.kind.value = exception?.kind || (info?.kind !== 'unconfigured' ? info?.kind : 'school') || 'school'; form.elements.label.value = exception?.label || ''; $('planning-exception-delete').hidden = !exception; openDialog('planning-exception-dialog', form.elements.kind);
  }
  $('planning-exception-form').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; const data = {promotion_id: promotionId(), date: form.elements.date.value, kind: form.elements.kind.value, label: form.elements.label.value.trim()}; saveForm(form, () => request('/calendar/exceptions', {method: 'PUT', data}), 'Exception enregistrée.'); });
  function openCourse(course = null, overrides = {}) {
    if (state.loading || state.quickBusy || !state.data) return;
    if (course?.kind === 'event') { window.AcademyPlanningExtras?.openEvent(course); return; }
    if (!state.data?.subjects?.length) { notice('Préparez une matière avant de créer un cours.'); openSubject(); return; }
    state.courseEdit = course; const form = $('planning-course-form'); form.reset(); dateLimits(form);
    const values = {...(course || {}), ...overrides}, primary = course?.promotion_id || promotionId(); let subjectId = values.subject_id || state.subject || '';
    if (course && !catalogSubjects().some(item => item.id === subjectId)) {
      const old = state.data.catalog?.subjects?.find(item => item.id === subjectId);
      subjectId = catalogSubjects().find(item => item.promotion_id === primary && item.catalog_subject_id === old?.catalog_subject_id)?.id || '';
    }
    populate(form.elements.subject_id, catalogSubjects().filter(item => String(item.promotion_id) === String(primary)), item => item.name, 'Choisir une matière', subjectId);
    const subject = catalogSubjects().find(item => String(item.id) === String(subjectId));
    populate(form.elements.trainer_id, state.data.catalog?.trainers || state.data.trainers || [], trainerName, 'Choisir un formateur', values.trainer_id || subject?.trainer_id);
    state.courseShared = (course?.shared || state.quickShared || []).map(item => ({promotion_id: String(item.promotion_id), subject_id: String(item.subject_id)}));
    $('planning-course-primary').textContent = 'Promotion de référence : ' + (catalogPromotions().find(item => String(item.id) === String(primary))?.nom || state.data.promotion.nom);
    renderSharedRows($('planning-course-shared'), state.courseShared, primary, courseSharedChanged);
    populate(form.elements.room_id, state.data.rooms || [], item => item.name + (item.active === false || item.active === 0 ? ' · Inactive' : ''), 'Sans salle attribuée', Object.prototype.hasOwnProperty.call(values, 'room_id') ? (values.room_id || '') : $('planning-room').value);
    form.elements.zoom_url.value = values.zoom_url || '';
    form.elements.date.value = values.date || (state.week < state.data.promotion.date_debut ? state.data.promotion.date_debut : state.week); form.elements.start.value = values.start || '09:00'; form.elements.end_at_midnight.checked = values.end === '24:00'; form.elements.end.value = values.end === '24:00' ? '23:59' : values.end || '11:00'; form.elements.end.disabled = form.elements.end_at_midnight.checked; form.elements.end.required = !form.elements.end_at_midnight.checked; form.elements.title.value = values.title || '';
    const warning = $('planning-course-warning'), warnings = course ? courseWarnings(course) : []; warning.textContent = warnings.length ? '⚠︎ À compléter : ' + warnings.join(' · ') : ''; warning.hidden = !warnings.length;
    $('planning-course-delete').hidden = !course; $('planning-course-repeat').hidden = !course; $('planning-course-repeat').disabled = false; openDialog('planning-course-dialog', form.elements.subject_id);
  }
  $('planning-course-form').addEventListener('input', () => { $('planning-course-repeat').disabled = true; $('planning-course-repeat').title = 'Enregistrez les modifications du cours avant de le répéter.'; });
  $('planning-course-form').elements.subject_id.addEventListener('change', event => { const subject = catalogSubjects().find(item => String(item.id) === event.target.value); if (subject) $('planning-course-form').elements.trainer_id.value = subject.trainer_id; });
  $('planning-course-form').elements.end_at_midnight.addEventListener('change', event => { const input = $('planning-course-form').elements.end; input.disabled = event.target.checked; input.required = !event.target.checked; });
  function courseSharedChanged() { $('planning-course-repeat').disabled = true; }
  const courseValues = form => ({zoom_url: form.elements.zoom_url.value.trim(), promotion_id: state.courseEdit?.promotion_id || promotionId(), subject_id: form.elements.subject_id.value, trainer_id: form.elements.trainer_id.value, room_id: form.elements.room_id.value || null, date: form.elements.date.value, start: form.elements.start.value, end: form.elements.end_at_midnight.checked ? '24:00' : form.elements.end.value, title: form.elements.title.value.trim(), shared: cleanShared(state.courseShared, state.courseEdit?.promotion_id || promotionId())});
  $('planning-course-form').addEventListener('submit', event => {
    event.preventDefault(); const form = event.currentTarget; let data; try { data = courseValues(form); } catch (failure) { formError(form, failure.message); return; } if (state.courseEdit) data.version = state.courseEdit.version;
    if (data.start >= data.end) { formError(form, 'L’heure de fin doit suivre l’heure de début.'); return; }
    saveForm(form, () => request('/courses' + (state.courseEdit ? '/' + encodeURIComponent(state.courseEdit.id) : ''), {method: state.courseEdit ? 'PUT' : 'POST', data}), state.courseEdit ? 'Cours mis à jour.' : 'Cours ajouté au planning.');
  });
  function confirmAction(text, action, success, closeDialog = null, after = null) {
    $('planning-confirm-action').textContent = 'Confirmer'; $('planning-confirm-text').textContent = text; const dialog = $('planning-confirm-dialog'); openDialog('planning-confirm-dialog', $('planning-confirm-action'));
    $('planning-confirm-action').onclick = async () => {
      if (dialog.dataset.busy) return; busyDialog(dialog, true); const error = dialog.querySelector('.planning-form-error'); error.hidden = true;
      try { await action(); dialog.close(); if (closeDialog) $(closeDialog).close(); notice(success); await loadState(); if (after) after(); }
      catch (failure) { error.textContent = failure.message; error.hidden = false; }
      finally { busyDialog(dialog, false); }
    };
  }
  async function openDeletion(subjectId = '') {
    if (state.loading || !state.data?.period) return;
    const dialog = $('planning-delete-dialog'), period = state.data.period;
    state.deletion = {courses: [], selected: new Set(), preview: null, period};
    $('planning-delete-period').textContent = yearLabel(period);
    populate($('planning-delete-subject'), state.data.subjects, item => item.name, 'Toutes les matières', subjectId);
    for (const [id, value] of [['planning-delete-from', period.start_date], ['planning-delete-to', period.end_date]]) { $(id).min = period.start_date; $(id).max = period.end_date; $(id).value = value; }
    showDeletionSelection(); openDialog('planning-delete-dialog'); busyDialog(dialog, true);
    try {
      const result = await request('/state?' + new URLSearchParams({promotion_id: promotionId(), period_id: period.id, start: period.start_date, end: period.end_date}));
      state.deletion.courses = result.courses || [];
    } catch (failure) { formError(dialog, failure.message); }
    finally { busyDialog(dialog, false); renderDeletion(); }
  }
  function deletionVisible() {
    const subject = $('planning-delete-subject').value, start = $('planning-delete-from').value, end = $('planning-delete-to').value;
    return (state.deletion?.courses || []).filter(course => (!subject || course.display_subject_id === subject) && (!start || course.date >= start) && (!end || course.date <= end));
  }
  function deletionRow(course, selectable = false) {
    const row = el(selectable ? 'label' : 'div', 'planning-delete-row');
    if (selectable) {
      const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.value = course.id; checkbox.checked = state.deletion.selected.has(course.id);
      checkbox.addEventListener('change', () => { if (checkbox.checked) state.deletion.selected.add(course.id); else state.deletion.selected.delete(course.id); renderDeletionCount(); }); row.append(checkbox);
    }
    const description = el('span'); description.append(el('b', '', fullDate(course.date) + ' · ' + course.start + '–' + course.end), el('span', '', course.display_subject_name + ' · ' + course.trainer_name + (course.is_shared ? ' · Cours partagé' : ''))); row.append(description);
    return row;
  }
  function renderDeletionCount() {
    const count = state.deletion?.selected.size || 0, subject = $('planning-delete-subject').value;
    $('planning-delete-count').textContent = count + ' cours sélectionné(s) sur l’année';
    $('planning-delete-preview').disabled = !count;
    $('planning-delete-all-subject').hidden = !subject || !!state.deletion?.preview;
    $('planning-delete-all-subject').disabled = !subject || !state.deletion?.courses.some(course => course.display_subject_id === subject);
    $('planning-delete-select-all').disabled = !deletionVisible().length;
  }
  function renderDeletion() {
    const courses = deletionVisible(), list = $('planning-delete-list'); list.replaceChildren(...courses.map(course => deletionRow(course, true)));
    if (!courses.length) list.append(el('p', '', 'Aucun cours pour ces filtres dans cette année.'));
    renderDeletionCount();
  }
  function showDeletionSelection() {
    state.deletion.preview = null;
    for (const id of ['planning-delete-review', 'planning-delete-confirm', 'planning-delete-back']) $(id).hidden = true;
    for (const id of ['planning-delete-selection', 'planning-delete-preview', 'planning-delete-all-subject']) $(id).hidden = false;
    renderDeletion();
  }
  async function previewDeletion(mode) {
    const dialog = $('planning-delete-dialog'); if (dialog.dataset.busy) return;
    const data = {promotion_id: promotionId(), period_id: state.deletion.period.id, mode, ...(mode === 'subject' ? {subject_id: $('planning-delete-subject').value} : {course_ids: [...state.deletion.selected]})};
    busyDialog(dialog, true); formError(dialog, '');
    try {
      const preview = await request('/courses/delete-preview', {method: 'POST', data}); state.deletion.preview = preview;
      $('planning-delete-summary').textContent = preview.count + ' cours · ' + minuteLabel(preview.minutes) + ' seront retirés du planning ci-dessus. Vérifiez la liste avant de confirmer.';
      $('planning-delete-shared').textContent = preview.shared_count ? preview.shared_count + ' cours partagé(s) seront retirés de cette promotion et conservés pour les autres promotions.' : '';
      $('planning-delete-review-list').replaceChildren(...preview.courses.map(course => deletionRow(course)));
      $('planning-delete-confirm').textContent = 'Supprimer ces ' + preview.count + ' cours';
      for (const id of ['planning-delete-selection', 'planning-delete-preview', 'planning-delete-all-subject']) $(id).hidden = true;
      for (const id of ['planning-delete-review', 'planning-delete-confirm', 'planning-delete-back']) $(id).hidden = false;
    } catch (failure) { formError(dialog, failure.message); }
    finally { busyDialog(dialog, false); if (state.deletion.preview) $('planning-delete-confirm').focus(); }
  }
  $('planning-delete-open').addEventListener('click', () => openDeletion(state.subject));
  for (const id of ['planning-delete-subject', 'planning-delete-from', 'planning-delete-to']) $(id).addEventListener('change', renderDeletion);
  $('planning-delete-select-all').addEventListener('click', () => { deletionVisible().forEach(course => state.deletion.selected.add(course.id)); renderDeletion(); });
  $('planning-delete-clear').addEventListener('click', () => { state.deletion.selected.clear(); renderDeletion(); });
  $('planning-delete-back').addEventListener('click', showDeletionSelection);
  $('planning-delete-preview').addEventListener('click', () => previewDeletion('selected'));
  $('planning-delete-all-subject').addEventListener('click', () => previewDeletion('subject'));
  $('planning-delete-confirm').addEventListener('click', async () => {
    const dialog = $('planning-delete-dialog'), preview = state.deletion?.preview; if (!preview || dialog.dataset.busy) return;
    busyDialog(dialog, true); formError(dialog, '');
    try { const result = await request('/courses/delete-batch', {method: 'POST', data: {preview_token: preview.preview_token}}); dialog.close(); clearSlot(); notice(result.message); await loadState(); }
    catch (failure) { formError(dialog, failure.message); }
    finally { busyDialog(dialog, false); }
  });
  $('planning-subject-delete').addEventListener('click', () => { if (state.subjectEdit) confirmAction('Retirer « ' + state.subjectEdit.name + ' » de ce planning ? Les cours existants doivent d’abord être réaffectés. La fiche reste dans le catalogue des diplômes.', () => request('/subjects/' + encodeURIComponent(state.subjectEdit.id), {method: 'DELETE'}), 'Matière retirée de ce planning.', 'planning-subject-dialog'); });
  $('planning-period-delete').addEventListener('click', () => { if (state.ruleEdit) confirmAction('Supprimer cette période ? Les jours concernés retrouveront le rythme des autres règles, ou deviendront non définis. Les cours existants seront vérifiés avant toute modification.', () => request('/calendar/rules/' + encodeURIComponent(state.ruleEdit.id), {method: 'DELETE'}), 'Période supprimée.', 'planning-period-dialog'); });
  $('planning-exception-delete').addEventListener('click', () => { if (state.exceptionEdit) confirmAction('Retirer cette exception ? La journée retrouvera le rythme habituel de la promotion.', () => request('/calendar/exceptions/' + encodeURIComponent(promotionId()) + '/' + encodeURIComponent(state.exceptionEdit.date), {method: 'DELETE'}), 'Exception retirée.', 'planning-exception-dialog'); });
  $('planning-course-delete').addEventListener('click', () => { if (state.courseEdit) confirmAction('Supprimer le cours « ' + courseName(state.courseEdit) + ' » du ' + formatDate(state.courseEdit.date) + ' à ' + state.courseEdit.start + ' ? Cette suppression concerne uniquement ce créneau.', () => request('/courses/' + encodeURIComponent(state.courseEdit.id), {method: 'DELETE', data: {version: state.courseEdit.version}}), 'Cours supprimé.', 'planning-course-dialog'); });
  function batchDateProblem(date) {
    const batch = state.batch, info = (batch?.calendar?.days || []).find(day => day.date === date);
    if (!info) return 'En dehors des dates de la promotion.';
    if (isPublicHoliday(info)) return (info.label || 'Jour férié') + ' · Jour férié, aucun cours possible.';
    if (date === batch.course?.date) return 'Le cours existe déjà à cette date.';
    if (info.kind !== 'school') return (info.label || kinds[info.kind] || 'Journée non définie') + ' · Aucun cours possible.';
    return '';
  }
  function updateBatchDates() {
    const batch = state.batch; if (!batch) return;
    const dates = [...batch.dates].sort(); $('planning-batch-date-count').textContent = dates.length + ' jour' + (dates.length !== 1 ? 's' : '') + ' sélectionné' + (dates.length !== 1 ? 's' : '');
    $('planning-batch-date-selected').textContent = dates.length ? dates.map(date => formatDate(date, {day: 'numeric', month: 'short', year: 'numeric'})).join(' · ') : 'Choisissez les jours de duplication dans le calendrier.';
    $('planning-batch-date-clear').disabled = !dates.length;
    $('planning-batch-date-months').querySelectorAll('[data-batch-date]').forEach(cell => { const selected = batch.dates.has(cell.dataset.batchDate); cell.classList.toggle('is-selected', selected); cell.setAttribute('aria-pressed', String(selected)); });
    $('planning-batch-preview').disabled = batch.mode === 'dates' && (batch.calendarLoading || !batch.calendar || !dates.length);
    updateBatchCommit();
  }
  function setBatchDate(date, selected) {
    const batch = state.batch; if (!batch || batch.mode !== 'dates' || $('planning-batch-dialog').dataset.busy || batchDateProblem(date)) return;
    if (selected) batch.dates.add(date); else batch.dates.delete(date);
    invalidateBatch(); updateBatchDates();
  }
  function batchDateClick(date) { if (!state.batch?.dateClickSuppressed) setBatchDate(date, !state.batch.dates.has(date)); }
  function beginBatchDate(date, event) {
    if (event.button !== 0 || !state.batch || $('planning-batch-dialog').dataset.busy || batchDateProblem(date)) return;
    event.preventDefault(); event.currentTarget.focus({preventScroll: true}); state.batch.dateClickSuppressed = true;
    state.batch.dateGesture = {selected: !state.batch.dates.has(date)}; setBatchDate(date, state.batch.dateGesture.selected);
  }
  function extendBatchDate(date) { if (state.batch?.dateGesture) setBatchDate(date, state.batch.dateGesture.selected); }
  function batchDateKey(date, event) {
    const shifts = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7}; if (!(event.key in shifts)) return;
    let targetDate = addDays(date, shifts[event.key]);
    for (let step = 0; step < 741; step++, targetDate = addDays(targetDate, shifts[event.key])) {
      const target = $('planning-batch-date-months').querySelector('[data-batch-date="' + targetDate + '"]'); if (!target) return;
      if (!target.disabled) { event.preventDefault(); target.focus(); return; }
    }
  }
  function renderBatchDateCalendar() {
    const container = $('planning-batch-date-months'), batch = state.batch; container.replaceChildren();
    $('planning-batch-date-loading').hidden = !batch?.calendarLoading;
    $('planning-batch-date-retry').hidden = !!batch?.calendar || !!batch?.calendarLoading;
    if (!batch?.calendar) { updateBatchDates(); return; }
    const promotion = batch.calendar.promotion, start = promotion.date_debut, end = promotion.date_fin;
    const map = new Map((batch.calendar.days || []).map(day => [day.date, day])), cursor = parseDate(start); cursor.setDate(1); const lastDate = parseDate(end);
    for (let index = 0; cursor <= lastDate && index < 36; index++, cursor.setMonth(cursor.getMonth() + 1)) {
      const year = cursor.getFullYear(), month = cursor.getMonth(), block = el('article', 'planning-batch-month'); block.append(el('h3', '', cursor.toLocaleDateString('fr-FR', {month: 'long', year: 'numeric'}))); const grid = el('div', 'planning-month-grid');
      for (const name of ['L', 'M', 'M', 'J', 'V', 'S', 'D']) grid.append(el('span', 'planning-month-weekday', name));
      for (let gap = 0; gap < (cursor.getDay() + 6) % 7; gap++) grid.append(el('span', 'planning-month-blank'));
      for (let day = 1; day <= new Date(year, month + 1, 0).getDate(); day++) {
        const date = dateString(new Date(year, month, day, 12)), info = map.get(date), reason = batchDateProblem(date), cell = button(String(day), 'planning-batch-day kind-' + (info?.kind || 'closed'), () => batchDateClick(date)); cell.dataset.batchDate = date; cell.disabled = !!reason;
        cell.title = formatDate(date, {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'}) + ' · ' + (reason || 'Journée école · Choisir pour dupliquer le cours.'); cell.setAttribute('aria-label', cell.title); cell.setAttribute('aria-pressed', String(batch.dates.has(date)));
        cell.addEventListener('pointerdown', event => beginBatchDate(date, event)); cell.addEventListener('pointerenter', () => extendBatchDate(date)); cell.addEventListener('keydown', event => batchDateKey(date, event)); grid.append(cell);
      }
      block.append(grid); container.append(block);
    }
    updateBatchDates();
  }
  function batchWeekProblem(week) {
    const batch = state.batch, promotion = batch?.calendar?.promotion;
    if (!promotion || week < monday(promotion.date_debut) || week > monday(promotion.date_fin)) return 'En dehors des dates de la promotion.';
    if (week === batch.sourceWeek) return 'Semaine source : elle ne peut pas être dupliquée sur elle-même.';
    return '';
  }
  function updateBatchWeeks() {
    const batch = state.batch; if (!batch) return;
    const weeks = [...(batch.weeks || [])].sort();
    $('planning-batch-week-count').textContent = weeks.length + ' semaine' + (weeks.length !== 1 ? 's' : '') + ' sélectionnée' + (weeks.length !== 1 ? 's' : '');
    $('planning-batch-week-selected').textContent = weeks.length ? weeks.map(week => 'Du ' + formatDate(week, {day: 'numeric', month: 'short'}) + ' au ' + formatDate(addDays(week, 6), {day: 'numeric', month: 'short', year: 'numeric'})).join(' · ') : 'Choisissez les semaines dans le calendrier.';
    $('planning-batch-week-clear').disabled = !weeks.length;
    $('planning-batch-week-months').querySelectorAll('[data-batch-week]').forEach(cell => { const selected = batch.weeks.has(cell.dataset.batchWeek); cell.classList.toggle('is-selected', selected); cell.setAttribute('aria-pressed', String(selected)); });
    if (batch.mode === 'weeks') $('planning-batch-preview').disabled = batch.calendarLoading || !batch.calendar || !weeks.length;
    updateBatchCommit();
  }
  function setBatchWeek(week, selected) {
    const batch = state.batch; if (!batch || batch.mode !== 'weeks' || $('planning-batch-dialog').dataset.busy || batchWeekProblem(week)) return;
    if (selected) batch.weeks.add(week); else batch.weeks.delete(week);
    invalidateBatch(); updateBatchWeeks();
  }
  function batchWeekClick(week) { if (!state.batch?.weekClickSuppressed) setBatchWeek(week, !state.batch.weeks.has(week)); }
  function beginBatchWeek(week, event) {
    if (event.button !== 0 || !state.batch || $('planning-batch-dialog').dataset.busy || batchWeekProblem(week)) return;
    event.preventDefault(); event.currentTarget.focus({preventScroll: true}); state.batch.weekClickSuppressed = true;
    state.batch.weekGesture = {selected: !state.batch.weeks.has(week)}; setBatchWeek(week, state.batch.weekGesture.selected);
  }
  function extendBatchWeek(week) { if (state.batch?.weekGesture) setBatchWeek(week, state.batch.weekGesture.selected); }
  function batchWeekKey(week, event) {
    const shifts = {ArrowUp: -7, ArrowDown: 7, ArrowLeft: -7, ArrowRight: 7}; if (!(event.key in shifts)) return;
    let next = addDays(week, shifts[event.key]);
    for (let step = 0; step < 160; step++, next = addDays(next, shifts[event.key])) {
      const target = $('planning-batch-week-months').querySelector('[data-batch-week="' + next + '"]');
      if (!target) return; if (!target.disabled) { event.preventDefault(); target.focus(); return; }
    }
  }
  function renderBatchWeekCalendar() {
    const container = $('planning-batch-week-months'), batch = state.batch; container.replaceChildren();
    $('planning-batch-week-loading').hidden = !batch?.calendarLoading;
    $('planning-batch-week-retry').hidden = !!batch?.calendar || !!batch?.calendarLoading;
    if (!batch?.calendar) { updateBatchWeeks(); return; }
    const promotion = batch.calendar.promotion, map = new Map((batch.calendar.days || []).map(day => [day.date, day]));
    const cursor = parseDate(promotion.date_debut); cursor.setDate(1); const last = parseDate(promotion.date_fin);
    for (let index = 0; cursor <= last && index < 36; index++, cursor.setMonth(cursor.getMonth() + 1)) {
      const year = cursor.getFullYear(), month = cursor.getMonth(), block = el('article', 'planning-batch-month planning-week-month');
      block.append(el('h3', '', cursor.toLocaleDateString('fr-FR', {month: 'long', year: 'numeric'})));
      const header = el('div', 'planning-batch-weekdays'); header.append(el('span', '', 'Sem.')); for (const day of ['L', 'M', 'M', 'J', 'V', 'S', 'D']) header.append(el('span', '', day)); block.append(header);
      for (let week = monday(dateString(cursor)); week <= dateString(new Date(year, month + 1, 0, 12)); week = addDays(week, 7)) {
        const reason = batchWeekProblem(week), label = 'Semaine du ' + formatDate(week, {day: 'numeric', month: 'long', year: 'numeric'}) + ' au ' + formatDate(addDays(week, 6));
        const row = button('', 'planning-batch-week', () => batchWeekClick(week)); row.dataset.batchWeek = week; row.disabled = !!reason;
        row.setAttribute('aria-pressed', 'false'); row.setAttribute('aria-label', label + (reason ? ' · ' + reason : '')); row.title = reason || label;
        const check = el('span', 'planning-batch-week-check', '✓'); check.setAttribute('aria-hidden', 'true'); row.append(check);
        for (let day = 0; day < 7; day++) { const date = addDays(week, day), info = map.get(date), value = parseDate(date), cell = el('span', 'kind-' + (info?.kind || 'outside') + (value.getMonth() !== month ? ' is-adjacent' : ''), value.getDate()); cell.title = formatDate(date) + ' · ' + (info?.label || kinds[info?.kind] || 'Hors promotion'); cell.setAttribute('aria-hidden', 'true'); row.append(cell); }
        if (!reason) { row.addEventListener('pointerdown', event => beginBatchWeek(week, event)); row.addEventListener('pointerenter', () => extendBatchWeek(week)); row.addEventListener('keydown', event => batchWeekKey(week, event)); }
        block.append(row);
      }
      container.append(block);
    }
    updateBatchWeeks();
  }
  async function loadBatchDateCalendar(batch) {
    if (!batch || batch.calendarLoading) return;
    const id = batch.course?.promotion_id || batch.promotionId;
    const promotion = catalogPromotions().find(item => String(item.id) === String(id));
    if (!promotion?.date_debut || !promotion?.date_fin) { formError($('planning-batch-form'), 'Complétez les dates de cette promotion avant de dupliquer les cours.'); return; }
    batch.calendarLoading = true; renderBatchDateCalendar(); renderBatchWeekCalendar();
    try {
      const calendar = await request('/state?' + new URLSearchParams({promotion_id: id, start: promotion.date_debut, end: promotion.date_fin}));
      if (state.batch !== batch) return; batch.calendar = calendar;
    } catch (failure) { if (state.batch === batch) formError($('planning-batch-form'), failure.message); }
    finally { if (state.batch === batch) { batch.calendarLoading = false; renderBatchDateCalendar(); renderBatchWeekCalendar(); } }
  }
  function setBatchMode(mode) {
    if (!state.batch || $('planning-batch-dialog').dataset.busy) return;
    state.batch.mode = state.batch.course ? (mode === 'repeat' ? 'repeat' : 'dates') : 'weeks';
    const form = $('planning-batch-form');
    for (const [field, active] of [['repeat', state.batch.mode === 'repeat']]) {
      const section = $('planning-batch-' + field + '-fields'); section.hidden = !active; section.querySelectorAll('input,select').forEach(input => { input.disabled = !active; });
    }
    $('planning-batch-weeks-fields').hidden = state.batch.mode !== 'weeks'; $('planning-batch-dates-fields').hidden = state.batch.mode !== 'dates'; $('planning-batch-mode-switch').hidden = !state.batch.course;
    $('planning-batch-mode-dates').setAttribute('aria-pressed', String(state.batch.mode === 'dates')); $('planning-batch-mode-repeat').setAttribute('aria-pressed', String(state.batch.mode === 'repeat'));
    form.elements.start_date.required = form.elements.end_date.required = state.batch.mode === 'repeat';
    invalidateBatch(); updateBatchDates(); updateBatchWeeks();
  }
  function openBatch(course = null) {
    if (!state.data || state.loading) return; if (!course && !state.data.courses?.some(c => c.kind !== 'event')) { notice('Cette semaine ne contient aucun cours à dupliquer.'); return; }
    state.batch = {mode: course ? 'dates' : 'weeks', course, sourceWeek: state.week, promotionId: promotionId(), preview: null, dates: new Set(), weeks: new Set(), calendar: null, calendarLoading: false}; const form = $('planning-batch-form'); form.reset();
    const promotion = catalogPromotions().find(item => String(item.id) === String(course?.promotion_id || promotionId())) || state.data.promotion;
    for (const input of form.querySelectorAll('input[type=date]')) { input.min = promotion.date_debut || ''; input.max = promotion.date_fin || ''; }
    form.elements.start_date.value = course ? addDays(course.date, 7) : state.week; form.elements.end_date.value = promotion.date_fin || addDays(state.week, 35);
    setWeekdays(form, course ? [(parseDate(course.date).getDay() + 6) % 7] : []);
    $('planning-batch-source').textContent = course ? courseName(course) + ' · ' + course.start + ' – ' + course.end + ' · ' + (course.trainer_name || 'Formateur affecté') + ' · ' + (course.room_name || 'Salle à affecter') : 'Dupliquer tous les cours du ' + formatDate(state.week) + ' au ' + formatDate(addDays(state.week, 6)) + '. Le décalage conserve les jours et les horaires. Les événements ponctuels ne sont pas dupliqués.';
    $('planning-batch-title').innerHTML = course ? 'Répéter les <em>bons créneaux.</em>' : 'Dupliquer vos <em>semaines.</em>';
    setBatchMode(state.batch.mode); renderBatchDateCalendar(); renderBatchWeekCalendar(); openDialog('planning-batch-dialog', course ? $('planning-batch-mode-dates') : $('planning-batch-week-clear'));
    loadBatchDateCalendar(state.batch);
  }
  function invalidateBatch() { if (state.batch) state.batch.preview = null; $('planning-batch-results').hidden = true; $('planning-batch-skip').checked = false; updateBatchCommit(); }
  $('planning-batch-mode-dates').addEventListener('click', () => setBatchMode('dates'));
  $('planning-batch-mode-repeat').addEventListener('click', () => setBatchMode('repeat'));
  $('planning-batch-date-clear').addEventListener('click', () => { if (state.batch && !$('planning-batch-dialog').dataset.busy) { state.batch.dates.clear(); invalidateBatch(); updateBatchDates(); } });
  $('planning-batch-week-clear').addEventListener('click', () => { if (state.batch && !$('planning-batch-dialog').dataset.busy) { state.batch.weeks.clear(); invalidateBatch(); updateBatchWeeks(); } });
  $('planning-batch-week-retry').addEventListener('click', () => loadBatchDateCalendar(state.batch));
  $('planning-batch-date-retry').addEventListener('click', () => loadBatchDateCalendar(state.batch));
  $('planning-batch-form').addEventListener('input', event => { if (!event.target.closest('#planning-batch-results')) invalidateBatch(); });
  function batchPreviewPayload(form) {
    const batch = state.batch, data = {promotion_id: batch.course?.promotion_id || promotionId(), mode: batch.mode};
    if (batch.mode === 'dates') {
      if (batch.calendarLoading || !batch.calendar || !batch.dates.size) throw Error('Choisissez au moins une journée école dans le calendrier.');
      Object.assign(data, {dates: [...batch.dates].sort(), source_course_id: batch.course.id, source_version: batch.course.version});
    } else if (batch.mode === 'repeat') {
      const course = batch.course; Object.assign(data, {start_date: form.elements.start_date.value, end_date: form.elements.end_date.value, weekdays: selectedWeekdays(form), interval_weeks: Number(form.elements.interval_weeks.value), template: {zoom_url: course.zoom_url || '', subject_id: course.subject_id, trainer_id: course.trainer_id, room_id: course.room_id || null, start: course.start, end: course.end, title: course.title || '', shared: course.shared || []}});
      if (!data.weekdays.length) throw Error('Sélectionnez au moins un jour à répéter.');
    } else if (batch.mode === 'weeks') {
      if (batch.calendarLoading || !batch.calendar || !batch.weeks.size) throw Error('Choisissez au moins une semaine dans le calendrier.');
      Object.assign(data, {promotion_id: batch.promotionId, source_start: batch.sourceWeek, target_weeks: [...batch.weeks].sort()});
    }
    return data;
  }
  $('planning-batch-form').addEventListener('submit', async event => {
    event.preventDefault(); const form = event.currentTarget, dialog = form.closest('dialog'); if (dialog.dataset.busy || !form.reportValidity() || !state.batch) return; formError(form, '');
    let data; try { data = batchPreviewPayload(form); } catch (failure) { formError(form, failure.message); return; }
    busyDialog(dialog, true); invalidateBatch();
    try {
      const preview = await request('/courses/preview', {method: 'POST', data}); state.batch.preview = preview; renderBatchPreview(preview);
    } catch (failure) { formError(form, failure.message); }
    finally { busyDialog(dialog, false); updateBatchCommit(); }
  });
  function renderBatchPreview(preview) {
    const container = $('planning-batch-items'); container.replaceChildren(); let conflicts = 0;
    for (const item of preview.items || []) {
      const course = item.course, recoverable = !item.valid && (item.conflicts || []).length > 0 && item.conflicts.every(issue => issue.type === 'subject_budget' && Number(issue.pending_minutes) > 0), label = el('label', 'planning-batch-item' + (!item.valid ? ' has-conflict' : '')); const checkbox = el('input'); checkbox.type = 'checkbox'; checkbox.value = String(item.key); checkbox.checked = !!item.valid; checkbox.disabled = !item.valid; checkbox.dataset.budgetEligible = item.valid || recoverable ? '1' : '0'; checkbox.addEventListener('change', updateBatchCommit);
      const detail = el('span'); detail.append(el('b', '', formatDate(course.date, {weekday: 'short', day: 'numeric', month: 'short', year: 'numeric'}) + ' · ' + course.start + ' – ' + course.end), el('small', '', item.valid ? courseName(course) + ' · Disponible' : recoverable ? 'Décochez une autre occurrence pour libérer le volume nécessaire, puis sélectionnez celle-ci.' : (item.conflicts || []).map(conflict => conflict.message).join(' · ')));
      if (!item.valid) conflicts++; label.append(checkbox, detail); container.append(label);
    }
    $('planning-batch-results-help').textContent = state.batch?.mode === 'weeks' ? 'Les cours cochés seront dupliqués. Les cours bloqués sont automatiquement exclus, sans empêcher la copie des autres. Si un nouveau blocage apparaît avant l’enregistrement, le cours concerné sera également laissé de côté.' : 'Seules les occurrences cochées seront créées. Aucun conflit n’est forcé. Décochez une occurrence pour libérer son volume et choisir une autre date. Les conflits de calendrier, de formateur ou de salle restent bloqués.';
    $('planning-batch-summary').textContent = (preview.items || []).length + ' cours vérifié(s) · ' + ((preview.items || []).length - conflicts) + ' disponible(s) · ' + conflicts + ' à laisser de côté'; $('planning-batch-conflict-consent').hidden = conflicts === 0; $('planning-batch-skip').checked = false; $('planning-batch-results').hidden = false; updateBatchCommit();
  }
  function batchBudgetStatus(preview, selectedKeys) {
    const totals = new Map(), limits = new Map();
    const groups = course => course.groups?.length ? course.groups : [{subject_id: course.subject_id}, ...(course.shared || [])];
    for (const subject of preview?.budgets || catalogSubjects()) limits.set(String(subject.id), subjectBudget(subject).remaining);
    for (const item of preview?.items || []) for (const issue of item.conflicts || []) if (issue.type === 'subject_budget') limits.set(String(issue.subject_id), Number(issue.planned_minutes) - Number(issue.scheduled_minutes));
    for (const item of preview?.items || []) if (selectedKeys.has(String(item.key))) for (const id of new Set(groups(item.course).map(group => String(group.subject_id)))) totals.set(id, (totals.get(id) || 0) + courseDuration(item.course));
    const withinBudget = [...totals].every(([id, total]) => limits.has(id) && total <= limits.get(id));
    return {withinBudget, canAdd: item => [...new Set(groups(item.course).map(group => String(group.subject_id)))].every(id => limits.has(id) && (totals.get(id) || 0) + courseDuration(item.course) <= limits.get(id))};
  }
  function updateBatchCommit() {
    const batch = state.batch, preview = batch?.preview, control = $('planning-batch-commit'), help = $('planning-batch-action-help'), busy = !!$('planning-batch-dialog').dataset.busy;
    if (!preview) {
      const form = $('planning-batch-form'), calendarMode = batch?.mode === 'weeks' || batch?.mode === 'dates';
      const selectedCount = batch?.mode === 'weeks' ? batch.weeks.size : batch?.dates?.size || 0;
      const ready = calendarMode ? !!batch.calendar && !batch.calendarLoading && selectedCount > 0 : !!batch && !!form.elements.start_date.value && !!form.elements.end_date.value && selectedWeekdays(form).length > 0;
      control.disabled = busy || !ready;
      control.textContent = busy ? 'Vérification en cours…' : batch?.mode === 'weeks' ? 'Vérifier les semaines choisies' : 'Vérifier les dates choisies';
      help.textContent = busy ? 'Les disponibilités et les volumes sont en cours de vérification.' : batch?.calendarLoading ? 'Le calendrier est en cours de chargement.' : !ready ? (batch?.mode === 'weeks' ? 'Sélectionnez au moins une semaine dans le calendrier.' : batch?.mode === 'dates' ? 'Sélectionnez au moins un jour dans le calendrier.' : 'Choisissez les dates et au moins un jour de répétition.') : 'Vérifiez votre sélection, puis confirmez les cours disponibles.';
      return;
    }
    const inputs = [...$('planning-batch-items').querySelectorAll('input')], selectedKeys = new Set(inputs.filter(input => input.checked).map(input => input.value));
    const budget = batchBudgetStatus(preview, selectedKeys);
    for (const input of inputs) { const item = preview.items?.find(item => String(item.key) === input.value); if (item && input.dataset.budgetEligible === '1') input.disabled = busy || (!input.checked && !budget.canAdd(item)); }
    const excludedConflicts = preview.items?.some(item => !item.valid && !selectedKeys.has(String(item.key)));
    const needsConsent = batch.mode !== 'weeks' && !!excludedConflicts && !$('planning-batch-skip').checked;
    $('planning-batch-conflict-consent').hidden = !excludedConflicts || batch.mode === 'weeks';
    control.disabled = busy || selectedKeys.size === 0 || !budget.withinBudget || needsConsent;
    control.textContent = busy ? 'Traitement en cours…' : 'Créer ' + selectedKeys.size + ' cours';
    help.textContent = busy ? 'Votre demande est en cours de traitement.' : selectedKeys.size === 0 ? (preview.items?.some(item => item.valid) ? 'Cochez au moins un cours disponible dans les résultats.' : 'Aucun cours ne peut être créé : les motifs sont indiqués dans les résultats. Choisissez d’autres dates ou corrigez ces blocages.') : !budget.withinBudget ? 'La sélection dépasse les heures disponibles. Décochez des cours ou relancez la vérification pour actualiser les volumes.' : needsConsent ? 'Cochez la confirmation ci-dessus pour laisser les cours en conflit de côté.' : selectedKeys.size + ' cours prêt' + (selectedKeys.size > 1 ? 's' : '') + ' à créer.' + (excludedConflicts ? ' Les cours bloqués seront laissés de côté.' : '');
  }
  $('planning-batch-skip').addEventListener('change', updateBatchCommit);
  $('planning-batch-commit').addEventListener('click', async () => {
    const preview = state.batch?.preview, dialog = $('planning-batch-dialog'), form = $('planning-batch-form'); if (dialog.dataset.busy || $('planning-batch-commit').disabled) return;
    if (!preview) { form.requestSubmit($('planning-batch-preview')); return; }
    const selected_keys = [...$('planning-batch-items').querySelectorAll('input:checked:not(:disabled)')].map(input => input.value); busyDialog(dialog, true); formError(form, '');
    try { const result = await request('/courses/batch', {method: 'POST', data: {preview_token: preview.preview_token, selected_keys}}); const weeksMode = state.batch?.mode === 'weeks'; dialog.close(); if ($('planning-course-dialog').open) $('planning-course-dialog').close(); notice(result.message || 'Les occurrences sélectionnées ont été créées.'); await loadState(); if (weeksMode) showBatchReport(preview, selected_keys, result); }
    catch (failure) { formError(form, failure.message + '\nVérifiez à nouveau les créneaux avant de réessayer.'); invalidateBatch(); }
    finally { busyDialog(dialog, false); updateBatchCommit(); }
  });
  function batchReportData(preview, selectedKeys, result) {
    const selected = new Set(selectedKeys.map(String)), skipped = new Map();
    for (const item of preview.items || []) if (!item.valid && !selected.has(String(item.key))) skipped.set(String(item.key), item);
    for (const item of result.skipped || []) skipped.set(String(item.key), item);
    return {created: Number(result.count ?? result.summary?.created ?? result.course_ids?.length ?? 0), skipped: [...skipped.values()]};
  }
  function showBatchReport(preview, selectedKeys, result) {
    const report = batchReportData(preview, selectedKeys, result), summary = $('planning-batch-report-summary'); summary.replaceChildren();
    for (const [value, label] of [[report.created, 'cours créé' + (report.created !== 1 ? 's' : '')], [report.skipped.length, 'cours laissé' + (report.skipped.length !== 1 ? 's' : '') + ' de côté']]) { const card = el('div'); card.append(el('strong', '', value), el('span', '', label)); summary.append(card); }
    const list = $('planning-batch-report-items'); list.replaceChildren();
    if (report.skipped.length) { list.append(el('h3', '', 'Les cours qui demandent votre attention')); for (const item of report.skipped) { const course = item.course || {}, row = el('article', 'planning-batch-report-item'); row.append(el('b', '', (course.date ? formatDate(course.date, {weekday: 'long', day: 'numeric', month: 'long', year: 'numeric'}) : 'Date à vérifier') + ' · ' + (course.start || '') + ' – ' + (course.end || '')), el('span', '', courseName(course)), el('p', '', (item.conflicts || []).map(issue => issue.message).join(' · ') || 'Ce cours n’a pas pu être dupliqué.')); list.append(row); } }
    else list.append(el('p', 'planning-batch-report-success', 'Tous les cours sélectionnés ont été dupliqués. Vous pouvez continuer à organiser vos semaines.'));
    openDialog('planning-batch-report-dialog');
  }
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
  $('planning-promotion').addEventListener('change', event => {
    const next = event.target.value, previous = String(state.data?.promotion?.id || ''); event.target.value = previous;
    navigatePlanning(() => { event.target.value = next; notice(''); state.periodId = ''; state.slot = null; state.quickShared = []; state.slotChecks.clear(); state.subject = ''; state.availability.clear(); state.availabilityReady = false; state.week = monday(today()); const url = new URL(location.href); if (next) url.searchParams.set('promotion_id', next); else url.searchParams.delete('promotion_id'); url.searchParams.delete('promotion'); url.searchParams.delete('period_id'); history.replaceState(null, '', url); loadState({initial: true}); });
  });
  $('planning-import-open')?.addEventListener('click', () => {
    if (!state.data?.period || state.loading) { notice('Sélectionnez une promotion et une année avant d’importer un planning.', true); return; }
    navigatePlanning(() => { location.href = '/admin/planning/import?' + new URLSearchParams({promotion_id: promotionId(), period_id: state.periodId}); });
  });
  $('planning-school-year').addEventListener('change', event => {
    const next = event.target.value, period = state.data?.periods.find(item => item.id === next); event.target.value = state.periodId;
    if (!period || state.loading || state.quickBusy) return;
    navigatePlanning(() => { state.periodId = next; state.slot = null; state.quickShared = []; state.slotChecks.clear(); state.subject = ''; state.year = null; state.week = monday(period.start_date); notice(''); const url = new URL(location.href); url.searchParams.set('period_id', next); history.replaceState(null, '', url); loadState(); });
  });
  $('planning-view-week').addEventListener('click', () => navigatePlanning(() => selectView('week'))); $('planning-view-year').addEventListener('click', () => selectView('year'));
  $('planning-step-calendar').addEventListener('click', () => selectView('year')); $('planning-step-subjects').addEventListener('click', () => navigatePlanning(() => { selectView('week'); openSubject(); })); $('planning-step-courses').addEventListener('click', () => navigatePlanning(() => { selectView('week'); $('planning-slot-form').elements.date.focus(); }));
  const goToWeek = date => navigatePlanning(() => { clearSlot(); state.quickShared = []; const period = state.data?.period; const bounded = period ? (date < period.start_date ? period.start_date : date > period.end_date ? period.end_date : date) : date; state.week = monday(bounded); selectView('week'); loadState(); });
  $('planning-date-open').addEventListener('click', openDatePicker);
  $('planning-month-prev').addEventListener('click', () => shiftPickerMonth(-1));
  $('planning-month-next').addEventListener('click', () => shiftPickerMonth(1));
  for (const id of ['planning-month', 'planning-month-year']) $(id).addEventListener('change', () => {
    state.dateMonth = $('planning-month-year').value + '-' + String(Number($('planning-month').value) + 1).padStart(2, '0') + '-01'; renderDatePicker();
  });
  for (const id of ['planning-course-prev', 'planning-course-next']) $(id).addEventListener('click', () => { if ($(id).dataset.date) pickPlanningDate($(id).dataset.date); });
  $('planning-mini-days').addEventListener('keydown', event => {
    const date = event.target.dataset.date; if (!date) return;
    const steps = {ArrowLeft: -1, ArrowRight: 1, ArrowUp: -7, ArrowDown: 7};
    let next;
    if (event.key in steps) next = addDays(date, steps[event.key]);
    else if (event.key === 'Home') next = monday(date);
    else if (event.key === 'End') next = addDays(monday(date), 6);
    else if (event.key === 'PageUp' || event.key === 'PageDown') {
      const target = parseDate(date), day = target.getDate(); target.setDate(1); target.setMonth(target.getMonth() + (event.key === 'PageUp' ? -1 : 1));
      target.setDate(Math.min(day, new Date(target.getFullYear(), target.getMonth() + 1, 0).getDate())); next = dateString(target);
    } else return;
    event.preventDefault(); if (next < state.data.promotion.date_debut || next > state.data.promotion.date_fin) return; state.dateMonth = next.slice(0, 7) + '-01'; renderDatePicker(next);
  });
  $('planning-prev').addEventListener('click', () => goToWeek(addDays(state.week, -7))); $('planning-next').addEventListener('click', () => goToWeek(addDays(state.week, 7))); $('planning-today').addEventListener('click', () => goToWeek(today())); $('planning-date').addEventListener('change', event => { if (event.target.value) goToWeek(event.target.value); });
  $('planning-subject-search').addEventListener('input', renderSubjects); $('planning-subject-new').addEventListener('click', () => openSubject()); $('planning-duration').addEventListener('change', loadAvailability); $('planning-room').addEventListener('change', () => { state.availabilitySeq++; state.availabilityReady = false; if (state.slot) checkSelectedSlot(); else loadAvailability(); }); $('planning-selection-clear').addEventListener('click', () => { state.subject = ''; state.availabilitySeq++; state.availability.clear(); state.availabilityReady = false; renderSubjects(); renderAvailability(); });
  $('planning-slot-form').addEventListener('input', () => { state.slotFormDirty = true; $('planning-slot-clear').hidden = false; });
  $('planning-slot-form').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; if (!form.reportValidity()) return; if (form.elements.start.value >= form.elements.end.value) { notice('Choisissez une heure de fin après l’heure de début.', true); return; } setSlot(form.elements.date.value, form.elements.start.value, form.elements.end.value); });
  $('planning-slot-clear').addEventListener('click', () => { if (!state.quickBusy) clearSlot(); });
  $('planning-quick-shared-add').addEventListener('click', () => { if (state.quickBusy) return; state.quickShared.push({promotion_id: '', subject_id: ''}); renderSharedRows($('planning-quick-shared'), state.quickShared, promotionId(), onQuickSharedChange); onQuickSharedChange(); });
  $('planning-course-shared-add').addEventListener('click', () => { state.courseShared.push({promotion_id: '', subject_id: ''}); renderSharedRows($('planning-course-shared'), state.courseShared, state.courseEdit?.promotion_id || promotionId(), courseSharedChanged); courseSharedChanged(); });
  document.querySelectorAll('[data-paint-kind]').forEach(control => control.addEventListener('click', () => { state.paintKind = control.dataset.paintKind; document.querySelectorAll('[data-paint-kind]').forEach(item => item.setAttribute('aria-pressed', String(item === control))); renderPaintDraft(); }));
  $('planning-paint-range').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; if (form.reportValidity()) applyPaintRange(form.elements.start.value, form.elements.end.value); });
  $('planning-paint-cancel').addEventListener('click', cancelPaint); $('planning-paint-save').addEventListener('click', savePaint); $('planning-paint-refresh').addEventListener('click', refreshPaint);
  window.addEventListener('beforeunload', event => { if (state.paintDraft.size) { event.preventDefault(); event.returnValue = ''; } });
  $('planning-period-new').addEventListener('click', () => openPeriod()); $('planning-exception-open').addEventListener('click', () => openException()); $('planning-course-new').addEventListener('click', () => openCourse()); $('planning-duplicate-week').addEventListener('click', () => openBatch()); $('planning-course-repeat').addEventListener('click', () => { if (state.courseEdit) openBatch(state.courseEdit); });
  $('planning-rooms-open').addEventListener('click', () => { if (!state.data || state.loading || state.quickBusy) return; resetRoom(); renderRooms(); openDialog('planning-rooms-dialog', $('planning-room-form').elements.name); });
  $('planning-export-open').addEventListener('click', () => { if (!promotionId() || !state.data) return; if (state.paintDraft.size) { notice('Enregistrez ou annulez le brouillon avant d’exporter.'); return; } const form = $('planning-export-form'); dateLimits(form); form.elements.view.value = state.view === 'year' ? 'annual' : 'weekly'; form.elements.start.value = state.view === 'year' ? state.data.promotion.date_debut || state.week : (state.week < state.data.promotion.date_debut ? state.data.promotion.date_debut : state.week); form.elements.end.value = state.view === 'year' ? state.data.promotion.date_fin || addDays(state.week, 6) : (addDays(state.week, 6) > state.data.promotion.date_fin ? state.data.promotion.date_fin : addDays(state.week, 6)); openDialog('planning-export-dialog', form.elements.start); });
  $('planning-export-form').elements.view.addEventListener('change', event => { const form = $('planning-export-form'), annual = event.target.value === 'annual'; form.elements.start.value = annual ? state.data.promotion.date_debut || state.week : (state.week < state.data.promotion.date_debut ? state.data.promotion.date_debut : state.week); form.elements.end.value = annual ? state.data.promotion.date_fin || addDays(state.week, 6) : (addDays(state.week, 6) > state.data.promotion.date_fin ? state.data.promotion.date_fin : addDays(state.week, 6)); });
  $('planning-export-form').addEventListener('submit', event => { event.preventDefault(); const form = event.currentTarget; if (!form.reportValidity()) return; if (form.elements.start.value > form.elements.end.value) { formError(form, 'La date de fin doit suivre la date de début.'); return; } const query = new URLSearchParams({promotion_id: promotionId(), period_id: state.periodId || '', start: form.elements.start.value, end: form.elements.end.value, view: form.elements.view.value}); window.open('/admin/planning/export.pdf?' + query, '_blank', 'noopener'); });
  window.AcademyPlanning = {getState: () => state, request, refresh: loadState, notice, promotionId, openCourse};
  state.periodId = new URL(location.href).searchParams.get('period_id') || '';
  loadState({initial: true});
})();

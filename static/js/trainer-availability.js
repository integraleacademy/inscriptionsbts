/* A selection remains local until the trainer reviews and confirms the preview. */
(function () {
  'use strict';
  const app = document.querySelector('[data-trainer-availability]');
  const configNode = document.getElementById('trainer-availability-config');
  if (!app || !configNode) return;
  let config;
  try { config = JSON.parse(configNode.textContent); } catch (_) { return; }
  const $ = id => document.getElementById(id);
  const months = $('ta-months'), dialog = $('ta-confirm-dialog');
  const selection = new Set();
  let data = config.state || { year: config.year, days: [] };
  let dayMap = new Map(), action = 'unavailable', busy = false, preview = null;
  let requestNumber = 0, drag = null, ignoreClick = false, anchor = null, returnFocus = null;
  const monthFormatter = new Intl.DateTimeFormat('fr-FR', { month: 'long', timeZone: 'UTC' });
  const dateFormatter = new Intl.DateTimeFormat('fr-FR', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
  const shortFormatter = new Intl.DateTimeFormat('fr-FR', { day: 'numeric', month: 'long', timeZone: 'UTC' });
  const dateObject = date => new Date(date + 'T12:00:00Z');
  const iso = date => date.toISOString().slice(0, 10);
  const label = date => dateFormatter.format(dateObject(date));
  const isOpen = () => dialog.open || dialog.hasAttribute('open');

  function notice(message, error = false) {
    const node = $('ta-notice');
    node.textContent = message;
    node.classList.toggle('ta-error', error);
    node.hidden = !message;
  }

  function selectable(day) {
    if (!day || busy) return false;
    if (action === 'available') return !!day.own_unavailable;
    return !day.public_holiday && !day.own_unavailable &&
      !(day.admin_unavailable && !day.partial) && day.date >= (data.min_date || data.today || '1900-01-01');
  }

  function updateSelection() {
    app.dataset.action = action;
    app.dataset.dirty = selection.size ? 'true' : 'false';
    const count = selection.size;
    $('ta-selection-count').textContent = count ? count + ' jour' + (count > 1 ? 's' : '') + ' sélectionné' + (count > 1 ? 's' : '') : 'Aucun jour sélectionné';
    $('ta-selection-hint').textContent = action === 'unavailable'
      ? 'Les cours déjà programmés vous seront signalés avant toute suppression.'
      : 'Seuls vos blocages personnels seront retirés. Les cours supprimés ne sont pas recréés.';
    $('ta-save').disabled = busy || !count;
    $('ta-clear').disabled = busy || !count;
    $('ta-previous').disabled = busy || !!count || Number(data.year) <= 1900;
    $('ta-next').disabled = busy || !!count || Number(data.year) >= 2200;
    $('ta-year-select').disabled = busy || !!count;
    $('ta-year-submit').disabled = busy || !!count;
    document.querySelectorAll('[data-ta-action]').forEach(button => {
      const active = button.dataset.taAction === action;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', String(active));
      button.disabled = busy || (!!count && !active);
    });
    months.querySelectorAll('[data-ta-date]').forEach(button => {
      const selected = selection.has(button.dataset.taDate);
      button.classList.toggle('is-selected', selected);
      button.setAttribute('aria-pressed', String(selected));
      button.disabled = !selectable(dayMap.get(button.dataset.taDate));
    });
    $('ta-instructions').textContent = action === 'unavailable'
      ? 'Cliquez sur les jours où vous êtes indisponible, ou faites glisser pour en sélectionner plusieurs. Vos choix seront appliqués après enregistrement.'
      : 'Sélectionnez vos jours d’indisponibilité pour les libérer. Les blocages de l’équipe pédagogique resteront en place.';
  }

  function render() {
    dayMap = new Map((data.days || []).map(day => [day.date, day]));
    $('ta-calendar-title').textContent = String(data.year);
    $('ta-year-select').value = String(data.year);
    $('ta-month-select').value = '';
    months.replaceChildren();
    for (let month = 0; month < 12; month++) {
      const first = new Date(Date.UTC(Number(data.year), month, 1, 12));
      const section = document.createElement('section');
      section.className = 'ta-month';
      const heading = document.createElement('h3');
      heading.id = 'ta-month-' + month;
      heading.textContent = monthFormatter.format(first);
      section.setAttribute('aria-labelledby', heading.id);
      section.appendChild(heading);
      const grid = document.createElement('div');
      grid.className = 'ta-days';
      ['L', 'M', 'M', 'J', 'V', 'S', 'D'].forEach(text => {
        const weekday = document.createElement('span');
        weekday.className = 'ta-weekday'; weekday.setAttribute('aria-hidden', 'true'); weekday.textContent = text; grid.appendChild(weekday);
      });
      for (let blank = 0; blank < (first.getUTCDay() + 6) % 7; blank++) {
        const spacer = document.createElement('span'); spacer.setAttribute('aria-hidden', 'true'); grid.appendChild(spacer);
      }
      const count = new Date(Date.UTC(Number(data.year), month + 1, 0)).getUTCDate();
      for (let number = 1; number <= count; number++) {
        const date = iso(new Date(Date.UTC(Number(data.year), month, number, 12)));
        const day = dayMap.get(date) || { date };
        dayMap.set(date, day);
        const button = document.createElement('button');
        button.type = 'button'; button.className = 'ta-day'; button.dataset.taDate = date;
        button.textContent = String(number);
        const weekday = dateObject(date).getUTCDay();
        button.classList.toggle('is-weekend', weekday === 0 || weekday === 6);
        button.classList.toggle('is-own', !!day.own_unavailable);
        button.classList.toggle('is-admin', !!day.admin_unavailable);
        button.classList.toggle('is-holiday', !!day.public_holiday);
        button.classList.toggle('is-partial', !!day.partial);
        button.classList.toggle('has-course', Number(day.course_count) > 0);
        button.classList.toggle('is-past', date < (data.today || '1900-01-01'));
        button.classList.toggle('is-today', date === data.today);
        if (date === data.today) button.setAttribute('aria-current', 'date');
        const details = [label(date)];
        if (day.public_holiday) details.push('Jour férié : ' + day.public_holiday);
        if (day.own_unavailable) details.push('Votre indisponibilité');
        if (day.admin_unavailable) details.push(day.partial ? 'Indisponibilité partielle indiquée par l’équipe' : 'Indisponibilité indiquée par l’équipe');
        if (day.reason) details.push(day.reason);
        if (Number(day.course_count) > 0) details.push(day.course_count + ' cours programmé' + (Number(day.course_count) > 1 ? 's' : ''));
        if (!day.unavailable && !day.public_holiday) details.push('Disponible');
        button.title = details.join(' · ');
        button.setAttribute('aria-label', details.join('. '));
        grid.appendChild(button);
      }
      section.appendChild(grid); months.appendChild(section);
    }
    updateSelection();
  }

  function selectDate(date, selected) {
    if (!selectable(dayMap.get(date))) return;
    if (selected) selection.add(date); else selection.delete(date);
    preview = null;
  }

  function selectRange(first, last, selected) {
    const lower = first < last ? first : last, upper = first < last ? last : first;
    for (const date of dayMap.keys()) if (date >= lower && date <= upper) selectDate(date, selected);
  }

  async function request(url, payload) {
    const options = { credentials: 'same-origin', headers: { 'Accept': 'application/json' }, cache: 'no-store' };
    if (payload) {
      options.method = 'POST'; options.headers['Content-Type'] = 'application/json';
      options.headers['X-CSRF-Token'] = config.csrf_token;
      options.body = JSON.stringify(payload);
    }
    const response = await fetch(url, options);
    let result;
    try { result = await response.json(); } catch (_) { result = {}; }
    if (!response.ok || result.ok === false) {
      const error = new Error(result.message || result.error || 'La demande n’a pas pu être enregistrée. Réessayez après actualisation.');
      error.status = response.status; throw error;
    }
    return result;
  }

  function setBusy(value) {
    busy = value; app.setAttribute('aria-busy', String(value));
    dialog.querySelectorAll('button').forEach(button => { button.disabled = value; });
    updateSelection();
  }

  async function loadYear(year, quiet = false) {
    if (busy || selection.size || isOpen() || drag) return;
    const sequence = ++requestNumber;
    if (!quiet) { setBusy(true); $('ta-loading').hidden = false; }
    try {
      const url = new URL(config.state_url, window.location.href); url.searchParams.set('year', String(year));
      const result = await request(url.toString());
      if (sequence !== requestNumber) return;
      if (quiet && (selection.size || isOpen() || busy || drag)) return;
      data = result; if (result.csrf_token) config.csrf_token = result.csrf_token;
      render();
      return true;
    } catch (error) { if (sequence === requestNumber && !quiet) notice(error.message, true); }
    finally { if (sequence === requestNumber && !quiet) { $('ta-loading').hidden = true; setBusy(false); } }
  }

  function closeDialog() {
    if (busy) return;
    if (typeof dialog.close === 'function') dialog.close(); else dialog.removeAttribute('open');
    preview = null;
    if (returnFocus && returnFocus.isConnected) returnFocus.focus();
  }

  function showPreview(result) {
    preview = result;
    const courses = Array.isArray(result.courses) ? result.courses : [];
    const destructive = courses.length > 0;
    dialog.classList.toggle('is-routine', !destructive);
    $('ta-confirm-eyebrow').textContent = destructive ? 'DES COURS SONT DÉJÀ PROGRAMMÉS' : 'VÉRIFIONS ENSEMBLE';
    $('ta-confirm-title').textContent = destructive ? 'Attention à vos cours prévus.' : (action === 'available' ? 'Vous êtes de nouveau disponible.' : 'Ces dates sont pour vous.');
    const daysWithCourses = [...new Set(courses.map(course => course.date))].sort();
    const courseDates = daysWithCourses.slice(0, 3).map(date => shortFormatter.format(dateObject(date))).join(', ');
    $('ta-confirm-description').textContent = destructive
      ? 'Vous avez déjà des cours programmés le ' + courseDates + (daysWithCourses.length > 3 ? ' et à d’autres dates sélectionnées' : '') + '. Confirmez-vous cette indisponibilité ? Les cours ci-dessous seront supprimés de tous les plannings.'
      : action === 'available'
        ? 'Votre indisponibilité personnelle sera retirée sur ces dates. Les cours précédemment supprimés ne seront pas recréés.'
        : 'Ces jours seront bloqués pour vos prochaines interventions. Aucun cours programmé ne sera supprimé.';
    const dates = Array.isArray(result.dates) ? result.dates : [...selection].sort();
    $('ta-confirm-summary').textContent = dates.length + ' jour' + (dates.length > 1 ? 's' : '') + ' · ' + dates.map(date => shortFormatter.format(dateObject(date))).join(' · ');
    const list = $('ta-conflict-courses'); list.replaceChildren();
    courses.forEach(course => {
      const item = document.createElement('article'); item.className = 'ta-conflict-course';
      const time = document.createElement('time'); time.dateTime = course.date;
      time.textContent = label(course.date) + ' · ' + course.start + ' – ' + course.end;
      const name = document.createElement('strong'); name.textContent = course.title || course.subject_name || 'Cours';
      const groups = document.createElement('p'); groups.textContent = (course.promotion_names || []).join(' · ');
      if (course.shared) groups.textContent += (groups.textContent ? ' · ' : '') + 'Cours commun';
      item.append(time, name, groups); list.appendChild(item);
    });
    list.hidden = !destructive; $('ta-delete-note').hidden = !destructive;
    $('ta-confirm').textContent = destructive ? 'Confirmer et supprimer ' + courses.length + ' cours' : 'Confirmer et enregistrer';
    $('ta-confirm').classList.toggle('danger', destructive);
    $('ta-dialog-error').hidden = true;
    returnFocus = document.activeElement;
    if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
    $('ta-cancel-dialog').focus();
  }

  async function previewDates() {
    if (!selection.size || busy) return;
    notice(''); setBusy(true);
    try {
      const result = await request(config.preview_url, { dates: [...selection].sort(), action });
      setBusy(false); showPreview(result);
    } catch (error) { notice(error.message, true); setBusy(false); }
  }

  async function commitDates() {
    if (!preview || busy) return;
    const confirmed = preview; setBusy(true); $('ta-dialog-error').hidden = true;
    try {
      const result = await request(config.commit_url, { preview_token: confirmed.preview_token, confirm_delete: confirmed.requires_confirmation === true || (confirmed.courses || []).length > 0 });
      selection.clear(); anchor = null;
      setBusy(false); closeDialog();
      notice(result.message || 'Vos indisponibilités ont été enregistrées. Les plannings et les compteurs d’heures sont à jour.');
      try { window.dispatchEvent(new CustomEvent('academy:planning-updated')); localStorage.setItem('academy-planning-updated', String(Date.now())); } catch (_) { /* Storage may be unavailable in private mode. */ }
      await loadYear(data.year);
    } catch (error) {
      setBusy(false);
      if (error.status === 409) {
        const selectedDates = [...selection];
        selection.clear(); anchor = null; closeDialog();
        const refreshed = await loadYear(data.year);
        selectedDates.forEach(date => { if (selectable(dayMap.get(date))) selection.add(date); });
        updateSelection();
        if (refreshed) notice('Le planning a changé depuis votre vérification. Rien n’a été supprimé. Votre sélection encore applicable est conservée : cliquez sur « Enregistrer mes dates » pour vérifier les cours à jour.', true);
      } else { $('ta-dialog-error').textContent = error.message; $('ta-dialog-error').hidden = false; }
    }
  }

  months.addEventListener('click', event => {
    const button = event.target.closest('[data-ta-date]');
    if (!button || !months.contains(button) || button.disabled || busy || ignoreClick) return;
    const date = button.dataset.taDate, selected = !selection.has(date);
    if (event.shiftKey && anchor) selectRange(anchor, date, selected); else selectDate(date, selected);
    anchor = date; updateSelection();
  });
  months.addEventListener('pointerdown', event => {
    if (event.button !== 0 || (event.pointerType && event.pointerType !== 'mouse') || busy) return;
    const button = event.target.closest('[data-ta-date]');
    if (!button || button.disabled) return;
    const date = button.dataset.taDate;
    drag = { first: date, last: date, selected: !selection.has(date), moved: false };
  });
  months.addEventListener('pointerover', event => {
    if (!drag || busy) return;
    const button = event.target.closest('[data-ta-date]');
    if (!button || button.dataset.taDate === drag.last) return;
    drag.moved = true; drag.last = button.dataset.taDate;
    selectRange(drag.first, drag.last, drag.selected); anchor = drag.first; updateSelection();
  });
  document.addEventListener('pointerup', () => {
    if (drag && drag.moved) { ignoreClick = true; setTimeout(() => { ignoreClick = false; }, 0); }
    drag = null;
  });
  document.addEventListener('pointercancel', () => { drag = null; });
  document.querySelectorAll('[data-ta-action]').forEach(button => button.addEventListener('click', () => {
    if (busy || selection.size) return;
    action = button.dataset.taAction; anchor = null; notice(''); updateSelection();
  }));
  $('ta-clear').addEventListener('click', () => { if (!busy) { selection.clear(); preview = null; anchor = null; updateSelection(); } });
  $('ta-previous').addEventListener('click', () => loadYear(Number(data.year) - 1));
  $('ta-next').addEventListener('click', () => loadYear(Number(data.year) + 1));
  $('ta-year-form').addEventListener('submit', event => {
    event.preventDefault();
    if (busy || selection.size || isOpen()) {
      notice('Enregistrez ou effacez votre sélection avant de changer d’année.');
      return;
    }
    const year = Number($('ta-year-select').value);
    if (Number.isInteger(year) && year >= 1900 && year <= 2200) loadYear(year);
  });
  $('ta-month-select').addEventListener('change', event => {
    const value = event.target.value;
    const target = value === '' ? $('ta-calendar-title') : $('ta-month-' + value);
    if (!target) return;
    target.scrollIntoView({behavior: window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth', block:'start'});
  });
  $('ta-save').addEventListener('click', previewDates);
  $('ta-confirm').addEventListener('click', commitDates);
  $('ta-close-dialog').addEventListener('click', closeDialog);
  $('ta-cancel-dialog').addEventListener('click', closeDialog);
  dialog.addEventListener('cancel', event => { event.preventDefault(); closeDialog(); });
  dialog.addEventListener('keydown', event => {
    if (event.key !== 'Tab') return;
    const buttons = [...dialog.querySelectorAll('button:not(:disabled)')];
    if (!buttons.length) { event.preventDefault(); return; }
    const first = buttons[0], last = buttons[buttons.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  });
  window.addEventListener('beforeunload', event => { if (selection.size) { event.preventDefault(); event.returnValue = ''; } });
  window.addEventListener('focus', () => { if (!document.hidden) loadYear(data.year, true); });
  window.addEventListener('storage', event => { if (event.key === 'academy-planning-updated') loadYear(data.year, true); });
  window.addEventListener('academy:planning-changed', event => {
    event.preventDefault();
    if (!selection.size && !busy && !isOpen()) loadYear(data.year, true);
    else notice('Le planning a été modifié. Votre sélection est conservée ; la liste des cours sera vérifiée à nouveau avant enregistrement.');
  });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) loadYear(data.year, true); });
  render();
  if (!config.state) loadYear(config.year);
})();

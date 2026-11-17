(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const board = byId('room-tv');
  const dialog = byId('room-tv-dialog');
  const launcher = byId('room-tv-open');
  const list = byId('tv-entries');
  const sheet = byId('tv-sheet');
  const viewport = sheet.parentElement;
  const headings = sheet.querySelector('.tv-headings');
  const empty = byId('tv-empty');
  const notice = byId('tv-notice');
  const fullscreenButton = byId('tv-fullscreen');
  const zone = {timeZone: 'Europe/Paris'};
  const dateKey = new Intl.DateTimeFormat('sv-SE', {...zone, year: 'numeric', month: '2-digit', day: '2-digit'});
  const longDate = new Intl.DateTimeFormat('fr-FR', {...zone, dateStyle: 'full'});
  const clock = new Intl.DateTimeFormat('fr-FR', {...zone, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
  const names = Intl.ListFormat && new Intl.ListFormat('fr-FR', {style: 'long', type: 'conjunction'});
  const timers = [];
  const noon = 12 * 60;
  let active = false, inflight = null, day = '', lastMinute = -1, offset = 0, lastSync = 0;
  let dayEntries = null, visibleEntries = [], signature = null, lastUpdate = '';
  let hadFullscreen = false;

  function span(className, text) {
    const element = document.createElement('span');
    element.className = className;
    element.textContent = text;
    return element;
  }

  function hhmm(minutes) {
    return [Math.floor(minutes / 60), minutes % 60].map(n => String(n).padStart(2, '0')).join(':');
  }

  function setState(row, entry, minute) {
    const current = entry.start_min <= minute && minute < entry.end_min;
    row.classList.toggle('current', current);
    row.querySelector('.tv-state').textContent = current ? 'En cours' : minute < entry.start_min ? 'À venir' : 'Terminé';
  }

  function courseRow(entry) {
    const row = document.createElement('li');
    row.className = 'tv-row';
    const times = document.createElement('div');
    times.className = 'tv-times';
    const hours = entry.start_min === 0 && entry.end_min === 1440 ? 'Journée entière' : hhmm(entry.start_min) + ' – ' + hhmm(entry.end_min);
    times.append(span('tv-time', hours), span('tv-state', ''));
    const topic = document.createElement('div');
    topic.className = 'tv-topic';
    if (entry.exam) topic.append(span('tv-exam', 'Examen'));
    topic.append(span('tv-title', entry.title));
    if (entry.detail) topic.append(span('tv-detail', entry.detail));
    const teachers = entry.trainers || [];
    const staff = teachers.length ? 'Avec ' + (names ? names.format(teachers) : teachers.join(', ')) : 'Formateur à confirmer';
    topic.append(span('tv-trainers', staff));
    row.append(times, topic, span('tv-room', entry.room || 'Salle à confirmer'));
    setState(row, entry, lastMinute);
    return row;
  }

  function setColumns(count) {
    sheet.style.setProperty('--groups', count);
    sheet.classList.toggle('tv-multiple', count > 1);
    while (headings.children.length < count) headings.append(headings.firstElementChild.cloneNode(true));
    while (headings.children.length > count) headings.lastElementChild.remove();
  }

  function fitSheet() {
    const width = viewport.clientWidth, height = viewport.clientHeight - 1;
    if (!active || sheet.hidden || !width || height <= 0) return;
    const maxColumns = Math.max(1, Math.min(3, visibleEntries.length, Math.floor(width / 520)));
    let bestSize = 0, bestColumns = 1;
    sheet.style.transform = '';
    // Measure the actual wrapped titles and room names. Prefer the largest
    // readable type, keeping a single column whenever it already fits.
    for (let columns = 1; columns <= maxColumns; columns++) {
      setColumns(columns);
      let low = 0, high = 1;
      for (let attempt = 0; attempt < 9; attempt++) {
        const size = attempt === 0 ? 1 : (low + high) / 2;
        sheet.style.fontSize = size + 'em';
        if (sheet.scrollHeight <= height && sheet.scrollWidth <= width) {
          low = size;
          if (size === 1) break;
        } else {
          high = size;
        }
      }
      if (low > bestSize) { bestSize = low; bestColumns = columns; }
      if (bestSize === 1) break;
    }
    setColumns(bestColumns);
    sheet.style.fontSize = (bestSize || 1 / 256) + 'em';
    // A TV browser can impose a minimum font size even when CSS requests less.
    const scale = Math.min(1, height / sheet.scrollHeight, width / sheet.scrollWidth);
    if (scale < 1) sheet.style.transform = 'scale(' + scale + ')';
  }

  function renderPeriod() {
    const morning = lastMinute < noon;
    byId('room-tv-heading').textContent = morning ? 'Cours du matin' : 'Cours de l’après-midi';
    if (dayEntries === null) return;
    visibleEntries = dayEntries.filter(entry => morning ? entry.start_min < noon : entry.end_min > noon);
    list.replaceChildren(...visibleEntries.map(courseRow));
    sheet.hidden = visibleEntries.length === 0;
    empty.hidden = !sheet.hidden;
    empty.textContent = morning ? 'Aucun cours prévu ce matin.' : 'Aucun cours prévu cet après-midi.';
    fitSheet();
  }

  function clear(message) {
    dayEntries = null; visibleEntries = []; signature = null; lastUpdate = '';
    list.replaceChildren();
    sheet.hidden = true;
    empty.textContent = message;
    empty.hidden = false;
  }

  function tick() {
    const now = new Date(Date.now() + offset);
    const stamp = clock.format(now);
    const key = dateKey.format(now);
    byId('tv-clock').textContent = stamp;
    const minute = Number(stamp.slice(0, 2)) * 60 + Number(stamp.slice(3, 5));
    if (key !== day) {
      day = key;
      byId('tv-date').textContent = longDate.format(now);
      byId('tv-date').dateTime = day;
      clear('Chargement du planning…');
      notice.textContent = '';
      refresh();
    }
    if (lastMinute !== minute) {
      const periodChanged = lastMinute < 0 || (lastMinute < noon) !== (minute < noon);
      lastMinute = minute;
      if (periodChanged) renderPeriod();
      else visibleEntries.forEach((entry, i) => setState(list.children[i], entry, minute));
    }
  }

  async function refresh(sync = false) {
    if (!active || inflight) return;
    const controller = new AbortController();
    inflight = controller;
    const timeout = setTimeout(() => controller.abort(), 50000);
    try {
      const url = new URL(board.dataset.feed, location.href);
      if (sync) {
        url.searchParams.set('sync', '1');
        lastSync = Date.now();
      }
      const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (inflight !== controller) return;
      if (response.status === 401 || response.status === 403 || response.redirected) {
        clear('Session expirée. Reconnectez-vous depuis la page des salles.');
        notice.textContent = '';
        return;
      }
      if (!response.ok) throw new Error();
      const data = await response.json();
      if (inflight !== controller) return;
      if (!Array.isArray(data.entries) || !Number.isFinite(Date.parse(data.now))) throw new Error();
      offset = Date.parse(data.now) - Date.now();
      tick();
      if (data.date !== day) return;
      lastUpdate = clock.format(new Date(Date.now() + offset)).slice(0, 5);
      notice.textContent = data.sync_delayed ? 'Actualisation des sessions en attente.' : '';
      const next = JSON.stringify(data.entries);
      if (next !== signature) {
        signature = next;
        dayEntries = data.entries;
        renderPeriod();
      }
    } catch {
      if (inflight !== controller) return;
      if (!lastUpdate) clear('Planning temporairement indisponible.');
      notice.textContent = lastUpdate ? 'Connexion interrompue · Dernière mise à jour à ' + lastUpdate : 'Nouvelle tentative automatique.';
    } finally {
      clearTimeout(timeout);
      if (inflight === controller) inflight = null;
      if (active && !sync && lastUpdate && !lastSync) refresh(true);
    }
  }

  const resize = window.ResizeObserver ? new ResizeObserver(fitSheet) : null;
  function start() {
    if (active) return;
    active = true;
    day = ''; lastMinute = -1;
    tick();
    timers.push(setInterval(tick, 1000));
    timers.push(setInterval(() => { if (!document.hidden) refresh(Date.now() - lastSync >= 300000); }, 60000));
    resize?.observe(viewport);
    document.fonts?.ready.then(fitSheet);
  }

  function stop() {
    active = false;
    inflight?.abort(); inflight = null;
    timers.splice(0).forEach(clearInterval);
    resize?.disconnect();
    clear('Chargement du planning…');
  }

  const fullscreen = () => document.fullscreenElement || document.webkitFullscreenElement;
  function enterFullscreen() {
    const request = board.requestFullscreen || board.webkitRequestFullscreen;
    if (request) {
      try { Promise.resolve(request.call(board)).catch(() => {}); } catch { /* Keep the full-window display. */ }
    }
  }
  function fullscreenChanged() {
    const entered = fullscreen() === board;
    fullscreenButton.hidden = entered || !(document.fullscreenEnabled || document.webkitFullscreenEnabled);
    if (hadFullscreen && !entered && dialog?.open) dialog.close();
    hadFullscreen = entered;
  }
  document.addEventListener('fullscreenchange', fullscreenChanged);
  document.addEventListener('webkitfullscreenchange', fullscreenChanged);
  fullscreenButton.addEventListener('click', enterFullscreen);
  window.addEventListener('resize', fitSheet);
  document.addEventListener('visibilitychange', () => { if (active && !document.hidden) { tick(); refresh(); } });
  fullscreenChanged();

  if (dialog) {
    launcher.addEventListener('click', event => {
      if (event.ctrlKey || event.metaKey || event.shiftKey || event.altKey || !dialog.showModal) return;
      event.preventDefault();
      dialog.showModal();
      enterFullscreen();
      start();
    });
    byId('tv-close').addEventListener('click', event => { event.preventDefault(); dialog.close(); });
    dialog.addEventListener('close', async () => {
      stop();
      if (fullscreen() === board) {
        const exit = document.exitFullscreen || document.webkitExitFullscreen;
        if (exit) {
          try { await exit.call(document); } catch { /* The browser has already exited. */ }
        }
      }
      if (!dialog.open) launcher.focus({preventScroll: true});
    });
  } else {
    start();
  }
})();

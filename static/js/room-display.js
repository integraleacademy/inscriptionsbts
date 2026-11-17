(() => {
  'use strict';
  const byId = id => document.getElementById(id);
  const board = byId('room-tv');
  const dialog = byId('room-tv-dialog');
  const launcher = byId('room-tv-open');
  const list = byId('tv-entries');
  const empty = byId('tv-empty');
  const notice = byId('tv-notice');
  const counter = byId('tv-page');
  const fullscreenButton = byId('tv-fullscreen');
  const zone = {timeZone: 'Europe/Paris'};
  const dateKey = new Intl.DateTimeFormat('sv-SE', {...zone, year: 'numeric', month: '2-digit', day: '2-digit'});
  const longDate = new Intl.DateTimeFormat('fr-FR', {...zone, dateStyle: 'full'});
  const clock = new Intl.DateTimeFormat('fr-FR', {...zone, hour: '2-digit', minute: '2-digit', second: '2-digit', hourCycle: 'h23'});
  const timers = [];
  let active = false, inflight = null, day = '', lastMinute = -1, offset = 0, lastSync = 0;
  let entries = [], signature = null, pages = [], page = 0, lastUpdate = '';
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
    row.append(times, topic, span('tv-room', entry.room || 'Salle à confirmer'));
    setState(row, entry, lastMinute);
    return row;
  }

  function showPage(index) {
    page = Math.min(index, Math.max(0, pages.length - 1));
    pages.forEach((rows, i) => rows.forEach(row => { row.hidden = i !== page; }));
    list.scrollTop = 0;
    counter.hidden = pages.length < 2;
    counter.textContent = pages.length > 1 ? 'Page ' + (page + 1) + ' / ' + pages.length : '';
  }

  function paginate() {
    if (!active) return;
    const rows = Array.from(list.children);
    rows.forEach(row => { row.hidden = false; });
    const height = list.clientHeight;
    pages = [];
    let used = 0;
    for (const row of rows) {
      const size = row.getBoundingClientRect().height;
      if (!pages.length || used + size > height + .5) {
        pages.push([]);
        used = 0;
      }
      pages[pages.length - 1].push(row);
      used += size;
    }
    showPage(page);
  }

  function clear(message) {
    entries = []; pages = []; page = 0; signature = null; lastUpdate = '';
    list.replaceChildren();
    empty.textContent = message;
    empty.hidden = false;
    counter.hidden = true;
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
      lastMinute = minute;
      entries.forEach((entry, i) => setState(list.children[i], entry, minute));
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
        entries = data.entries;
        list.replaceChildren(...entries.map(courseRow));
        empty.textContent = 'Aucun cours prévu aujourd’hui.';
        empty.hidden = entries.length > 0;
        paginate();
      }
    } catch {
      if (inflight !== controller) return;
      if (!lastUpdate) clear('Planning temporairement indisponible.');
      notice.textContent = lastUpdate ? 'Connexion interrompue · Dernière mise à jour à ' + lastUpdate : 'Nouvelle tentative automatique.';
    } finally {
      clearTimeout(timeout);
      if (inflight === controller) inflight = null;
    }
  }

  const resize = window.ResizeObserver ? new ResizeObserver(paginate) : null;
  function start() {
    if (active) return;
    active = true;
    day = ''; lastMinute = -1;
    tick();
    timers.push(setInterval(tick, 1000));
    timers.push(setInterval(() => { if (!document.hidden) refresh(Date.now() - lastSync >= 300000); }, 60000));
    timers.push(setInterval(() => { if (!document.hidden && pages.length > 1) showPage((page + 1) % pages.length); }, 12000));
    resize?.observe(list);
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
  window.addEventListener('resize', paginate);
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

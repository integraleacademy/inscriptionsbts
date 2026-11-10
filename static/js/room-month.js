(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const dialog = $('room-month');
  if (!dialog) return;
  const month = $('room-month-value'), start = $('room-month-start'), end = $('room-month-end');
  const weekends = $('room-month-weekends'), status = $('room-month-status'), results = $('room-month-results');
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/Paris'}).format(new Date());
  const dayDate = iso => new Date(iso + 'T12:00:00');
  const dateLabel = iso => dayDate(iso).toLocaleDateString('fr-FR', {weekday:'long', day:'numeric', month:'long'});
  const isoMonth = d => d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2, '0');
  const node = (tag, text, cls) => {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  };
  const filterToggle = $('room-month-filter-toggle'), filterPanel = $('room-month-filter-panel');
  const choices = $('room-month-filter-choices'), reset = $('room-month-filter-reset');
  const storageKey = 'bts.roomAvailability.excludedRooms.v1';
  const surface = $('room-month-surface'), fullButton = $('room-month-fullscreen');
  const scrollArea = dialog.querySelector('.month-scroll'), loading = $('room-month-loading');
  let data = null, preferredDay = null, sequence = 0, pending = null;
  let ownsNativeFullscreen = false;
  let excluded = readExclusions();

  function displayFullscreen(expanded) {
    dialog.classList.toggle('month-expanded', expanded);
    fullButton.setAttribute('aria-pressed', String(expanded));
    $('room-month-fullscreen-label').textContent = expanded ? 'Quitter le plein écran' : 'Plein écran';
  }
  async function leaveFullscreen() {
    displayFullscreen(false);
    if (document.fullscreenElement === surface) {
      try { await document.exitFullscreen(); } catch { /* The browser may already be exiting. */ }
    }
  }
  fullButton.addEventListener('click', async () => {
    if (dialog.classList.contains('month-expanded')) {
      await leaveFullscreen();
      return;
    }
    displayFullscreen(true);
    if (!document.fullscreenElement && surface.requestFullscreen) {
      try { await surface.requestFullscreen(); } catch { /* The dialog already fills the window. */ }
    }
  });
  document.addEventListener('fullscreenchange', () => {
    if (document.fullscreenElement === surface) {
      ownsNativeFullscreen = true;
      if (!dialog.open || !dialog.classList.contains('month-expanded')) leaveFullscreen();
    } else if (ownsNativeFullscreen) {
      ownsNativeFullscreen = false;
      displayFullscreen(false);
    }
  });
  dialog.addEventListener('cancel', event => {
    if (dialog.classList.contains('month-expanded')) {
      event.preventDefault();
      leaveFullscreen();
    }
  });

  function readExclusions() {
    try {
      const saved = JSON.parse(localStorage.getItem(storageKey) || '[]');
      return new Set(Array.isArray(saved) ? saved.filter(id => typeof id === 'string') : []);
    } catch {
      return new Set();
    }
  }
  function saveExclusions() {
    try {
      if (excluded.size) localStorage.setItem(storageKey, JSON.stringify([...excluded]));
      else localStorage.removeItem(storageKey);
    } catch { /* The selection remains available in this tab when storage is disabled. */ }
  }
  function visibleRooms() {
    return data.rooms.filter(room => !excluded.has(room.id));
  }
  function showFilterChoices(previousRooms) {
    if (previousRooms && previousRooms.length === data.rooms.length && previousRooms.every((room, i) =>
      room.id === data.rooms[i].id && room.name === data.rooms[i].name && room.active === data.rooms[i].active)) {
      for (const input of choices.querySelectorAll('input')) input.checked = excluded.has(input.value);
      return;
    }
    const fragment = document.createDocumentFragment();
    for (const room of data.rooms) {
      const label = node('label'), checkbox = node('input');
      checkbox.type = 'checkbox';
      checkbox.value = room.id;
      checkbox.checked = excluded.has(room.id);
      label.append(checkbox, node('span', room.name + (room.active ? '' : ' (inactive)')));
      fragment.append(label);
    }
    choices.replaceChildren(fragment);
  }
  filterToggle.addEventListener('click', () => {
    filterPanel.hidden = !filterPanel.hidden;
    filterToggle.setAttribute('aria-expanded', String(!filterPanel.hidden));
  });
  choices.addEventListener('change', event => {
    const input = event.target;
    if (!data || input.type !== 'checkbox') return;
    if (input.checked) excluded.add(input.value);
    else excluded.delete(input.value);
    saveExclusions();
    render();
  });
  reset.addEventListener('click', () => {
    excluded.clear();
    saveExclusions();
    for (const input of choices.querySelectorAll('input')) input.checked = false;
    filterToggle.focus();
    render();
  });
  window.addEventListener('storage', event => {
    if (event.key !== storageKey && event.key !== null) return;
    excluded = readExclusions();
    if (data && dialog.open) {
      for (const input of choices.querySelectorAll('input')) input.checked = excluded.has(input.value);
      render();
    }
  });
  function rememberMonth(open) {
    const url = new URL(location.href);
    if (open) {
      url.searchParams.set('vue', 'disponibilites');
      url.searchParams.set('mois', month.value);
    } else {
      url.searchParams.delete('vue');
      url.searchParams.delete('mois');
    }
    history.replaceState(null, '', url);
  }
  function showDay(day) {
    for (const button of $('room-month-days').querySelectorAll('[data-date]')) {
      button.setAttribute('aria-pressed', String(button.dataset.date === day));
    }
    $('room-month-day').textContent = dateLabel(day);
    const list = $('room-month-list');
    const cards = document.createDocumentFragment();
    const rank = {free:0, partial:1, busy:2};
    const sorted = visibleRooms().sort((a, b) => Number(b.active)-Number(a.active) || rank[a.days[day].state]-rank[b.days[day].state]);
    for (const room of sorted) {
      const slot = room.days[day], card = node('article');
      const label = !room.active ? 'Inactive' : {free:'Libre', partial:'Partielle', busy:'Indisponible'}[slot.state];
      card.append(node('strong', room.name), node('span', label, 'month-state ' + slot.state));
      if (slot.free.length) card.append(node('small', slot.free.map(([a,b]) => a + '–' + b).join(' · ')));
      cards.append(card);
    }
    list.replaceChildren(cards);
  }
  function dayToShow(dates) {
    if (preferredDay === null) {
      const current = today();
      return dates.includes(current) ? current : dates[0];
    }
    const distance = day => Math.abs(Number(day.slice(-2)) - preferredDay);
    return dates.reduce((nearest, day) => distance(day) < distance(nearest) ? day : nearest);
  }
  function render() {
    const rooms = visibleRooms();
    const excludedCount = data.rooms.length - rooms.length;
    results.hidden = false;
    $('room-month-exclusions').hidden = !data.rooms.length;
    $('room-month-filter-count').textContent = excludedCount
      ? excludedCount + (excludedCount === 1 ? ' salle exclue' : ' salles exclues') + ' sur ' + data.rooms.length
      : 'Toutes les salles affichées';
    reset.hidden = !excludedCount;
    $('room-month-calendar').hidden = !rooms.length;
    const empty = $('room-month-empty');
    empty.hidden = Boolean(rooms.length);
    if (!rooms.length) {
      empty.textContent = data.rooms.length ? 'Toutes les salles sont exclues. Décochez une salle pour voir ses disponibilités.' : 'Aucune salle enregistrée.';
      return;
    }
    const active = rooms.filter(room => room.active);
    const free = active.filter(r => data.dates.length && r.free_days === data.dates.length);
    let summary = 'Aucune salle libre sur tous les jours et horaires sélectionnés.';
    if (!active.length) summary = 'Les salles affichées sont inactives.';
    if (free.length) summary = free.map(room => room.name).join(' · ');
    $('room-month-free').textContent = summary;
    const first = dayDate(data.first);
    $('room-month-heading').textContent = first.toLocaleDateString('fr-FR', {month:'long', year:'numeric'});
    const grid = $('room-month-days');
    const cells = document.createDocumentFragment();
    const checked = new Set(data.dates), count = Number(data.last.slice(-2));
    const offset = (first.getDay() + 6) % 7;
    const displayedMonth = data.first.slice(0, 7);
    for (let cell = 0; cell < 42; cell++) {
      const n = cell - offset + 1;
      if (n < 1 || n > count) {
        const neighborDate = new Date(first.getTime());
        neighborDate.setDate(n);
        const neighbor = node('span', String(neighborDate.getDate()), 'month-neighbor');
        neighbor.setAttribute('aria-hidden', 'true');
        cells.append(neighbor);
        continue;
      }
      const day = displayedMonth + '-' + String(n).padStart(2, '0');
      const button = node('button');
      button.type = 'button';
      button.append(node('b', String(n)));
      if (checked.has(day)) {
        const full = active.filter(r => r.days[day].state === 'free').length;
        const partial = active.filter(r => r.days[day].state === 'partial').length;
        const label = full ? full + (full === 1 ? ' libre' : ' libres') : partial ? 'Partiel' : 'Aucune';
        button.className = full ? 'free' : partial ? 'partial' : 'busy';
        button.dataset.date = day;
        button.setAttribute('aria-label', dateLabel(day) + ', ' + full + ' salle(s) libre(s), ' + partial + ' partiellement libre(s)');
        button.append(node('small', label));
        button.addEventListener('click', () => {
          preferredDay = n;
          showDay(day);
        });
      } else {
        button.disabled = true;
        button.setAttribute('aria-label', dateLabel(day) + ', hors recherche');
      }
      cells.append(button);
    }
    grid.replaceChildren(cells);
    showDay(dayToShow(data.dates));
  }
  function setLoading(label = '') {
    loading.textContent = label;
    loading.hidden = !label;
    results.setAttribute('aria-busy', String(Boolean(label)));
    $('room-month-calendar').inert = Boolean(label);
  }
  async function load() {
    const ticket = ++sequence;
    pending?.abort();
    pending = null;
    $('room-month-retry').hidden = true;
    if (!month.validity.valid || !month.value || !start.value || !end.value || start.value >= end.value) {
      data = null;
      results.hidden = true;
      setLoading();
      status.textContent = 'Choisissez un mois et une heure de fin postérieure au début.';
      return;
    }
    rememberMonth(true);
    const [y, m] = month.value.split('-').map(Number);
    const last = new Date(y, m, 0).getDate();
    const params = new URLSearchParams({from:month.value+'-01', to:month.value+'-'+last, start:start.value, end:end.value,
      weekdays:weekends.checked ? '0,1,2,3,4,5,6' : '0,1,2,3,4'});
    const targetMonth = dayDate(month.value + '-01').toLocaleDateString('fr-FR', {month:'long', year:'numeric'});
    if (!data) status.textContent = '';
    setLoading('Chargement de ' + targetMonth + '…');
    const controller = new AbortController();
    pending = controller;
    try {
      const response = await fetch('/admin/planning/api/rooms/disponibilites?' + params,
        {credentials:'same-origin', headers:{Accept:'application/json'}, signal:controller.signal});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'La disponibilité est temporairement inaccessible.');
      if (ticket !== sequence || !dialog.open) return;
      const top = scrollArea.scrollTop;
      const previousRooms = data?.rooms;
      data = payload;
      showFilterChoices(previousRooms);
      status.textContent = data.connected ? '' : 'Liaison avec les sessions externes inactive. Le calendrier couvre les réservations enregistrées.';
      render();
      scrollArea.scrollTop = top;
    } catch (error) {
      if (ticket !== sequence || !dialog.open) return;
      data = null;
      results.hidden = true;
      status.textContent = error instanceof SyntaxError ? 'Impossible de charger les salles. Rechargez la page.' : error.message;
      $('room-month-retry').hidden = false;
    } finally {
      if (ticket === sequence) {
        pending = null;
        setLoading();
      }
    }
  }
  function open() {
    const requested = new URL(location.href).searchParams.get('mois');
    month.value = requested && /^\d{4}-(0[1-9]|1[0-2])$/.test(requested) ? requested : month.value || today().slice(0,7);
    if (!dialog.open) dialog.showModal();
    document.documentElement.classList.add('room-month-open');
    load();
  }
  $('room-month-open').addEventListener('click', event => { event.preventDefault(); open(); });
  dialog.querySelector('.tool-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    if (dialog.open) return;
    ++sequence;
    pending?.abort();
    pending = null;
    setLoading();
    leaveFullscreen();
    document.documentElement.classList.remove('room-month-open');
    rememberMonth(false);
  });
  $('room-month-retry').addEventListener('click', load);
  for (const field of [month, start, end, weekends]) field.addEventListener('change', load);
  for (const [id, offset] of [['room-month-prev',-1], ['room-month-next',1]]) {
    $(id).addEventListener('click', () => {
      const d = dayDate((month.value || today().slice(0,7)) + '-01');
      d.setMonth(d.getMonth() + offset);
      month.value = isoMonth(d);
      load();
    });
  }
  window.addEventListener('academy:rooms-changed', () => { if (dialog.open) load(); });
  if (new URL(location.href).searchParams.get('vue') === 'disponibilites') open();
})();

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
  let data = null, selected = '', sequence = 0;
  let excluded = readExclusions();

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
  function showFilterChoices() {
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
    selected = day;
    for (const button of $('room-month-days').querySelectorAll('[data-date]')) {
      button.setAttribute('aria-pressed', String(button.dataset.date === day));
    }
    $('room-month-day').textContent = dateLabel(day);
    const list = $('room-month-list');
    list.replaceChildren();
    const rank = {free:0, partial:1, busy:2};
    const sorted = visibleRooms().sort((a, b) => Number(b.active)-Number(a.active) || rank[a.days[day].state]-rank[b.days[day].state]);
    for (const room of sorted) {
      const slot = room.days[day], card = node('article');
      const label = !room.active ? 'Inactive' : {free:'Libre', partial:'Partielle', busy:'Indisponible'}[slot.state];
      card.append(node('strong', room.name), node('span', label, 'month-state ' + slot.state));
      if (slot.free.length) card.append(node('small', slot.free.map(([a,b]) => a + '–' + b).join(' · ')));
      list.append(card);
    }
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
    grid.replaceChildren();
    const checked = new Set(data.dates), count = Number(data.last.slice(-2));
    for (let n = 1; n <= count; n++) {
      const day = month.value + '-' + String(n).padStart(2, '0');
      const button = node('button');
      button.type = 'button';
      if (n === 1) button.style.gridColumnStart = String((first.getDay()+6)%7+1);
      button.append(node('b', String(n)));
      if (checked.has(day)) {
        const full = active.filter(r => r.days[day].state === 'free').length;
        const partial = active.filter(r => r.days[day].state === 'partial').length;
        const label = full ? full + (full === 1 ? ' libre' : ' libres') : partial ? 'Partiel' : 'Aucune';
        button.className = full ? 'free' : partial ? 'partial' : 'busy';
        button.dataset.date = day;
        button.setAttribute('aria-label', dateLabel(day) + ', ' + full + ' salle(s) libre(s), ' + partial + ' partiellement libre(s)');
        button.append(node('small', label));
        button.addEventListener('click', () => showDay(day));
      } else {
        button.disabled = true;
        button.setAttribute('aria-label', dateLabel(day) + ', hors recherche');
      }
      grid.append(button);
    }
    showDay(checked.has(selected) ? selected : checked.has(today()) ? today() : data.dates[0]);
  }
  async function load() {
    const ticket = ++sequence;
    data = null;
    results.hidden = true;
    $('room-month-retry').hidden = true;
    if (!month.validity.valid || !month.value || !start.value || !end.value || start.value >= end.value) {
      status.textContent = 'Choisissez un mois et une heure de fin postérieure au début.';
      return;
    }
    rememberMonth(true);
    const [y, m] = month.value.split('-').map(Number);
    const last = new Date(y, m, 0).getDate();
    const params = new URLSearchParams({from:month.value+'-01', to:month.value+'-'+last, start:start.value, end:end.value,
      weekdays:weekends.checked ? '0,1,2,3,4,5,6' : '0,1,2,3,4'});
    status.textContent = 'Recherche des créneaux libres…';
    try {
      const response = await fetch('/admin/planning/api/rooms/disponibilites?' + params, {credentials:'same-origin', headers:{Accept:'application/json'}});
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.message || 'La disponibilité est temporairement inaccessible.');
      if (ticket !== sequence || !dialog.open) return;
      data = payload;
      showFilterChoices();
      status.textContent = data.connected ? '' : 'Liaison avec les sessions externes inactive. Le calendrier couvre les réservations enregistrées.';
      render();
    } catch (error) {
      if (ticket === sequence) {
        status.textContent = error instanceof SyntaxError ? 'Impossible de charger les salles. Rechargez la page.' : error.message;
        $('room-month-retry').hidden = false;
      }
    }
  }
  function open() {
    const requested = new URL(location.href).searchParams.get('mois');
    month.value = requested && /^\d{4}-(0[1-9]|1[0-2])$/.test(requested) ? requested : month.value || today().slice(0,7);
    if (!dialog.open) dialog.showModal();
    load();
  }
  $('room-month-open').addEventListener('click', event => { event.preventDefault(); open(); });
  dialog.querySelector('.tool-close').addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { ++sequence; rememberMonth(false); });
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

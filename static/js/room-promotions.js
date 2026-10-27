(() => {
  'use strict';
  const form = document.getElementById('rooms-promotion-form');
  if (!form) return;
  const $ = id => document.getElementById(id);
  const field = name => form.elements[name];
  const csrf = document.querySelector('.catalog-app').dataset.csrf;
  const state = {promotions: [], courses: [], selected: new Set(), token: null, busy: false, loaded: false};
  const node = (tag, text, cls) => {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (cls) element.className = cls;
    return element;
  };
  const frenchDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? value.split('-').reverse().join('/') : '—';
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/Paris'}).format(new Date());
  const promotion = () => state.promotions.find(p => p.id === field('promotion_id').value);
  const period = () => promotion()?.periods.find(p => p.id === field('period_id').value);
  const visible = () => state.courses.filter(c => !field('unassigned').checked || !c.room_id);
  function message(id, text) { $(id).textContent = text || ''; $(id).hidden = !text; }
  function options(select, entries, placeholder, value = '') {
    select.replaceChildren(new Option(placeholder, ''));
    for (const [id, label] of entries) select.add(new Option(label, id));
    select.value = value;
  }
  async function request(path, data) {
    const response = await fetch('/admin/planning/api/rooms' + path, {
      method: data ? 'POST' : 'GET', credentials: 'same-origin',
      headers: {Accept: 'application/json', ...(data ? {'Content-Type': 'application/json', 'X-CSRF-Token': csrf} : {})},
      ...(data ? {body: JSON.stringify(data)} : {})
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw new Error([
      result.message || 'Chargement impossible. Réessayez.',
      ...(result.conflicts || []).map(c => (c.date ? frenchDate(c.date) + ' · ' : '') + c.message)
    ].join('\n'));
    return result;
  }
  function controls() {
    const ready = Boolean(period());
    for (const control of form.querySelectorAll('input,select,button')) control.disabled = state.busy;
    field('promotion_id').disabled = state.busy || !state.promotions.length;
    field('period_id').disabled = state.busy || !promotion()?.periods.length;
    for (const name of ['from', 'to', 'room_id', 'unassigned']) field(name).disabled = state.busy || !ready;
    $('rooms-promotion-load').disabled = state.busy || !ready;
    for (const id of ['rooms-promotion-all', 'rooms-promotion-none']) $(id).disabled = state.busy || !visible().length;
    $('rooms-promotion-check').disabled = state.busy || !state.selected.size || !field('room_id').value;
    $('rooms-promotion-save').disabled = state.busy || !state.token;
    form.setAttribute('aria-busy', String(state.busy));
  }
  function invalidate() {
    state.token = null;
    message('rooms-promotion-preview', '');
    controls();
  }
  async function work(operation) {
    if (state.busy) return;
    state.busy = true; controls();
    message('rooms-promotion-error', ''); message('rooms-promotion-success', '');
    try { await operation(); }
    catch (error) { invalidate(); message('rooms-promotion-error', error.message); }
    finally { state.busy = false; controls(); }
  }
  function renderCourses() {
    const list = $('rooms-promotion-courses'), courses = visible();
    state.selected = new Set([...state.selected].filter(id => courses.some(c => c.id === id)));
    list.replaceChildren();
    for (const course of courses) {
      const row = node('label', undefined, 'bulk-room-row'), check = node('input');
      check.type = 'checkbox'; check.value = course.id; check.checked = state.selected.has(course.id);
      check.addEventListener('change', () => {
        check.checked ? state.selected.add(course.id) : state.selected.delete(course.id);
        invalidate(); count();
      });
      row.append(check, node('span', frenchDate(course.date) + ' · ' + course.start + '–' + course.end),
        node('span', course.display_subject_name || course.subject_name || course.title),
        node('small', (course.room_name || 'Sans salle') + (course.is_shared ? ' · cours commun' : '')));
      list.append(row);
    }
    if (!courses.length) list.append(node('p', !period() ? 'Choisissez une promotion et une année.' :
      !state.loaded ? 'Cliquez sur « Afficher les cours » pour charger cette période.' :
      state.courses.length ? 'Tous les créneaux ont déjà une salle. Décochez le filtre « sans salle » pour les réaffecter.' :
      'Aucun cours planifié sur cette période. Ajoutez ou importez les cours dans le planning de la promotion.'));
    count(); controls();
  }
  function count() { $('rooms-promotion-count').textContent = state.selected.size + ' créneau(x) sélectionné(s) sur ' + visible().length; }
  function resetCourses() { state.courses = []; state.selected.clear(); state.loaded = false; invalidate(); renderCourses(); }
  function planningLink() {
    const params = new URLSearchParams();
    if (promotion()) params.set('promotion_id', promotion().id);
    if (period()) params.set('period_id', period().id);
    $('rooms-promotion-planning').href = '/admin/planning' + (params.size ? '?' + params : '');
  }
  async function loadCourses() {
    resetCourses();
    if (!period()) return;
    if (!field('from').checkValidity() || !field('to').checkValidity() || field('from').value > field('to').value)
      throw new Error('Choisissez une période valide dans l’année du planning.');
    const params = new URLSearchParams({promotion_id: promotion().id, period_id: period().id,
      start: field('from').value, end: field('to').value});
    const result = await request('/courses?' + params);
    state.courses = result.courses; state.loaded = true;
    state.selected = new Set(visible().map(c => c.id));
    renderCourses();
  }
  async function changePeriod() {
    resetCourses(); planningLink();
    const year = period();
    for (const name of ['from', 'to']) {
      field(name).min = year?.start_date || ''; field(name).max = year?.end_date || '';
      field(name).value = year ? (name === 'from' ? year.start_date : year.end_date) : '';
    }
    message('rooms-promotion-help', year ? year.label + ' · du ' + frenchDate(year.start_date) + ' au ' + frenchDate(year.end_date) :
      promotion() ? 'Complétez les dates de cette promotion pour pouvoir affecter ses cours.' : 'Choisissez la promotion BTS à affecter.');
    if (year) await loadCourses();
  }
  async function changePromotion() {
    const years = promotion()?.periods || [], current = today();
    const preferred = years.find(y => y.start_date <= current && y.end_date >= current) || years.find(y => y.start_date > current) || years[0];
    options(field('period_id'), years.map(y => [y.id, y.label]), 'Choisir une année', preferred?.id || '');
    await changePeriod();
  }
  async function loadPromotions() {
    invalidate();
    const result = await request('/promotions'), old = field('promotion_id').value;
    state.promotions = result.promotions;
    const requested = new URLSearchParams(location.search).get('promotion_id');
    const selected = state.promotions.some(p => p.id === old) ? old : state.promotions.some(p => p.id === requested) ? requested : '';
    options(field('promotion_id'), state.promotions.map(p => [p.id, p.name]), state.promotions.length ? 'Choisir une promotion BTS' : 'Aucune promotion active', selected);
    options(field('room_id'), result.rooms.map(r => [r.id, r.name]), 'Choisir une salle', field('room_id').value);
    await changePromotion();
    if (!state.promotions.length) message('rooms-promotion-help', 'Aucune promotion BTS active. Créez ou réactivez une promotion depuis sa fiche.');
  }
  field('promotion_id').addEventListener('change', () => work(changePromotion));
  field('period_id').addEventListener('change', () => work(changePeriod));
  for (const name of ['from', 'to']) field(name).addEventListener('change', resetCourses);
  field('room_id').addEventListener('change', invalidate);
  field('unassigned').addEventListener('change', () => { invalidate(); state.selected = new Set(visible().map(c => c.id)); renderCourses(); });
  $('rooms-promotion-load').addEventListener('click', () => work(loadCourses));
  $('rooms-promotions-reload').addEventListener('click', () => work(loadPromotions));
  $('rooms-promotion-all').addEventListener('click', () => { state.selected = new Set(visible().map(c => c.id)); invalidate(); renderCourses(); });
  $('rooms-promotion-none').addEventListener('click', () => { state.selected.clear(); invalidate(); renderCourses(); });
  form.addEventListener('submit', event => {
    event.preventDefault();
    if (!form.reportValidity() || !state.selected.size) return;
    const payload = {promotion_id: promotion().id, period_id: period().id, room_id: field('room_id').value,
      courses: state.courses.filter(c => state.selected.has(c.id)).map(c => ({id: c.id, version: c.version}))};
    work(async () => {
      invalidate();
      const result = await request('/bulk-preview', payload); state.token = result.token;
      message('rooms-promotion-preview', result.count + ' créneau(x) vérifié(s) pour « ' + promotion().name + ' ».' +
        (result.shared ? ' Attention : ' + result.shared + ' cours commun(s), toutes leurs promotions changeront de salle.' : '') + ' Vous pouvez confirmer l’affectation.');
    });
  });
  $('rooms-promotion-save').addEventListener('click', () => {
    if (!state.token) return;
    const token = state.token;
    work(async () => {
      invalidate();
      const result = await request('/bulk-commit', {token});
      message('rooms-promotion-success', result.count + ' créneau(x) affecté(s) à la salle choisie.');
      window.dispatchEvent(new CustomEvent('academy:rooms-changed', {detail: {origin: 'promotions'}}));
      await loadCourses();
    });
  });
  $('rooms-promotion-open').addEventListener('click', () => {
    $('rooms-promotion-panel').open = true;
    field('promotion_id').focus({preventScroll: true});
  });
  window.addEventListener('academy:rooms-changed', event => {
    if (event.detail?.origin === 'catalog') work(loadPromotions);
    else if (event.detail?.origin !== 'promotions' && state.loaded) work(loadCourses);
  });
  work(loadPromotions);
})();

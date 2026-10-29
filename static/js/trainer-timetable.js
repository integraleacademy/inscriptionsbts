/* Trainer-file navigation and edits use the canonical planning API. */
(() => {
  'use strict';
  const root = document.querySelector('[data-admin-trainer-planning]');
  if (!root) return;
  const $ = selector => root.querySelector(selector);
  const dialog = $('.tap-course-dialog'), form = $('[data-tap-editor]');
  let course, catalog, opening = 0, navigation = 0, roomRequest = 0, controller, saving = false, dirty = false;
  const status = message => { $('[data-tap-status]').textContent = message; };
  const error = message => { $('[data-tap-error]').textContent = message; $('[data-tap-error]').hidden = !message; };
  async function api(url, options = {}) {
    const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options,
      headers: {Accept: 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.csrf, ...options.headers}});
    let data;
    try { data = await response.json(); } catch (_) { throw Error('La session a expiré ou le serveur est indisponible. Rechargez la page.'); }
    if (!response.ok || data.ok === false) {
      const details = [...new Set((data.conflicts || []).map(c => c.message || c.label).filter(Boolean))];
      throw Error([data.message || 'Impossible d’enregistrer cette modification.', ...details].join('\n'));
    }
    return data;
  }
  async function navigate(url, push = true) {
    const target = new URL(url, location.href);
    if (target.origin !== location.origin || target.pathname !== location.pathname) return;
    const seq = ++navigation;
    controller?.abort(); controller = new AbortController();
    const viewport = $('.tap-week-scroll');
    const positions = {x: window.scrollX, y: window.scrollY, top: viewport.scrollTop, left: viewport.scrollLeft};
    // Some workspace layouts scroll the content pane rather than the window.
    const ancestors = []; for (let el = root.parentElement; el; el = el.parentElement) ancestors.push([el, el.scrollTop, el.scrollLeft]);
    root.setAttribute('aria-busy', 'true'); status('Chargement du planning…');
    try {
      const response = await fetch(target, {credentials: 'same-origin', cache: 'no-store', signal: controller.signal});
      if (!response.ok) throw Error('Impossible de charger cette période. Réessayez.');
      const page = new DOMParser().parseFromString(await response.text(), 'text/html');
      const content = page.querySelector('[data-tap-content]');
      if (!content) throw Error('La session a expiré. Rechargez la page.');
      if (seq !== navigation) return;
      $('[data-tap-content]').replaceWith(content);
      const newRoot = page.querySelector('[data-admin-trainer-planning]');
      if (newRoot?.dataset.csrf) root.dataset.csrf = newRoot.dataset.csrf;
      document.querySelectorAll('.tw-tab').forEach((a, index) => { const next = page.querySelectorAll('.tw-tab')[index]; if (next) a.href = next.href; });
      if (push) history.pushState({}, '', target);
      $('.tap-week-scroll').scrollTop = positions.top; $('.tap-week-scroll').scrollLeft = positions.left;
      ancestors.forEach(([el, top, left]) => { el.scrollTop = top; el.scrollLeft = left; });
      window.scrollTo({left: positions.x, top: positions.y, behavior: 'instant'});
      status('');
    } catch (e) { if (e.name !== 'AbortError' && seq === navigation) status(e.message); }
    finally { if (seq === navigation) root.removeAttribute('aria-busy'); }
  }
  function options(select, rows, current, empty) {
    select.replaceChildren();
    if (empty) select.append(new Option(empty, ''));
    rows.forEach(r => select.append(new Option(r.label, r.id)));
    if (current && !rows.some(r => r.id === current)) select.append(new Option('Valeur actuelle · à vérifier', current));
    select.value = current || '';
  }
  async function loadRooms() {
    const seq = ++roomRequest, select = form.elements.room_id, selected = select.value;
    select.disabled = true; select.setCustomValidity('');
    const query = new URLSearchParams({date:form.elements.date.value, start:form.elements.start.value,
      end:form.elements.end_at_midnight.checked ? '24:00' : form.elements.end.value, exclude_course_id:course.id});
    $('[data-tap-room-status]').textContent = 'Recherche des salles disponibles…';
    try {
      const data = await api('/admin/planning/api/rooms/available?'+query);
      if (seq !== roomRequest || !dialog.open) return;
      const available = data.rooms.some(r => r.id === selected);
      options(select,data.rooms.map(r=>({id:r.id,label:r.name})),available ? selected : '', 'Salle à affecter');
      if (selected && !available) {
        const option = new Option('Salle précédente indisponible · choisissez une autre salle',selected,true,true);
        option.disabled = true; select.append(option);
        select.setCustomValidity('Choisissez une salle disponible ou « Salle à affecter ».');
      }
      $('[data-tap-room-status]').textContent = data.rooms.length+' salle(s) disponible(s) pour ce créneau.';
      select.disabled = false;
    } catch (e) { if (seq === roomRequest) { $('[data-tap-room-status]').textContent = e.message; select.disabled = false; select.setCustomValidity('Vérifiez la date et les horaires pour actualiser les salles.'); } }
  }
  async function openCourse(id) {
    const seq = ++opening; roomRequest++; course = null; dirty = false; form.hidden = true;
    $('[data-tap-editor-status]').textContent = 'Chargement du créneau…';
    if (!dialog.open) dialog.showModal();
    try {
      const [result, resources] = await Promise.all([api('/admin/planning/api/courses/' + encodeURIComponent(id)), api('/admin/planning/api/catalog')]);
      if (seq !== opening || !dialog.open) return;
      course = result.course; catalog = resources;
      const names = course.groups.map(g => g.promotion_name || 'Promotion à préciser').join(' · ');
      $('[data-tap-groups]').textContent = (course.is_shared ? 'Cours commun : ' : 'Promotion : ') + names;
      $('[data-tap-delete-groups]').textContent = names;
      for (const field of ['date', 'start', 'end', 'title', 'zoom_url']) form.elements[field].value = course[field] || '';
      form.elements.end_at_midnight.checked = course.end === '24:00';
      form.elements.end.disabled = form.elements.end_at_midnight.checked;
      const subjects = $('[data-tap-subjects]'); subjects.replaceChildren();
      if (course.kind !== 'event') course.groups.forEach(group => {
        const label = document.createElement('label'), select = document.createElement('select');
        label.textContent = 'Matière · ' + group.promotion_name; select.dataset.promotion = group.promotion_id;
        options(select, catalog.subjects.filter(s => s.promotion_id === group.promotion_id && (!s.period_id || !course.date || (s.period_start <= course.date && course.date <= s.period_end)))
          .map(s => ({id:s.id, label:s.name})), group.subject_id);
        // Catalogs predating period metadata still expose every assigned subject.
        if (select.options.length <= 1) options(select, catalog.subjects.filter(s => s.promotion_id === group.promotion_id).map(s => ({id:s.id,label:s.name})), group.subject_id);
        label.append(select); subjects.append(label);
      });
      const trainers = catalog.trainers.filter(t => course.groups.every(g => t.promotion_ids.includes(g.promotion_id)));
      options(form.elements.trainer_id, trainers.map(t => ({id:t.id, label:[t.prenom,t.nom].join(' ')})), course.trainer_id, course.kind === 'event' ? 'Sans formateur' : null);
      options(form.elements.room_id, catalog.rooms.filter(r => r.active).map(r => ({id:r.id,label:r.name})), course.room_id, 'Salle à affecter');
      error(''); $('[data-tap-confirm]').hidden = true; $('[data-tap-editor-status]').textContent = '';
      form.hidden = false; form.elements.date.focus();
      await loadRooms();
    } catch (e) { if (seq === opening) $('[data-tap-editor-status]').textContent = e.message; }
  }
  function payload() {
    const data = {version: course.version};
    for (const name of ['date','start','end','title','trainer_id','room_id','zoom_url']) data[name] = form.elements[name].value;
    if (form.elements.end_at_midnight.checked) data.end = '24:00';
    if (course.kind !== 'event') {
      const groups = [...form.querySelectorAll('[data-promotion]')].map(s => ({promotion_id:s.dataset.promotion, subject_id:s.value}));
      data.subject_id = groups.find(g => g.promotion_id === course.promotion_id).subject_id;
      data.shared = groups.filter(g => g.promotion_id !== course.promotion_id);
    }
    return data;
  }
  async function save(remove = false) {
    if (saving || !course) return;
    if (!remove && (form.elements.room_id.disabled || !form.reportValidity())) return;
    saving = true; error('');
    const data = remove ? {version:course.version} : payload();
    form.querySelectorAll('button,input,select').forEach(el => el.disabled = true);
    try {
      await api('/admin/planning/api/courses/' + encodeURIComponent(course.id), {method: remove ? 'DELETE' : 'PUT', body:JSON.stringify(data)});
      dirty = false; dialog.close();
      try { localStorage.setItem('academy-planning-updated', String(Date.now())); } catch (_) {}
      await navigate(location.href, false);
      status(remove ? 'Créneau supprimé dans tous les plannings. Les heures sont recalculées.' : 'Créneau mis à jour dans tous les plannings. Les heures sont recalculées.');
      window.dispatchEvent(new Event('academy:planning-updated'));
    } catch (e) { error(e.message); }
    finally { saving = false; form.querySelectorAll('button,input,select').forEach(el => el.disabled = false); form.elements.end.disabled = form.elements.end_at_midnight.checked; }
  }
  root.addEventListener('click', e => {
    const link = e.target.closest('[data-tap-week]');
    if (link && !e.ctrlKey && !e.metaKey && !e.shiftKey && !e.altKey) { e.preventDefault(); navigate(link.href); return; }
    const card = e.target.closest('[data-course-id]'); if (card) openCourse(card.dataset.courseId);
    if (e.target.closest('[data-tap-close]') && !saving) { opening++; dialog.close(); }
    if (e.target.closest('[data-tap-delete]')) $('[data-tap-confirm]').hidden = false;
    if (e.target.closest('[data-tap-cancel-delete]')) $('[data-tap-confirm]').hidden = true;
    if (e.target.closest('[data-tap-confirm-delete]')) save(true);
  });
  root.addEventListener('keydown', e => { const card = e.target.closest('[data-course-id]'); if (card && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); openCourse(card.dataset.courseId); } });
  root.addEventListener('submit', e => {
    if (e.target.matches('[data-tap-navigation]')) { e.preventDefault(); const url = new URL(location.href); url.search = new URLSearchParams(new FormData(e.target)); navigate(url); }
    if (e.target === form) { e.preventDefault(); save(); }
    if (e.target.matches('[data-tap-export]') && e.target.elements.period.value === 'custom') {
      const start = e.target.elements.start.value, end = e.target.elements.end.value;
      if (!start || !end || end < start || (new Date(end)-new Date(start))/86400000 > 366) { e.preventDefault(); status('Choisissez une période valide d’un an maximum.'); }
    }
  });
  root.addEventListener('change', e => {
    if (e.target.matches('[data-tap-export] select[name=period]')) root.querySelectorAll('[data-tap-custom]').forEach(el => el.hidden = e.target.value !== 'custom');
    if (form.contains(e.target) && ['date','start','end','end_at_midnight'].includes(e.target.name)) {
      form.elements.end.disabled = form.elements.end_at_midnight.checked; loadRooms();
    }
    if (e.target === form.elements.room_id) e.target.setCustomValidity('');
  });
  form.addEventListener('input', () => { dirty = true; });
  dialog.addEventListener('cancel', e => { if (saving) e.preventDefault(); else opening++; });
  window.addEventListener('popstate', () => navigate(location.href, false));
  window.addEventListener('academy:planning-changed', e => {
    e.preventDefault();
    if (dialog.open || saving || dirty) status('Le planning a changé. Fermez le créneau puis actualisez la semaine pour voir les modifications.');
    else navigate(location.href, false);
  });
  dialog.addEventListener('close', () => { dirty = false; });
})();

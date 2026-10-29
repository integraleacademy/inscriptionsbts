/* Read-only course inspection, separate from selecting unavailable dates. */
(() => {
  'use strict';
  const source = document.getElementById('tap-availability-config') || document.getElementById('trainer-availability-config');
  if (!source) return;
  const config = JSON.parse(source.textContent);
  if (!config.courses_url) return;
  const node = (tag, cls, text) => {
    const element = document.createElement(tag);
    if (cls) element.className = cls;
    if (text !== undefined) element.textContent = text;
    return element;
  };
  const dialog = node('dialog', 'tc-dialog');
  dialog.setAttribute('aria-labelledby', 'tc-title');
  const close = node('button', 'tc-close', 'Fermer'); close.type = 'button';
  const title = node('h2', '', 'Cours prévus'); title.id = 'tc-title';
  const dateLabel = node('p', 'tc-date');
  const status = node('p', 'tc-status'); status.setAttribute('role', 'status');
  const list = node('div', 'tc-courses');
  const link = node('a', 'tc-planning-link', 'Voir cette journée dans le planning');
  dialog.append(close, title, dateLabel, status, list, link);
  document.body.append(dialog);
  let controller, trigger;
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => {
    controller?.abort();
    if (trigger?.isConnected) trigger.focus({preventScroll: true});
  });
  dialog.addEventListener('click', event => {
    if (event.target === dialog) {
      const rect = dialog.getBoundingClientRect();
      if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
    }
  });
  document.addEventListener('click', async event => {
    const button = event.target.closest('[data-course-date]');
    if (!button) return;
    event.preventDefault();
    trigger = button;
    controller?.abort();
    const request = controller = new AbortController();
    const day = button.dataset.courseDate;
    dateLabel.textContent = new Date(day + 'T12:00:00').toLocaleDateString('fr-FR', {weekday:'long', day:'numeric', month:'long', year:'numeric'});
    status.textContent = 'Chargement des cours…'; list.replaceChildren();
    const planning = new URL(config.planning_url, window.location.href); planning.searchParams.set('date', day); link.href = planning.href;
    if (!dialog.open) dialog.showModal();
    try {
      const url = new URL(config.courses_url, window.location.href); url.searchParams.set('date', day);
      const response = await fetch(url, {credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}, signal:request.signal});
      if (!response.ok) throw Error('Les cours n’ont pas pu être chargés. Fermez cette fenêtre et réessayez.');
      const result = await response.json();
      if (request !== controller || !dialog.open) return;
      const courses = result.courses || [];
      status.textContent = courses.length ? courses.length + ' cours prévu' + (courses.length > 1 ? 's' : '') : 'Aucun cours prévu pour cette journée. Le planning a peut-être été modifié.';
      for (const course of courses) {
        const card = node('article', 'tc-course');
        card.append(node('p', 'tc-time', course.start + ' – ' + course.end));
        card.append(node('h3', '', course.subject_name || course.title || 'Cours'));
        if (course.title && course.title !== course.subject_name) card.append(node('p', '', course.title));
        card.append(node('p', 'tc-room', course.room_name ? 'Salle : ' + course.room_name : 'Salle non affectée'));
        card.append(node('p', 'tc-promotions', (course.shared ? 'Cours commun · ' : '') + (course.promotion_names || []).join(' / ')));
        list.append(card);
      }
    } catch (error) {
      if (error.name !== 'AbortError') status.textContent = error.message;
    }
  });
})();

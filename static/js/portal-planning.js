/* Progressive enhancement only: all schedules and navigation render server-side. */
(() => {
  'use strict';
  const app = document.querySelector('[data-portal-planning]');
  if (!app) return;
  const toggle = app.querySelector('[data-portal-view-switch]');
  const controls = Array.from(app.querySelectorAll('[data-planning-view]'));
  const applyView = view => {
    app.dataset.view = view === 'list' ? 'list' : 'week';
    controls.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.planningView === app.dataset.view)));
  };
  if (toggle) {
    toggle.hidden = false;
    try { applyView(localStorage.getItem('academy.portal.planning.view')); } catch (_) { applyView('week'); }
    controls.forEach(button => button.addEventListener('click', () => {
      applyView(button.dataset.planningView);
      try { localStorage.setItem('academy.portal.planning.view', app.dataset.view); } catch (_) { /* preference is optional */ }
    }));
  }
  const updateLiveState = () => {
    const pieces = Object.fromEntries(new Intl.DateTimeFormat('en-GB', {timeZone:'Europe/Paris',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date()).map(item => [item.type,item.value]));
    const today = `${pieces.year}-${pieces.month}-${pieces.day}`, now = Number(pieces.hour) * 60 + Number(pieces.minute);
    app.querySelectorAll('[data-portal-course]').forEach(card => {
      const badge = card.querySelector('[data-course-live]');
      if (!badge) return;
      const parse = value => { const parts = String(value || '').split(':').map(Number); return parts.length === 2 ? parts[0] * 60 + parts[1] : NaN; };
      const start = parse(card.dataset.start), end = parse(card.dataset.end);
      if (card.dataset.date !== today || !Number.isFinite(start) || !Number.isFinite(end) || now >= end) { delete card.dataset.liveState; badge.hidden = true; badge.textContent = ''; return; }
      card.dataset.liveState = now >= start ? 'ongoing' : 'upcoming';
      badge.textContent = now >= start ? 'En cours' : 'À venir'; badge.hidden = false;
    });
  };
  try { updateLiveState(); setInterval(updateLiveState, 60000); } catch (_) { /* schedules remain readable without Intl */ }
})();

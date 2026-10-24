/* Keep portrait fallbacks and the record's visible status in sync. */
(() => {
  'use strict';
  document.querySelectorAll('[data-candidate-photo]').forEach(image => {
    const fallback = () => image.closest('.candidate-portrait')?.classList.add('photo-unavailable');
    image.addEventListener('error', fallback, {once: true});
    if (image.complete && !image.naturalWidth) fallback();
  });
  const select = document.getElementById('candidate-status');
  const badge = document.querySelector('[data-sheet-status]');
  if (select && badge) {
    const sync = () => {
      const current = select.dataset.current;
      const option = Array.from(select.options).find(item => item.value === current);
      badge.textContent = option?.textContent || 'Dossier en cours';
      badge.className = 'sheet-status-badge status-' + (current || 'preinscription');
    };
    new MutationObserver(sync).observe(select, {attributes: true, attributeFilter: ['data-current']});
    sync();
  }
})();

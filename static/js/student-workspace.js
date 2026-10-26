(() => {
  'use strict';
  const bulk = document.querySelector('[data-bulk-absence]');
  if (bulk) {
    const boxes = Array.from(bulk.querySelectorAll('[name="events"]'));
    const start = bulk.querySelector('[data-period-start]');
    const end = bulk.querySelector('[data-period-end]');
    const select = bulk.querySelector('[data-select-period]');
    const clear = bulk.querySelector('[data-clear-period]');
    const feedback = bulk.querySelector('[data-period-feedback]');
    const count = bulk.querySelector('[data-selection-count]');
    const submit = bulk.querySelector('[data-bulk-submit]');
    const update = () => {
      const checked = boxes.filter(box => box.checked);
      const days = new Set(checked.map(box => box.dataset.eventDate)).size;
      count.textContent = checked.length ? `${checked.length} événement(s) sur ${days} jour(s) · un seul envoi` : 'Aucun événement sélectionné.';
      submit.disabled = !checked.length || checked.length > 200;
      if (checked.length > 200) count.textContent += ' · Maximum 200 événements par demande.';
    };
    select.hidden = clear.hidden = false;
    select.addEventListener('click', () => {
      if (!start.value || !end.value || start.value > end.value) {
        feedback.textContent = 'Indique une date de début et une date de fin valide, dans cet ordre.';
        return;
      }
      boxes.forEach(box => { box.checked = box.dataset.eventDate >= start.value && box.dataset.eventDate <= end.value; });
      const n = boxes.filter(box => box.checked).length;
      feedback.textContent = n ? `${n} événement(s) coché(s) dans cette période, dates incluses. Vérifie la sélection ci-dessous.` : 'Aucun événement à justifier sur cette période. Vérifie les dates ou consulte les demandes déjà envoyées.';
      update();
      const first = boxes.find(box => box.checked);
      if (first) {
        const list = bulk.querySelector('.sw-select-list');
        list.scrollTop += first.closest('label').getBoundingClientRect().top - list.getBoundingClientRect().top - 4;
      }
    });
    clear.addEventListener('click', () => { boxes.forEach(box => { box.checked = false; }); update(); });
    boxes.forEach(box => box.addEventListener('change', update));
    update();
  }
  const form = document.querySelector('[data-absence-form]');
  if (form) {
    const reason = form.querySelector('[data-absence-reason]');
    const hint = form.querySelector('[data-evidence-hint]');
    const message = form.querySelector('[name="message"]');
    const files = form.querySelector('[name="documents"]');
    const uploadLabel = form.querySelector('[data-upload-label]');
    const update = () => {
      hint.textContent = reason.selectedOptions[0]?.dataset.evidence || 'Choisis un motif pour connaître le justificatif attendu.';
      message.required = reason.value === 'other';
      message.minLength = reason.value === 'other' ? 10 : 0;
      if (uploadLabel) uploadLabel.textContent = reason.value === 'company_work' ? 'Joindre le planning de ton entreprise' : uploadLabel.dataset.defaultLabel;
      if (files) files.required = Number(files.dataset.existingFiles) === 0 || (reason.value === 'company_work' && files.dataset.existingReason !== 'company_work');
    };
    reason.addEventListener('change', update);
    update();
    files?.addEventListener('change', () => {
      const list = Array.from(files.files || []);
      files.setCustomValidity(list.length > 5 || list.some(f => f.size > 10 * 1024 * 1024) || list.reduce((n,f) => n+f.size,0) > 20 * 1024 * 1024 ? 'Maximum 5 documents, 10 Mo par fichier et 20 Mo au total.' : '');
      files.reportValidity();
    });
  }
  const review = document.querySelector('[data-review-form]');
  if (review) {
    const choice = review.querySelector('[name="decision"]');
    const comment = review.querySelector('[name="comment"]');
    choice.addEventListener('change', () => { comment.required = choice.value !== 'accepted'; comment.minLength = comment.required ? 5 : 0; });
  }
})();

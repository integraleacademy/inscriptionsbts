(() => {
  'use strict';
  const form = document.querySelector('[data-absence-form]');
  if (form) {
    const reason = form.querySelector('[data-absence-reason]');
    const hint = form.querySelector('[data-evidence-hint]');
    const message = form.querySelector('[name="message"]');
    const update = () => {
      hint.textContent = reason.selectedOptions[0]?.dataset.evidence || 'Choisis un motif pour connaître le justificatif attendu.';
      message.required = reason.value === 'other';
      message.minLength = reason.value === 'other' ? 10 : 0;
    };
    reason.addEventListener('change', update);
    update();
    const files = form.querySelector('[name="documents"]');
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

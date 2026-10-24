/* A placement is independent from edits to the student's administrative fields. */
(() => {
  const form = document.getElementById('candidate-promotion-form');
  if (!form) return;
  const button = form.querySelector('button[type="submit"]');
  const feedback = form.querySelector('[data-promotion-feedback]');
  const details = form.querySelector('[data-promotion-details]');
  const date = value => /^\d{4}-\d{2}-\d{2}$/.test(value || '') ? value.split('-').reverse().join('/') : '';
  let saving = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving) return;
    saving = true; button.disabled = true; feedback.hidden = true;
    const data = new FormData(form);
    try {
      const response = await fetch(form.action, {method:'POST', credentials:'same-origin', headers:{Accept:'application/json'}, body:data});
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw Error(result.message || result.error || 'La promotion n’a pas pu être enregistrée. Rechargez la page puis réessayez.');
      const promotion = result.promotion;
      details.textContent = promotion ? promotion.nom + (promotion.date_debut && promotion.date_fin ? ' · Du ' + date(promotion.date_debut) + ' au ' + date(promotion.date_fin) : ' · Niveau et dates à compléter') : 'Aucune promotion affectée.';
      feedback.textContent = result.message || 'Promotion enregistrée.';
      feedback.classList.remove('promotion-feedback-error');
    } catch (error) {
      feedback.textContent = error.message;
      feedback.classList.add('promotion-feedback-error');
    } finally {
      saving = false; button.disabled = false; feedback.hidden = false;
    }
  });
})();

(() => {
  'use strict';
  const form = document.getElementById('candidate-create-form');
  if (!form) return;
  const filterPromotions = () => {
    const fields = form.elements;
    for (const option of fields.promotion_id.options) {
      const visible = !option.value || (option.dataset.bts === fields.bts.value && option.dataset.year === fields.rentree_annee.value);
      option.hidden = !visible;
      option.disabled = !visible;
      if (!visible && option.selected) fields.promotion_id.value = '';
    }
  };
  form.elements.bts.addEventListener('change', filterPromotions);
  form.elements.rentree_annee.addEventListener('change', filterPromotions);
  filterPromotions();
  const submit = form.querySelector('[type=submit]');
  const reset = () => { submit.disabled = false; form.removeAttribute('aria-busy'); };
  form.addEventListener('submit', () => { submit.disabled = true; form.setAttribute('aria-busy', 'true'); });
  window.addEventListener('pageshow', reset);
})();

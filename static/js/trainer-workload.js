/* Admin-only workload: figures are recomputed by the server from saved courses. */
(() => {
  'use strict';
  const root = document.querySelector('[data-trainer-workload]');
  if (!root) return;
  const form = document.getElementById('trainer-hourly-rate-form');
  const feedback = document.getElementById('tw-rate-feedback');
  let saving = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (saving || !form.reportValidity()) return;
    saving = true;
    const button = form.querySelector('button[type=submit]');
    button.disabled = true;
    feedback.hidden = false;
    feedback.textContent = 'Enregistrement du tarif…';
    feedback.className = 'tw-feedback';
    try {
      const response = await fetch(form.action, {method: 'POST', credentials: 'same-origin', headers: {Accept: 'application/json'}, body: new FormData(form)});
      const result = await response.json().catch(() => ({}));
      if (!response.ok || !result.ok) throw new Error(result.message || 'Le tarif n’a pas été enregistré. Rechargez la fiche puis réessayez.');
      feedback.textContent = result.message;
      feedback.className = 'tw-feedback success';
      window.location.reload();
    } catch (error) {
      feedback.textContent = error.message;
      feedback.className = 'tw-feedback error';
      saving = false;
      button.disabled = false;
    }
  });
  const amount = document.getElementById('tw-invoice-amount');
  const result = document.getElementById('tw-invoice-result');
  const expected = BigInt(root.dataset.estimateCents);
  const money = value => new Intl.NumberFormat('fr-FR', {style: 'currency', currency: 'EUR'}).format(Number(value) / 100);
  amount.addEventListener('input', () => {
    result.className = 'tw-invoice-result';
    const raw = amount.value.trim().replace(/[ \u00a0\u202f]/g, '').replace(',', '.');
    if (!raw) { result.textContent = 'La différence avec les ' + money(expected) + ' prévues s’affichera ici.'; return; }
    if (!/^\d{1,9}(?:\.\d{1,2})?$/.test(raw)) { result.textContent = 'Indiquez un montant positif, avec deux décimales au maximum.'; return; }
    const [euros, decimals = ''] = raw.split('.');
    const cents = BigInt(euros) * 100n + BigInt(decimals.padEnd(2, '0'));
    const difference = cents - expected;
    if (difference === 0n) {
      result.classList.add('matching');
      result.textContent = 'Le montant correspond exactement aux heures et tarifs du planning.';
    } else {
      result.classList.add('difference');
      result.textContent = 'Écart : ' + money(difference < 0n ? -difference : difference) + (difference > 0n ? ' de plus' : ' de moins') + ' que le montant prévisionnel (' + money(expected) + ').';
    }
  });
})();

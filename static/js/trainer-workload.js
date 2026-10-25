/* Admin-only workload: figures are recomputed by the server from saved courses. */
(() => {
  'use strict';
  const root = document.querySelector('[data-trainer-workload]');
  if (!root) return;
  const form = document.getElementById('trainer-hourly-rate-form');
  const feedback = document.getElementById('tw-rate-feedback');
  let saving = false;
  if (form) form.addEventListener('submit', async event => {
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
  const expected = BigInt(root.dataset.estimateCents || '0');
  const money = value => new Intl.NumberFormat('fr-FR', {style: 'currency', currency: 'EUR'}).format(Number(value) / 100);
  if (amount && result) amount.addEventListener('input', () => {
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
  const accountForm = document.getElementById('trainer-profile-form');
  const accountFeedback = document.getElementById('tw-profile-feedback');
  const accessFeedback = document.getElementById('tw-access-feedback');
  let accountBusy = false, accountDirty = false;
  const protectAccountEdits = () => {
    accountDirty = true;
    root.querySelectorAll('[data-profile-action]').forEach(button => { button.disabled = true; });
    if (accessFeedback) {
      accessFeedback.hidden = false; accessFeedback.className = 'tw-feedback';
      accessFeedback.textContent = 'Enregistrez les informations modifiées avant de gérer les accès du formateur.';
    }
  };
  if (accountForm) {
    accountForm.addEventListener('input', protectAccountEdits);
    accountForm.addEventListener('change', protectAccountEdits);
  }
  async function saveAccount(url, data, feedback, reload) {
    if (accountBusy) return;
    accountBusy = true;
    const controls = [...root.querySelectorAll('#trainer-profile-form input,#trainer-profile-form select,#trainer-profile-form textarea,#trainer-profile-form button,[data-profile-action]')];
    const originalDisabled = controls.map(button => button.disabled);
    controls.forEach(button => { button.disabled = true; });
    feedback.hidden = false; feedback.className = 'tw-feedback'; feedback.textContent = 'Enregistrement en cours…';
    try {
      const response = await fetch(url, {method:'POST',credentials:'same-origin',headers:{Accept:'application/json','X-CSRF-Token':root.dataset.csrf},body:data});
      const answer = await response.json().catch(() => ({}));
      if (!response.ok || !answer.ok) throw new Error(answer.message || 'La modification n’a pas été enregistrée. Réessayez après actualisation.');
      feedback.className = 'tw-feedback success'; feedback.textContent = answer.message;
      if (reload) window.location.reload();
    } catch (error) { feedback.className = 'tw-feedback error'; feedback.textContent = error.message; }
    finally { accountBusy = false; controls.forEach((button,index) => { button.disabled = originalDisabled[index]; }); }
  }
  if (accountForm) accountForm.addEventListener('submit', event => {
    event.preventDefault();
    if (accountForm.reportValidity()) saveAccount(accountForm.action,new FormData(accountForm),accountFeedback,true);
  });
  root.querySelectorAll('[data-profile-action]').forEach(button => button.addEventListener('click', () => {
    if (accountDirty || accountBusy) return;
    const data = new FormData();
    data.set('csrf_token',root.dataset.csrf);
    if (button.dataset.profileAction === 'status') data.set('active',button.dataset.active);
    saveAccount(button.dataset.url,data,accessFeedback,button.dataset.profileAction === 'status');
  }));
})();

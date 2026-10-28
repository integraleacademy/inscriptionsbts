/* Keep entered values on validation errors; a successful save reloads #londres. */
document.querySelectorAll('[data-mobility-form]').forEach(form => {
  let busy = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(form);
    if (event.submitter?.name) data.set(event.submitter.name, event.submitter.value);
    const message = form.querySelector('[data-mobility-message]');
    const buttons = [...form.querySelectorAll('button')];
    message.hidden = true;
    busy = true; form.setAttribute('aria-busy', 'true');
    buttons.forEach(button => { button.disabled = true; });
    try {
      // Controls named "action" shadow HTMLFormElement.action in real browsers.
      const response = await fetch(form.getAttribute('action'), { method: 'POST', body: data, headers: { Accept: 'application/json' } });
      const result = await response.json().catch(() => null);
      if (result?.refresh_url) {
        window.location.hash = 'londres';
        window.location.reload();
        return;
      }
      if (!response.ok || !result?.ok) {
        const fallback = response.status === 403 || response.redirected
          ? 'Votre session a expiré. Reconnectez-vous puis rouvrez cette fiche.'
          : response.status === 400 ? 'La page a expiré ou un champ est invalide. Rechargez la fiche si le problème persiste.'
          : 'Le serveur n’a pas pu traiter la demande. Vos informations sont conservées à l’écran ; réessayez dans quelques instants.';
        throw new Error(result?.error || fallback);
      }
      // Assigning the same hash alone would not reload the saved values.
      window.location.hash = 'londres';
      window.location.reload();
    } catch (error) {
      message.textContent = error.message;
      message.hidden = false;
      message.scrollIntoView({ block: 'center', behavior: 'smooth' });
      busy = false; form.removeAttribute('aria-busy');
      buttons.forEach(button => { button.disabled = false; });
    }
  });
});

// Poll only while the London panel is visible, without discarding edited fields.
document.querySelectorAll('[data-signature-poll]').forEach(panel => {
  let polling = false;
  let edited = false;
  document.querySelectorAll('[data-mobility-form]').forEach(form => {
    form.addEventListener('input', () => { edited = true; });
  });
  setInterval(async () => {
    if (polling || document.hidden || !panel.getClientRects().length || document.querySelector('[data-mobility-form][aria-busy="true"]')) return;
    polling = true;
    try {
      const body = new FormData();
      body.set('csrf_token', panel.dataset.signatureCsrf);
      body.set('poll', 'yes');
      const response = await fetch(panel.dataset.signaturePoll, {method:'POST', body, headers:{Accept:'application/json'}});
      const result = response.ok ? await response.json() : null;
      if (result?.signature?.etag && result.signature.etag !== panel.dataset.signatureEtag && !edited) window.location.reload();
    } catch (_) { /* The explicit refresh button remains available. */ }
    finally { polling = false; }
  }, 30000);
});

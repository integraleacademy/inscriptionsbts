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

// One click authorizes preparation and delivery. Status is persisted on the server.
(() => {
  const root = document.querySelector?.('[data-london-workspace]');
  if (!root) return;
  const dialog = document.getElementById('london-transmission');
  const form = root.querySelector('[data-london-send]');
  const statusURL = root.dataset.statusUrl;
  const title = dialog.querySelector('#london-dialog-title');
  const description = dialog.querySelector('#london-dialog-description');
  const close = dialog.querySelector('[data-london-dialog-close]');
  const note = dialog.querySelector('.london-dialog-note');
  let waiting = false, changed = false, polling = false, lastChecked = 0;
  const tabs = [...root.querySelectorAll('[data-london-tab]')];
  const storageKey = 'london-tab:' + statusURL;
  function select(key) {
    tabs.forEach(tab => {
      const selected = tab.dataset.londonTab === key;
      tab.setAttribute('aria-selected', String(selected)); tab.tabIndex = selected ? 0 : -1;
      document.getElementById('london-panel-' + tab.dataset.londonTab).hidden = !selected;
    });
    try { sessionStorage.setItem(storageKey, key); } catch (_) {}
  }
  tabs.forEach((tab,index) => {
    tab.addEventListener('click', () => select(tab.dataset.londonTab));
    tab.addEventListener('keydown', event => {
      if (!['ArrowLeft','ArrowRight','Home','End'].includes(event.key)) return;
      event.preventDefault();
      const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length-1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
      tabs[next].focus(); select(tabs[next].dataset.londonTab);
    });
  });
  root.querySelectorAll('[data-london-open]').forEach(button => button.addEventListener('click', () => select(button.dataset.londonOpen)));
  try { const saved = sessionStorage.getItem(storageKey); if (tabs.some(tab => tab.dataset.londonTab === saved)) select(saved); } catch (_) {}
  function progress(stage) {
    [...dialog.querySelectorAll('[data-stage]')].forEach((li,index) => {
      li.classList.toggle('is-done', index < stage); li.classList.toggle('is-current', index === stage);
      li.querySelector('span').textContent = index < stage ? '✓' : '';
    });
  }
  function error(message) {
    waiting = false; dialog.classList.add('is-error');
    title.textContent = 'Transmission à vérifier'; description.textContent = message;
    close.textContent = 'Revenir au suivi'; note.textContent = 'Le suivi conserve les opérations déjà réalisées pour éviter tout doublon.';
  }
  function show(state) {
    if (!state) return;
    changed = true;
    if (['ongoing','done','completed'].includes(state.status)) {
      waiting = false; progress(3); dialog.classList.add('is-success');
      title.textContent = state.status === 'completed' ? 'La convention est entièrement signée' : 'La convention a été transmise';
      description.textContent = state.status === 'completed' ? 'Le PDF signé est archivé dans ce dossier.' : 'Les invitations sont envoyées. Chaque signataire validera sa signature avec un code reçu par SMS.';
      close.textContent = 'Voir le suivi des signatures'; note.textContent = 'Une notification apparaîtra dans « Voyage à Londres » lorsque toutes les signatures seront réunies.';
    } else if (state.error || !state.active) {
      error(state.error || 'La demande est arrêtée. Consultez son suivi avant un nouvel envoi.');
    } else {
      progress(1); description.textContent = 'La convention est prête. Nous transmettons le document et préparons les invitations sécurisées.';
    }
  }
  async function poll() {
    if (polling || document.hidden || (!waiting && Date.now() - lastChecked < 30000)) return;
    lastChecked = Date.now(); polling = true;
    try {
      const response = await fetch(statusURL, {headers:{Accept:'application/json'}});
      if (!response.ok || response.redirected) {
        if (waiting && (response.status === 403 || response.redirected)) error('Votre session a expiré. Reconnectez-vous pour retrouver le suivi.');
        return;
      }
      const result = await response.json();
      if (waiting) show(result.signature);
      else if (!dialog.open && result.signature?.etag && result.signature.etag !== root.dataset.signatureEtag) {
        if (!document.querySelector('[data-mobility-form][aria-busy="true"]') && !document.querySelector('.london-cancel[open]')) window.location.reload();
      }
    } catch (_) { /* A transient network error never authorizes another send. */ }
    finally { polling = false; }
  }
  close.addEventListener('click', () => dialog.close());
  dialog.addEventListener('close', () => { if (changed || waiting) window.location.reload(); });
  form?.addEventListener('submit', async event => {
    event.preventDefault(); if (waiting) return;
    waiting = true; changed = false;
    form.querySelector('button').disabled = true;
    dialog.classList.remove('is-error','is-success'); progress(0);
    title.textContent = 'Convention Londres en cours de transmission';
    description.textContent = 'Nous récupérons les informations et préparons le document.';
    description.setAttribute('aria-live','polite'); dialog.showModal();
    try {
      const response = await fetch(form.getAttribute('action'), {method:'POST',body:new FormData(form),headers:{Accept:'application/json'}});
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.ok) {
        changed = true;
        error(result?.issues?.map(item => item.message).join(' ') || result?.error || (response.redirected || response.status === 403 ? 'Votre session a expiré. Reconnectez-vous pour continuer.' : 'Le serveur n’a pas confirmé la transmission. Consultez le suivi avant de réessayer.'));
        return;
      }
      show(result.signature); if (waiting) await poll();
    } catch (_) {
      changed = true; error('La connexion a été interrompue. Consultez le suivi : votre demande peut déjà être en cours de transmission.');
    }
  });
  setInterval(() => { if (waiting || (!document.hidden && root.getClientRects().length)) poll(); }, 2500);
})();

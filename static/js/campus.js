(() => {
  'use strict';
  const root = document.querySelector('[data-enrollments]');
  if (!root) return;
  const all = root.querySelector('[data-select-all]');
  const bulk = root.querySelector('[data-assign-bulk]');
  const target = document.getElementById('bulk-promotion');
  const feedback = root.querySelector('[data-enrollment-feedback]');
  const contractFeedback = root.querySelector('[data-contract-feedback]');
  const checkContracts = root.querySelector('[data-check-contracts]');
  const contractsEnabled = !checkContracts.disabled;
  const filters = root.querySelector('.campus-filters');
  let busy = false, checking = false, refreshPending = false, refreshVersion = 0;
  const renderedRows = new Map([...root.querySelectorAll('tr[data-enrollment-id]')].map(row => [row.dataset.enrollmentId, row.outerHTML]));
  const observedPhotos = new WeakSet();
  const checks = () => [...root.querySelectorAll('[data-select-student]')];
  const selected = () => checks().filter(c => c.checked);

  function sync() {
    const chosen = selected(), current = checks();
    const groups = new Set(chosen.map(c => c.closest('tr').dataset.bts + '|' + c.closest('tr').dataset.year));
    root.querySelector('[data-selected-count]').textContent = chosen.length + ' étudiant' + (chosen.length > 1 ? 's' : '') + ' sélectionné' + (chosen.length > 1 ? 's' : '');
    all.checked = !!current.length && chosen.length === current.length;
    all.indeterminate = !!chosen.length && !all.checked;
    [...target.options].forEach(o => {o.disabled = !!o.value && groups.size > 0 && (groups.size > 1 || !groups.has(o.dataset.bts + '|' + o.dataset.year));});
    if (target.selectedOptions[0]?.disabled) target.value = '';
    bulk.disabled = busy || !chosen.length || groups.size !== 1 || !target.value;
  }

  function photos() {
    root.querySelectorAll('[data-student-photo]').forEach(photo => {
      if (observedPhotos.has(photo)) return;
      observedPhotos.add(photo);
      // Retain the initials if an old upload is missing or unreadable.
      photo.addEventListener('error', () => {photo.hidden = true;}, {once: true});
      if (photo.complete && !photo.naturalWidth) photo.hidden = true;
    });
  }

  async function json(url, options = {}) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 40000);
    try {
      const response = await fetch(url, {credentials: 'same-origin', cache: 'no-store', ...options, signal: controller.signal});
      const result = await response.json().catch(() => {throw Error('La session a expiré. Rechargez la page.');});
      if (!response.ok || !result.ok) throw Error(result.error || result.message || 'Impossible de terminer la vérification. Réessayez plus tard.');
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw Error('La vérification prend trop de temps. Les dossiers non vérifiés restent « À vérifier ».');
      throw error;
    } finally {clearTimeout(timer);}
  }

  async function refresh() {
    const version = ++refreshVersion;
    const result = await json('/admin/inscriptions/donnees' + location.search);
    if (version !== refreshVersion) return result;
    root.querySelector('[data-enrollment-stats]').innerHTML = result.stats_html;
    // Never replace a promotion selector while the administrator is using it.
    const body = root.querySelector('[data-enrollment-rows]');
    if (busy || body.contains(document.activeElement)) {
      refreshPending = true;
      return result;
    }
    const ids = new Set(selected().map(c => c.value));
    const placements = new Map([...body.querySelectorAll('tr[data-enrollment-id]')].map(row => [row.dataset.enrollmentId, row.querySelector('select').value]));
    const incoming = document.createElement('tbody');
    incoming.innerHTML = result.rows_html;
    const currentRows = new Map([...body.querySelectorAll('tr[data-enrollment-id]')].map(row => [row.dataset.enrollmentId, row]));
    const nextIds = new Set();
    incoming.querySelectorAll('tr[data-enrollment-id]').forEach(row => {
      const id = row.dataset.enrollmentId, previous = currentRows.get(id), html = row.outerHTML;
      nextIds.add(id);
      // Reuse unchanged rows and already loaded portraits during discovery.
      if (previous && renderedRows.get(id) === html) row.replaceWith(previous);
      else if (previous) {
        const photo = previous.querySelector('[data-student-photo]');
        const nextPhoto = row.querySelector('[data-student-photo]');
        if (photo && nextPhoto && photo.getAttribute('src') === nextPhoto.getAttribute('src')) nextPhoto.replaceWith(photo);
      }
      renderedRows.set(id, html);
    });
    for (const id of renderedRows.keys()) if (!nextIds.has(id)) renderedRows.delete(id);
    body.replaceChildren(...incoming.childNodes);
    checks().forEach(c => {c.checked = ids.has(c.value);});
    body.querySelectorAll('tr[data-enrollment-id]').forEach(row => {
      if (placements.has(row.dataset.enrollmentId)) row.querySelector('select').value = placements.get(row.dataset.enrollmentId);
    });
    refreshPending = false;
    photos(); sync();
    return result;
  }

  async function discover(ids) {
    if (checking || busy || !contractsEnabled) return;
    checking = true;
    checkContracts.disabled = true;
    let done = 0;
    try {
      if (!ids) ids = (await refresh()).discovery;
      for (const id of ids) {
        contractFeedback.textContent = `Vérification des contrats : ${done + 1} / ${ids.length} étudiants… Les compteurs se mettent à jour progressivement.`;
        let finished = false;
        for (let phase = 0; phase < 8; phase++) {
          const result = await json(`/admin/candidat/${encodeURIComponent(id)}/contrats-apprentissage/detecter`, {
            method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.wedofCsrf}, body: '{}'
          });
          if (result.stop_sync) throw Error(result.message);
          if (!result.pending) {finished = true; break;}
        }
        if (!finished) throw Error('La recherche de ce dossier est incomplète. Consultez sa fiche pour la poursuivre.');
        done++;
        await refresh();
      }
      contractFeedback.textContent = 'Vérification terminée. Les compteurs correspondent aux filtres appliqués ; les éventuels cas ambigus restent « À vérifier ».';
    } catch (error) {
      contractFeedback.textContent = error.message + ' Les contrats déjà trouvés sont conservés ; les dossiers non vérifiés restent « À vérifier ».';
      try {await refresh();} catch (_) { /* Keep the original, actionable error. */ }
    } finally {
      checking = false;
      checkContracts.disabled = !contractsEnabled || busy;
    }
  }

  async function assign(ids, promotion) {
    if (busy) return;
    feedback.hidden = false;
    if (!promotion) {feedback.textContent = 'Choisissez une promotion.'; return;}
    busy = true;
    const controls = [...root.querySelectorAll('button,input,select')];
    const disabled = controls.map(n => n.disabled);
    controls.forEach(n => {n.disabled = true;});
    feedback.textContent = 'Affectation en cours…';
    try {
      await json('/admin/inscriptions/affecter', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.csrf}, body: JSON.stringify({ids, promotion_id: promotion})});
      location.reload();
    } catch (error) {
      feedback.textContent = error.message;
      busy = false;
      controls.forEach((n, i) => {n.disabled = disabled[i];});
      checkContracts.disabled = !contractsEnabled || checking;
      sync();
    }
  }

  root.addEventListener('change', event => {
    if (event.target.matches('[data-select-student]') || event.target === target) sync();
    if (event.target === all) {checks().forEach(c => {c.checked = all.checked;}); sync();}
    if (filters.contains(event.target) && (event.target.tagName === 'SELECT' || event.target.type === 'number')) filters.requestSubmit();
  });
  root.addEventListener('click', event => {
    const button = event.target.closest('[data-assign-one]');
    if (button) {const row = button.closest('tr'); assign([row.dataset.enrollmentId], row.querySelector('select').value);}
  });
  root.addEventListener('focusout', () => {
    if (refreshPending) setTimeout(() => {if (!busy) refresh().catch(() => {});}, 0);
  });
  bulk.addEventListener('click', () => assign(selected().map(c => c.value), target.value));
  checkContracts.addEventListener('click', () => discover());
  // Re-read local links after another tab attaches a contract. No remote polling.
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden && !checking && !busy) refresh().catch(() => {});
  });
  photos(); sync();
  const queue = JSON.parse(root.querySelector('[data-contract-discovery]').textContent);
  if (queue.length) discover(queue);
})();

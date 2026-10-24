/* Promotion mutations require an explicit save or a confirmed status action. */
(() => {
  'use strict';
  const root = document.querySelector('.promotions-admin');
  if (!root) return;
  const $ = id => document.getElementById(id);
  const config = JSON.parse($('promotions-data').textContent);
  const dialog = $('promotion-dialog'), form = $('promotion-form'), error = $('promotion-error');
  const confirmation = $('promotion-confirmation');
  let current = null, busy = false, dirty = false, opener = null, confirmed = false;
  const report = message => { error.textContent = message; error.hidden = !message; };
  function updateActions() {
    $('promotion-toggle').disabled = busy || dirty;
    $('promotion-save-note').textContent = dirty && current ? 'Enregistrez vos modifications avant d’archiver ou de réactiver la promotion.' : 'Les étudiants et les formateurs sont affectés séparément.';
  }
  function setBusy(value) {
    busy = value; dialog.setAttribute('aria-busy', String(value));
    dialog.querySelectorAll('input,select,button').forEach(control => { control.disabled = value; });
    updateActions();
  }
  function setDirty() { dirty = true; confirmation.hidden = true; confirmed = false; updateActions(); }
  function setDateRange() { form.elements.date_fin.min = form.elements.date_debut.value || ''; }
  function openEditor(promotion, trigger) {
    if (busy) return;
    current = promotion || null; opener = trigger; dirty = false; confirmed = false;
    form.reset(); report(''); confirmation.hidden = true;
    form.elements.nom.value = promotion?.nom || '';
    form.elements.bts.value = promotion?.bts || config.selected_bts || '';
    form.elements.niveau.value = promotion?.niveau ? String(promotion.niveau) : '';
    const year = String(promotion?.rentree_annee || config.selected_year || '');
    if (year && ![...form.elements.rentree_annee.options].some(option => option.value === year)) form.elements.rentree_annee.add(new Option('Rentrée ' + year, year));
    form.elements.rentree_annee.value = year;
    form.elements.date_debut.value = promotion?.date_debut || '';
    form.elements.date_fin.value = promotion?.date_fin || ''; setDateRange();
    $('promotion-editor-title').textContent = promotion ? 'La promotion' : 'Nouvelle promotion';
    $('promotion-save').textContent = promotion ? 'Enregistrer les modifications' : 'Créer la promotion';
    $('promotion-existing-actions').hidden = !promotion;
    if (promotion) {
      const state = $('promotion-editor-state');
      state.textContent = promotion.active ? (promotion.needs_setup ? 'À compléter' : 'Promotion active') : 'Promotion archivée';
      state.className = 'promotion-state ' + (!promotion.active ? 'archived' : promotion.needs_setup ? 'setup' : 'active');
      $('promotion-toggle').textContent = promotion.active ? 'Archiver la promotion' : 'Réactiver la promotion';
      $('promotion-students-link').href = '/admin?' + new URLSearchParams({bts: promotion.bts, rentree: promotion.rentree_annee});
      $('promotion-trainers-link').href = '/admin/formateurs?' + new URLSearchParams({promotion: promotion.id});
    }
    updateActions(); dialog.showModal(); form.elements.nom.focus();
  }
  async function post(path, data) {
    const response = await fetch(path, {method: 'POST', credentials: 'same-origin', headers: {Accept: 'application/json'}, body: data});
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw Error(result.message || result.error || 'L’action n’a pas abouti. Reconnectez-vous puis réessayez.');
    return result;
  }
  function finish(message) {
    try { sessionStorage.setItem('promotion-notice', message); } catch (_) { /* Saved cards also provide confirmation. */ }
    location.reload();
  }
  $('promotion-create-open').addEventListener('click', event => openEditor(null, event.currentTarget));
  document.querySelectorAll('[data-create-promotion]').forEach(button => button.addEventListener('click', () => openEditor(null, button)));
  document.querySelectorAll('[data-edit-promotion]').forEach(button => button.addEventListener('click', () => {
    const promotion = config.promotions.find(item => String(item.id) === button.dataset.editPromotion);
    if (promotion) openEditor(promotion, button);
  }));
  dialog.querySelectorAll('[data-close-promotion]').forEach(button => button.addEventListener('click', () => { if (!busy) dialog.close(); }));
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => opener?.focus());
  form.addEventListener('input', setDirty); form.addEventListener('change', setDirty);
  form.elements.date_debut.addEventListener('change', setDateRange);
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !form.reportValidity()) return; report('');
    if (form.elements.date_debut.value > form.elements.date_fin.value) { report('La date de fin doit être postérieure ou égale à la date de début.'); form.elements.date_fin.focus(); return; }
    form.elements.nom.value = form.elements.nom.value.trim();
    if (!form.elements.nom.value) { report('Saisissez un nom pour cette promotion.'); form.elements.nom.focus(); return; }
    const data = new FormData(form), path = current ? '/admin/promotions/' + encodeURIComponent(current.id) + '/update' : '/admin/promotions';
    setBusy(true);
    try { const result = await post(path, data); finish(result.message || 'Promotion enregistrée.'); }
    catch (failure) { report(failure.message); }
    finally { setBusy(false); }
  });
  $('promotion-toggle').addEventListener('click', () => {
    if (busy || dirty || !current) return;
    report(''); confirmed = true;
    $('promotion-confirmation-text').textContent = current.active ? 'Archiver « ' + current.nom + ' » ? Les affectations seront conservées, mais les formateurs n’auront plus accès aux étudiants de cette promotion. Vous pourrez la réactiver.' : 'Réactiver « ' + current.nom + ' » ? Les formateurs affectés retrouveront l’accès aux étudiants dont l’inscription est confirmée.';
    $('promotion-action-confirm').textContent = current.active ? 'Archiver la promotion' : 'Réactiver la promotion';
    confirmation.hidden = false; $('promotion-action-confirm').focus();
  });
  $('promotion-action-cancel').addEventListener('click', () => { confirmation.hidden = true; confirmed = false; $('promotion-toggle').focus(); });
  $('promotion-action-confirm').addEventListener('click', async () => {
    if (busy || dirty || !current || !confirmed) return;
    const data = new FormData(); data.append('csrf_token', root.dataset.csrf); data.append('active', current.active ? '0' : '1');
    setBusy(true);
    try { const result = await post('/admin/promotions/' + encodeURIComponent(current.id) + '/status', data); finish(result.message || 'État de la promotion mis à jour.'); }
    catch (failure) { report(failure.message); confirmation.hidden = true; confirmed = false; }
    finally { setBusy(false); }
  });
  const normal = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr').trim();
  const search = $('promotion-search'), status = $('promotion-status-filter'), cards = [...document.querySelectorAll('[data-promotion-card]')];
  function filter() {
    let count = 0; const query = normal(search.value);
    for (const card of cards) {
      const statusMatches = status.value === 'all' || (status.value === 'active' && card.dataset.active === '1') || (status.value === 'archived' && card.dataset.active === '0') || (status.value === 'setup' && card.dataset.setup === '1');
      card.hidden = !statusMatches || !normal(card.dataset.search).includes(query);
      if (!card.hidden) count++;
    }
    $('promotion-result-count').textContent = count + ' promotion' + (count !== 1 ? 's' : '') + ' affichée' + (count !== 1 ? 's' : '');
    $('promotion-empty').hidden = count !== 0;
  }
  search.addEventListener('input', filter); status.addEventListener('change', filter); filter();
  try { const message = sessionStorage.getItem('promotion-notice'); if (message) { $('promotion-notice').textContent = message; $('promotion-notice').hidden = false; sessionStorage.removeItem('promotion-notice'); } } catch (_) { /* Storage is optional. */ }
})();

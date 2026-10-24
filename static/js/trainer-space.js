/* Formateur UI: no account change or e-mail is triggered by editing a field. */
(() => {
  'use strict';
  const normal = value => String(value || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLocaleLowerCase('fr').trim();
  const $ = id => document.getElementById(id);
  const directory = document.querySelector('.trainer-admin');
  if (directory) {
    const config = JSON.parse($('trainer-admin-data').textContent);
    const dialog = $('trainer-account-dialog'), form = $('trainer-account-form');
    const assignments = $('trainer-assignment-list'), hiddenAssignments = $('trainer-assignment-inputs');
    const error = $('trainer-account-error'), confirmation = $('trainer-account-confirmation');
    let current = null, dirty = false, busy = false, confirmedAction = null, opener = null, actionOpener = null;
    const report = message => { error.textContent = message; error.hidden = !message; };
    const firstName = value => value.trim().toLocaleLowerCase('fr').replace(/(^|[\s'’\-])(\p{L})/gu, (_, prefix, letter) => prefix + letter.toLocaleUpperCase('fr'));
    function updateActionButtons() {
      $('trainer-send-access').disabled = busy || dirty || !current?.active;
      $('trainer-toggle-status').disabled = busy || dirty;
      $('trainer-account-save-note').textContent = dirty && current ? 'Enregistrez vos modifications avant d’utiliser les actions du compte.' : 'Les accès restent limités aux promotions sélectionnées.';
    }
    function setDirty() { dirty = true; confirmation.hidden = true; confirmedAction = null; updateActionButtons(); }
    function setBusy(value) {
      busy = value;
      dialog.setAttribute('aria-busy', String(value));
      dialog.querySelectorAll('button,input,select').forEach(item => { item.disabled = value; });
      updateActionButtons(); updateUnavailabilityTimeControls();
    }
    function promotionLabel(promotion) {
      const level = promotion.niveau ? (Number(promotion.niveau) === 1 ? '1re année' : '2e année') : 'Niveau à compléter';
      return promotion.nom + ' · BTS ' + promotion.bts + ' · ' + level + ' · Rentrée ' + promotion.rentree_annee + (!promotion.active ? ' · Archivée' : '');
    }
    function addAssignment(value = {}, markDirty = true) {
      const row = document.createElement('div'); row.className = 'trainer-assignment-row trainer-promotion-assignment';
      const label = document.createElement('label'); label.textContent = 'Promotion';
      const select = document.createElement('select'); select.className = 'trainer-assignment-promotion'; select.required = true;
      select.add(new Option('Choisir une promotion', ''));
      const existing = new Set((current?.assignments || []).map(item => String(item.id)));
      for (const promotion of config.promotions || []) {
        if (promotion.active || existing.has(String(promotion.id))) select.add(new Option(promotionLabel(promotion), String(promotion.id)));
      }
      select.value = value.id ? String(value.id) : '';
      label.append(select);
      const detail = document.createElement('small'); detail.className = 'trainer-assignment-detail';
      const showDetail = () => {
        const promotion = (config.promotions || []).find(item => String(item.id) === select.value);
        detail.textContent = promotion ? promotionLabel(promotion) : 'Choisissez une promotion pour définir le groupe d’étudiants accessible.';
      };
      select.addEventListener('change', showDetail); showDetail(); label.append(detail);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'trainer-assignment-remove';
      remove.textContent = '×'; remove.setAttribute('aria-label', 'Retirer cette affectation');
      remove.addEventListener('click', () => { row.remove(); setDirty(); });
      row.append(label, remove); assignments.append(row);
      if (markDirty) setDirty();
    }
    function openEditor(account, button) {
      if (busy) return;
      current = account || null; opener = button; dirty = false; report('');
      confirmation.hidden = true; confirmedAction = null; form.reset(); assignments.replaceChildren(); hiddenAssignments.replaceChildren();
      form.elements.prenom.value = account?.prenom || '';
      form.elements.nom.value = account?.nom || '';
      form.elements.email.value = account?.email || '';
      $('trainer-account-title').textContent = account ? 'Le compte de ' + account.prenom : 'Nouveau formateur';
      $('trainer-account-save').textContent = account ? 'Enregistrer les modifications' : 'Créer le compte';
      $('trainer-existing-actions').hidden = !account; $('trainer-new-guidance').hidden = !!account;
      if (account) {
        $('trainer-editor-state').textContent = account.active ? (account.activated ? 'Compte actif' : 'Activation en attente') : 'Compte désactivé';
        $('trainer-editor-state').className = 'trainer-account-state ' + (account.active ? 'active' : 'disabled');
        $('trainer-toggle-status').textContent = account.active ? 'Désactiver le compte' : 'Réactiver le compte';
        for (const assignment of account.assignments || []) addAssignment(assignment, false);
      } else if (config.selected_promotion) {
        const requested = (config.promotions || []).find(item => String(item.id) === String(config.selected_promotion) && item.active);
        if (requested) addAssignment(requested, false);
      }
      $('trainer-no-promotions').hidden = (config.promotions || []).some(item => item.active);
      updateActionButtons(); dialog.showModal(); form.elements.prenom.focus(); loadUnavailability(account?.id, true);
    }
    function closeEditor() { if (!busy) dialog.close(); }
    function reloadWithNotice(message) {
      try { sessionStorage.setItem('trainer-admin-notice', message); } catch (_) { /* The saved list remains the success signal. */ }
      location.reload();
    }
    async function post(path, data) {
      const response = await fetch(path, {method: 'POST', headers: {Accept: 'application/json'}, credentials: 'same-origin', body: data});
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok === false) throw Error(result.error || result.message || 'L’action n’a pas abouti. Reconnectez-vous puis réessayez.');
      return result;
    }
    form.addEventListener('input', setDirty);
    form.addEventListener('change', setDirty);
    form.elements.nom.addEventListener('blur', () => { form.elements.nom.value = form.elements.nom.value.trim().toLocaleUpperCase('fr'); });
    form.elements.prenom.addEventListener('blur', () => { form.elements.prenom.value = firstName(form.elements.prenom.value); });
    $('trainer-add-assignment').addEventListener('click', () => addAssignment());
    $('trainer-create-open').addEventListener('click', event => openEditor(null, event.currentTarget));
    document.querySelectorAll('[data-create-trainer]').forEach(button => button.addEventListener('click', () => openEditor(null, button)));
    document.querySelectorAll('[data-edit-trainer]').forEach(button => button.addEventListener('click', () => openEditor(config.accounts.find(account => String(account.id) === button.dataset.editTrainer), button)));
    dialog.querySelectorAll('[data-close-trainer-dialog]').forEach(button => button.addEventListener('click', closeEditor));
    dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
    dialog.addEventListener('close', () => opener?.focus());
    form.addEventListener('submit', async event => {
      event.preventDefault(); if (busy || !form.reportValidity()) return;
      report(''); hiddenAssignments.replaceChildren();
      const selected = new Set();
      for (const row of assignments.children) {
        const promotionId = row.querySelector('.trainer-assignment-promotion').value;
        if (selected.has(promotionId)) { report('Cette promotion est présente plusieurs fois. Conservez une seule ligne par promotion.'); return; }
        selected.add(promotionId);
        const input = document.createElement('input'); input.type = 'hidden'; input.name = 'assignments'; input.value = promotionId; hiddenAssignments.append(input);
      }
      form.elements.nom.value = form.elements.nom.value.trim().toLocaleUpperCase('fr');
      form.elements.prenom.value = firstName(form.elements.prenom.value);
      const data = new FormData(form), creating = !current;
      setBusy(true);
      try { const result = await post(creating ? '/admin/formateurs' : '/admin/formateurs/' + encodeURIComponent(current.id) + '/update', data); reloadWithNotice(result.message || (creating ? 'Compte formateur créé. Vous pouvez maintenant lui envoyer ses accès.' : 'Compte formateur mis à jour.')); }
      catch (failure) { report(failure.message); }
      finally { setBusy(false); }
    });
    function confirm(action) {
      if (busy || dirty || !current) return;
      report(''); confirmedAction = action; actionOpener = action === 'send-access' ? $('trainer-send-access') : $('trainer-toggle-status');
      const send = action === 'send-access';
      $('trainer-account-confirmation-text').textContent = send ? (current.activated ? 'Un lien de réinitialisation du mot de passe, valable 30 minutes, sera envoyé à ' + current.email + '. Aucun mot de passe ne sera envoyé en clair.' : 'Un lien d’activation, valable 72 heures, sera envoyé à ' + current.email + ' pour lui permettre de choisir son mot de passe.') : (current.active ? 'Le formateur ne pourra plus accéder à son espace. Son compte et ses affectations seront conservés.' : 'Le formateur pourra à nouveau accéder aux promotions actives qui lui sont attribuées.');
      $('trainer-action-confirm').textContent = send ? 'Envoyer les accès' : (current.active ? 'Désactiver le compte' : 'Réactiver le compte');
      confirmation.hidden = false;
      $('trainer-action-confirm').focus();
    }
    $('trainer-send-access').addEventListener('click', () => { if (current?.active) confirm('send-access'); });
    $('trainer-toggle-status').addEventListener('click', () => confirm('status'));
    $('trainer-action-cancel').addEventListener('click', () => { confirmation.hidden = true; confirmedAction = null; actionOpener?.focus(); });
    $('trainer-action-confirm').addEventListener('click', async () => {
      if (!current || !confirmedAction || busy || dirty) return;
      const action = confirmedAction, data = new FormData(); data.append('csrf_token', directory.dataset.csrf);
      if (action === 'status') data.append('active', current.active ? '0' : '1');
      setBusy(true);
      try { const result = await post('/admin/formateurs/' + encodeURIComponent(current.id) + '/' + action, data); reloadWithNotice(result.message || 'Action effectuée.'); }
      catch (failure) { report(failure.message); confirmation.hidden = true; confirmedAction = null; }
      finally { setBusy(false); }
    });
    let unavailabilitySequence = 0, pendingUnavailability = null, unavailabilityDeleteOpener = null;
    const unavailabilityForm = $('trainer-unavailability-form');
    const readableDate = value => new Date(value + 'T12:00:00').toLocaleDateString('fr-FR', {day: 'numeric', month: 'short', year: 'numeric'});
    function unavailableFeedback(message, failure = false) {
      const feedback = $('trainer-unavailability-feedback'); feedback.textContent = message || ''; feedback.hidden = !message; feedback.className = 'trainer-feedback ' + (failure ? 'error' : 'success');
    }
    function updateUnavailabilityTimeControls() {
      if (!unavailabilityForm) return; const allDay = unavailabilityForm.elements.all_day.checked;
      $('trainer-unavailability-times').hidden = allDay;
      for (const field of ['time_start', 'time_end']) { unavailabilityForm.elements[field].disabled = busy || allDay; unavailabilityForm.elements[field].required = !allDay; }
    }
    async function unavailabilityRequest(path, method = 'GET', data = {}) {
      const response = await fetch(path, {method, credentials: 'same-origin', headers: {Accept: 'application/json', ...(method !== 'GET' ? {'Content-Type': 'application/json', 'X-CSRF-Token': directory.dataset.planningCsrf} : {})}, ...(method !== 'GET' ? {body: JSON.stringify(data)} : {})});
      const result = await response.json().catch(() => ({}));
      if (!response.ok || result.ok === false) throw Error([result.message || result.error || 'L’action n’a pas abouti.', ...(result.conflicts || []).map(item => (item.date ? readableDate(item.date) + ' : ' : '') + item.message)].join('\n'));
      return result;
    }
    async function loadUnavailability(trainerId, reset = false) {
      const sequence = ++unavailabilitySequence, section = $('trainer-unavailability'); section.hidden = !trainerId || !directory.dataset.planningCsrf;
      pendingUnavailability = null; $('trainer-unavailability-confirm').hidden = true;
      if (!trainerId || !directory.dataset.planningCsrf) return;
      if (reset) { unavailabilityForm.reset(); unavailableFeedback(''); const date = new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/Paris', year: 'numeric', month: '2-digit', day: '2-digit'}).format(new Date()); unavailabilityForm.elements.start_date.value = date; unavailabilityForm.elements.end_date.value = date; updateUnavailabilityTimeControls(); }
      const container = $('trainer-unavailability-items'); container.replaceChildren(); const loading = document.createElement('p'); loading.textContent = 'Chargement des indisponibilités…'; container.append(loading);
      try {
        const result = await unavailabilityRequest('/admin/formateurs/' + encodeURIComponent(trainerId) + '/indisponibilites');
        if (sequence !== unavailabilitySequence || String(current?.id) !== String(trainerId)) return;
        container.replaceChildren();
        for (const block of result.items || []) {
          const item = document.createElement('article'); item.className = 'trainer-unavailability-item'; const details = document.createElement('div'), title = document.createElement('b'), dates = document.createElement('span'), times = document.createElement('small');
          title.textContent = block.reason; dates.textContent = readableDate(block.start_date) + ' — ' + readableDate(block.end_date); times.textContent = (block.weekdays || [0, 1, 2, 3, 4, 5, 6]).map(day => ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'][day]).join(' · ') + ' · ' + (block.times?.length ? block.times.map(slot => slot.start + '–' + slot.end).join(', ') : 'Toute la journée'); details.append(title, dates, times);
          const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'trainer-button'; remove.textContent = 'Retirer'; remove.setAttribute('aria-label', 'Retirer l’indisponibilité ' + block.reason); remove.addEventListener('click', () => { if (busy) return; pendingUnavailability = block; unavailabilityDeleteOpener = remove; $('trainer-unavailability-confirm-text').textContent = 'Retirer l’indisponibilité « ' + block.reason + ' » du ' + readableDate(block.start_date) + ' au ' + readableDate(block.end_date) + ' ? Ces créneaux redeviendront disponibles s’ils ne sont pas occupés par un cours.'; $('trainer-unavailability-confirm').hidden = false; $('trainer-unavailability-delete').focus(); }); item.append(details, remove); container.append(item);
        }
        if (!container.children.length) { const empty = document.createElement('p'); empty.textContent = 'Aucune indisponibilité enregistrée.'; container.append(empty); }
        return true;
      } catch (failure) { if (sequence === unavailabilitySequence) { container.replaceChildren(); unavailableFeedback(failure.message, true); } return false; }
    }
    unavailabilityForm?.elements.all_day.addEventListener('change', updateUnavailabilityTimeControls);
    unavailabilityForm?.addEventListener('submit', async event => {
      event.preventDefault(); if (busy || !current || !unavailabilityForm.reportValidity()) return;
      const trainerId = current.id, form = unavailabilityForm, weekdays = [...form.querySelectorAll('input[name=weekdays]:checked')].map(input => Number(input.value));
      if (!weekdays.length) { unavailableFeedback('Sélectionnez au moins un jour de la semaine.', true); return; }
      if (form.elements.start_date.value > form.elements.end_date.value) { unavailableFeedback('La date de fin doit suivre la date de début.', true); return; }
      const times = form.elements.all_day.checked ? [] : [{start: form.elements.time_start.value, end: form.elements.time_end.value}];
      if (times.length && times[0].start >= times[0].end) { unavailableFeedback('L’heure de fin doit suivre l’heure de début.', true); return; }
      const data = {start_date: form.elements.start_date.value, end_date: form.elements.end_date.value, weekdays, times, reason: form.elements.reason.value.trim()}; unavailableFeedback(''); setBusy(true);
      try { const result = await unavailabilityRequest('/admin/formateurs/' + encodeURIComponent(trainerId) + '/indisponibilites', 'POST', data); const refreshed = await loadUnavailability(trainerId); unavailableFeedback((result.message || 'Indisponibilité enregistrée.') + (refreshed ? '' : ' La liste n’a pas pu être actualisée. Rouvrez la fiche pour vérifier.'), !refreshed); }
      catch (failure) { unavailableFeedback(failure.message, true); }
      finally { setBusy(false); }
    });
    $('trainer-unavailability-cancel')?.addEventListener('click', () => { pendingUnavailability = null; $('trainer-unavailability-confirm').hidden = true; unavailabilityDeleteOpener?.focus(); });
    $('trainer-unavailability-delete')?.addEventListener('click', async () => {
      if (busy || !current || !pendingUnavailability) return; const trainerId = current.id, blockId = pendingUnavailability.id; setBusy(true); unavailableFeedback('');
      try { await unavailabilityRequest('/admin/formateurs/' + encodeURIComponent(trainerId) + '/indisponibilites/' + encodeURIComponent(blockId), 'DELETE'); const refreshed = await loadUnavailability(trainerId); unavailableFeedback('Indisponibilité retirée.' + (refreshed ? '' : ' La liste n’a pas pu être actualisée. Rouvrez la fiche pour vérifier.'), !refreshed); }
      catch (failure) { unavailableFeedback(failure.message, true); }
      finally { setBusy(false); $('trainer-unavailability-confirm').hidden = true; pendingUnavailability = null; $('trainer-unavailability-save').focus(); }
    });
    const search = $('trainer-search'), rows = [...document.querySelectorAll('[data-trainer-row]')];
    search?.addEventListener('input', () => {
      const query = normal(search.value); let count = 0;
      rows.forEach(row => { row.hidden = !normal(row.dataset.search).includes(query); if (!row.hidden) count++; });
      $('trainer-account-count').textContent = count + ' compte' + (count !== 1 ? 's' : '') + (query ? ' trouvé' + (count !== 1 ? 's' : '') : '');
      if ($('trainer-search-empty')) $('trainer-search-empty').hidden = count !== 0;
    });
    try { const message = sessionStorage.getItem('trainer-admin-notice'); if (message) { $('trainer-admin-notice').textContent = message; $('trainer-admin-notice').hidden = false; sessionStorage.removeItem('trainer-admin-notice'); } } catch (_) { /* Storage is optional. */ }
  }
  const rosterRows = [...document.querySelectorAll('[data-student-row]')];
  const studentSearch = $('trainer-student-search'), promotion = $('trainer-student-promotion');
  if (studentSearch && promotion) {
    function filter() {
      let count = 0; const query = normal(studentSearch.value);
      rosterRows.forEach(row => {
        row.hidden = !normal(row.dataset.search).includes(query) || (!!promotion.value && row.dataset.promotion !== promotion.value);
        if (!row.hidden) count++;
      });
      document.querySelectorAll('[data-promotion-roster]').forEach(group => {
        const visible = [...group.querySelectorAll('[data-student-row]')].filter(row => !row.hidden).length;
        group.hidden = visible === 0;
        const result = group.querySelector('[data-promotion-result]');
        if (result) result.textContent = visible + ' étudiant' + (visible !== 1 ? 's' : '');
      });
      $('trainer-student-result-count').textContent = count + ' étudiant' + (count !== 1 ? 's' : '') + ' affiché' + (count !== 1 ? 's' : '');
      if ($('trainer-student-empty')) $('trainer-student-empty').hidden = count !== 0;
    }
    studentSearch.addEventListener('input', filter); promotion.addEventListener('change', filter);
    $('trainer-student-reset').addEventListener('click', () => { studentSearch.value = ''; promotion.value = ''; filter(); });
    document.querySelectorAll('[data-focus-promotion]').forEach(button => button.addEventListener('click', () => {
      studentSearch.value = ''; promotion.value = button.dataset.focusPromotion; filter();
      $('trainer-roster-title').scrollIntoView({block: 'start', behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
      promotion.focus({preventScroll: true});
    }));
    filter();
  }
})();

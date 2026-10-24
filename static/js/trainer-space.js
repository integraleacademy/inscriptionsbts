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
      $('trainer-account-save-note').textContent = dirty && current ? 'Enregistrez vos modifications avant d’utiliser les actions du compte.' : 'Les accès restent limités aux groupes sélectionnés.';
    }
    function setDirty() { dirty = true; confirmation.hidden = true; confirmedAction = null; updateActionButtons(); }
    function setBusy(value) {
      busy = value;
      dialog.setAttribute('aria-busy', String(value));
      dialog.querySelectorAll('button,input,select').forEach(item => { item.disabled = value; });
      updateActionButtons();
    }
    function addAssignment(value = {}, markDirty = true) {
      const row = document.createElement('div'); row.className = 'trainer-assignment-row';
      const btsLabel = document.createElement('label'), yearLabel = document.createElement('label');
      btsLabel.textContent = 'BTS'; yearLabel.textContent = 'Rentrée';
      const bts = document.createElement('select'), year = document.createElement('select');
      bts.className = 'trainer-assignment-bts'; year.className = 'trainer-assignment-year';
      bts.required = year.required = true;
      bts.add(new Option('Choisir un BTS', ''));
      for (const code of Object.keys(config.bts)) { const option = new Option('BTS ' + code, code); bts.add(option); }
      bts.value = value.bts || config.selected_bts || '';
      for (const item of config.years) year.add(new Option(String(item), String(item)));
      const selectedYear = String(value.rentree_annee || config.selected_year || new Date().getFullYear());
      if (![...year.options].some(option => option.value === selectedYear)) year.add(new Option(selectedYear, selectedYear));
      year.value = selectedYear;
      btsLabel.append(bts); yearLabel.append(year);
      const remove = document.createElement('button'); remove.type = 'button'; remove.className = 'trainer-assignment-remove';
      remove.textContent = '×'; remove.setAttribute('aria-label', 'Retirer cette affectation');
      remove.addEventListener('click', () => { row.remove(); setDirty(); });
      row.append(btsLabel, yearLabel, remove); assignments.append(row);
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
      } else if (config.selected_bts) addAssignment({}, false);
      updateActionButtons(); dialog.showModal(); form.elements.prenom.focus();
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
      const pairs = new Set();
      for (const row of assignments.children) {
        const pair = row.querySelector('.trainer-assignment-bts').value + ':' + row.querySelector('.trainer-assignment-year').value;
        if (pairs.has(pair)) { report('Ce groupe est présent plusieurs fois. Conservez une seule ligne par BTS et rentrée.'); return; }
        pairs.add(pair);
        const input = document.createElement('input'); input.type = 'hidden'; input.name = 'assignments'; input.value = pair; hiddenAssignments.append(input);
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
      $('trainer-account-confirmation-text').textContent = send ? (current.activated ? 'Un lien de réinitialisation du mot de passe, valable 30 minutes, sera envoyé à ' + current.email + '. Aucun mot de passe ne sera envoyé en clair.' : 'Un lien d’activation, valable 72 heures, sera envoyé à ' + current.email + ' pour lui permettre de choisir son mot de passe.') : (current.active ? 'Le formateur ne pourra plus accéder à son espace. Son compte et ses affectations seront conservés.' : 'Le formateur pourra à nouveau accéder aux groupes qui lui sont attribués.');
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
  const studentSearch = $('trainer-student-search'), bts = $('trainer-student-bts'), year = $('trainer-student-year');
  if (studentSearch && bts && year) {
    function filter() {
      let count = 0; const query = normal(studentSearch.value);
      rosterRows.forEach(row => {
        row.hidden = !normal(row.dataset.search).includes(query) || (!!bts.value && row.dataset.bts !== bts.value) || (!!year.value && row.dataset.year !== year.value);
        if (!row.hidden) count++;
      });
      $('trainer-student-result-count').textContent = count + ' étudiant' + (count !== 1 ? 's' : '') + ' affiché' + (count !== 1 ? 's' : '');
      if ($('trainer-student-empty')) $('trainer-student-empty').hidden = count !== 0;
    }
    studentSearch.addEventListener('input', filter); bts.addEventListener('change', filter); year.addEventListener('change', filter);
    $('trainer-student-reset').addEventListener('click', () => { studentSearch.value = ''; bts.value = ''; year.value = ''; filter(); });
    filter();
  }
})();

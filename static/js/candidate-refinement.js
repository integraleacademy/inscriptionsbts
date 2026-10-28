/* Keep portrait fallbacks and the record's visible status in sync. */
(() => {
  'use strict';
  document.querySelectorAll('[data-candidate-photo]').forEach(image => {
    const fallback = () => image.closest('.candidate-portrait')?.classList.add('photo-unavailable');
    image.addEventListener('error', fallback, {once: true});
    if (image.complete && !image.naturalWidth) fallback();
  });
  const select = document.getElementById('candidate-status');
  const badge = document.querySelector('[data-sheet-status]');
  if (select && badge) {
    const sync = async () => {
      const current = select.dataset.current;
      try {
        const cid = document.querySelector('.candidate-sheet').dataset.candidateId;
        const response = await fetch('/admin/row/' + encodeURIComponent(cid), {headers: {Accept: 'application/json'}});
        const data = await response.json();
        if (!response.ok || !data.ok || current !== select.dataset.current) return;
        const option = Array.from(select.options).find(item => item.value === data.row.statut);
        badge.textContent = data.row.display_status_label || option?.textContent || 'Dossier en cours';
        badge.className = 'sheet-status-badge status-' + (data.row.display_status || data.row.statut || 'preinscription');
      } catch (_) { /* Keep the last server-confirmed badge on a network failure. */ }
    };
    new MutationObserver(sync).observe(select, {attributes: true, attributeFilter: ['data-current']});
    document.addEventListener('candidate-employment-changed', sync);
  }
})();

/* One recipient, one explicit send: preview and sending remain separate requests. */
(() => {
  'use strict';
  const sheet = document.querySelector('.candidate-sheet[data-candidate-id]');
  const dialog = document.getElementById('student-composer');
  if (!sheet || !dialog) return;
  const $ = id => document.getElementById(id);
  const form = $('student-message-form'), subject = $('student-message-subject');
  const composerHeader = dialog.querySelector('.student-composer-head');
  new ResizeObserver(() => dialog.style.setProperty('--composer-head-height', composerHeader.getBoundingClientRect().height + 'px')).observe(composerHeader);
  const body = $('student-message-body'), recipient = $('student-message-recipient');
  const fileInput = $('student-message-files'), fileList = $('student-message-file-list');
  const previewButton = $('student-message-preview-button'), sendButton = $('student-message-send');
  const error = $('student-message-error'), success = $('student-message-success');
  const initialSubject = 'Intégrale Academy — Votre inscription en BTS ' + sheet.dataset.course;
  const drafts = {email: {subject: initialSubject, body: '', files: []}, sms: {subject: '', body: '', files: []}};
  let accessTemplate = false;
  let channel = 'email', files = [], previewToken = '', busy = false, lastOpener = null;
  const basePath = '/admin/candidat/' + encodeURIComponent(sheet.dataset.candidateId);
  const report = message => { error.textContent = message; error.hidden = !message; };
  const currentRecipient = () => channel === 'email' ? sheet.dataset.email : sheet.dataset.phone;
  const assistant = window.setupEmailAssistant({form, endpoint: basePath + '/message-assistant', csrf: sheet.dataset.messageCsrf,
    context: () => ({type: 'email', subject: subject.value, body: body.value, sender_id: form.elements.sender_id.value}),
    canUse: () => !busy && channel === 'email'});
  function syncSender() {
    const sender = form.querySelector('[name=sender_id]:checked');
    $('student-message-sender-address').textContent = 'Expéditeur et adresse de réponse : ' + sender.dataset.email;
  }
  function count() {
    $('student-message-count').textContent = channel === 'sms' ? `${Array.from(body.value).length} caractères` : '';
  }
  function invalidatePreview() {
    previewToken = '';
    sendButton.disabled = true;
    $('student-message-preview-result').hidden = true;
    $('student-message-preview-empty').hidden = false;
    $('student-message-preview-state').textContent = 'À préparer';
    $('student-message-preview-frame').removeAttribute('srcdoc');
    success.hidden = true;
    $('student-message-footer-note').textContent = 'Rien n’est envoyé avant votre confirmation.';
  }
  function remember() {
    drafts[channel] = {subject: subject.value, body: body.value, files: [...files]};
  }
  function renderFiles() {
    fileList.replaceChildren();
    files.forEach((file, index) => {
      const li = document.createElement('li'), name = document.createElement('span'), remove = document.createElement('button');
      name.textContent = `${file.name} · ${Math.max(1, Math.ceil(file.size / 1024))} Ko`;
      remove.type = 'button'; remove.textContent = 'Retirer';
      remove.setAttribute('aria-label', 'Retirer ' + file.name);
      remove.addEventListener('click', () => { files.splice(index, 1); renderFiles(); remember(); invalidatePreview(); });
      li.append(name, remove); fileList.append(li);
    });
  }
  function switchChannel(next, save = true) {
    if (busy) return;
    if (save) remember();
    accessTemplate = false;
    channel = next === 'sms' ? 'sms' : 'email';
    const mail = channel === 'email', draft = drafts[channel];
    dialog.dataset.channel = channel;
    $('student-composer-title').textContent = mail ? 'Écrire un e-mail' : 'Envoyer un SMS';
    sendButton.textContent = mail ? 'Envoyer cet e-mail' : 'Envoyer ce SMS';
    recipient.value = currentRecipient() || (mail ? 'Adresse e-mail non renseignée' : 'Téléphone non renseigné');
    subject.value = draft.subject; subject.required = mail;
    body.value = draft.body; body.maxLength = mail ? 20000 : 1600;
    files = [...draft.files]; fileInput.value = '';
    $('student-message-subject-field').hidden = !mail;
    $('student-message-attachments').hidden = !mail;
    $('student-message-email-options').hidden = !mail;
    $('student-message-cta-fields').hidden = !mail;
    $('student-message-cta-fields').querySelectorAll('input').forEach(input => { input.disabled = !mail; });
    assistant.setVisible(mail); syncSender();
    dialog.querySelectorAll('[data-composer-channel]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.composerChannel === channel)));
    renderFiles(); count(); report(''); invalidatePreview();
  }
  function setBusy(value) {
    busy = value;
    dialog.setAttribute('aria-busy', String(value));
    dialog.querySelectorAll('button,input,textarea').forEach(control => { control.disabled = value; });
    if (!value) $('student-message-cta-fields').querySelectorAll('input').forEach(input => { input.disabled = channel !== 'email'; });
    sendButton.disabled = value || !previewToken;
    previewButton.textContent = value ? 'Traitement…' : 'Prévisualiser';
  }
  function validate() {
    if (!currentRecipient()) {
      report(channel === 'email' ? 'Renseignez d’abord l’adresse e-mail dans la fiche de l’étudiant.' : 'Renseignez d’abord le téléphone dans la fiche de l’étudiant.');
      return false;
    }
    if (!body.value.trim() || (channel === 'email' && !subject.value.trim())) {
      report('Renseignez ' + (channel === 'email' ? 'l’objet et le message.' : 'le message.'));
      return false;
    }
    return form.reportValidity();
  }
  function payload() {
    const data = new FormData();
    data.append('type', channel); data.append('subject', channel === 'email' ? subject.value : '');
    if (accessTemplate && channel === 'email') data.append('template', 'student_access');
    data.append('body', body.value); data.append('csrf_token', sheet.dataset.messageCsrf);
    if (channel === 'email') {
      for (const name of ['sender_id', 'layout', 'accent_title', 'action_url', 'action_label']) data.append(name, form.elements[name].value);
    }
    if (channel === 'email') files.forEach(file => data.append('attachment', file, file.name));
    if (previewToken) data.append('preview_token', previewToken);
    return data;
  }
  async function request(path, data) {
    const response = await fetch(basePath + path, {method: 'POST', headers: {Accept: 'application/json'}, credentials: 'same-origin', body: data});
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw Error(result.error || 'Impossible de terminer cette action. Reconnectez-vous puis réessayez.');
    return result;
  }
  document.querySelectorAll('[data-compose]').forEach(button => button.addEventListener('click', () => {
    lastOpener = button;
    switchChannel(button.dataset.compose, false);
    if (button.hasAttribute('data-access-message')) {
      accessTemplate = true;
      subject.value = 'Votre espace étudiant Intégrale Academy vous attend';
      body.value = 'Bonjour,\n\nRetrouvez votre planning, vos cours, vos notes, le suivi de vos absences et les informations de votre entreprise dans votre espace étudiant.\n\nPour vous connecter, utilisez votre adresse e-mail (' + sheet.dataset.email + ') ou votre nom de famille, puis votre mot de passe personnel.\n\nPremière connexion : votre mot de passe initial est votre date de naissance au format JJMMAAAA. Vous serez invité à le remplacer par un mot de passe personnel. Si vous l’avez déjà changé, utilisez le mot de passe que vous avez choisi.\n\nMot de passe oublié ? Cliquez sur « Mot de passe oublié » sur la page de connexion.\n\nÀ très bientôt,\nL’équipe Intégrale Academy';
      files = []; renderFiles(); count(); invalidatePreview();
    }
    dialog.showModal();
    (channel === 'email' ? subject : body).focus();
  }));
  dialog.querySelectorAll('[data-composer-channel]').forEach(button => button.addEventListener('click', () => switchChannel(button.dataset.composerChannel)));
  dialog.querySelectorAll('[data-close-composer]').forEach(button => button.addEventListener('click', () => { if (!busy) dialog.close(); }));
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => { assistant.reset(); remember(); lastOpener?.focus(); });
  [subject, body].forEach(input => input.addEventListener('input', () => { remember(); count(); report(''); invalidatePreview(); }));
  form.querySelectorAll('[name=sender_id],[name=layout],[name=accent_title],[name=action_url],[name=action_label]').forEach(input => {
    input.addEventListener('input', () => { syncSender(); invalidatePreview(); });
  });
  fileInput.addEventListener('change', () => {
    const additions = Array.from(fileInput.files || []);
    const next = [...files, ...additions];
    fileInput.value = '';
    if (next.length > 5 || next.reduce((sum, file) => sum + file.size, 0) > 10 * 1024 * 1024) {
      report('Sélectionnez au maximum 5 fichiers et 10 Mo au total.'); return;
    }
    if (next.some(file => !/\.(pdf|jpe?g|png)$/i.test(file.name))) {
      report('Les pièces jointes doivent être au format PDF, JPG ou PNG.'); return;
    }
    files = next; renderFiles(); remember(); report(''); invalidatePreview();
  });
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !validate()) return;
    report(''); invalidatePreview();
    const data = payload();
    setBusy(true);
    try {
      const result = await request('/message-preview', data);
      if (!result.preview_token) throw Error('L’aperçu n’a pas pu être préparé. Réessayez.');
      previewToken = result.preview_token;
      $('student-message-preview-recipient').textContent = result.recipient;
      $('student-message-preview-subject').textContent = result.subject || '';
      $('student-message-preview-subject-row').hidden = channel !== 'email';
      $('student-message-preview-sender-row').hidden = channel !== 'email';
      $('student-message-preview-sender').textContent = result.sender?.email ? result.sender.name + ' <' + result.sender.email + '>' : '';
      const frame = $('student-message-preview-frame'), sms = $('student-message-preview-sms');
      frame.hidden = channel !== 'email'; sms.hidden = channel !== 'sms';
      if (channel === 'email') frame.srcdoc = result.html || '';
      else sms.textContent = result.body || body.value;
      $('student-message-preview-files').textContent = result.attachments?.length ? 'Pièces jointes : ' + result.attachments.join(', ') : '';
      $('student-message-preview-result').hidden = false; $('student-message-preview-empty').hidden = true;
      $('student-message-preview-state').textContent = 'Prêt à envoyer';
      $('student-message-footer-note').textContent = 'Vérifiez le destinataire et le contenu, puis confirmez l’envoi.';
      if (matchMedia('(max-width: 760px)').matches) $('student-message-preview-title').scrollIntoView({block: 'start', behavior: 'smooth'});
    } catch (e) { report(e.message); }
    finally { setBusy(false); }
  });
  sendButton.addEventListener('click', async () => {
    if (busy || !previewToken || !validate()) return;
    const data = payload(); report(''); setBusy(true);
    try {
      const result = await request('/message', data);
      success.textContent = result.message || (channel === 'email' ? 'L’e-mail a été envoyé à l’étudiant.' : 'Le SMS a été envoyé à l’étudiant.');
      success.hidden = false; previewToken = '';
      $('student-message-preview-state').textContent = 'Envoyé';
      $('student-message-footer-note').textContent = 'Cet échange est enregistré dans l’historique du dossier.';
      drafts[channel] = {subject: channel === 'email' ? initialSubject : '', body: '', files: []};
      subject.value = drafts[channel].subject; body.value = ''; files = []; fileInput.value = ''; renderFiles(); count();
      $('refresh-history')?.click();
    } catch (e) { report(e.message); }
    finally { setBusy(false); }
  });
})();

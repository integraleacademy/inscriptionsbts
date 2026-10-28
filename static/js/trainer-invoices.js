/* Private invoice audit. Untrusted filenames and AI text are always text nodes. */
(() => {
  'use strict';
  const root = document.querySelector('[data-trainer-invoices]');
  if (!root) return;
  const form = root.querySelector('[data-ti-form]');
  const feedback = root.querySelector('[data-ti-feedback]');
  const log = root.querySelector('[data-ti-batch-log]');
  const list = root.querySelector('[data-ti-invoices]');
  const summary = root.querySelector('[data-ti-summary]');
  const archiveToggle = root.querySelector('[data-ti-show-archived]');
  const refreshButton = root.querySelector('[data-ti-refresh]');
  const base = root.dataset.base;
  let busy = false, current = null, timer = null;
  const e = (tag, text, cls) => {
    const node = document.createElement(tag);
    if (text !== undefined && text !== null) node.textContent = String(text);
    if (cls) node.className = cls;
    return node;
  };
  const hours = value => value === null || value === undefined ? 'Non établi' : `${value < 0 ? '−' : ''}${Math.trunc(Math.abs(value) / 60)} h${Math.abs(value % 60) ? ' ' + String(Math.abs(value % 60)).padStart(2, '0') : ''}`;
  const money = (value, currency = 'EUR') => {
    if (value === null || value === undefined) return 'Non établi';
    const label = currency === '€' ? 'EUR' : String(currency || '').trim().toUpperCase();
    if (/^[A-Z]{3}$/.test(label)) {
      try { return new Intl.NumberFormat('fr-FR', {style: 'currency', currency: label}).format(value / 100); } catch (_) { /* display literal below */ }
    }
    return new Intl.NumberFormat('fr-FR', {minimumFractionDigits: 2, maximumFractionDigits: 2}).format(value / 100) + ' ' + (label || '(devise inconnue)');
  };
  const dateTime = value => {
    if (!value) return 'Non renseignée';
    const d = new Date(value);
    return Number.isNaN(d.getTime()) ? value : d.toLocaleString('fr-FR', {timeZone: 'Europe/Paris'});
  };
  const courseLabel = c => `${c.date.split('-').reverse().join('/')} · ${c.start}–${c.end} · ${c.title} · ${c.promotions.join(' / ')}${c.is_shared ? ' · cours commun' : ''}`;
  function tell(message, error = false) {
    feedback.hidden = !message;
    feedback.textContent = message;
    feedback.classList.toggle('is-error', error);
  }
  function lock(value) {
    busy = value;
    root.setAttribute('aria-busy', String(value));
    root.querySelectorAll('button, input[type=file], select').forEach(control => { control.disabled = value; });
  }
  async function api(url, options = {}) {
    const headers = new Headers(options.headers || {});
    headers.set('Accept', 'application/json');
    if (options.method && options.method !== 'GET') headers.set('X-CSRF-Token', root.dataset.csrf);
    const response = await fetch(url, {...options, headers, credentials: 'same-origin', cache: 'no-store'});
    let data;
    try { data = await response.json(); } catch (_) { throw new Error('Réponse serveur illisible ou session expirée. Rechargez la fiche ; les fichiers déjà importés sont conservés.'); }
    if (!response.ok || !data.ok) throw new Error(data.message || 'La demande n’a pas abouti.');
    return data;
  }
  function issues(items) {
    const ul = e('ul', null, 'ti-issues');
    for (const item of items) {
      ul.append(e('li', (item.line ? `Ligne ${item.line} · ` : '') + item.message, item.level === 'error' ? 'is-error' : 'is-review'));
    }
    return ul;
  }
  function metric(title, value, detail) {
    const box = e('div', null, 'ti-metric');
    box.append(e('span', title), e('strong', value), e('small', detail));
    return box;
  }
  function renderSummary(data) {
    summary.replaceChildren();
    const a = data.aggregate;
    const grid = e('div', null, 'ti-metrics');
    grid.append(metric('Factures analysées', a.analyzed_count, `${a.pending_count} document(s) restant à analyser`));
    grid.append(metric('Heures facturées', hours(a.teaching_minutes), `${hours(a.planned_minutes)} planifiées · cours communs comptés une fois`));
    grid.append(metric(`Cours facturés${a.basis ? ' · '+a.basis.toUpperCase() : ''}`, money(a.teaching_cents), 'Hors frais et autres postes'));
    grid.append(metric('Écart au planning complet', money(a.difference_cents), `${money(a.expected_cents)} prévus · un écart négatif peut correspondre à une facture partielle`));
    summary.append(grid);
    if (a.issues.length) summary.append(issues(a.issues));
    if (a.analyzed_count && a.unmatched_courses.length) {
      const details = e('details', null, 'ti-unmatched');
      details.append(e('summary', `${a.unmatched_courses.length} séance(s) non rapprochée(s)`));
      details.append(e('p', 'Ces séances peuvent être incluses dans des lignes globales non détaillées : elles ne sont pas forcément non facturées.', 'ti-help'));
      const ul = e('ul');
      for (const c of a.unmatched_courses) ul.append(e('li', courseLabel(c)));
      details.append(ul); summary.append(details);
    }
  }
  function actionButton(title, callback) {
    const button = e('button', title, 'trainer-button');
    button.type = 'button'; button.disabled = busy;
    button.addEventListener('click', callback);
    return button;
  }
  async function act(url, payload, message) {
    if (busy) return;
    lock(true); tell(message);
    try {
      const options = {method: 'POST'};
      if (payload !== undefined) { options.headers = {'Content-Type': 'application/json'}; options.body = JSON.stringify(payload); }
      const result = await api(url, options);
      tell(result.message || 'Terminé.');
    } catch (error) { tell(error.message, true); }
    finally { try { await load(); } catch (error) { tell(error.message, true); } lock(false); }
  }
  function renderInvoice(item, openIds) {
    const details = e('details', null, 'ti-document');
    details.dataset.invoiceId = item.id;
    details.open = openIds.has(item.id);
    const head = e('summary', null, 'ti-document-summary');
    const identity = e('div');
    identity.append(e('strong', item.extraction && item.extraction.number ? `Facture ${item.extraction.number}` : item.filename));
    identity.append(e('small', `${item.filename} · base de comparaison ${item.basis.toUpperCase()} · importée le ${dateTime(item.created_at)}`));
    const state = item.archived ? 'archived' : (item.report ? item.report.status : item.status);
    const labels = {archived:'Écartée du contrôle',uploaded:'À analyser',processing:'Analyse en cours',failed:'Analyse à relancer',coherent:'Cohérent avec le planning',a_verifier:'À vérifier',ecarts:'Écarts détectés'};
    head.append(identity, e('span', labels[state] || 'À vérifier', 'ti-badge ti-'+state));
    details.append(head);
    const body = e('div', null, 'ti-document-body');
    const actions = e('div', null, 'ti-document-actions');
    const link = e('a', 'Télécharger l’original', 'trainer-button');
    link.href = `${base}/${encodeURIComponent(item.id)}/original`;
    actions.append(link);
    if (!item.archived && item.status !== 'processing') {
      actions.append(actionButton(item.report ? 'Relancer la lecture IA' : 'Analyser la facture', () => act(`${base}/${encodeURIComponent(item.id)}/analyser`, undefined, 'Lecture de la facture et rapprochement en cours…')));
    }
    if (item.status !== 'processing') actions.append(actionButton(item.archived ? 'Restaurer' : 'Écarter du contrôle', () => {
      if (!item.archived && !window.confirm('Écarter cette facture du bilan ? Son fichier original et ses analyses resteront conservés.')) return;
      act(`${base}/${encodeURIComponent(item.id)}/archiver`, {archived: !item.archived}, 'Mise à jour du document…');
    }));
    body.append(actions);
    if (item.error) body.append(e('p', item.error, 'ti-feedback is-error'));
    if (item.status === 'processing') body.append(e('p', 'L’analyse est en cours. Le document reste conservé en cas d’interruption.', 'ti-help'));
    if (item.report) {
      const report = item.report, data = item.extraction;
      body.append(e('p', `Lecture IA du ${dateTime(item.analyzed_at)} · ${item.model}. Rapprochement recalculé avec le planning actuel.`, 'ti-help'));
      if (item.planning_changed) body.append(e('p', 'Le planning, les tarifs ou les indices de réalisation ont changé depuis cette lecture IA. Les calculs sont actualisés ; relancez la lecture pour revoir les propositions de rapprochement.', 'ti-changed'));
      body.append(e('p', data.summary, 'ti-ai-summary'));
      const totals = e('div', null, 'ti-invoice-totals');
      totals.append(metric('Total HT', money(report.totals.total_ht, data.currency), 'Lu sur la facture'));
      totals.append(metric('TVA', money(report.totals.total_vat, data.currency), 'L’absence d’une mention n’est pas assimilée à zéro'));
      totals.append(metric('Total TTC', money(report.totals.total_ttc, data.currency), 'Lu sur la facture'));
      body.append(totals);
      if (report.issues.length) body.append(issues(report.issues));
      else body.append(e('p', 'Aucun écart détecté dans les contrôles disponibles. Relisez l’original avant toute validation.', 'ti-positive'));
      const wrap = e('div', null, 'ti-table-wrap');
      const table = e('table', null, 'ti-table');
      const thead = e('thead'), tr = e('tr');
      for (const title of ['Ligne de facture', 'Durée facturée / planning', 'Montant / prévision', 'Séances rapprochées et indices']) { const th = e('th', title); th.scope = 'col'; tr.append(th); }
      thead.append(tr); table.append(thead);
      const tbody = e('tbody');
      for (const row of report.lines) {
        const tr = e('tr');
        const description = e('td'); description.append(e('strong', `${row.number}. ${row.description}`), e('small', row.evidence));
        const duration = e('td'); duration.append(e('strong', hours(row.minutes)), e('small', `Planning : ${hours(row.planned_minutes)}`));
        const amount = e('td'); amount.append(e('strong', money(row.amount_cents, data.currency)), e('small', `Prévision : ${money(row.expected_cents)} ${item.basis.toUpperCase()}`));
        const courses = e('td');
        for (const course of row.courses) {
          courses.append(e('p', courseLabel(course)));
          courses.append(e('small', `${course.rollcall_at ? 'Appel finalisé' : 'Pas d’appel finalisé'} · ${course.journal_at ? 'Cahier de texte renseigné' : 'Pas de cahier de texte'}`));
        }
        if (!row.courses.length) courses.append(e('span', row.kind === 'teaching' ? 'Non rapprochée' : 'Poste hors heures de cours'));
        else courses.append(e('small', row.exact_match ? 'Correspondance date et horaires' : 'Correspondance proposée à confirmer', row.exact_match ? 'ti-positive' : 'ti-help'));
        tr.append(description, duration, amount, courses); tbody.append(tr);
      }
      table.append(tbody); wrap.append(table); body.append(wrap, e('p', report.notice, 'ti-privacy'));
    }
    details.append(body);
    return details;
  }
  function render(data) {
    const openIds = new Set(Array.from(list.querySelectorAll('details[open][data-invoice-id]'), x => x.dataset.invoiceId));
    list.replaceChildren(); renderSummary(data);
    const visible = data.invoices.filter(item => !item.archived || archiveToggle.checked);
    if (!visible.length) list.append(e('p', 'Aucune facture active pour ce mois. Importez les documents ci-dessus pour commencer le contrôle.', 'ti-empty'));
    for (const item of visible) list.append(renderInvoice(item, openIds));
  }
  async function load() {
    const data = await api(`${base}?month=${encodeURIComponent(root.dataset.month)}`);
    current = data; render(data);
    if (!data.ai_configured && !busy) tell('Les imports sont disponibles. Renseignez la clé dans Paramètres → OpenAI pour lancer l’analyse.', true);
    clearTimeout(timer);
    if (data.invoices.some(item => item.status === 'processing' && !item.archived)) {
      timer = setTimeout(() => { if (!busy) load().catch(error => tell(error.message, true)); }, 5000);
    }
  }
  archiveToggle.addEventListener('change', () => { if (current) render(current); });
  refreshButton.addEventListener('click', () => { if (!busy) load().catch(error => tell(error.message, true)); });
  form.addEventListener('submit', async event => {
    event.preventDefault(); if (busy || !form.reportValidity()) return;
    const files = Array.from(form.elements.files.files), basis = form.elements.basis.value;
    if (!files.length || files.length > 10) { tell('Sélectionnez de 1 à 10 fichiers.', true); return; }
    if (files.some(file => !file.size || file.size > 12 * 1024 * 1024)) { tell('Chaque fichier doit être non vide et faire au maximum 12 Mo.', true); return; }
    lock(true); log.replaceChildren(); let failures = 0;
    for (let index = 0; index < files.length; index++) {
      const file = files[index];
      const line = e('p', `${index+1}/${files.length} · ${file.name} : import…`); log.append(line);
      tell(`Document ${index+1} sur ${files.length} : ${file.name}`);
      try {
        const body = new FormData(); body.append('file', file); body.append('month', root.dataset.month); body.append('basis', basis);
        const upload = await api(base, {method: 'POST', body});
        if (upload.duplicate) { line.textContent = file.name + ' : ' + upload.message; continue; }
        line.textContent = file.name + ' : importé, analyse IA en cours…';
        await load();
        await api(`${base}/${encodeURIComponent(upload.id)}/analyser`, {method: 'POST'});
        line.textContent = file.name + ' : analyse terminée, rapport disponible ci-dessous.';
      } catch (error) { failures++; line.textContent = file.name + ' : ' + error.message; line.classList.add('is-error'); }
      try { await load(); } catch (error) { tell(error.message, true); }
    }
    lock(false);
    if (!failures) form.elements.files.value = '';
    tell(failures ? `Traitement terminé avec ${failures} document(s) à vérifier. Les imports réussis sont conservés.` : 'Traitement terminé. Consultez le bilan mensuel et le rapport de chaque facture.', failures > 0);
    try { await load(); } catch (error) { tell(error.message, true); }
  });
  load().catch(error => tell(error.message, true));
})();

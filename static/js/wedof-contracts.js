(() => {
  'use strict';
  const panel = document.getElementById('panel-contrat-apprentissage');
  if (!panel) return;
  const $ = id => document.getElementById(id);
  const root = document.querySelector('.candidate-sheet');
  const base = `/admin/candidat/${encodeURIComponent(root.dataset.candidateId)}/contrats-apprentissage`;
  let busy = false, loaded = false, previewToken = '', resultToken = '';
  const views = new Map(), filters = new Map();
  const notice = (id, text) => { $(id).textContent = text || ''; $(id).hidden = !text; };
  const el = (tag, text, cls = '') => { const node = document.createElement(tag); node.textContent = text; node.className = cls; return node; };
  async function api(path = '', data) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 40000);
    try {
      const response = await fetch(base + path, {method: data === undefined ? 'GET' : 'POST', credentials: 'same-origin', signal: controller.signal,
        headers: {'Accept': 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': panel.dataset.csrf},
        ...(data === undefined ? {} : {body: JSON.stringify(data)})});
      const result = await response.json().catch(() => {throw new Error('La session a expiré. Rechargez la fiche.');});
      if (!response.ok || !result.ok) throw new Error(result.message || 'Cette opération n’a pas pu être terminée.');
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('Le serveur n’a pas confirmé le résultat. Rechargez les contrats avant de réessayer.');
      throw error;
    } finally {clearTimeout(timer);}
  }
  async function run(task) {
    if (busy) return;
    busy = true; panel.setAttribute('aria-busy', 'true');
    const controls = [...panel.querySelectorAll('button,input,select')];
    const previous = controls.map(node => node.disabled); controls.forEach(node => node.disabled = true);
    notice('wc-error', ''); notice('wc-notice', '');
    try {await task();} catch (error) {notice('wc-error', error.message);}
    finally {controls.forEach((node, i) => node.disabled = previous[i]); busy = false; panel.removeAttribute('aria-busy');}
  }
  async function load() {
    const result = await api(); $('wc-list').innerHTML = result.html; loaded = true;
    panel.querySelectorAll('[data-contract-id]').forEach(card => {
      activateTab(card, views.get(card.dataset.contractId) || 'overview');
      filterSchedule(card, filters.get(card.dataset.contractId) || 'all');
    });
    document.dispatchEvent(new Event('candidate-employment-changed'));
    return result;
  }
  function activateTab(card, name, focus = false) {
    const tabs = [...card.querySelectorAll('[data-wc-tab]')];
    const selected = tabs.find(tab => tab.dataset.wcTab === name) || tabs[0];
    if (!selected) return;
    name = selected.dataset.wcTab; views.set(card.dataset.contractId, name);
    tabs.forEach(tab => { const active = tab === selected; tab.setAttribute('aria-selected', String(active)); tab.tabIndex = active ? 0 : -1; });
    card.querySelectorAll('[data-wc-panel]').forEach(section => section.hidden = section.dataset.wcPanel !== name);
    if (focus) { selected.focus(); selected.scrollIntoView({block: 'nearest', inline: 'nearest'}); }
  }
  function filterSchedule(card, name) {
    const buttons = [...card.querySelectorAll('[data-wc-filter]')];
    if (!buttons.some(button => button.dataset.wcFilter === name)) name = 'all';
    filters.set(card.dataset.contractId, name);
    buttons.forEach(button => button.setAttribute('aria-pressed', String(button.dataset.wcFilter === name)));
    let visible = 0;
    card.querySelectorAll('[data-wc-due]').forEach(row => { row.hidden = name !== 'all' && row.dataset.wcDue !== name; if (!row.hidden) visible++; });
    const empty = card.querySelector('.wc-filter-empty'); if (empty) empty.hidden = visible > 0;
  }
  async function discover(manual = false) {
    notice('wc-notice', 'Recherche automatique du contrat dans WEDOF…');
    for (let phase = 0; phase < 8; phase++) {
      const result = await api('/detecter', {manual, origin: 'interactive'});
      notice('wc-notice', result.message);
      if (result.pending) continue;
      if (result.linked) await load();
      else if (result.items?.length) {
        $('wc-search').hidden = false;
        renderResults(result);
      }
      return;
    }
    throw new Error('La recherche reste incomplète. Utilisez la référence exacte du contrat.');
  }
  async function initialLoad() {
    await load();
  }
  const openSearch = () => { $('wc-search').hidden = false; $('wc-reference').focus(); };
  $('wc-add').addEventListener('click', openSearch);
  $('wc-close-search').addEventListener('click', () => {$('wc-search').hidden = true;});
  $('wc-kind').addEventListener('change', () => {
    const kind = $('wc-kind').value;
    $('wc-financer').required = kind === 'number';
    $('wc-reference').placeholder = kind === 'wedof' ? 'Identifiant numérique WEDOF' : kind === 'folder' ? 'Référence du dossier de formation' : 'Numéro de contrat ou DECA';
    $('wc-results').replaceChildren(); $('wc-preview').hidden = true; previewToken = resultToken = '';
  });
  async function search(data) {
    renderResults(await api('/rechercher', data));
  }
  function renderResults(result) {
    $('wc-preview').hidden = true; previewToken = '';
    resultToken = result.token;
    const target = $('wc-results'); target.replaceChildren(el('p', result.message, 'wc-results-heading'));
    for (const item of result.items) {
      const card = el('div', '', 'wc-result'), info = el('div', '');
      info.append(el('strong', item.employer_name || 'Entreprise non communiquée'), el('p', `Contrat ${item.external_number || item.working_contract_id} · ${item.state_label || 'État non communiqué'}`));
      if (item.deca_number) info.append(el('p', `DECA ${item.deca_number}`));
      const button = el('button', 'Vérifier ce contrat', 'btn'); button.type = 'button';
      button.addEventListener('click', () => run(async () => {
        const preview = await api('/apercu', {token: resultToken, contract_id: item.working_contract_id});
        previewToken = preview.token; $('wc-preview').innerHTML = preview.html; $('wc-preview').hidden = false;
        $('wc-preview').scrollIntoView({behavior: 'smooth', block: 'nearest'});
      }));
      card.append(info, button); target.append(card);
    }
    if (result.next_token) {
      const more = el('button', 'Poursuivre la recherche dans la page suivante', 'btn'); more.type = 'button';
      more.addEventListener('click', () => run(() => search({next_token: result.next_token}))); target.append(more);
    }
  }
  $('wc-search-form').addEventListener('submit', event => {
    event.preventDefault(); const data = Object.fromEntries(new FormData(event.target));
    run(() => search(data));
  });
  panel.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button || busy) return;
    const card = button.closest('[data-contract-id]');
    if (card && (button.dataset.wcTab || button.dataset.wcGoto)) activateTab(card, button.dataset.wcTab || button.dataset.wcGoto, Boolean(button.dataset.wcGoto));
    if (card && button.dataset.wcFilter) filterSchedule(card, button.dataset.wcFilter);
    if (button.hasAttribute('data-wc-open')) openSearch();
    if (button.hasAttribute('data-wc-detect')) run(() => discover(true));
    if (button.id === 'wc-link') run(async () => {
      const result = await api('/rattacher', {token: previewToken, identity_confirmed: Boolean($('wc-confirm-identity')?.checked)});
      previewToken = ''; $('wc-search').hidden = true; $('wc-preview').hidden = true; $('wc-results').replaceChildren();
      await load(); notice('wc-notice', result.message);
    });
    if (button.dataset.wcRefresh) run(async () => {
      try {const result = await api(`/${encodeURIComponent(button.dataset.wcRefresh)}/actualiser`, {}); notice('wc-notice', result.message);}
      finally {await load();}
    });
    if (button.dataset.wcUnlink && confirm('Retirer le lien avec cette fiche étudiante ? Le contrat sera conservé dans WEDOF.')) run(async () => {
      const result = await api(`/${encodeURIComponent(button.dataset.wcUnlink)}/detacher`, {}); await load(); notice('wc-notice', result.message);
    });
  });
  panel.addEventListener('keydown', event => {
    const button = event.target.closest('[data-wc-tab]');
    if (!button || busy || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const card = button.closest('[data-contract-id]'), tabs = [...card.querySelectorAll('[data-wc-tab]')];
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (tabs.indexOf(button) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    activateTab(card, tabs[next].dataset.wcTab, true);
  });
  const observer = new MutationObserver(() => {if (!panel.hidden && !loaded && !busy) run(initialLoad);});
  observer.observe(panel, {attributes: true, attributeFilter: ['hidden']});
  if (!panel.hidden) run(initialLoad);
})();

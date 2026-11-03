(() => {
  'use strict';
  const panel = document.getElementById('panel-contrat-apprentissage');
  if (!panel) return;
  const $ = id => document.getElementById(id);
  const root = document.querySelector('.candidate-sheet');
  const base = `/admin/candidat/${encodeURIComponent(root.dataset.candidateId)}/contrats-apprentissage`;
  let busy = false, loaded = false;
  const views = new Map(), filters = new Map();
  const notice = (id, text) => { $(id).textContent = text || ''; $(id).hidden = !text; };
  async function api() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 40000);
    try {
      const response = await fetch(base, {method: 'GET', credentials: 'same-origin', signal: controller.signal, headers: {'Accept': 'application/json'}});
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
  panel.addEventListener('click', event => {
    const button = event.target.closest('button'); if (!button || busy) return;
    const card = button.closest('[data-contract-id]');
    if (card && (button.dataset.wcTab || button.dataset.wcGoto)) activateTab(card, button.dataset.wcTab || button.dataset.wcGoto, Boolean(button.dataset.wcGoto));
    if (card && button.dataset.wcFilter) filterSchedule(card, button.dataset.wcFilter);
  });
  panel.addEventListener('keydown', event => {
    const button = event.target.closest('[data-wc-tab]');
    if (!button || busy || !['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const card = button.closest('[data-contract-id]'), tabs = [...card.querySelectorAll('[data-wc-tab]')];
    const next = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : (tabs.indexOf(button) + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length;
    activateTab(card, tabs[next].dataset.wcTab, true);
  });
  const observer = new MutationObserver(() => {if (!panel.hidden && !loaded && !busy) run(load);});
  observer.observe(panel, {attributes: true, attributeFilter: ['hidden']});
  if (!panel.hidden) run(load);
})();

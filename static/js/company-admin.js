/* Progressive tabs keep edited values while navigating the company file. */
(() => {
  'use strict';
  const root = document.querySelector('[data-company-profile]');
  if (root) {
    const tabs = [...root.querySelectorAll('[data-company-tab]')];
    const panels = [...root.querySelectorAll('[data-company-panel]')];
    function activate(key, updateURL = false, moveFocus = false) {
      const selected = tabs.find(tab => tab.dataset.companyTab === key);
      if (!selected) return;
      tabs.forEach(tab => {
        const active = tab === selected;
        tab.setAttribute('aria-selected', String(active));
        tab.tabIndex = active ? 0 : -1;
      });
      panels.forEach(panel => { panel.hidden = panel.dataset.companyPanel !== key; });
      root.dataset.activeTab = key;
      if (updateURL) history.pushState(null, '', selected.href);
      if (moveFocus) selected.focus();
    }
    root.querySelectorAll('[data-company-tab], [data-company-tab-link]').forEach(link => {
      link.addEventListener('click', event => {
        if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
        event.preventDefault();
        const key = link.dataset.companyTab || link.dataset.companyTabLink;
        activate(key, true, !!link.dataset.companyTabLink);
      });
    });
    tabs.forEach((tab, index) => tab.addEventListener('keydown', event => {
      let next;
      if (event.key === 'ArrowRight') next = (index + 1) % tabs.length;
      else if (event.key === 'ArrowLeft') next = (index + tabs.length - 1) % tabs.length;
      else if (event.key === 'Home') next = 0;
      else if (event.key === 'End') next = tabs.length - 1;
      else return;
      event.preventDefault();
      activate(tabs[next].dataset.companyTab, true, true);
    }));
    window.addEventListener('popstate', () => activate(new URL(location.href).searchParams.get('tab') || 'overview'));
    root.addEventListener('invalid', event => {
      const panel = event.target.closest('[data-company-panel]');
      if (panel?.hidden) activate(panel.dataset.companyPanel, true);
    }, true);
    activate(root.dataset.activeTab);
  }
  document.querySelectorAll('[data-co-toggle]').forEach(button => {
    button.addEventListener('click', () => {
      const panel = document.getElementById(button.dataset.coToggle);
      if (!panel) return;
      panel.hidden = !panel.hidden;
      button.setAttribute('aria-expanded', String(!panel.hidden));
    });
  });
  const trackedForms = [...document.querySelectorAll('[data-company-edit-form]')];
  const changed = new Map();
  let submitting = false;
  trackedForms.forEach(form => {
    const serialize = () => JSON.stringify([...new FormData(form).entries()]);
    const original = serialize();
    const initialDirty = form.hasAttribute('data-dirty-on-load');
    const state = form.querySelector('[data-save-state]');
    function update() {
      const dirty = initialDirty || serialize() !== original;
      changed.set(form, dirty);
      if (state) state.textContent = dirty ? 'Modifications non enregistrées' : '';
    }
    form.addEventListener('input', update);
    form.addEventListener('change', update);
    form.addEventListener('company:registry-imported', update);
    update();
  });
  document.querySelectorAll('form').forEach(form => form.addEventListener('submit', event => {
    // Avoid discarding an edited company form by submitting an unrelated action.
    if (!trackedForms.includes(form) && [...changed.values()].some(Boolean)) {
      if (!window.confirm('Les coordonnées ont des modifications non enregistrées. Quitter sans les enregistrer ?')) {
        event.preventDefault();
        return;
      }
    }
    submitting = true;
  }));
  window.addEventListener('beforeunload', event => {
    if (!submitting && [...changed.values()].some(Boolean)) {
      event.preventDefault();
      event.returnValue = '';
    }
  });
})();

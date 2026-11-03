(() => {
  'use strict';
  const root = document.querySelector('.settings-app');
  if (!root) return;
  const $ = id => document.getElementById(id);
  function openLinkedSection() {
    const [anchor, query] = window.location.hash.slice(1).split('?');
    let section = $(anchor);
    if (!root.contains(section)) return;
    if (anchor === 'akto-dossier' && query) {
      const fields = new URLSearchParams(query);
      for (const [name, id] of [['reference', 'akto-dossier-ref'], ['deca', 'akto-dossier-deca'], ['internal', 'akto-dossier-interne']]) {
        const value = fields.get(name);
        if ($(id) && value && /^[a-zA-Z0-9./_-]{1,80}$/.test(value)) $(id).value = value;
      }
    }
    const target = section;
    while (section) {
      if (section.tagName === 'DETAILS') section.open = true;
      section = section.parentElement;
    }
    if (anchor === 'akto-dossier' && query) target.scrollIntoView({block: 'center'});
  }
  openLinkedSection();
  window.addEventListener('hashchange', openLinkedSection);
  root.addEventListener('click', event => {
    if (event.target.closest('[data-refresh-job]')) window.location.reload();
  });
  root.addEventListener('submit', async event => {
    const button = event.submitter;
    if (!button?.matches('[data-background-job]')) return;
    event.preventDefault();
    const form = event.target;
    const body = new FormData(form);
    if (button.name) body.set(button.name, button.value);
    button.disabled = true;
    let notice = form.querySelector('.job-notice');
    if (!notice) {
      notice = document.createElement('p');
      notice.className = 'settings-message job-notice';
      notice.setAttribute('role', 'status');
      form.append(notice);
    }
    notice.textContent = 'Envoi de la demande au serveur…';
    try {
      const response = await fetch(form.getAttribute('action'), {method: 'POST', body, keepalive: true,
        credentials: 'same-origin', headers: {Accept: 'application/json'}});
      const result = await response.json();
      if (!response.ok) throw new Error(result.message);
      notice.textContent = result.message + ' ';
      const refresh = document.createElement('button');
      refresh.type = 'button';
      refresh.dataset.refreshJob = '';
      refresh.className = 'settings-button';
      refresh.textContent = 'Actualiser le statut';
      notice.append(refresh);
    } catch (error) {
      notice.textContent = error instanceof TypeError || error instanceof SyntaxError ?
        'La confirmation du serveur est indisponible. Actualisez le statut avant de relancer.' : error.message;
      button.disabled = false;
    }
  });
  let busy = false;
  const message = (id, text) => { $(id).textContent = text || ''; $(id).hidden = !text; };
  function render(settings) {
    $('openai-status').textContent = settings.configured ? 'Connexion configurée' : 'À configurer';
    $('openai-status').classList.toggle('configured', settings.configured);
    $('openai-form').hidden = settings.managed_by_server;
    $('openai-key').disabled = settings.managed_by_server;
    $('openai-managed').hidden = !settings.managed_by_server;
    $('openai-remove').hidden = !settings.configured || settings.managed_by_server;
    $('openai-save').textContent = settings.configured ? 'Remplacer la clé' : 'Enregistrer la clé';
  }
  async function request(method = 'GET') {
    if (busy) return;
    busy = true;
    $('openai-save').disabled = $('openai-remove').disabled = $('openai-retry').disabled = true;
    message('openai-error', ''); message('openai-success', '');
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('/admin/planning/api/references/settings', {
        method, credentials: 'same-origin', signal: controller.signal,
        headers: {Accept: 'application/json', ...(method !== 'GET' ? {'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.csrf} : {})},
        ...(method !== 'GET' ? {body: JSON.stringify(method === 'PUT' ? {api_key: $('openai-key').value.trim()} : {})} : {})
      });
      const data = await response.json().catch(() => { throw new Error('La session a expiré. Rechargez la page.'); });
      if (!response.ok || !data.ok) throw new Error(data.message || 'La connexion n’a pas pu être enregistrée.');
      render(data); $('openai-retry').hidden = true;
      if (method !== 'GET') { $('openai-key').value = ''; message('openai-success', method === 'PUT' ? 'La clé API est enregistrée. Vous pouvez importer les matières.' : 'La clé API a été retirée.'); }
    } catch (error) {
      message('openai-error', error.name === 'AbortError' ? 'Le serveur ne répond pas. Réessayez dans quelques instants.' : error.message);
      if (method === 'GET') { $('openai-status').textContent = 'Connexion à vérifier'; $('openai-retry').hidden = false; }
    } finally {
      clearTimeout(timer); busy = false;
      $('openai-save').disabled = $('openai-remove').disabled = $('openai-retry').disabled = false;
    }
  }
  $('openai-form').addEventListener('submit', event => { event.preventDefault(); if (event.target.reportValidity()) request('PUT'); });
  $('openai-remove').addEventListener('click', () => request('DELETE'));
  $('openai-retry').addEventListener('click', () => request());
  request();
})();

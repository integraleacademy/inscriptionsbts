(() => {
  'use strict';
  const root = document.querySelector('.settings-app');
  if (!root) return;
  const $ = id => document.getElementById(id);
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

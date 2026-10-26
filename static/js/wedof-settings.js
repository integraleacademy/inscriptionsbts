(() => {
  'use strict';
  const root = document.getElementById('wedof'); if (!root) return;
  const $ = id => document.getElementById(`wedof-${id}`);
  let busy = false;
  const message = (id, value) => {$(id).textContent = value || ''; $(id).hidden = !value;};
  async function request(method = 'GET') {
    if (busy) return; busy = true;
    ['save', 'remove', 'retry'].forEach(id => $(id).disabled = true);
    message('error', ''); message('success', '');
    try {
      const response = await fetch('/admin/api/wedof/settings', {method, credentials: 'same-origin',
        headers: {'Accept': 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': root.dataset.wedofCsrf},
        ...(method === 'GET' ? {} : {body: JSON.stringify(method === 'PUT' ? {api_key: $('key').value.trim()} : {})})});
      const data = await response.json().catch(() => {throw new Error('La session a expiré. Rechargez la page.');});
      if (!response.ok || !data.ok) throw new Error(data.message || 'La connexion n’a pas pu être enregistrée.');
      $('status').textContent = data.configured ? 'Clé configurée' : 'À configurer';
      $('status').classList.toggle('configured', data.configured);
      $('form').hidden = data.managed_by_server; $('managed').hidden = !data.managed_by_server;
      $('remove').hidden = !data.configured || data.managed_by_server;
      $('save').textContent = data.configured ? 'Remplacer la clé' : 'Enregistrer la clé';
      $('retry').hidden = true; message('error', data.warning);
      if (method !== 'GET') {$('key').value = ''; message('success', method === 'PUT' ? 'La clé est enregistrée. Vous pouvez rechercher un contrat depuis une fiche étudiante.' : 'La clé a été retirée. Les contrats déjà rattachés restent consultables.');}
    } catch (error) {message('error', error.message); $('retry').hidden = false;}
    finally {busy = false; ['save', 'remove', 'retry'].forEach(id => $(id).disabled = false);}
  }
  $('form').addEventListener('submit', event => {event.preventDefault(); if (event.target.reportValidity()) request('PUT');});
  $('remove').addEventListener('click', () => {if (confirm('Retirer la connexion WEDOF ? Les contrats enregistrés seront conservés.')) request('DELETE');});
  $('retry').addEventListener('click', () => request()); request();
})();

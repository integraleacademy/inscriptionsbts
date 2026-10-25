/* Refresh open schedules without discarding work in progress. No student data is stored. */
(() => {
  'use strict';
  const url = document.body.dataset.planningSyncUrl;
  let revision = document.body.dataset.planningSyncRevision;
  if (!url || !revision) return;
  let pending = false, stopped = false, dirty = false, banner;
  const markDirty = event => {
    if (event.target.matches('input,select,textarea,[contenteditable="true"]')) dirty = true;
  };
  document.addEventListener('input', markDirty, true);
  document.addEventListener('change', markDirty, true);
  const showRefresh = () => {
    if (banner) return;
    banner = document.createElement('aside');
    banner.className = 'planning-live-update-toast';
    banner.setAttribute('role', 'status');
    const text = document.createElement('span');
    text.textContent = 'Le planning a été mis à jour. Terminez votre saisie avant d’actualiser.';
    const button = document.createElement('button');
    button.type = 'button'; button.textContent = 'Actualiser';
    button.addEventListener('click', () => window.location.reload());
    banner.append(text, button); document.body.append(banner);
  };
  async function check() {
    if (pending || stopped || document.hidden) return;
    pending = true;
    try {
      const response = await fetch(url, {credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json'}});
      if (response.status === 401 || response.status === 403) { stopped = true; return; }
      if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) return;
      const data = await response.json();
      if (typeof data.revision !== 'string' || !/^[a-f0-9]{64}$/.test(data.revision) || data.revision === revision) return;
      revision = data.revision;
      const event = new CustomEvent('academy:planning-changed', {cancelable:true, detail:{revision}});
      if (!window.dispatchEvent(event)) return;
      if (dirty || document.querySelector('dialog[open]') || document.querySelector('input[type="file"]:valid')?.files?.length) showRefresh();
      else window.location.reload();
    } catch (_) { /* Keep the existing schedule usable while offline. */ }
    finally { pending = false; }
  }
  window.addEventListener('focus', check);
  window.addEventListener('academy:planning-updated', check);
  window.addEventListener('storage', event => { if (event.key === 'academy-planning-updated') check(); });
  document.addEventListener('visibilitychange', () => { if (!document.hidden) check(); });
  setInterval(check, 30000);
  check();
})();

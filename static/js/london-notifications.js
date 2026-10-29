(() => {
  const badge = document.querySelector('[data-london-notification-count]');
  if (!badge) return;
  const panel = document.querySelector('[data-london-notifications]');
  let busy = false, previous = '';
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true;
    try {
      const response = await fetch('/admin/voyage-londres/notifications', {headers:{Accept:'application/json'}});
      if (!response.ok || response.redirected) return;
      const result = await response.json();
      badge.textContent = result.count > 99 ? '99+' : String(result.count);
      badge.hidden = !result.count;
      badge.setAttribute('aria-label', `${result.count} convention(s) entièrement signée(s) à consulter`);
      const link = badge.closest('a');
      link.setAttribute('aria-label', result.count ? `Voyage à Londres, ${result.count} nouvelle(s) convention(s) signée(s)` : 'Voyage à Londres');
      if (!panel) return;
      panel.hidden = !result.count;
      const fingerprint = JSON.stringify(result.notifications);
      if (fingerprint === previous) return;
      previous = fingerprint;
      const list = panel.querySelector('[data-london-notification-list]'); list.replaceChildren();
      for (const item of result.notifications) {
        const row = document.createElement('li');
        const student = document.createElement('a'); student.href = item.url; student.textContent = item.name;
        const pdf = document.createElement('a'); pdf.href = item.document_url; pdf.textContent = 'Voir le PDF signé ↗'; pdf.target = '_blank'; pdf.rel = 'noopener';
        const read = document.createElement('button'); read.type = 'button'; read.textContent = 'Marquer comme lu';
        read.addEventListener('click', async () => {
          read.disabled = true;
          try {
            const body = new FormData(); body.set('csrf_token', panel.dataset.csrf);
            const result = await fetch('/admin/voyage-londres/notifications/' + encodeURIComponent(item.version_id) + '/lue', {method:'POST',body,headers:{Accept:'application/json'}});
            if (!result.ok || result.redirected) throw Error('La notification n’a pas pu être marquée comme lue. Actualisez la page puis réessayez.');
            await refresh();
          } catch (e) { const error = panel.querySelector('[data-london-notification-error]'); error.hidden = false; error.textContent = e.message; }
          finally { read.disabled = false; }
        });
        row.append(student,pdf,read); list.append(row);
      }
    } catch (_) { /* Preserve the server-rendered badge during a network interruption. */ }
    finally { busy = false; }
  }
  refresh(); setInterval(refresh, 45000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
})();

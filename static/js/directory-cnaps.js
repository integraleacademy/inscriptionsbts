(() => {
  'use strict';
  const rows = document.getElementById('directory-rows');
  if (!rows) return;

  const entries = new Map();
  const queue = [];
  const dateFormat = new Intl.DateTimeFormat('fr-FR', {timeZone: 'Europe/Paris'});
  const cacheDuration = 5 * 60_000;
  let active = 0;

  function display(entry) {
    const {node, status} = entry;
    const badge = node.querySelector('[data-cnaps-status]');
    badge.textContent = status?.label || 'Vérification…';
    badge.className = 'candidate-cnaps-badge is-' + (status?.tone || 'neutral');
    const note = node.querySelector('[data-cnaps-note]');
    note.textContent = [status?.note, status?.stale && 'Dernier statut connu'].filter(Boolean).join(' · ');
    note.hidden = !note.textContent;
    const sent = entry.sentAt || node.dataset.collectionSent;
    if (sent) {
      const date = new Date(sent);
      const collection = node.querySelector('[data-cnaps-collection]');
      collection.textContent = Number.isNaN(date.getTime())
        ? 'E-mail de collecte envoyé' : 'Collecte envoyée le ' + dateFormat.format(date);
      collection.hidden = false;
    }
  }

  async function read(entry) {
    let retryAfter = 60_000;
    try {
      const url = new URL(entry.url, location.origin);
      if (entry.force) url.searchParams.set('refresh', '1');
      entry.force = false;
      const response = await fetch(url, {headers: {Accept: 'application/json'}, cache: 'no-store'});
      const data = await response.json().catch(() => null);
      entry.sentAt = data?.collection_sent_at;
      if (response.ok && data?.ok && data.summary) {
        entry.status = data.summary;
        entry.lastKnown = data.found ? data.summary : null;
        if (!data.summary.stale) retryAfter = cacheDuration;
      } else if (response.status === 409) {
        entry.lastKnown = null;
        entry.status = {label: 'Identité à vérifier', tone: 'warning'};
      } else if (response.status === 401 || response.status === 403 || response.status === 404) {
        entry.lastKnown = null;
        entry.status = {label: response.status === 404 ? 'Suivi indisponible' : 'Connexion requise', tone: 'warning'};
      } else {
        throw new Error();
      }
    } catch {
      entry.status = entry.lastKnown ? {...entry.lastKnown, stale: true} : {label: 'Suivi indisponible', tone: 'warning'};
    } finally {
      entry.nextRead = Date.now() + retryAfter;
      entry.pending = false;
      if (entry.node.isConnected) display(entry);
      active--;
      drain();
    }
  }

  function drain() {
    while (active < 2 && queue.length) {
      const entry = queue.shift();
      if (!entry.node.isConnected) {
        entry.pending = false;
        continue;
      }
      active++;
      read(entry);
    }
  }

  function enqueue(node) {
    const entry = entries.get(node.dataset.cnapsUrl);
    if (!entry || entry.node !== node || entry.pending || entry.nextRead > Date.now()) return;
    entry.pending = true;
    queue.push(entry);
    drain();
  }

  const visible = window.IntersectionObserver && new IntersectionObserver(changes => {
    for (const change of changes) {
      if (change.isIntersecting) {
        visible.unobserve(change.target);
        enqueue(change.target);
      }
    }
  }, {rootMargin: '200px 0px'});

  function bindRows() {
    visible?.disconnect();
    for (const node of rows.querySelectorAll('[data-cnaps-url]')) {
      const url = node.dataset.cnapsUrl;
      let entry = entries.get(url);
      if (!entry || entry.revision !== node.dataset.revision) {
        entry = {url, revision: node.dataset.revision};
        entries.set(url, entry);
      }
      entry.node = node;
      entry.sentAt = node.dataset.collectionSent || entry.sentAt;
      display(entry);
      if (visible) visible.observe(node);
      else enqueue(node);
    }
    for (const [url, entry] of entries) {
      if (!entry.node.isConnected) entries.delete(url);
    }
  }

  // The directory replaces its table body contents on manual and automatic refresh.
  document.getElementById('directory-refresh')?.addEventListener('click', () => {
    for (const entry of entries.values()) {
      if (!entry.pending) {
        entry.nextRead = 0;
        entry.force = true;
      }
    }
  });
  new MutationObserver(bindRows).observe(rows, {childList: true});
  bindRows();
})();

(() => {
  'use strict';
  const sheet = document.querySelector('.candidate-sheet');
  const panel = document.getElementById('panel-documents');
  const card = document.getElementById('candidate-cnaps');
  if (!sheet || sheet.dataset.course !== 'PARCOURS-SECURITE' || !panel || !card) return;

  const tracking = document.getElementById('candidate-cnaps-tracking');
  const collection = document.getElementById('candidate-cnaps-collection');
  const feedback = document.getElementById('candidate-cnaps-feedback');
  const refresh = document.getElementById('candidate-cnaps-refresh');
  const source = document.getElementById('candidate-cnaps-source');
  const endpoint = '/admin/candidat/' + encodeURIComponent(sheet.dataset.candidateId) + '/cnaps-tracking';
  const cacheDuration = 5 * 60 * 1000;
  let inFlight = null, lastAttempt = 0, hasData = false;

  const element = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  const value = (data, ...keys) => {
    for (const key of keys) {
      const result = data?.[key];
      if ((typeof result === 'string' && result.trim()) || typeof result === 'number') return String(result);
    }
    return '';
  };
  const tone = status => {
    const key = status.normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().trim();
    if (['ACCEPTE', 'ACTIF', 'CARTE PROFESSIONNELLE OK'].includes(key)) return 'is-success';
    if (['TRANSMIS', 'ENREGISTRE', 'EN INSTRUCTION'].includes(key)) return 'is-info';
    if (['REFUSE', 'INACTIF', 'EXPIRE'].includes(key)) return 'is-danger';
    return 'is-warning';
  };
  const formattedDate = (raw, withTime = false) => {
    if (!raw) return 'Non disponible';
    let date;
    const french = String(raw).match(/^(\d{2})\/(\d{2})\/(\d{4})$/);
    if (french) date = new Date(Number(french[3]), Number(french[2]) - 1, Number(french[1]));
    else date = new Date(/^\d{4}-\d{2}-\d{2}$/.test(String(raw)) ? String(raw) + 'T12:00:00' : raw);
    if (!Number.isFinite(date.getTime())) return 'Non disponible';
    return new Intl.DateTimeFormat('fr-FR', {
      dateStyle: 'medium', ...(withTime ? {timeStyle: 'short'} : {}), timeZone: 'Europe/Paris',
    }).format(date);
  };
  const badge = status => element('span', status, 'candidate-cnaps-badge ' + tone(status));
  const safeSource = raw => {
    try {
      const url = new URL(raw);
      if (url.origin !== 'https://gestionstagiaires-r5no.onrender.com' || url.username || url.password ||
          url.pathname !== '/admin/sessions/suivi-cnaps' || url.search || url.hash) return '';
      return url.href;
    } catch { return ''; }
  };

  function renderCollection(data) {
    if (!Object.prototype.hasOwnProperty.call(data, 'collection_sent_at')) return;
    const sent = value(data, 'collection_sent_at');
    collection.classList.toggle('has-sent', !!sent);
    collection.textContent = sent
      ? 'Dernière demande envoyée par e-mail : ' + formattedDate(sent, true) + '.'
      : 'Aucune demande d’informations envoyée depuis cette fiche.';
  }

  function fact(label, content) {
    const box = element('div', undefined, 'candidate-cnaps-fact');
    const details = element('dd');
    details.append(typeof content === 'string' ? document.createTextNode(content) : content);
    box.append(element('dt', label), details);
    return box;
  }

  function render(data) {
    const link = safeSource(value(data, 'source_url'));
    source.hidden = !link;
    if (link) source.href = link;
    else source.removeAttribute('href');
    tracking.replaceChildren();
    if (data.found === false) {
      const empty = element('p', undefined, 'candidate-cnaps-empty');
      empty.append(element('strong', 'Aucun dossier retrouvé'),
        document.createTextNode('Le dossier apparaîtra ici dès qu’il sera retrouvé dans le suivi partagé avec le nom et le prénom du candidat.'));
      tracking.append(empty);
      return;
    }
    const cnaps = data.cnaps || data;
    const status = value(cnaps, 'cnaps_status', 'statut_cnaps', 'status', 'statut') || 'Non renseigné';
    const overview = element('dl', undefined, 'candidate-cnaps-overview');
    overview.append(
      fact('Statut du dossier', badge(status)),
      fact('NUB', value(data, 'nub') || value(cnaps, 'nub') || 'Non renseigné'),
      fact('Inscription', value(data, 'inscription') || value(data.trainee, 'inscription') || 'Non renseignée'),
    );
    tracking.append(overview);
    const titles = [data.card_pro?.titles, data.card_pro?.titres, cnaps.titles, cnaps.titres,
      cnaps.professional_titles].find(Array.isArray) || [];
    if (titles.length) {
      tracking.append(element('h3', 'Titres et autorisations', 'candidate-cnaps-titles-heading'));
      const list = element('div', undefined, 'candidate-cnaps-titles');
      for (const title of titles) {
        if (!title || typeof title !== 'object') continue;
        const article = element('article', undefined, 'candidate-cnaps-title');
        const head = element('div', undefined, 'candidate-cnaps-title-head');
        const name = value(title, 'type', 'title', 'titre', 'name', 'label', 'code') || 'Titre ou autorisation';
        const state = value(title, 'state', 'status', 'etat') || 'Non renseigné';
        const expiry = value(title, 'expires_at', 'expiration_date', 'date_expiration', 'valid_until');
        head.append(element('strong', name), badge(state));
        article.append(head, element('p', 'Expiration : ' + formattedDate(expiry), 'candidate-cnaps-expiry'));
        if (title.expires_before_training === true) {
          article.append(element('p', 'Expiration avant le début de la formation.', 'candidate-cnaps-warning'));
        }
        list.append(article);
      }
      tracking.append(list);
    } else {
      tracking.append(element('p', 'Aucun titre ni autorisation retourné pour le moment.', 'candidate-cnaps-empty'));
    }
    const checked = value(cnaps, 'last_checked_at', 'last_verification_at', 'date_derniere_verification', 'checked_at');
    tracking.append(element('p', 'Dernière vérification : ' + formattedDate(checked, true), 'candidate-cnaps-checked'));
    if (cnaps.nub_missing === true || cnaps.nub_present === false) {
      tracking.append(element('p', 'NUB absent : la vérification des titres et autorisations est impossible.', 'candidate-cnaps-warning'));
    }
    if (cnaps.cnaps_unavailable === true) {
      tracking.append(element('p', 'L’annuaire du Ministère de l’intérieur (CNAPS) était indisponible lors de la dernière vérification.', 'candidate-cnaps-warning'));
    }
  }

  async function load(force = false) {
    if (inFlight) return inFlight;
    if (!force && lastAttempt && Date.now() - lastAttempt < cacheDuration) return;
    lastAttempt = Date.now();
    refresh.disabled = true;
    refresh.textContent = 'Actualisation…';
    tracking.setAttribute('aria-busy', 'true');
    feedback.hidden = true;
    if (!hasData) tracking.replaceChildren(element('p', 'Chargement du suivi…', 'candidate-cnaps-empty'));
    inFlight = (async () => {
      try {
        const response = await fetch(endpoint + (force ? '?refresh=1' : ''), {
          method: 'GET', headers: {Accept: 'application/json'}, credentials: 'same-origin', cache: 'no-store',
        });
        const data = await response.json().catch(() => null);
        if (data && typeof data === 'object') renderCollection(data);
        if (!response.ok || !data || data.ok !== true) {
          const fallback = response.status === 403 ? 'Reconnectez-vous pour consulter le suivi.' : 'Le suivi du dossier est momentanément indisponible.';
          throw new Error(value(data, 'error') || fallback);
        }
        render(data);
        hasData = true;
        if (data.stale === true || data.refresh_failed === true) {
          feedback.textContent = 'Actualisation temporairement indisponible. Les dernières informations connues restent affichées.';
          const explanation = value(data, 'refresh_error');
          if (explanation) feedback.append(document.createTextNode(' ' + explanation));
          feedback.hidden = false;
        }
      } catch (error) {
        if (!hasData) {
          const empty = element('p', undefined, 'candidate-cnaps-empty');
          empty.append(element('strong', 'Suivi temporairement indisponible'),
            document.createTextNode('Vous pouvez réessayer avec « Actualiser le suivi ».'));
          tracking.replaceChildren(empty);
        }
        if (collection.textContent === 'Vérification du dernier envoi…') {
          collection.textContent = 'Historique de la demande momentanément indisponible.';
        }
        feedback.textContent = (hasData ? 'Les dernières informations connues restent affichées. ' : '') +
          (error.message || 'L’actualisation du suivi a échoué.');
        feedback.hidden = false;
      } finally {
        refresh.disabled = false;
        refresh.textContent = 'Actualiser le suivi';
        tracking.setAttribute('aria-busy', 'false');
        inFlight = null;
      }
    })();
    return inFlight;
  }

  refresh.addEventListener('click', () => load(true));
  document.addEventListener('candidate-cnaps-sent', async event => {
    if (event.detail?.candidateId !== sheet.dataset.candidateId) return;
    collection.classList.add('has-sent');
    collection.textContent = 'Demande envoyée par e-mail. Mise à jour de l’historique…';
    if (inFlight) await inFlight;
    try {
      const response = await fetch(endpoint + '?collection_only=1', {
        method: 'GET', headers: {Accept: 'application/json'}, credentials: 'same-origin', cache: 'no-store',
      });
      const data = await response.json();
      if (!response.ok || data?.ok !== true) throw new Error();
      renderCollection(data);
    } catch {
      collection.classList.add('has-sent');
      collection.textContent = 'Demande envoyée par e-mail. Le message est disponible dans l’onglet E-mails envoyés.';
    }
  });
  new MutationObserver(() => { if (!panel.hidden) load(); }).observe(panel, {attributes: true, attributeFilter: ['hidden']});
  if (!panel.hidden) load();
})();

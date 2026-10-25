/* Admin-only SIRET lookup. A preview never changes a form until Import is clicked. */
(() => {
  'use strict';
  document.querySelectorAll('[data-company-registry]').forEach(root => {
    const form = root.closest('form');
    const siret = form.elements.namedItem('siret');
    const token = form.elements.namedItem('registry_token');
    const search = root.querySelector('[data-registry-search]');
    const status = root.querySelector('[data-registry-status]');
    const preview = root.querySelector('[data-registry-preview]');
    const importer = root.querySelector('[data-registry-import]');
    const imported = root.querySelector('[data-registry-imported]');
    const saved = form.querySelector('[data-registry-saved]');
    let timer, controller, sequence = 0, result = null;
    let importedSiret = token.value ? normalize(siret.value) : null;
    let lastSiret = normalize(siret.value);
    const labels = {
      legal_name: 'Raison sociale', trade_name: 'Nom commercial / enseigne',
      address: 'Adresse de l’établissement', postal_code: 'Code postal', city: 'Commune',
      legal_form: 'Forme juridique', activity_code: 'Code APE / NAF de l’établissement',
      activity_label: 'Activité principale de l’établissement'
    };
    function normalize(value) { return value.replace(/\s/g, ''); }
    function message(text, error = false) {
      status.textContent = text;
      status.classList.toggle('is-error', error);
    }
    function invalidate() {
      clearTimeout(timer);
      sequence++;
      controller?.abort();
      controller = null;
      result = null;
      preview.hidden = true;
      root.removeAttribute('aria-busy');
      search.disabled = false;
    }
    function row(list, label, value) {
      if (!value) return;
      const group = document.createElement('div');
      const term = document.createElement('dt');
      const detail = document.createElement('dd');
      term.textContent = label;
      detail.textContent = value;
      group.append(term, detail);
      list.append(group);
    }
    async function lookup() {
      invalidate();
      const number = normalize(siret.value);
      if (!/^[0-9]{14}$/.test(number)) {
        message('Saisissez un SIRET composé de 14 chiffres.', true);
        siret.focus();
        return;
      }
      const current = sequence;
      controller = new AbortController();
      search.disabled = true;
      root.setAttribute('aria-busy', 'true');
      message('Recherche de l’établissement dans l’annuaire…');
      try {
        const url = new URL(root.dataset.lookupUrl, window.location.origin);
        url.searchParams.set('siret', number);
        const response = await fetch(url, {signal: controller.signal, headers: {Accept: 'application/json'}, credentials: 'same-origin', cache: 'no-store'});
        if (current !== sequence || normalize(siret.value) !== number) return;
        if (response.status === 403 || response.redirected) throw new Error('Votre session a expiré. Rechargez la page pour vous reconnecter.');
        const data = await response.json();
        if (current !== sequence || normalize(siret.value) !== number) return;
        if (!response.ok) throw new Error(data.error || 'La recherche est indisponible pour le moment.');
        if (data.fields?.siret !== number || !Array.isArray(data.details) || !data.token) throw new Error('La réponse reçue ne correspond pas au SIRET recherché.');
        result = data;
        root.querySelector('[data-registry-name]').textContent = data.fields.name;
        root.querySelector('[data-registry-address]').textContent = data.fields.address || 'Adresse non renseignée dans l’annuaire';
        root.querySelector('[data-registry-identity]').textContent = `SIRET ${number} · SIREN ${number.slice(0, 9)}`;
        const warning = root.querySelector('[data-registry-warning]');
        warning.textContent = (data.warnings || []).join(' ');
        warning.hidden = !warning.textContent;
        const list = root.querySelector('[data-registry-data]');
        list.replaceChildren();
        Object.entries(labels).forEach(([key, label]) => row(list, label, data.fields[key]));
        data.details.forEach(item => row(list, item.label, item.value));
        root.querySelector('[data-registry-source]').href = `https://annuaire-entreprises.data.gouv.fr/etablissement/${number}`;
        importer.disabled = false;
        importer.textContent = 'Importer ces informations';
        preview.hidden = false;
        message('Établissement trouvé. Vérifiez les informations puis cliquez sur « Importer ces informations ».');
      } catch (error) {
        if (current !== sequence || error.name === 'AbortError') return;
        message(error instanceof SyntaxError ? 'L’annuaire est indisponible. Vous pouvez compléter la fiche manuellement.' : (error.message === 'Failed to fetch' ? 'Connexion impossible. Réessayez ou complétez la fiche manuellement.' : error.message), true);
      } finally {
        if (current === sequence) {
          search.disabled = false;
          root.removeAttribute('aria-busy');
        }
      }
    }
    siret.addEventListener('input', () => {
      const number = normalize(siret.value);
      if (number === lastSiret) return;
      lastSiret = number;
      invalidate();
      if (importedSiret !== number) {
        token.value = '';
        imported.hidden = true;
        importedSiret = null;
      }
      if (saved) saved.hidden = saved.dataset.siret !== number;
      message('La recherche démarre après la saisie des 14 chiffres. Vous pouvez aussi remplir la fiche manuellement.');
      if (/^[0-9]{14}$/.test(number)) timer = setTimeout(lookup, 450);
    });
    siret.addEventListener('keydown', event => {
      if (event.key === 'Enter') { event.preventDefault(); lookup(); }
    });
    search.addEventListener('click', lookup);
    importer.addEventListener('click', () => {
      if (!result || result.fields.siret !== normalize(siret.value)) return;
      // Whitelist excludes contact/email/phone, account state and authentication.
      ['name', 'siret', ...Object.keys(labels)].forEach(key => {
        const input = form.elements.namedItem(key);
        if (input) input.value = result.fields[key] || '';
      });
      token.value = result.token;
      importedSiret = result.fields.siret;
      form.querySelector('[data-registry-fields]').open = true;
      if (saved) saved.hidden = true;
      imported.hidden = false;
      importer.textContent = 'Informations importées';
      importer.disabled = true;
      message('Informations importées dans le formulaire. Complétez le contact puis enregistrez la fiche.');
    });
    form.addEventListener('submit', () => {
      if (importedSiret && importedSiret !== normalize(siret.value)) token.value = '';
    });
  });
})();

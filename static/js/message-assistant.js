/* Shared draft-only interaction: generated text is applied explicitly, never sent. */
window.setupEmailAssistant = ({form, endpoint, csrf, context, canUse = () => true}) => {
  const panel = form.querySelector('[data-email-assistant]');
  const find = name => panel.querySelector('[data-ai-' + name + ']');
  const instruction = find('instruction'), generate = find('generate'), apply = find('apply');
  let revision = 0, proposal = null, pending = null;
  const report = message => { find('status').textContent = message; find('status').hidden = !message; };
  const reset = () => {
    revision++; proposal = null; find('result').hidden = true;
    if (pending) { pending.abort(); pending = null; }
    generate.disabled = false; generate.textContent = 'Générer une proposition';
    panel.removeAttribute('aria-busy'); report('');
  };
  form.addEventListener('input', reset);
  form.addEventListener('change', reset);
  generate.addEventListener('click', async () => {
    if (pending || !canUse()) return;
    reset();
    if (!instruction.value.trim()) { report('Décrivez le mail que vous souhaitez rédiger.'); instruction.focus(); return; }
    let data;
    try { data = {...context(), instruction: instruction.value.trim()}; }
    catch (error) { report(error.message); return; }
    const current = revision, controller = new AbortController(); pending = controller;
    generate.disabled = true; generate.textContent = 'Rédaction en cours…';
    panel.setAttribute('aria-busy', 'true'); report('L’IA prépare votre proposition…');
    const timeout = setTimeout(() => controller.abort(), 30000);
    try {
      const response = await fetch(endpoint, {method: 'POST', credentials: 'same-origin', cache: 'no-store',
        signal: controller.signal, headers: {'Content-Type': 'application/json', 'X-CSRF-Token': csrf}, body: JSON.stringify(data)});
      const result = await response.json().catch(() => ({}));
      if (revision !== current) return;
      if (!response.ok || !result.ok) throw Error(result.error || 'Impossible de rédiger le mail. Rechargez la page puis réessayez.');
      if (typeof result.subject !== 'string' || typeof result.body !== 'string') throw Error('Proposition incomplète. Réessayez.');
      proposal = result;
      find('subject').textContent = result.subject; find('body').textContent = result.body;
      find('result').hidden = false; report('Proposition prête. Relisez-la, puis utilisez-la si elle vous convient.');
    } catch (error) {
      if (revision === current) report(error.name === 'AbortError' ? 'La rédaction prend trop de temps. Réessayez dans un instant.' : error.message);
    } finally {
      clearTimeout(timeout);
      if (pending === controller) { pending = null; generate.disabled = false; generate.textContent = 'Générer une proposition'; panel.removeAttribute('aria-busy'); }
    }
  });
  apply.addEventListener('click', () => {
    if (!proposal || !canUse()) return;
    const draft = proposal;
    form.elements.subject.value = draft.subject;
    form.elements.body.value = draft.body;
    // Reuse each composer's invalidation, counters and draft preservation.
    form.elements.body.dispatchEvent(new Event('input', {bubbles: true}));
    report('Proposition insérée. Vous pouvez la modifier puis prévisualiser le mail.');
    form.elements.body.focus();
  });
  return {reset, setVisible(visible) { if (panel.hidden !== !visible) reset(); panel.hidden = !visible; }};
};

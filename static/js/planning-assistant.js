(() => {
  'use strict';
  const $ = id => document.getElementById(id), dialog = $('planning-assistant');
  if (!dialog) return;
  const log = $('planning-chat-history'), form = $('planning-chat-form'), field = $('planning-chat-message');
  const intro = $('planning-chat-intro'), status = $('planning-chat-status'), scroll = dialog.querySelector('.chat-scroll');
  let conversation = [], activeButton = null, busy = false, lastContext = '';
  function context() {
    const isPlanning = dialog.dataset.page === 'planning';
    return {page:dialog.dataset.page, promotion_id:isPlanning ? $('planning-promotion')?.value || null : null,
      period_id:isPlanning ? $('planning-school-year')?.value || null : null};
  }
  function node(tag, text, cls) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function record(role, text) {
    conversation.push({role, text:text.slice(0, 3000)});
    conversation = conversation.slice(-10);
  }
  function bubble(role, message) {
    const card = node('div', undefined, 'chat-turn ' + role);
    card.append(node('p', message));
    log.append(card);
    intro.hidden = true;
    scroll.scrollTop = scroll.scrollHeight;
    return card;
  }
  function resetProposal() {
    if (activeButton) activeButton.remove();
    activeButton = null;
  }
  function working(on, message = '') {
    busy = on;
    form.querySelector('button').disabled = on;
    if (activeButton) activeButton.disabled = on;
    status.textContent = message;
    if (on) scroll.scrollTop = scroll.scrollHeight;
  }
  async function request(path, data) {
    const response = await fetch('/admin/planning/api/assistant' + path, {method:'POST', credentials:'same-origin',
      headers:{'Content-Type':'application/json', 'X-CSRF-Token':dialog.dataset.csrf}, body:JSON.stringify(data)});
    const answer = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(answer.message || 'La demande a échoué. Rechargez la page puis réessayez.');
      error.status = response.status;
      throw error;
    }
    return answer;
  }
  function renderAnswer(answer, scope) {
    const card = bubble('assistant', answer.message);
    record('assistant', answer.message);
    if (answer.details?.length) {
      const details = node('details'), list = node('ul');
      details.append(node('summary', 'Voir le détail (' + answer.details.length + ')'));
      for (const line of answer.details) list.append(node('li', line));
      details.append(list);
      card.append(details);
      details.open = answer.details.length <= 5;
    }
    if (answer.warning) card.append(node('p', answer.warning, 'chat-warning'));
    if (answer.preview_token) {
      const button = node('button', answer.confirm_label, 'tool-primary');
      button.type = 'button';
      activeButton = button;
      card.append(button);
      button.addEventListener('click', async () => {
        if (busy || button !== activeButton) return;
        if (JSON.stringify(context()) !== JSON.stringify(scope)) {
          resetProposal(); bubble('assistant', 'La promotion ou l’année a changé. Relancez la demande.'); return;
        }
        working(true, 'Vérification et enregistrement…');
        try {
          const saved = await request('/confirmer', {preview_token:answer.preview_token, context:scope});
          resetProposal();
          bubble('assistant', saved.message);
          record('assistant', saved.message);
          window.dispatchEvent(new CustomEvent('academy:rooms-changed', {detail:{origin:'assistant'}}));
          window.AcademyPlanning?.refresh();
        } catch (error) {
          if (error.status === 409 || error.status === 400) resetProposal();
          bubble('assistant', error.message);
        } finally { working(false); }
      });
    }
    scroll.scrollTop = scroll.scrollHeight;
  }
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const message = field.value.trim();
    if (busy || !message) return;
    const scope = context(), history = conversation.slice();
    resetProposal();
    field.value = '';
    bubble('user', message); record('user', message);
    working(true, 'Lecture de votre demande…');
    try {
      const answer = await request('', {message, history, context:scope});
      if (JSON.stringify(context()) !== JSON.stringify(scope)) throw new Error('Le planning affiché a changé. Relancez la demande.');
      renderAnswer(answer, scope);
    } catch (error) {
      const card = bubble('assistant', error.message);
      if (error.status === 503 && error.message.includes('OpenAI')) {
        const settings = node('a', 'Ouvrir les paramètres OpenAI');
        settings.href = '/admin/parametres#openai';
        card.append(settings);
      }
      record('assistant', error.message);
    } finally { working(false); if (dialog.open) field.focus(); }
  });
  field.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  for (const button of intro.querySelectorAll('button')) {
    button.addEventListener('click', () => { field.value = button.textContent; field.focus(); });
  }
  for (const button of document.querySelectorAll('[data-open-planning-chat]')) {
    button.addEventListener('click', () => {
      const scope = context(), key = JSON.stringify(scope);
      if (key !== lastContext) { log.replaceChildren(); conversation = []; resetProposal(); intro.hidden = false; field.value = ''; lastContext = key; }
      const scopeLabel = [$('planning-promotion')?.selectedOptions[0]?.textContent,
        $('planning-school-year')?.selectedOptions[0]?.textContent].filter(Boolean).join(' · ');
      $('planning-chat-scope').textContent = scope.promotion_id ? scopeLabel :
        (scope.page === 'planning' ? 'Indiquez dans votre demande la promotion à organiser.' : 'Disponibilités et affectations des salles');
      dialog.showModal(); field.focus();
    });
  }
  dialog.querySelector('.tool-close').addEventListener('click', () => dialog.close());
})();

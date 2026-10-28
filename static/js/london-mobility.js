/* Keep entered values on validation errors; a successful save reloads #londres. */
document.querySelectorAll('[data-mobility-form]').forEach(form => {
  let busy = false;
  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    const data = new FormData(form);
    if (event.submitter?.name) data.set(event.submitter.name, event.submitter.value);
    const message = form.querySelector('[data-mobility-message]');
    const buttons = [...form.querySelectorAll('button')];
    message.hidden = true;
    busy = true; form.setAttribute('aria-busy', 'true');
    buttons.forEach(button => { button.disabled = true; });
    try {
      const response = await fetch(form.action, { method: 'POST', body: data, headers: { Accept: 'application/json' } });
      const result = await response.json().catch(() => null);
      if (!response.ok || !result?.ok) throw new Error(result?.error || 'La demande n’a pas abouti. Rechargez la fiche avant de réessayer.');
      // Assigning the same hash alone would not reload the saved values.
      window.location.hash = 'londres';
      window.location.reload();
    } catch (error) {
      message.textContent = error.message;
      message.hidden = false;
      message.scrollIntoView({ block: 'center', behavior: 'smooth' });
      busy = false; form.removeAttribute('aria-busy');
      buttons.forEach(button => { button.disabled = false; });
    }
  });
});

(() => {
  'use strict';
  const panel = document.getElementById('panel-cyclades');
  if (!panel) return;
  const form = panel.querySelector('.cy-search');
  const button = form.querySelector('button');
  const result = panel.querySelector('.cy-result');
  const error = panel.querySelector('.cy-request-error');
  let loading = false;
  let initialRequested = false;
  let lastMarkup = result.firstElementChild.outerHTML;
  let timer;

  function visible() { return !panel.hidden && !document.hidden; }

  function schedule() {
    clearTimeout(timer);
    if (!visible()) return;
    const data = result.firstElementChild.dataset;
    if (data.initial === '1' && !initialRequested) {
      initialRequested = true;
      timer = setTimeout(() => refresh('initial'), 0);
    } else if (data.busy === '1') {
      timer = setTimeout(() => refresh(), 4000);
    }
  }

  async function refresh(mode) {
    if (loading || !visible()) return;
    clearTimeout(timer);
    loading = true;
    button.disabled = true;
    error.hidden = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const options = {headers: {'X-Cyclades-Fragment': '1'}, cache: 'no-store', signal: controller.signal};
      if (mode) {
        options.method = 'POST';
        options.body = new FormData(form);
        options.body.set('mode', mode);
      }
      const response = await fetch(panel.dataset.searchUrl, options);
      if (!response.ok) throw new Error();
      const html = new DOMParser().parseFromString(await response.text(), 'text/html');
      const next = html.querySelector('.cy-response');
      if (!next) throw new Error();
      if (lastMarkup !== next.outerHTML) {
        lastMarkup = next.outerHTML;
        result.replaceChildren(next);
      }
      form.hidden = next.dataset.canSearch !== '1';
    } catch {
      error.textContent = 'Impossible d’actualiser la recherche. Réessayez dans un instant.';
      error.hidden = false;
    } finally {
      clearTimeout(timeout);
      button.disabled = result.firstElementChild.dataset.busy === '1';
      loading = false;
      schedule();
    }
  }

  form.addEventListener('submit', event => { event.preventDefault(); refresh('manual'); });
  function onVisibility() {
    clearTimeout(timer);
    if (visible()) refresh();
  }
  new MutationObserver(onVisibility).observe(panel, {attributes: true, attributeFilter: ['hidden']});
  document.addEventListener('visibilitychange', onVisibility);
  onVisibility();
})();

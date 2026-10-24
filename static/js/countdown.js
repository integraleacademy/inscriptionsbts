(() => {
  const panel = document.querySelector('[data-opens]');
  if (!panel || panel.dataset.scheduled !== 'true') return;
  const target = new Date(panel.dataset.opens).getTime();
  const serverStart = new Date(panel.dataset.serverNow).getTime();
  const started = performance.now();
  const now = () => serverStart + performance.now() - started;
  let timer;
  function update() {
    const seconds = Math.max(0, Math.ceil((target - now()) / 1000));
    const parts = [Math.floor(seconds / 86400), Math.floor(seconds / 3600) % 24, Math.floor(seconds / 60) % 60, seconds % 60];
    ['days', 'hours', 'minutes', 'seconds'].forEach((key, i) => { document.getElementById(`count-${key}`).textContent = String(parts[i]).padStart(2, '0'); });
    if (seconds === 0) { clearInterval(timer); window.location.reload(); }
  }
  if (target > now()) { update(); timer = setInterval(update, 1000); }
  else { window.location.reload(); }
})();

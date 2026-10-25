(() => {
  const menu = document.querySelector('[data-account-menu]');
  if (!menu) return;
  const toggle = menu.querySelector('summary');
  document.addEventListener('click', event => {
    if (!menu.contains(event.target)) menu.open = false;
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && menu.open) {
      menu.open = false;
      toggle.focus();
    }
  });
  menu.addEventListener('focusout', () => {
    queueMicrotask(() => {
      if (!menu.contains(document.activeElement)) menu.open = false;
    });
  });
  toggle.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      menu.open = true;
      menu.querySelector('a').focus();
    }
  });
})();

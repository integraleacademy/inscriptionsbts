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
  menu.addEventListener('focusout', event => {
    // During a native click, activeElement can briefly be body before the link
    // gains focus. Use the destination so the menu does not swallow that click.
    if (event.relatedTarget && !menu.contains(event.relatedTarget)) menu.open = false;
  });
  toggle.addEventListener('keydown', event => {
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      menu.open = true;
      menu.querySelector('a').focus();
    }
  });
})();

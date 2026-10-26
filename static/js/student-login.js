(() => {
  const password = document.getElementById('access-password'), toggle = document.getElementById('access-password-toggle');
  if (!password || !toggle) return;
  toggle.addEventListener('click', () => {
    const visible = password.type === 'password'; password.type = visible ? 'text' : 'password';
    toggle.textContent = visible ? 'Masquer le mot de passe' : 'Afficher le mot de passe'; toggle.setAttribute('aria-pressed', String(visible));
  });
  const caps = document.getElementById('access-caps-lock');
  ['keydown','keyup'].forEach(type => password.addEventListener(type, event => { caps.hidden = !event.getModifierState('CapsLock'); }));
  password.addEventListener('blur', () => { caps.hidden = true; });
})();

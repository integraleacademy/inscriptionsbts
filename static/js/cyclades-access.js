const field = (id) => document.getElementById(id);
field('print').addEventListener('click', () => window.print());
field('copy').addEventListener('click', async () => {
  const text = [
    'Votre espace candidat Cyclades', field('portal').href,
    'Identifiant : ' + field('login').textContent,
    'Mot de passe provisoire : ' + field('pass').textContent,
    'Si vous avez personnalisé votre mot de passe, utilisez celui que vous avez choisi.'
  ].join('\n');
  try {
    await navigator.clipboard.writeText(text);
    field('feedback').textContent = 'Accès copiés.';
  } catch {
    field('feedback').textContent = 'Sélectionnez les deux valeurs pour les copier.';
  }
});

/* Presentation only: keep structured identities unchanged in storage and APIs. */
(() => {
  const clean = value => String(value ?? '').trim().replace(/\s+/gu, ' ');
  const lastName = value => clean(value).toLocaleUpperCase('fr');
  const firstName = value => clean(value).toLocaleLowerCase('fr').split(/([ '’\-‐‑‒–—])/u).map(part => part.slice(0, 1).toLocaleUpperCase('fr') + part.slice(1)).join('');
  const fullName = (nom, prenom) => [firstName(prenom), lastName(nom)].filter(Boolean).join(' ');
  const initials = (nom, prenom) => (firstName(prenom).slice(0, 1) + lastName(nom).slice(0, 1)).toLocaleUpperCase('fr');
  window.AcademyNames = Object.freeze({lastName, firstName, fullName, initials});
})();

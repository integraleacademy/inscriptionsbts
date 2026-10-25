// Uses the real rendered template and shipped script; no network or sign-in.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');

(async () => {
  const html = fs.readFileSync(process.argv[2], 'utf8');
  const dom = new JSDOM(html, {url: 'https://example.test/candidature', runScripts: 'outside-only'});
  const w = dom.window, d = w.document;
  w.eval(fs.readFileSync('static/js/academy-header.js', 'utf8'));
  const menu = d.querySelector('[data-account-menu]');
  const toggle = menu.querySelector('summary');
  const links = [...menu.querySelectorAll('a')];
  let checks = 0;
  const check = (condition, message) => { assert.ok(condition, message); checks++; };

  check(!menu.open, 'The connection menu starts closed');
  toggle.click();
  check(menu.open, 'Clicking Connexion opens the native disclosure');
  toggle.click();
  check(!menu.open, 'A second click closes it');
  toggle.focus();
  toggle.dispatchEvent(new w.KeyboardEvent('keydown', {key: 'ArrowDown', bubbles: true, cancelable: true}));
  check(menu.open && d.activeElement === links[0], 'Arrow Down opens the menu and focuses the first space');
  links[1].focus();
  await Promise.resolve();
  check(menu.open, 'Moving focus between spaces keeps the menu open');
  links[1].dispatchEvent(new w.KeyboardEvent('keydown', {key: 'Escape', bubbles: true}));
  check(!menu.open && d.activeElement === toggle, 'Escape closes the menu and returns focus to Connexion');
  toggle.click();
  d.querySelector('.preparation-intro').click();
  check(!menu.open, 'Clicking outside closes the menu');
  toggle.click();
  menu.querySelector('nav > p').click();
  check(menu.open, 'Clicking inside leaves the choices available');
  d.querySelector('#start-application').focus();
  await Promise.resolve();
  check(!menu.open, 'Leaving the menu by keyboard closes it');
  menu.open = true;
  toggle.dispatchEvent(new w.FocusEvent('focusout', {bubbles: true, relatedTarget: links[0]}));
  await Promise.resolve();
  check(menu.open, 'The native focus transition to a link must not close the menu before its click');
  links[0].dispatchEvent(new w.FocusEvent('focusout', {bubbles: true, relatedTarget: d.querySelector('#start-application')}));
  check(!menu.open, 'A focus destination outside the menu closes it');
  check(links.map(link => link.pathname).join(',') === '/espace/connexion,/formateur/connexion,/login', 'Each choice uses the existing authenticated entry point');
  check(links.every(link => !link.hasAttribute('target')), 'Space selection stays in the current tab');
  dom.window.close();
  console.log(`${checks} shared header checks passed`);
})().catch(error => { console.error(error); process.exitCode = 1; });

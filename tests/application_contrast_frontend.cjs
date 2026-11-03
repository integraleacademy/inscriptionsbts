// Keep the admission choices legible after all global button and link themes.
// Load every production stylesheet, in template order, to exercise that cascade.
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {JSDOM, VirtualConsole} = require('jsdom');
const virtualConsole = new VirtualConsole();
virtualConsole.on('jsdomError', error => { throw error; });
const dom = new JSDOM(fs.readFileSync(process.argv[2], 'utf8'), {runScripts: 'outside-only', virtualConsole});
const d = dom.window.document;
for (const link of d.querySelectorAll('link[rel=stylesheet]')) {
  const path = link.getAttribute('href').split('?')[0];
  if (!path.startsWith('/static/')) continue;
  const style = d.createElement('style');
  style.textContent = fs.readFileSync('.' + path, 'utf8');
  d.head.append(style);
}
function luminance(color) {
  const rgb = color.match(/[\d.]+/g).map(Number);
  assert.equal(rgb.length, 3, 'A solid rendered color is required');
  const linear = rgb.map(value => value / 255).map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2];
}
function contrast(first, second) {
  const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (values[0] + .05) / (values[1] + .05);
}
const cards = d.querySelectorAll('.route-options .route-option');
assert.equal(cards.length, 3);
for (const card of cards) {
  const style = dom.window.getComputedStyle(card);
  assert.ok(contrast(style.color, style.backgroundColor) >= 4.5, card.textContent + ' must remain readable');
}
const connexion = dom.window.getComputedStyle(d.querySelector('.academy-account-toggle'));
assert.ok(contrast(connexion.color, connexion.backgroundColor) >= 4.5, 'Connexion remains readable independently of the page theme');
console.log('All three training choices and the account button pass text contrast.');
dom.window.close();

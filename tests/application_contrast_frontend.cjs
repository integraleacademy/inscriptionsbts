// Regression: the preparation CTA inherited !important white text from button-dark.
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
const start = dom.window.getComputedStyle(d.getElementById('start-application'));
const panel = dom.window.getComputedStyle(d.querySelector('.preparation-start'));
const connexion = dom.window.getComputedStyle(d.querySelector('.academy-account-toggle'));
assert.ok(contrast(start.color, start.backgroundColor) >= 4.5, 'The start/resume label stays readable after all shared styles');
assert.ok(contrast(start.backgroundColor, panel.backgroundColor) >= 3, 'The start button stands out from its card');
assert.ok(contrast(connexion.color, connexion.backgroundColor) >= 4.5, 'Connexion remains readable independently of the page theme');
console.log(`3 contrast checks passed; start button text ${contrast(start.color, start.backgroundColor).toFixed(2)}:1`);
dom.window.close();

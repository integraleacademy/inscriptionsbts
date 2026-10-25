/* The invoice comparison is advisory, integer-cent based and never sends money. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {JSDOM} = require('jsdom');
const fixture = `<div data-trainer-workload data-estimate-cents="123456" data-all-priced="true"><form id="trainer-hourly-rate-form" action="/admin/formateurs/t1/tarif"><input name="csrf_token" value="token"><button type="submit">Save</button></form><p id="tw-rate-feedback" hidden></p><input id="tw-invoice-amount"><p id="tw-invoice-result"></p></div>`;
const dom = new JSDOM(fixture, {url: 'https://school.example.test/admin/formateurs/t1', runScripts: 'outside-only'});
const {window} = dom;
window.fetch = async () => ({ok: false, json: async () => ({message: 'Le tarif a été modifié entre-temps.'})});
window.eval(fs.readFileSync(path.join(__dirname, '../static/js/trainer-workload.js'), 'utf8'));
const input = window.document.getElementById('tw-invoice-amount');
const result = window.document.getElementById('tw-invoice-result');
function enter(value) {input.value = value; input.dispatchEvent(new window.Event('input')); return result.textContent;}
assert.match(enter('1 234,56'), /correspond exactement/);
assert.ok(result.classList.contains('matching'));
assert.match(enter('1234.57'), /0,01.*de plus/);
assert.match(enter('1234,55'), /0,01.*de moins/);
assert.match(enter('1\u202f234,56'), /correspond exactement/);
assert.match(enter('-1'), /montant positif/);
assert.match(enter('1.234'), /deux décimales/);
assert.match(enter('Infinity'), /montant positif/);
assert.match(enter('0'), /1\D234,56.*de moins/);
assert.match(enter(''), /différence.*prévues/);
assert.equal(result.className, 'tw-invoice-result');
const form = window.document.getElementById('trainer-hourly-rate-form');
form.reportValidity = () => true;
form.dispatchEvent(new window.Event('submit', {cancelable: true}));
assert.equal(form.querySelector('button').disabled, true);
setTimeout(() => {
  assert.equal(form.querySelector('button').disabled, false);
  assert.match(window.document.getElementById('tw-rate-feedback').textContent, /modifié entre-temps/);
  assert.equal(window.document.getElementById('tw-rate-feedback').hidden, false);
  console.log('15 trainer workload interface assertions passed.');
  window.close();
}, 0);

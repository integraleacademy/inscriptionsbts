// Render index.html with Flask first; jsdom exercises the real shipped script.
// NODE_PATH=/path/to/node_modules node tests/application_journey_frontend.cjs /path/to/application.html
const fs = require('node:fs');
const assert = require('node:assert/strict');
const {JSDOM} = require('jsdom');
const html = fs.readFileSync(process.argv[2], 'utf8');
let checks = 0;
function check(condition, message) { assert.ok(condition, message); checks++; }
function setup({preview = true, saved = null} = {}) {
  const dom = new JSDOM(html, {url: 'https://example.test/candidature', runScripts: 'outside-only'});
  const w = dom.window, d = w.document, form = d.getElementById('application-form');
  w.matchMedia = () => ({matches: true});
  w.HTMLElement.prototype.scrollIntoView = () => {};
  const calls = [];
  w.fetch = async (url, options) => {
    calls.push({url, options});
    return {ok: true, headers: {get: () => 'application/json'}, json: async () => ({success: true, ok: true, redirect: '/espace/test-only'})};
  };
  let celebrated = false;
  w.BTSAdmissionCelebration = {show: () => { celebrated = true; }};
  form.dataset.preview = String(preview);
  if (!preview) {
    d.getElementById('send-application').disabled = false;
    d.getElementById('save-application').disabled = false;
    form.querySelector('[name=admin_preview]')?.remove();
  }
  d.getElementById('saved-application').textContent = JSON.stringify(saved);
  w.eval(fs.readFileSync('static/js/admission-validation.js', 'utf8'));
  w.eval(fs.readFileSync('static/js/application-2027.js', 'utf8'));
  const change = input => input.dispatchEvent(new w.Event('change', {bubbles: true}));
  const click = id => d.getElementById(id).click();
  const current = () => d.querySelector('.application-step:not([hidden])')?.dataset.stepId;
  const choose = (name, value) => { const input = form.querySelector(`[name="${name}"][value="${value}"]`); input.checked = true; change(input); };
  const fill = (name, value) => {const input = form.elements.namedItem(name); input.value = value; input.dispatchEvent(new w.Event('input', {bubbles: true})); change(input);};
  const jump = id => { const step = [...d.querySelectorAll('.application-step')].findIndex(x => x.dataset.stepId === id); d.getElementById('preview-step').value = String(step); change(d.getElementById('preview-step')); };
  const file = (name, filename, size = 12000) => {
    const input = form.elements.namedItem(name), selected = new w.File(['x'.repeat(size)],filename);
    // jsdom has no file picker; its native required check ignores an overridden
    // FileList. Keep custom validity (format/size) and required semantics intact.
    Object.defineProperty(input, 'files', {configurable: true, value: [selected]});
    input.checkValidity = input.reportValidity = () => (!input.required || input.files.length > 0) && !input.validity.customError;
    change(input); return selected;
  };
  return {dom,w,d,form,calls,click,current,choose,fill,jump,file,celebrated: () => celebrated};
}

(async () => {
  {
    const {dom,d,form,click,current,choose,fill,jump,file,calls} = setup();
    check(!d.getElementById('application-guide').hidden && d.getElementById('application-journey').hidden, 'Preparation is the initial view');
    check(d.getElementById('start-application').textContent.includes('Commencer ma pré-inscription'), 'Requested start label appears');
    d.querySelector('[data-prepared=identity]').click();
    check(d.getElementById('preparation-count').textContent === '1 / 5 pièces préparées', 'Checklist counts prepared documents');
    click('start-application');
    check(current() === 'formation' && d.getElementById('application-guide').hidden, 'Starting reveals only the BTS choice');
    check(d.querySelectorAll('.application-step:not([hidden])').length === 1, 'Exactly one question screen is visible');
    choose('bts','MCO'); click('next-step');
    check(current() === 'format', 'Course format has a separate screen');
    choose('mode','distanciel'); click('next-step');
    check(current() === 'identite', 'Non-MOS skips security and APS questions');
    fill('nom','dupont'); fill('prenom','camille');
    click('review-preparation');
    check(!d.getElementById('application-guide').hidden && d.getElementById('start-application').textContent.includes('Reprendre'), 'Guide can be reopened during the journey');
    click('start-application');
    check(current() === 'identite' && form.elements.nom.value === 'dupont', 'Returning from guide preserves current screen and answers');
    jump('formation'); choose('bts','MOS'); click('next-step'); click('next-step');
    check(current() === 'mos', 'MOS adds its specific question');
    choose('mos_parcours','autre'); click('next-step');
    check(current() === 'aps', 'Other MOS situation adds the APS question');
    choose('aps_souhaitee','non'); fill('raison_aps','Autre organisme'); click('next-step');
    check(current() === 'identite', 'APS answer continues to identity');
    jump('formation'); choose('bts','MCO');
    check(form.elements.raison_aps.disabled && form.elements.aps_souhaitee[0].disabled, 'Changing away from MOS excludes previous security answers');
    choose('bts','MOS'); choose('mos_parcours','carte_cnaps');
    check(form.elements.raison_aps.disabled, 'Existing CNAPS card excludes APS follow-up');
    choose('mos_parcours','autre');
    check(!form.elements.raison_aps.disabled && form.elements.raison_aps.value === 'Autre organisme', 'Returning to prior condition restores its answer');
    jump('naissance'); fill('date_naissance',`${new Date().getFullYear()-16}-01-01`);
    click('next-step'); click('next-step'); click('next-step');
    check(current() === 'responsable', 'Under-18 flow includes legal guardian');
    click('next-step');
    check(current() === 'responsable-contact', 'Guardian contact is its own small screen');
    jump('naissance'); fill('date_naissance','2000-01-01');
    check(form.elements.resp_nom.disabled && form.elements.resp_email.disabled, 'Adult flow excludes guardian fields from validation and payload');
    jump('zone'); choose('cherche_idf','oui'); click('next-step');
    check(current() === 'accompagnement', 'Île-de-France selection offers Pôle Alternance');
    choose('souhaite_accompagnement','oui'); click('previous-step'); choose('cherche_idf','non'); click('next-step');
    check(current() === 'motif' && form.elements.souhaite_accompagnement[0].disabled, 'Other regions skip partner follow-up');
    jump('photo'); const originalFile = file('photo','portrait.png'); click('review-preparation'); click('start-application');
    check(current() === 'photo' && form.elements.photo.files[0] === originalFile, 'Guide keeps already selected files in the same page');
    jump('recap');
    check(d.querySelectorAll('#application-recap > details').length > 0, 'Recap groups answers into expandable chapters');
    check(!d.getElementById('application-recap').textContent.includes('Ton responsable légal'), 'Recap omits irrelevant guardian questions');
    check(d.getElementById('send-application').disabled, 'Admin preview cannot send');
    form.dispatchEvent(new dom.window.Event('submit',{bubbles:true,cancelable:true}));
    check(calls.length === 0, 'Preview produced no draft or application request');
    dom.window.close();
  }
  {
    const {dom,d,form,calls,click,current,choose,fill,file,w,celebrated} = setup({preview:false});
    click('start-application'); click('next-step');
    check(current() === 'formation' && !d.getElementById('application-error').hidden, 'BTS selection is required');
    choose('bts','MCO'); click('next-step'); click('next-step');
    check(current() === 'format', 'Course mode is required on its own screen');
    choose('mode','presentiel'); click('next-step');
    fill('nom','dupont'); fill('prenom','camille'); click('next-step');
    check(form.elements.nom.value === 'DUPONT' && form.elements.prenom.value === 'Camille', 'Names retain normalization');
    fill('date_naissance','2000-01-01'); fill('sexe','Femme'); click('next-step');
    fill('pays_naissance','France'); fill('ville_naissance','Paris'); fill('cp_naissance','75001'); click('next-step');
    fill('nationalite','Française'); click('next-step');
    check(current() === 'email', 'Adult MCO path reaches email without conditional detours');
    fill('email','camille@example.test'); fill('email_confirm','different@example.test'); click('next-step');
    check(current() === 'email', 'Mismatched confirmation prevents continuing');
    fill('email_confirm','camille@example.test'); click('next-step');
    fill('tel','0612345678'); click('next-step');
    fill('adresse','1 rue Test'); fill('cp','75001'); fill('ville','Paris'); click('next-step');
    fill('num_secu','200017512345600'); click('next-step');
    check(current() === 'securite-sociale', 'Invalid NIR cannot advance');
    const core = '2000175123456'; fill('num_secu',core+String(97-Number(BigInt(core)%97n)).padStart(2,'0')); click('next-step');
    fill('baccalaureat','Oui'); fill('bac_type','Autre'); click('next-step');
    check(current() === 'bac', 'Other diploma requires its explanation');
    fill('bac_autre','Diplôme équivalent'); click('next-step');
    choose('permis_b','Oui'); click('next-step'); choose('entreprise_trouvee','non'); click('next-step'); choose('recherches_commencees','oui'); click('next-step'); choose('cherche_idf','non'); click('next-step');
    fill('projet_pourquoi','Apprendre le commerce'); click('next-step'); fill('projet_objectif','Devenir responsable'); click('next-step');
    for (const name of ['qualites','motivation','valeurs','travail']) {
      click('next-step'); check(current() === name, `${name} requires at least one option`);
      form.querySelector(`[name="${name}[]"]`).click(); click('next-step');
    }
    fill('projet_passions','La musique et les voyages'); click('next-step');
    file('ci','identite.exe'); click('next-step'); check(current() === 'piece-identite', 'Wrong identity file extension is rejected');
    file('ci','identite.pdf'); click('next-step');
    check(current() === 'photo' && !form.elements.ci2.required, 'Optional identity back is preserved');
    file('photo','portrait.png',8*1024*1024+1); click('next-step'); check(current() === 'photo', 'File over 8 MB is rejected');
    file('photo','portrait.png'); click('next-step');
    file('carte_vitale','vitale.pdf',5); click('next-step'); check(current() === 'carte-vitale', 'Empty PDF is rejected');
    file('carte_vitale','vitale.pdf'); click('next-step'); file('cv','cv.pdf'); click('next-step'); file('lm','lettre.pdf'); click('next-step');
    check(current() === 'recap' && !d.getElementById('send-application').hidden, 'Complete valid path reaches final review');
    check(d.getElementById('step-percent').textContent === '100 %', 'Progress reaches 100% for the actual path');
    check(!d.getElementById('application-recap').textContent.includes(form.elements.num_secu.value), 'Recap masks the social security number');
    form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
    check(calls.length === 0, 'Consent is still required before submitting');
    form.elements.consent.checked = true;
    form.dispatchEvent(new w.Event('submit',{bubbles:true,cancelable:true}));
    await new Promise(resolve => setImmediate(resolve));
    check(calls.length === 1 && calls[0].url.endsWith('/submit') && celebrated(), 'Valid application makes one mocked submission and opens confirmation');
    check(!calls[0].options.body.has('resp_nom') && !calls[0].options.body.has('mos_parcours'), 'Submitted payload excludes skipped fields');
    dom.window.close();
  }
  {
    const saved = {bts:'MOS', mode:'distanciel', mos_parcours:'autre', aps_souhaitee:'oui', nom:'TEST', prenom:'Camille', email:'camille@example.test', 'qualites[]':['curieux','serieux']};
    const {dom,d,form,click,current,calls} = setup({preview:false,saved});
    check(d.getElementById('application-guide').hidden && current()==='formation', 'Draft resumes directly in form');
    check(form.querySelectorAll('[name="qualites[]"]:checked').length===2, 'Draft retains multiple profile answers');
    click('save-application'); await new Promise(resolve=>setImmediate(resolve));
    check(calls.length===1 && calls[0].url==='/save_draft', 'Draft save continues to use existing endpoint');
    const sent = JSON.parse(calls[0].options.body).full_form;
    check(sent.bts==='MOS' && sent.aps_souhaitee==='oui' && sent['qualites[]'].length===2, 'Draft payload preserves conditional and multiple answers');
    check(d.getElementById('application-notice').textContent.includes('lien de reprise'), 'Draft result tells applicant how to resume');
    dom.window.close();
  }
  {
    const {dom,click,current,calls} = setup({preview:false}); click('start-application'); click('save-application');
    check(current()==='email' && calls.length===0, 'Saving without email focuses the correct new email screen without sending');
    dom.window.close();
  }
  console.log(`PASS: ${checks} guided application checks; only mocked network calls.`);
})().catch(error => {console.error(error); process.exitCode=1;});

(() => {
  'use strict';
  const root = document.querySelector('[data-gradebook]');
  if (!root) return;
  const $ = id => document.getElementById(id), state = JSON.parse($('gradebook-state').textContent);
  const teacher = state.role === 'trainer', dirty = new Set();
  let busy = false, editing = null, grading = null;
  const el = (tag, text, cls) => { const node = document.createElement(tag); if (text !== undefined) node.textContent = text; if (cls) node.className = cls; return node; };
  const date = value => (value || '').split('-').reverse().join('/');
  const numeric = value => Number(value).toLocaleString('fr-FR', {maximumFractionDigits:2});
  function message(text, error = false) { const n = $('gb-feedback'); n.textContent = text; n.className = 'teach-feedback ' + (error ? 'error' : 'success'); n.hidden = false; }
  async function api(path, data) {
    const options = {method:data === undefined ? 'GET' : 'POST', credentials:'same-origin', cache:'no-store', headers:{Accept:'application/json', 'X-CSRF-Token':root.dataset.csrf}};
    if (data !== undefined) { options.headers['Content-Type'] = 'application/json'; options.body = JSON.stringify(data); }
    const response = await fetch('/formateur/devoirs-notes/' + path, options), answer = await response.json().catch(() => ({}));
    if (!response.ok || !answer.ok) throw new Error(answer.message || 'Impossible d’enregistrer. Vérifiez votre connexion puis réessayez.');
    return answer.item;
  }
  async function run(button, action) {
    if (busy) return;
    busy = true;
    const caption = button?.textContent;
    if (button) { button.disabled = true; button.textContent = 'En cours…'; }
    try { await action(); } catch (error) { message(error.message, true); }
    finally { busy = false; if (button) { button.disabled = false; button.textContent = caption; } }
  }
  function keep(item) {
    const index = state.items.findIndex(i => i.id === item.id);
    if (index < 0) state.items.unshift(item); else state.items[index] = item;
    state.items.sort((a,b) => b.evaluation_date.localeCompare(a.evaluation_date) || b.created_at.localeCompare(a.created_at));
    render();
  }
  function option(select, value, text) { const n = el('option', text); n.value = value; select.append(n); }
  function filterSubjects() {
    const previous = $('gb-filter-subject').value, promotion = $('gb-filter-promotion').value;
    const available = new Map();
    state.items.forEach(item => item.groups.forEach(group => { if (!promotion || group.promotion_id === promotion) available.set(group.subject_id, group.name); }));
    const select = $('gb-filter-subject'); select.replaceChildren(); option(select, '', 'Toutes les matières');
    [...available.entries()].sort((a,b) => a[1].localeCompare(b[1], 'fr')).forEach(([id,name]) => option(select,id,name));
    if (available.has(previous)) select.value = previous;
  }
  function render() {
    filterSubjects();
    const promotion = $('gb-filter-promotion').value, subject = $('gb-filter-subject').value, query = $('gb-search').value.trim().toLocaleLowerCase('fr');
    const items = state.items.filter(item => item.groups.some(g => (!promotion || g.promotion_id === promotion) && (!subject || g.subject_id === subject)) && (!query || item.title.toLocaleLowerCase('fr').includes(query)));
    $('gb-count').textContent = items.length + (items.length > 1 ? ' éléments' : ' élément');
    const list = $('gb-list'); list.replaceChildren();
    if (!items.length) list.append(el('p', state.items.length ? 'Aucun résultat pour ces filtres.' : teacher ? 'Créez un devoir ou ajoutez une évaluation pour saisir vos premières notes.' : 'Aucun devoir ou résultat publié pour le moment.', 'teach-empty'));
    items.forEach(item => {
      const article = el('article', undefined, 'gb-item'), heading = el('div', undefined, 'gb-item-heading'), title = el('div'), tags = el('div', undefined, 'gb-tags');
      title.append(el('p', item.promotion_names + ' · ' + item.subject_name, 'teach-eyebrow'), el('h3', item.title));
      tags.append(el('span', item.kind === 'evaluation' ? 'Évaluation' : 'Devoir', 'teach-tag'));
      if (teacher) tags.append(el('span', item.published ? 'Publié' : 'Brouillon', 'teach-tag ' + (item.published ? 'success' : 'warning')));
      heading.append(title, tags); article.append(heading);
      article.append(el('p', (item.kind === 'evaluation' ? 'Évaluation du ' + date(item.evaluation_date) : 'À rendre le ' + date(item.due_date)) + ' · Sur ' + numeric(item.scale) + ' · Coefficient ' + numeric(item.coefficient)));
      if (item.instructions) article.append(el('div', item.instructions, 'teach-read-content'));
      if (teacher) {
        const actions = el('div', undefined, 'teach-inline'), edit = el('button', 'Modifier', 'teach-button'), notes = el('button', 'Saisir les notes', 'teach-button primary');
        edit.type = notes.type = 'button';
        edit.addEventListener('click', () => { if (!busy && canClose()) run(edit, async () => openEditor(await api(encodeURIComponent(item.id) + '/state'))); });
        notes.addEventListener('click', () => { if (!busy && canClose()) run(notes, async () => openGrades(await api(encodeURIComponent(item.id) + '/state'))); });
        actions.append(edit, notes, el('span', item.graded_count + ' note' + (item.graded_count > 1 ? 's' : '') + ' saisie' + (item.graded_count > 1 ? 's' : ''), 'teach-tag')); article.append(actions);
      } else {
        const grade = item.grades[0], result = el('div', undefined, 'teach-result');
        result.append(el('strong', grade?.status === 'graded' ? numeric(grade.score) + ' / ' + numeric(item.scale) : grade?.status === 'absent' ? 'Absent' : grade?.status === 'exempt' ? 'Dispensé' : 'En attente de note'));
        if (grade?.comment) result.append(el('p', grade.comment));
        article.append(result);
      }
      list.append(article);
    });
  }
  ['gb-filter-promotion','gb-filter-subject'].forEach(id => $(id).addEventListener('change',render)); $('gb-search').addEventListener('input',render);
  render();
  if (!teacher) return;
  function canClose() { return !dirty.size || window.confirm('Abandonner les modifications non enregistrées ?'); }
  function closeEditors() { dirty.clear(); $('gb-editor').hidden = $('gb-grades').hidden = true; }
  ['gb-editor','gb-grades'].forEach(id => {
    $(id).addEventListener('input', () => dirty.add(id)); $(id).addEventListener('change', () => dirty.add(id));
    $(id + '-close').addEventListener('click', () => { if (!busy && (!dirty.has(id) || window.confirm('Abandonner les modifications non enregistrées ?'))) { dirty.delete(id); $(id).hidden = true; } });
  });
  window.addEventListener('beforeunload', event => { if (dirty.size) { event.preventDefault(); event.returnValue = ''; } });
  function editorSubjects(selected = '') {
    const p = state.promotions.find(p => p.id === $('gb-promotion').value), select = $('gb-subject'); select.replaceChildren(); option(select,'','Choisir une matière');
    state.subjects.filter(s => p && s.diploma_codes.includes(p.bts)).forEach(s => option(select,s.id,s.name));
    if (selected) select.value = selected;
  }
  function kindChanged() {
    const evaluation = $('gb-kind').value === 'evaluation';
    $('gb-due-label').hidden = evaluation; $('gb-due').required = !evaluation;
    $('gb-editor-title').textContent = (editing ? 'Modifier ' : 'Nouvelle ') + (evaluation ? 'l’évaluation' : 'le devoir');
    if (!editing) $('gb-editor-title').textContent = evaluation ? 'Ajouter une évaluation et ses notes' : 'Créer un devoir';
    $('gb-save').textContent = !editing && evaluation ? 'Créer et saisir les notes' : evaluation ? 'Enregistrer l’évaluation' : 'Enregistrer le devoir';
  }
  function openEditor(item = null, kind = 'homework') {
    closeEditors(); editing = item; $('gb-editor').hidden = false; $('gb-editor').reset();
    $('gb-kind').value = item?.kind || kind;
    $('gb-promotion').value = item?.groups[0].promotion_id || $('gb-filter-promotion').value || (state.promotions.length === 1 ? state.promotions[0].id : '');
    editorSubjects(item?.groups[0].subject_id || $('gb-filter-subject').value);
    if (item && !$('gb-subject').value) { option($('gb-subject'),item.groups[0].subject_id,item.groups[0].name); $('gb-subject').value = item.groups[0].subject_id; }
    $('gb-promotion').disabled = $('gb-subject').disabled = !!item;
    $('gb-scope-note').hidden = !item; $('gb-scope-note').textContent = item ? item.promotion_names + ' · ' + item.subject_name + ' — la promotion et la matière sont conservées pour préserver les notes.' : '';
    $('gb-title').value = item?.title || ''; $('gb-instructions').value = item?.instructions || '';
    $('gb-date').value = item?.evaluation_date || state.today; $('gb-due').value = item?.due_date || state.today;
    $('gb-scale').value = item?.scale ?? 20; $('gb-coefficient').value = item?.coefficient ?? 1; $('gb-published').checked = !!item?.published;
    kindChanged(); $('gb-editor').scrollIntoView({behavior:'smooth', block:'start'}); $('gb-title').focus({preventScroll:true});
  }
  $('gb-promotion').addEventListener('change', () => editorSubjects()); $('gb-kind').addEventListener('change',kindChanged);
  $('gb-new-homework').addEventListener('click', () => { if (!busy && canClose()) openEditor(); });
  $('gb-new-evaluation').addEventListener('click', () => { if (!busy && canClose()) openEditor(null,'evaluation'); });
  $('gb-editor').addEventListener('submit', event => {
    event.preventDefault(); if (!event.currentTarget.reportValidity()) return;
    const data = {id:editing?.id || null,version:editing?.version || 0,kind:$('gb-kind').value,
      promotion_id:$('gb-promotion').value,subject_id:$('gb-subject').value,title:$('gb-title').value,
      instructions:$('gb-instructions').value,evaluation_date:$('gb-date').value,due_date:$('gb-due').value,
      scale:$('gb-scale').value,coefficient:$('gb-coefficient').value,published:$('gb-published').checked};
    const startGrading = !editing && data.kind === 'evaluation';
    run(event.submitter, async () => {
      const item = await api('enregistrer',data); dirty.delete('gb-editor'); $('gb-editor').hidden = true; keep(item);
      message(item.kind === 'evaluation' ? 'Évaluation enregistrée. Vous pouvez saisir les notes.' : 'Devoir enregistré.');
      if (startGrading) openGrades(item);
    });
  });
  function openGrades(item) {
    closeEditors(); grading = item; $('gb-grades').hidden = false;
    $('gb-grades-title').textContent = item.title + ' · Notes sur ' + numeric(item.scale);
    $('gb-grades-scope').textContent = item.promotion_names + ' · ' + item.subject_name;
    $('gb-grades-publication').textContent = item.published ? 'Chaque étudiant voit uniquement sa note et son appréciation après enregistrement.' : 'Brouillon : les notes restent privées. Utilisez Modifier pour publier l’évaluation.';
    const rows = $('gb-grades-rows'); rows.replaceChildren();
    if (!item.students.length) rows.append(el('p','Aucun étudiant confirmé dans cette promotion.','teach-empty'));
    item.students.forEach(student => {
      const grade = item.grades.find(g => g.candidate_id === student.id), row = el('div',undefined,'teach-grade-row'); row.dataset.gradeStudent = student.id;
      const name = el('strong', AcademyNames.fullName(student.nom, student.prenom)); name.append(el('small', student.promotion_name)); name.append(el('span', student.mode === 'presentiel' ? 'En présentiel' : student.mode === 'distanciel' ? 'En distanciel' : 'Modalité à préciser', 'study-badge mode-' + (['presentiel','distanciel'].includes(student.mode) ? student.mode : 'unknown')));
      const statusLabel = el('label','Statut'), status = el('select'); status.dataset.gradeStatus = '';
      [['pending','Non noté'],['graded','Noté'],['absent','Absent'],['exempt','Dispensé']].forEach(([value,label]) => option(status,value,label)); status.value = grade?.status || 'pending'; statusLabel.append(status);
      const scoreLabel = el('label','Sur ' + numeric(item.scale)), score = el('input'); score.type = 'number'; score.min = '0'; score.max = item.scale; score.step = '.01'; score.dataset.gradeScore = ''; score.value = grade?.score ?? ''; scoreLabel.append(score);
      const commentLabel = el('label','Appréciation'), comment = el('input'); comment.type = 'text'; comment.maxLength = 2000; comment.dataset.gradeComment = ''; comment.value = grade?.comment || ''; commentLabel.append(comment);
      const refresh = () => { score.disabled = ['absent','exempt'].includes(status.value); score.required = status.value === 'graded'; average(); };
      status.addEventListener('change',refresh); score.addEventListener('input', () => { if (score.value !== '') status.value = 'graded'; else if (status.value === 'graded') status.value = 'pending'; refresh(); });
      row.append(name,statusLabel,scoreLabel,commentLabel); rows.append(row); refresh();
    });
    average(); $('gb-grades').scrollIntoView({behavior:'smooth',block:'start'});
  }
  function average() {
    let sum = 0, count = 0;
    root.querySelectorAll('[data-grade-student]').forEach(row => {
      const score = row.querySelector('[data-grade-score]');
      if (row.querySelector('[data-grade-status]').value === 'graded' && score.value !== '' && Number.isFinite(Number(score.value))) { sum += Number(score.value); count++; }
    });
    $('gb-average').textContent = count ? 'Moyenne : ' + numeric(sum/count) + ' / ' + numeric(grading.scale) + ' · ' + count + ' notes' : 'Aucune note saisie';
  }
  $('gb-grades').addEventListener('submit', event => {
    event.preventDefault(); if (!grading || !event.currentTarget.reportValidity()) return;
    const students = [...root.querySelectorAll('[data-grade-student]')].map(row => ({id:row.dataset.gradeStudent,status:row.querySelector('[data-grade-status]').value,score:row.querySelector('[data-grade-score]').value,comment:row.querySelector('[data-grade-comment]').value}));
    run(event.submitter, async () => {
      const item = await api(encodeURIComponent(grading.id) + '/notes',{version:grading.version,students});
      grading = item; dirty.delete('gb-grades'); keep(item); message('Notes et appréciations enregistrées.');
    });
  });
})();

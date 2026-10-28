(() => {
  'use strict';
  const $ = id => document.getElementById(id), table = $('rooms-calendar');
  if (!table) return;
  const form = $('rooms-session-form'), csrf = document.querySelector('.catalog-app').dataset.csrf;
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const date = d => new Date(d + 'T12:00:00');
  const iso = d => [d.getFullYear(), String(d.getMonth() + 1).padStart(2, '0'), String(d.getDate()).padStart(2, '0')].join('-');
  const add = (d, n) => { const x = date(d); x.setDate(x.getDate() + n); return iso(x); };
  const monday = d => add(d, -((date(d).getDay() + 6) % 7));
  const today = () => new Intl.DateTimeFormat('sv-SE', {timeZone: 'Europe/Paris'}).format(new Date());
  const frenchDate = d => /^\d{4}-\d{2}-\d{2}$/.test(d || '') ? d.split('-').reverse().join('/') : 'Présentiel à préciser';
  const label = d => date(d).toLocaleDateString('fr-FR', {weekday: 'short'}) + ' ' + frenchDate(d);
  const error = (id, msg) => { $(id).textContent = msg || ''; $(id).hidden = !msg; };
  const changed = () => window.dispatchEvent(new CustomEvent('academy:rooms-changed', {detail: {origin: 'calendar'}}));
  let rooms = [], sessions = [], sequence = 0, fingerprint = '', lastSync = 0, sessionsPromise = null;
  let multiple = false, moving = [], editingBlock = null;
  let dragging = null, dragBusy = false, pointerHeld = false, refreshAfterDrag = false, syncAfterDrag = false, suppressClickUntil = 0;
  let reservations = [];
  const selection = new Map();
  const moveDialog = $('rooms-course-dialog'), moveForm = $('rooms-course-form');
  const blockDialog = $('rooms-unavailable-dialog'), blockForm = $('rooms-unavailable-form');
  const exportDialog = $('rooms-export-dialog'), exportForm = $('rooms-export-form');

  // Keep ISO values for the API and the native picker, with an explicit French
  // editing surface: browser/OS locale must not turn dates into MM/DD/YYYY.
  const valueProperty = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value');
  const disabledProperty = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'disabled');
  for (const input of document.querySelectorAll('.room-planner input[type=date], #rooms-unavailable-dialog input[type=date], #rooms-export-dialog input[type=date]')) {
    const wrapper = node('span', undefined, 'room-date-field'), display = node('input'), picker = node('button', '▦', 'room-date-picker');
    const labelText = input.closest('label')?.textContent.trim() || 'Date';
    display.type = 'text'; display.inputMode = 'numeric'; display.placeholder = 'JJ/MM/AAAA'; display.maxLength = 10;
    display.pattern = '[0-9]{2}/[0-9]{2}/[0-9]{4}'; display.required = input.required;
    display.setAttribute('aria-label', labelText + ' (JJ/MM/AAAA)');
    if (input.id) display.id = input.id + '-display';
    picker.type = 'button'; picker.setAttribute('aria-label', 'Calendrier : ' + labelText);
    input.before(wrapper); wrapper.append(display, picker, input); input.classList.add('room-native-date');
    input.tabIndex = -1; input.required = false; input.setAttribute('aria-hidden', 'true');
    const sync = () => { display.value = input.value ? frenchDate(input.value) : ''; display.setCustomValidity(''); display.disabled = picker.disabled = input.disabled; };
    Object.defineProperty(input, 'value', {configurable: true, get() { return valueProperty.get.call(this); }, set(value) { valueProperty.set.call(this, value); sync(); }});
    Object.defineProperty(input, 'disabled', {configurable: true, get() { return disabledProperty.get.call(this); }, set(value) { disabledProperty.set.call(this, value); display.disabled = picker.disabled = Boolean(value); }});
    function readDate() {
      display.setCustomValidity('');
      const match = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(display.value.trim());
      const candidate = match ? match[3] + '-' + match[2] + '-' + match[1] : '';
      valueProperty.set.call(input, candidate);
      if (display.value && (!candidate || input.value !== candidate || !input.validity.valid)) {
        display.setCustomValidity('Indiquez une date valide au format JJ/MM/AAAA.'); return false;
      }
      return true;
    }
    display.addEventListener('input', () => { if (readDate()) input.dispatchEvent(new Event('input', {bubbles: true})); });
    display.addEventListener('change', () => {
      if (!readDate()) { display.reportValidity(); return; }
      input.dispatchEvent(new Event('change', {bubbles: true}));
    });
    input.addEventListener('change', sync);
    picker.addEventListener('click', () => { if (input.showPicker) input.showPicker(); else display.focus(); });
    sync();
  }

  async function request(path, data, method) {
    const response = await fetch('/admin/planning/api/rooms' + path, {
      method: method || (data ? 'POST' : 'GET'), credentials: 'same-origin',
      headers: {Accept: 'application/json', ...(data ? {'Content-Type': 'application/json', 'X-CSRF-Token': csrf} : {})},
      ...(data ? {body: JSON.stringify(data)} : {})
    });
    const result = await response.json().catch(() => ({}));
    if (!response.ok || result.ok === false) throw new Error([result.message || 'Chargement impossible.',
      ...(result.conflicts || []).map(c => (c.date ? frenchDate(c.date) + ' · ' : '') + c.message)].join('\n'));
    return result;
  }
  function roomOptions(select, value = select.value) {
    select.replaceChildren(new Option('Choisir une salle', ''));
    for (const r of rooms.filter(r => r.id && r.active)) select.add(new Option(r.name, r.id));
    select.value = value;
  }
  function updateSelection() {
    for (const id of ['rooms-multiple', 'rooms-move-selected', 'rooms-clear-selected']) $(id).disabled = dragBusy;
    $('rooms-multiple').setAttribute('aria-pressed', String(multiple));
    $('rooms-multiple').textContent = multiple ? 'Terminer la sélection' : 'Sélectionner plusieurs créneaux';
    $('rooms-move-selected').hidden = $('rooms-clear-selected').hidden = !selection.size;
    $('rooms-selected-count').textContent = selection.size ? selection.size + ' créneau(x) sélectionné(s). Glissez un créneau sélectionné pour déplacer tout le groupe.' : multiple ? 'Cliquez sur les créneaux à déplacer, puis glissez la sélection vers une salle.' : '';
    for (const card of table.querySelectorAll('[data-key]')) {
      const selected = selection.has(card.dataset.key);
      card.classList.toggle('selected', selected);
      if (multiple) card.setAttribute('aria-pressed', String(selected)); else card.removeAttribute('aria-pressed');
    }
  }
  function render(result, start) {
    rooms = result.rooms; reservations = result.reservations; roomOptions(form.elements.room_id);
    table.replaceChildren();
    const head = node('thead'), header = node('tr'); header.append(node('th', 'Salle'));
    for (let i = 0; i < 7; i++) header.append(node('th', label(add(start, i))));
    head.append(header); table.append(head); const body = node('tbody');
    for (const room of rooms) {
      const row = node('tr'), heading = node('th', room.name + (room.active ? '' : ' · inactive')); heading.scope = 'row'; row.append(heading);
      for (let i = 0; i < 7; i++) {
        const cell = node('td'), day = add(start, i);
        cell.dataset.roomId = room.id || ''; cell.dataset.date = day;
        const bookings = result.reservations.filter(b => b.room_id === room.id && b.date === day).sort((a, b) => a.start_min - b.start_min);
        for (const b of bookings) {
          const formation = ['A3P', 'APS', 'DESP', 'SSIAP', 'BTS', 'UNAVAILABLE'].includes(b.formation) ? b.formation.toLowerCase() : 'other';
          const card = node('button', undefined, 'room-booking ' + b.source + ' formation-' + formation + (b.conflict ? ' conflict' : '') + (b.exam ? ' room-exam' : ''));
          card.type = 'button'; card.dataset.key = b.key;
          card.draggable = b.source !== 'unavailable' && !b.pending;
          if (card.draggable) {
            card.setAttribute('aria-describedby', 'rooms-drag-help');
            card.addEventListener('dragstart', event => startDrag(event, b, card));
            card.addEventListener('dragend', endDrag);
          }
          const action = b.source === 'unavailable' ? 'Modifier l’indisponibilité' : 'Changer la salle';
          card.setAttribute('aria-label', (b.exam ? 'EXAMEN · ' : '') + action + ' · ' + b.title + ' · ' + label(b.date) + ' · ' + b.start + '–' + b.end);
          if (b.exam) card.append(node('span', 'EXAMEN', 'room-exam-badge'));
          card.append(node('strong', b.start === '00:00' && b.end === '24:00' ? 'Journée entière' : b.start + '–' + b.end), node('span', b.title));
          if (b.source === 'session') card.append(node('small', 'Présentiel : ' + frenchDate(b.presence_start)));
          else if (b.promotion_name) card.append(node('small', b.promotion_name));
          if (b.exam_full_day) card.append(node('b', 'Journée réservée pour l’examen'));
          if (b.conflict) card.append(node('b', '⚠ Chevauchement à corriger'));
          if (b.pending) card.append(node('small', 'Réservation en cours de confirmation'));
          card.append(node('small', action));
          card.addEventListener('click', () => {
            if (dragging || dragBusy || Date.now() < suppressClickUntil) return;
            if (b.source === 'unavailable') return openBlock(b);
            if (b.pending) return error('rooms-error', 'Ce créneau attend une confirmation de la session. Réessayez après l’actualisation.');
            if (multiple) { selection.has(b.key) ? selection.delete(b.key) : selection.set(b.key, b); updateSelection(); }
            else openMove([b]);
          });
          cell.append(card);
        }
        if (!bookings.length) cell.append(node('span', room.active ? 'Libre' : '—', 'room-free'));
        row.append(cell);
      }
      body.append(row);
    }
    table.append(body); updateSelection();
    const conflicts = result.reservations.filter(b => b.conflict).length;
    let status = rooms.filter(r => r.id).length + ' salle(s) · ' + result.reservations.length + ' réservation(s) · du ' + frenchDate(start) + ' au ' + frenchDate(add(start, 6)) + '.';
    if (conflicts) status += ' ⚠ ' + conflicts + ' réservation(s) en chevauchement à corriger.';
    if (!result.connected) status += ' Liaison avec les sessions non configurée.';
    else if (!result.ready) status += ' Première synchronisation des sessions nécessaire.';
    else status += ' Actualisation automatique active.';
    $('rooms-status').textContent = status;
    $('rooms-status').classList.toggle('rooms-error', Boolean(conflicts || (result.connected && !result.ready)));
  }
  async function load(forceSync = false) {
    if (pointerHeld || dragging || dragBusy) { refreshAfterDrag = true; syncAfterDrag ||= forceSync; return; }
    const dateDisplay = $('rooms-date-display');
    if (!dateDisplay.validity.valid || (document.activeElement === dateDisplay && !dateDisplay.value)) return;
    const seq = ++sequence, start = monday($('rooms-date').value || today()); $('rooms-date').value = start;
    const sync = forceSync || Date.now() - lastSync > 60000;
    if (sync) lastSync = Date.now();
    table.setAttribute('aria-busy', 'true');
    try {
      const result = await request('/schedule?' + new URLSearchParams({start, end: add(start, 6), sync: sync ? '1' : '0'}));
      if (seq !== sequence || pointerHeld || dragging || dragBusy) return;
      error('rooms-error', result.sync_warning);
      const next = JSON.stringify(result);
      if (next !== fingerprint) { render(result, start); fingerprint = next; }
    } catch (e) { if (seq === sequence) error('rooms-error', e.message); }
    finally { if (seq === sequence) table.removeAttribute('aria-busy'); }
  }

  function dragMessage(message, tone = '') {
    const feedback = $('rooms-drag-status');
    feedback.textContent = message; feedback.hidden = !message;
    feedback.classList.toggle('is-error', tone === 'error');
    feedback.classList.toggle('is-success', tone === 'success');
  }
  function dropTarget(cell) {
    const booking = dragging?.booking, bookings = dragging?.bookings;
    const room = rooms.find(r => r.id && r.id === cell?.dataset.roomId);
    if (!booking || !room?.active) return {message: 'Choisissez une salle active.'};
    if (cell.dataset.date !== booking.date) return {message: 'Restez dans la colonne du ' + frenchDate(booking.date) + ' pour changer uniquement la salle.'};
    if (bookings.every(b => b.room_id === room.id)) return {message: (bookings.length > 1 ? 'Tous ces créneaux sont déjà affectés à ' : 'Ce créneau est déjà affecté à ') + room.name + '.'};
    const others = reservations.filter(r => r.room_id === room.id && !dragging.keys.has(r.key));
    for (let i = 0; i < bookings.length; i++) {
      const b = bookings[i];
      const occupied = [...others, ...bookings.slice(0, i)].find(r => r.date === b.date && r.start_min < b.end_min && r.end_min > b.start_min);
      if (occupied) return {message: room.name + ' indisponible le ' + frenchDate(b.date) + ' · ' + b.start + '–' + b.end + ' : ' + occupied.title + '. Aucun créneau ne sera déplacé.'};
    }
    if (bookings.length > 1) return {room, message: 'Relâchez pour affecter les ' + bookings.length + ' créneaux sélectionnés à ' + room.name + '. Chaque créneau conserve sa date et ses horaires.'};
    return {room, message: 'Relâchez pour affecter « ' + booking.title + ' » à ' + room.name + ' · ' + frenchDate(booking.date) + ' · ' + booking.start + '–' + booking.end + '.'};
  }
  function clearDrag() {
    dragging = null; pointerHeld = false; suppressClickUntil = Date.now() + 350;
    table.classList.remove('is-dragging');
    for (const element of table.querySelectorAll('.room-dragging, .room-drop-allowed, .room-drop-blocked, .room-drop-active')) {
      element.classList.remove('room-dragging', 'room-drop-allowed', 'room-drop-blocked', 'room-drop-active');
      element.removeAttribute('data-drag-count');
    }
  }
  function resumeRefresh() {
    if (refreshAfterDrag && !pointerHeld && !dragging && !dragBusy) {
      const sync = syncAfterDrag; refreshAfterDrag = syncAfterDrag = false; load(sync);
    }
  }
  // A refresh must also wait between pressing the mouse and dragstart.
  table.addEventListener('pointerdown', event => {
    if (event.button !== 0 || event.pointerType === 'touch' || !event.target.closest?.('button[draggable=true]')) return;
    pointerHeld = true; refreshAfterDrag = true; sequence++; table.removeAttribute('aria-busy');
  });
  for (const name of ['pointerup', 'pointercancel']) document.addEventListener(name, () => {
    if (!pointerHeld) return;
    pointerHeld = false; setTimeout(resumeRefresh, 0);
  });
  function startDrag(event, booking, card) {
    if (dragBusy || !event.dataTransfer) { event.preventDefault(); return; }
    if (multiple && !selection.has(booking.key)) {
      event.preventDefault(); pointerHeld = false;
      dragMessage('Cliquez sur ce créneau pour le sélectionner avant de glisser la sélection.', 'error');
      resumeRefresh(); return;
    }
    // A selected card carries the whole selection, including other dates/weeks.
    // Keep the selected versions: the server rejects the entire batch if stale.
    const bookings = selection.has(booking.key) ? [...selection.values()] : [booking];
    dragging = {booking, bookings, keys: new Set(bookings.map(b => b.key))}; refreshAfterDrag = true;
    // Invalidate an older fetch so polling cannot remove the card mid-drag.
    sequence++; table.removeAttribute('aria-busy');
    event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', bookings.length > 1 ? bookings.length + ' créneaux sélectionnés' : booking.title);
    table.classList.add('is-dragging');
    for (const selected of table.querySelectorAll('[data-key]')) if (dragging.keys.has(selected.dataset.key)) selected.classList.add('room-dragging');
    if (bookings.length > 1) card.dataset.dragCount = bookings.length;
    for (const cell of table.querySelectorAll('td[data-room-id]')) {
      if (cell.dataset.date === booking.date) {
        cell.classList.add(dropTarget(cell).room ? 'room-drop-allowed' : 'room-drop-blocked');
      }
    }
    dragMessage((bookings.length > 1 ? 'Déplacez les ' + bookings.length + ' créneaux sélectionnés' : 'Déplacez « ' + booking.title + ' »') + ' vers une autre salle, dans la colonne du ' + frenchDate(booking.date) + '. Chaque créneau conserve sa date et ses horaires.');
  }
  function endDrag() {
    if (!dragging) return;
    const reason = dragging.rejection, count = dragging.bookings.length;
    clearDrag(); dragMessage(reason || 'Déplacement annulé. ' + (count > 1 ? 'Les créneaux conservent leurs salles.' : 'Le créneau conserve sa salle.'), reason ? 'error' : ''); resumeRefresh();
  }
  table.addEventListener('dragover', event => {
    if (!dragging || dragBusy) return;
    const cell = event.target.closest?.('td[data-room-id]');
    if (!cell || !table.contains(cell)) return;
    event.preventDefault();
    for (const previous of table.querySelectorAll('.room-drop-active')) previous.classList.remove('room-drop-active');
    const target = dropTarget(cell); event.dataTransfer.dropEffect = target.room ? 'move' : 'none';
    dragging.rejection = target.room ? '' : target.message;
    if (!target.room) cell.classList.add('room-drop-blocked');
    cell.classList.add('room-drop-active'); dragMessage(target.message, target.room ? '' : 'error');
  });
  table.addEventListener('dragleave', event => {
    const cell = event.target.closest?.('td[data-room-id]');
    if (cell && !cell.contains(event.relatedTarget)) cell.classList.remove('room-drop-active');
  });
  table.addEventListener('drop', async event => {
    if (!dragging || dragBusy) return;
    const cell = event.target.closest?.('td[data-room-id]');
    if (!cell || !table.contains(cell)) return;
    event.preventDefault();
    const {booking, bookings, keys} = dragging, target = dropTarget(cell); clearDrag();
    if (!target.room) { dragMessage(target.message, 'error'); resumeRefresh(); return; }
    dragBusy = true; updateSelection(); table.setAttribute('aria-busy', 'true');
    dragMessage('Vérification de la disponibilité de ' + target.room.name + (bookings.length > 1 ? ' pour les ' + bookings.length + ' créneaux…' : '…'));
    try {
      await request('/calendar-move', {room_id: target.room.id, slots: bookings.map(b => ({key: b.key, date: b.date,
        version: b.version, revision: b.revision, room_version: b.room_version}))});
      const owners = new Set(bookings.map(b => b.owner).filter(Boolean));
      for (const [key, item] of selection) if (keys.has(key) || owners.has(item.owner)) selection.delete(key);
      updateSelection();
      dragMessage(bookings.length > 1 ? 'Les ' + bookings.length + ' créneaux ont été affectés à ' + target.room.name + '. Leurs dates et horaires sont conservés.' : '« ' + booking.title + ' » affecté à ' + target.room.name + ' · ' + frenchDate(booking.date) + ' · ' + booking.start + '–' + booking.end + '.', 'success');
      changed();
    } catch (error) { dragMessage(error.message + '\nVérifiez le planning actualisé avant de réessayer.', 'error'); }
    finally { dragBusy = false; updateSelection(); table.removeAttribute('aria-busy'); resumeRefresh(); }
  });
  function show(dialog) { dialog._opener = document.activeElement; dialog.showModal(); }
  async function dialogWork(dialog, errorId, operation) {
    if (dialog.dataset.busy) return;
    dialog.dataset.busy = '1'; error(errorId, '');
    const controls = [...dialog.querySelectorAll('button,select,input')].map(n => [n, n.disabled]); controls.forEach(([n]) => n.disabled = true);
    try { await operation(); }
    catch (e) { error(errorId, e.message); }
    finally { delete dialog.dataset.busy; controls.forEach(([n, disabled]) => n.disabled = disabled); }
  }
  for (const dialog of [moveDialog, blockDialog, exportDialog]) {
    for (const button of dialog.querySelectorAll('[data-room-close]')) button.addEventListener('click', () => { if (!dialog.dataset.busy) dialog.close(); });
    dialog.addEventListener('cancel', e => { if (dialog.dataset.busy) e.preventDefault(); });
    dialog.addEventListener('close', () => (dialog._opener?.isConnected ? dialog._opener : $('rooms-refresh')).focus());
  }
  function openMove(bookings) {
    moving = bookings; error('rooms-course-error', '');
    $('rooms-course-heading').textContent = bookings.length > 1 ? 'Changer la salle de ' + bookings.length + ' créneaux' : 'Changer la salle';
    $('rooms-course-description').textContent = bookings.slice(0, 8).map(b => b.title + ' · ' + frenchDate(b.date) + ' · ' + b.start + '–' + b.end).join('\n') + (bookings.length > 8 ? '\nEt ' + (bookings.length - 8) + ' autre(s) créneau(x).' : '');
    $('rooms-course-shared').hidden = !bookings.some(b => b.is_shared);
    $('rooms-course-shared').textContent = 'Les cours communs changent de salle pour toutes les promotions concernées.';
    roomOptions(moveForm.elements.room_id, bookings.every(b => b.room_id === bookings[0].room_id) ? bookings[0].room_id || '' : '');
    moveForm.elements.room_id.required = true; show(moveDialog); moveForm.elements.room_id.focus();
  }
  moveForm.addEventListener('submit', e => {
    e.preventDefault(); if (!moving.length || !moveForm.reportValidity()) return;
    dialogWork(moveDialog, 'rooms-course-error', async () => {
      await request('/calendar-move', {room_id: moveForm.elements.room_id.value, slots: moving.map(b => ({key: b.key, date: b.date, version: b.version, revision: b.revision, room_version: b.room_version}))});
      selection.clear(); updateSelection(); moveDialog.close(); changed();
    });
  });
  $('rooms-multiple').addEventListener('click', () => { multiple = !multiple; updateSelection(); });
  $('rooms-clear-selected').addEventListener('click', () => { selection.clear(); updateSelection(); });
  $('rooms-move-selected').addEventListener('click', () => { if (selection.size) openMove([...selection.values()]); });

  function blockTimes() { $('rooms-unavailable-times').hidden = blockForm.elements.all_day.checked; }
  function openBlock(block = null) {
    editingBlock = block; blockForm.reset(); error('rooms-unavailable-error', '');
    $('rooms-unavailable-heading').textContent = block ? 'Modifier l’indisponibilité' : 'Indiquer une indisponibilité';
    $('rooms-unavailable-delete').hidden = !block;
    roomOptions(blockForm.elements.room_id, block?.room_id || '');
    blockForm.elements.start_date.value = block?.start_date || $('rooms-date').value;
    blockForm.elements.end_date.value = block?.end_date || blockForm.elements.start_date.value;
    blockForm.elements.all_day.checked = !block || (block.start === '00:00' && block.end === '24:00');
    if (block) { blockForm.elements.start.value = block.start; blockForm.elements.end.value = block.end === '24:00' ? '23:59' : block.end; blockForm.elements.reason.value = block.reason; }
    blockTimes(); show(blockDialog);
  }
  blockForm.elements.all_day.addEventListener('change', blockTimes);
  blockForm.elements.start_date.addEventListener('input', () => { if (blockForm.elements.end_date.value < blockForm.elements.start_date.value) blockForm.elements.end_date.value = blockForm.elements.start_date.value; });
  $('rooms-unavailable-add').addEventListener('click', () => openBlock());
  blockForm.addEventListener('submit', e => {
    e.preventDefault(); if (!blockForm.reportValidity()) return;
    dialogWork(blockDialog, 'rooms-unavailable-error', async () => {
      const f = blockForm.elements;
      await request('/unavailability' + (editingBlock ? '/' + encodeURIComponent(editingBlock.id) : ''), {
        room_id: f.room_id.value, start_date: f.start_date.value, end_date: f.end_date.value, reason: f.reason.value,
        start: f.all_day.checked ? '00:00' : f.start.value, end: f.all_day.checked ? '24:00' : f.end.value, version: editingBlock?.version
      }, editingBlock ? 'PUT' : 'POST');
      blockDialog.close(); changed();
    });
  });
  $('rooms-unavailable-delete').addEventListener('click', () => dialogWork(blockDialog, 'rooms-unavailable-error', async () => {
    await request('/unavailability/' + encodeURIComponent(editingBlock.id), {version: editingBlock.version}, 'DELETE'); blockDialog.close(); changed();
  }));
  $('rooms-export-open').addEventListener('click', () => {
    exportForm.elements.start.value = $('rooms-date').value; exportForm.elements.end.value = add($('rooms-date').value, 6);
    error('rooms-export-error', ''); show(exportDialog);
  });
  exportForm.addEventListener('submit', e => {
    e.preventDefault(); if (!exportForm.reportValidity()) return;
    dialogWork(exportDialog, 'rooms-export-error', async () => {
      const start = exportForm.elements.start.value, end = exportForm.elements.end.value;
      const response = await fetch('/admin/salles/export.pdf?' + new URLSearchParams({start, end}), {credentials: 'same-origin'});
      if (!response.ok) { const data = await response.json().catch(() => ({})); throw new Error(data.message || 'Le PDF n’a pas pu être créé.'); }
      const url = URL.createObjectURL(await response.blob()), link = document.createElement('a');
      link.href = url; link.download = 'planning-salles-' + frenchDate(start).replaceAll('/', '-') + '-' + frenchDate(end).replaceAll('/', '-') + '.pdf';
      document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 60000); exportDialog.close();
    });
  });

  const selectedSession = () => sessions.find(s => s.owner === form.elements.owner.value);
  function details() {
    const s = selectedSession(), fallback = !s || s.generated;
    $('rooms-session-fallback').hidden = fallback; $('rooms-session-fallback').disabled = fallback;
    error('rooms-session-error', '');
    $('rooms-session-detail').textContent = s ? 'Présentiel : ' + frenchDate(s.start) + (s.end ? ' → ' + frenchDate(s.end) : '') +
      (s.exam_dates?.length ? ' · Examen(s) : ' + s.exam_dates.map(frenchDate).join(', ') : '') +
      (s.exam_full_day?.length ? ' · Sans horaires d’examen, la journée entière est réservée.' : '') : '';
    form.elements.room_id.value = s?.config?.room_id || '';
    form.elements.presence_start.value = s?.start || ''; form.elements.presence_end.value = s?.end || '';
    form.elements.start.value = s?.config?.start || '08:00'; form.elements.end.value = s?.config?.end || '18:00';
    for (const input of form.querySelectorAll('[name=weekdays]')) input.checked = (s?.config?.weekdays || [0, 1, 2, 3, 4]).includes(Number(input.value));
  }
  function loadSessions() {
    if (sessionsPromise) return sessionsPromise;
    sessionsPromise = (async () => {
      error('rooms-session-error', ''); const old = form.elements.owner.value;
      try {
        const result = await request('/sessions'); sessions = result.sessions.filter(s => s.owner.startsWith('session:')).sort((a, b) => (a.start || '9999').localeCompare(b.start || '9999'));
        form.elements.owner.replaceChildren(new Option(sessions.length ? 'Choisir une session' : 'Aucune session à partir du 26/10/2026', ''));
        for (const s of sessions) form.elements.owner.add(new Option((s.name || s.title) + ' · ' + frenchDate(s.start) + ' · ' + (s.assigned ? 'salle affectée' : 'À AFFECTER'), s.owner));
        const requested = new URLSearchParams(location.search).get('session_id');
        form.elements.owner.value = old || (requested ? 'session:' + requested : ''); details(); await load(); return true;
      } catch (e) { error('rooms-session-error', e.message); return false; }
      finally { sessionsPromise = null; }
    })(); return sessionsPromise;
  }
  $('rooms-session-panel').addEventListener('toggle', () => { if ($('rooms-session-panel').open && !sessions.length) loadSessions(); });
  $('rooms-sessions-reload').addEventListener('click', loadSessions); form.elements.owner.addEventListener('change', details);
  form.addEventListener('submit', async e => {
    e.preventDefault(); const s = selectedSession(); if (!s || !form.reportValidity() || form.dataset.busy) return;
    error('rooms-session-error', ''); form.dataset.busy = '1';
    const f = form.elements, payload = {owner: s.owner, revision: s.revision, room_id: f.room_id.value, start: f.start.value, end: f.end.value,
      presence_start: f.presence_start.value, presence_end: f.presence_end.value, weekdays: [...form.querySelectorAll('[name=weekdays]:checked')].map(n => Number(n.value))};
    const controls = [...form.elements].map(n => [n, n.disabled]); controls.forEach(([n]) => n.disabled = true);
    try { const result = await request('/sessions', payload); await loadSessions(); changed(); $('rooms-session-detail').textContent = result.message; }
    catch (e) { error('rooms-session-error', e.message); }
    finally { delete form.dataset.busy; controls.forEach(([n, disabled]) => n.disabled = disabled); }
  });
  $('rooms-prev').addEventListener('click', () => { $('rooms-date').value = add($('rooms-date').value, -7); load(); });
  $('rooms-next').addEventListener('click', () => { $('rooms-date').value = add($('rooms-date').value, 7); load(); });
  $('rooms-date').addEventListener('change', () => load()); $('rooms-today').addEventListener('click', () => { $('rooms-date').value = today(); load(); });
  $('rooms-refresh').addEventListener('click', () => load(true));
  window.addEventListener('academy:rooms-changed', () => load());
  window.addEventListener('focus', () => load());
  document.addEventListener('visibilitychange', () => { if (!document.hidden) load(); });
  $('rooms-date').value = today(); load();
  if (new URLSearchParams(location.search).has('session_id')) $('rooms-session-panel').open = true;
  setInterval(() => { if (!document.hidden) load(); }, 20000);
})();

/* Original files are never overwritten; only normalized crop coordinates persist. */
(() => {
  'use strict';
  const sheet = document.querySelector('.candidate-sheet');
  const opener = document.getElementById('open-photo-crop');
  if (!sheet || !opener) return;
  const $ = id => document.getElementById(id);
  const dialog = $('photo-crop-dialog'), canvas = $('photo-crop-canvas'), context = canvas.getContext('2d');
  const zoom = $('photo-crop-zoom'), save = $('photo-crop-save'), error = $('photo-crop-error');
  const source = new Image(), rotated = document.createElement('canvas');
  const base = '/admin/candidat/' + encodeURIComponent(sheet.dataset.candidateId);
  let rotation = 0, scale = 1, fit = 1, x = 0, y = 0, drag = null, busy = false, loaded = false, hash = '', objectURL = null;
  function report(message) { error.textContent = message; error.hidden = !message; }
  function controls(value) {
    busy = value;
    dialog.querySelectorAll('button,input').forEach(button => { button.disabled = value; });
    save.disabled = value || !loaded;
  }
  function draw() {
    if (!loaded) return;
    x = Math.max(canvas.width - rotated.width * scale, Math.min(0, x));
    y = Math.max(canvas.height - rotated.height * scale, Math.min(0, y));
    context.clearRect(0, 0, canvas.width, canvas.height);
    context.drawImage(rotated, x, y, rotated.width * scale, rotated.height * scale);
    $('photo-crop-zoom-value').textContent = Math.round(Number(zoom.value) * 100) + ' %';
  }
  function center() {
    x = (canvas.width - rotated.width * scale) / 2;
    y = (canvas.height - rotated.height * scale) / 2;
    draw();
  }
  function orient() {
    const swapped = rotation % 180 !== 0;
    rotated.width = swapped ? source.naturalHeight : source.naturalWidth;
    rotated.height = swapped ? source.naturalWidth : source.naturalHeight;
    const ctx = rotated.getContext('2d');
    ctx.translate(rotated.width / 2, rotated.height / 2);
    ctx.rotate(rotation * Math.PI / 180);
    ctx.drawImage(source, -source.naturalWidth / 2, -source.naturalHeight / 2);
    fit = Math.max(canvas.width / rotated.width, canvas.height / rotated.height);
    zoom.value = '1'; scale = fit; center();
  }
  opener.addEventListener('click', async () => {
    dialog.showModal(); loaded = false; report(''); controls(true);
    $('photo-crop-loading').hidden = false;
    try {
      const response = await fetch(base + '/photo?original=1', {credentials:'same-origin', cache:'no-store'});
      if (!response.ok) throw Error('La photo originale ne peut pas être chargée.');
      hash = response.headers.get('X-Photo-Source');
      const saved = JSON.parse(response.headers.get('X-Photo-Crop') || 'null');
      const blob = await response.blob();
      if (objectURL) URL.revokeObjectURL(objectURL);
      objectURL = URL.createObjectURL(blob);
      await new Promise((resolve, reject) => { source.onload = resolve; source.onerror = () => reject(Error('Format de photo non lisible.')); source.src = objectURL; });
      loaded = true; rotation = saved ? saved.rotation : 0; orient();
      if (saved) {
        scale = canvas.width / (saved.width * rotated.width);
        zoom.value = String(scale / fit);
        x = -saved.x * rotated.width * scale;
        y = -saved.y * rotated.height * scale;
        draw();
      }
    } catch (e) { report(e.message); }
    finally { $('photo-crop-loading').hidden = true; controls(false); }
  });
  zoom.addEventListener('input', () => {
    if (!loaded || busy) return;
    const next = fit * Number(zoom.value);
    x = canvas.width / 2 - (canvas.width / 2 - x) * next / scale;
    y = canvas.height / 2 - (canvas.height / 2 - y) * next / scale;
    scale = next; draw();
  });
  $('photo-crop-rotate').addEventListener('click', () => { if (loaded && !busy) { rotation = (rotation + 90) % 360; orient(); } });
  $('photo-crop-center').addEventListener('click', center);
  canvas.addEventListener('pointerdown', event => {
    if (!loaded || busy) return;
    canvas.setPointerCapture(event.pointerId); drag = {x:event.clientX, y:event.clientY}; canvas.focus();
  });
  canvas.addEventListener('pointermove', event => {
    if (!drag || busy) return;
    const bounds = canvas.getBoundingClientRect();
    x += (event.clientX - drag.x) * canvas.width / bounds.width;
    y += (event.clientY - drag.y) * canvas.height / bounds.height;
    drag = {x:event.clientX, y:event.clientY}; draw();
  });
  ['pointerup', 'pointercancel', 'lostpointercapture'].forEach(type => canvas.addEventListener(type, () => { drag = null; }));
  canvas.addEventListener('keydown', event => {
    const offsets = {ArrowLeft:[-10,0], ArrowRight:[10,0], ArrowUp:[0,-10], ArrowDown:[0,10]};
    if (!offsets[event.key] || !loaded || busy) return;
    event.preventDefault(); x += offsets[event.key][0]; y += offsets[event.key][1]; draw();
  });
  async function persist(reset) {
    if (!loaded || busy) return;
    controls(true); report('');
    const data = reset ? {reset:true} : {rotation, x:-x/(scale*rotated.width), y:-y/(scale*rotated.height),
      width:canvas.width/(scale*rotated.width), height:canvas.height/(scale*rotated.height)};
    try {
      const response = await fetch(base + '/photo-crop', {method:'POST',credentials:'same-origin',
        headers:{'Content-Type':'application/json','X-CSRF-Token':sheet.dataset.messageCsrf},body:JSON.stringify({...data, source_hash:hash})});
      const result = await response.json();
      if (!response.ok || !result.ok) throw Error(result.error || 'Impossible d’enregistrer le cadrage.');
      document.querySelectorAll('[data-candidate-photo]').forEach(image => { image.closest('.candidate-portrait')?.classList.remove('photo-unavailable'); image.src = base + '/photo?v=' + Date.now(); });
      dialog.close();
    } catch (e) { report(e.message); }
    finally { controls(false); }
  }
  save.addEventListener('click', () => persist(false));
  $('photo-crop-reset').addEventListener('click', () => persist(true));
  dialog.querySelectorAll('[data-close-photo]').forEach(button => button.addEventListener('click', () => { if (!busy) dialog.close(); }));
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => { drag = null; opener.focus(); if (objectURL) { URL.revokeObjectURL(objectURL); objectURL = null; } });
})();

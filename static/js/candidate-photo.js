/* The preview and server use the same inverse transform; originals are retained. */
(() => {
  'use strict';
  const sheet = document.querySelector('.candidate-sheet');
  const opener = document.getElementById('open-photo-crop');
  if (!sheet || !opener) return;
  const $ = id => document.getElementById(id);
  const dialog = $('photo-crop-dialog'), canvas = $('photo-crop-canvas'), context = canvas.getContext('2d');
  const zoom = $('photo-crop-zoom'), angle = $('photo-crop-angle'), save = $('photo-crop-save'), error = $('photo-crop-error');
  const source = new Image(), base = '/admin/candidat/' + encodeURIComponent(sheet.dataset.candidateId);
  let rotation = 0, scale = 1, fit = 1, cx = 0, cy = 0, drag = null, busy = false, loaded = false, hash = '', objectURL = null;
  const radians = () => (rotation + Number(angle.value)) * Math.PI / 180;
  function report(message) { error.textContent = message; error.hidden = !message; }
  function controls(value) {
    busy = value;
    dialog.querySelectorAll('button,input').forEach(button => { button.disabled = value; });
    save.disabled = value || !loaded;
  }
  function minimumScale() {
    const c = Math.abs(Math.cos(radians())), s = Math.abs(Math.sin(radians()));
    return Math.max((c*canvas.width+s*canvas.height)/source.naturalWidth,
                    (s*canvas.width+c*canvas.height)/source.naturalHeight);
  }
  function draw() {
    if (!loaded) return;
    fit = minimumScale(); scale = Math.max(fit, Math.min(fit*10, scale));
    const c = Math.abs(Math.cos(radians())), s = Math.abs(Math.sin(radians()));
    const halfW = (c*canvas.width+s*canvas.height)/scale/2;
    const halfH = (s*canvas.width+c*canvas.height)/scale/2;
    cx = Math.max(halfW, Math.min(source.naturalWidth-halfW, cx));
    cy = Math.max(halfH, Math.min(source.naturalHeight-halfH, cy));
    context.setTransform(1,0,0,1,0,0); context.clearRect(0,0,canvas.width,canvas.height);
    context.translate(canvas.width/2,canvas.height/2); context.scale(scale,scale); context.rotate(radians());
    context.drawImage(source,-cx,-cy);
    zoom.value = String(scale/fit);
    $('photo-crop-zoom-value').textContent = Math.round(scale/fit*100)+' %';
    $('photo-crop-angle-value').textContent = Number(angle.value).toLocaleString('fr-FR')+'°';
  }
  function center() { if (!loaded || busy) return; cx=source.naturalWidth/2; cy=source.naturalHeight/2; draw(); }
  function zoomTo(value) { if (!loaded || busy) return; scale=fit*Math.max(1,Math.min(10,value)); draw(); }
  function move(dx,dy) {
    const c=Math.cos(radians()),s=Math.sin(radians());
    cx-=(c*dx+s*dy)/scale; cy-=(-s*dx+c*dy)/scale; draw();
  }
  opener.addEventListener('click',async()=>{
    dialog.showModal();loaded=false;report('');controls(true);$('photo-crop-loading').hidden=false;
    try {
      const response=await fetch(base+'/photo?original=1',{credentials:'same-origin',cache:'no-store'});
      if(!response.ok)throw Error('La photo originale ne peut pas être chargée.');
      hash=response.headers.get('X-Photo-Source');
      const saved=JSON.parse(response.headers.get('X-Photo-Crop')||'null'),blob=await response.blob();
      if(objectURL)URL.revokeObjectURL(objectURL);objectURL=URL.createObjectURL(blob);
      await new Promise((resolve,reject)=>{source.onload=resolve;source.onerror=()=>reject(Error('Format de photo non lisible.'));source.src=objectURL;});
      loaded=true;rotation=saved?saved.rotation:0;angle.value=String(saved?.straighten||0);
      cx=source.naturalWidth/2;cy=source.naturalHeight/2;scale=minimumScale();
      if(saved?.version===2){cx=saved.cx*source.naturalWidth;cy=saved.cy*source.naturalHeight;scale=canvas.width/(saved.width*source.naturalWidth);}
      else if(saved){
        const swapped=rotation%180!==0,rw=swapped?source.naturalHeight:source.naturalWidth,rh=swapped?source.naturalWidth:source.naturalHeight;
        const rx=(saved.x+saved.width/2-.5)*rw,ry=(saved.y+saved.height/2-.5)*rh,c=Math.cos(radians()),s=Math.sin(radians());
        cx+=c*rx+s*ry;cy+=-s*rx+c*ry;scale=canvas.width/(saved.width*rw);
      }
      draw();
    }catch(e){report(e.message);}finally{$('photo-crop-loading').hidden=true;controls(false);}
  });
  zoom.addEventListener('input',()=>zoomTo(Number(zoom.value)));
  angle.addEventListener('input',()=>{if(loaded&&!busy)draw();});
  $('photo-crop-zoom-in').addEventListener('click',()=>zoomTo(scale/fit*1.25));
  $('photo-crop-zoom-out').addEventListener('click',()=>zoomTo(scale/fit/1.25));
  $('photo-crop-rotate').addEventListener('click',()=>{if(loaded&&!busy){rotation=(rotation+90)%360;draw();}});
  $('photo-crop-center').addEventListener('click',center);
  canvas.addEventListener('wheel',event=>{if(loaded&&!busy){event.preventDefault();zoomTo(scale/fit*(event.deltaY<0?1.08:1/1.08));}},{passive:false});
  canvas.addEventListener('pointerdown',event=>{if(!loaded||busy)return;canvas.setPointerCapture(event.pointerId);drag={x:event.clientX,y:event.clientY};canvas.focus();});
  canvas.addEventListener('pointermove',event=>{
    if(!drag||busy)return;const bounds=canvas.getBoundingClientRect();
    move((event.clientX-drag.x)*canvas.width/bounds.width,(event.clientY-drag.y)*canvas.height/bounds.height);
    drag={x:event.clientX,y:event.clientY};
  });
  ['pointerup','pointercancel','lostpointercapture'].forEach(type=>canvas.addEventListener(type,()=>{drag=null;}));
  canvas.addEventListener('keydown',event=>{
    const offsets={ArrowLeft:[-10,0],ArrowRight:[10,0],ArrowUp:[0,-10],ArrowDown:[0,10]};
    if(!offsets[event.key]||!loaded||busy)return;event.preventDefault();move(...offsets[event.key]);
  });
  async function persist(reset){
    if(!loaded||busy)return;controls(true);report('');
    const data=reset?{reset:true}:{version:2,rotation,straighten:Number(angle.value),cx:cx/source.naturalWidth,cy:cy/source.naturalHeight,
      width:canvas.width/(scale*source.naturalWidth),height:canvas.height/(scale*source.naturalHeight)};
    try{
      const response=await fetch(base+'/photo-crop',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':sheet.dataset.messageCsrf},body:JSON.stringify({...data,source_hash:hash})});
      const result=await response.json();if(!response.ok||!result.ok)throw Error(result.error||'Impossible d’enregistrer le cadrage.');
      document.querySelectorAll('[data-candidate-photo]').forEach(image=>{image.closest('.candidate-portrait')?.classList.remove('photo-unavailable');image.src=base+'/photo?v='+Date.now();});
      dialog.close();
    }catch(e){report(e.message);}finally{controls(false);}
  }
  save.addEventListener('click',()=>persist(false));$('photo-crop-reset').addEventListener('click',()=>persist(true));
  dialog.querySelectorAll('[data-close-photo]').forEach(button=>button.addEventListener('click',()=>{if(!busy)dialog.close();}));
  dialog.addEventListener('cancel',event=>{if(busy)event.preventDefault();});
  dialog.addEventListener('close',()=>{drag=null;opener.focus();if(objectURL){URL.revokeObjectURL(objectURL);objectURL=null;}});
})();

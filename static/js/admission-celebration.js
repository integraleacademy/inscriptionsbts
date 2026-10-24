(() => {
  'use strict';
  const dialog = document.getElementById('application-success');
  if (!dialog) return;
  const canvas = dialog.querySelector('canvas');
  const next = document.getElementById('celebration-continue');
  const eyebrow = dialog.querySelector('.celebration-eyebrow');
  let preview = false, destination = null, frame = 0;
  function stop() { cancelAnimationFrame(frame); frame = 0; }
  function fireworks() {
    stop();
    if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const width = window.innerWidth, height = window.innerHeight;
    const scale = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = width * scale; canvas.height = height * scale; ctx.scale(scale, scale);
    const colors = ['#e9ca82', '#f5dfad', '#a8bb83', '#e1a28b', '#f8f4d9'];
    const particles = [];
    const bursts = [{t:0,x:.18,y:.28},{t:450,x:.82,y:.22},{t:950,x:.52,y:.12},{t:1500,x:.12,y:.58},{t:2100,x:.89,y:.49}];
    const start = performance.now(); let previous = start;
    function tick(now) {
      const elapsed = now - start, step = Math.min((now - previous) / 16.67, 2); previous = now;
      ctx.clearRect(0, 0, width, height);
      bursts.forEach(b => {
        if (b.fired || elapsed < b.t) return;
        b.fired = true;
        for (let i=0;i<45;i++) {
          const angle = (Math.PI*2*i)/45, speed = 1.1 + Math.random()*2.4;
          particles.push({x:width*b.x,y:height*b.y,vx:Math.cos(angle)*speed,vy:Math.sin(angle)*speed,life:1,size:1+Math.random()*1.7,color:colors[i%colors.length]});
        }
      });
      for (let i=particles.length-1;i>=0;i--) {
        const p=particles[i];p.x+=p.vx*step;p.y+=p.vy*step;p.vy+=.022*step;p.vx*=.992;p.life-=.009*step;
        if(p.life<=0){particles.splice(i,1);continue;}
        ctx.globalAlpha=p.life*.8;ctx.fillStyle=p.color;ctx.beginPath();ctx.arc(p.x,p.y,p.size,0,Math.PI*2);ctx.fill();
      }
      ctx.globalAlpha=1;
      if(elapsed<4600 && dialog.open) frame=requestAnimationFrame(tick); else {ctx.clearRect(0,0,width,height);stop();}
    }
    frame=requestAnimationFrame(tick);
  }
  window.BTSAdmissionCelebration = {
    show(redirect, isPreview = false) {
      preview = isPreview;
      destination = null;
      if (!preview) {
        const url = new URL(redirect, window.location.origin);
        if (url.origin !== window.location.origin || !url.pathname.startsWith('/espace/')) throw new Error('Le lien de suivi du dossier est invalide. Contacte notre équipe.');
        destination = url.href;
      }
      document.body.classList.remove('application-sending');
      eyebrow.textContent = preview ? 'APERÇU · AUCUN DOSSIER ENVOYÉ' : 'CANDIDATURE TRANSMISE';
      next.textContent = preview ? 'Revenir au formulaire' : 'Découvrir mon espace étudiant';
      next.href = destination || '#';
      if (!dialog.open) dialog.showModal();
      document.getElementById('celebration-title').focus({preventScroll:true});
      fireworks();
    }
  };
  next.addEventListener('click', event => { if(preview){event.preventDefault();stop();dialog.close();document.getElementById('preview-success')?.focus();} });
  dialog.addEventListener('cancel', event => {if(!preview){event.preventDefault();if(destination)window.location.assign(destination);}});
  dialog.addEventListener('close', stop);
  document.getElementById('preview-success')?.addEventListener('click', () => window.BTSAdmissionCelebration.show(null, true));
})();

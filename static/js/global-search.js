(() => {
  const root=document.querySelector('[data-global-search]');if(!root)return;
  const input=root.querySelector('input'),panel=root.querySelector('.global-search-results'),items=panel.querySelector('[data-search-items]'),status=panel.querySelector('[data-search-status]');let timer,sequence=0;
  const close=()=>{panel.hidden=true;input.setAttribute('aria-expanded','false');sequence++};
  async function search(){const current=++sequence;panel.hidden=false;input.setAttribute('aria-expanded','true');status.textContent='Recherche…';
    try{const response=await fetch('/admin/recherche?q='+encodeURIComponent(input.value),{cache:'no-store'});if(!response.ok)throw Error();const answer=await response.json();if(current!==sequence)return;items.replaceChildren();
      answer.results.forEach(r=>{const a=document.createElement('a');a.href=r.url;const title=document.createElement('strong');title.textContent=r.label;const detail=document.createElement('small');detail.textContent=r.detail;const badgeKind=document.createElement('span');badgeKind.className='search-kind';badgeKind.dataset.kind=r.kind;badgeKind.textContent=r.kind.toLocaleUpperCase('fr-FR');const heading=document.createElement('span');heading.className='search-result-heading';heading.append(title,badgeKind);a.append(heading,detail);if(r.kind==='Étudiant'){const badge=document.createElement('span');badge.className='study-badge mode-'+(['presentiel','distanciel'].includes(r.mode)?r.mode:'unknown');badge.textContent=r.mode==='presentiel'?'En présentiel':r.mode==='distanciel'?'En distanciel':'Modalité à préciser';a.append(badge)}items.append(a)});status.textContent=answer.results.length?answer.results.length+' résultat(s)':'Aucun résultat';
    }catch(e){if(current===sequence){items.replaceChildren();status.textContent='Recherche indisponible. Rechargez la page.'}}
  }
  input.addEventListener('input',()=>{clearTimeout(timer);sequence++;timer=setTimeout(search,180)});input.addEventListener('focus',search);
  root.addEventListener('keydown',e=>{const links=[...items.querySelectorAll('a')];if(e.key==='Escape'){close();input.focus();close()}if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();const at=links.indexOf(document.activeElement),next=e.key==='ArrowDown'?at+1:at-1;(links[(next+links.length)%links.length]||input).focus()}});
  document.addEventListener('pointerdown',e=>{if(!root.contains(e.target))close()});document.addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();input.focus()}});
})();

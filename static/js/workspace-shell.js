(() => {
  const button=document.querySelector('.workspace-topbar .menu-toggle');if(!button)return;
  const scrim=document.querySelector('.sidebar-scrim'),mobile=matchMedia('(max-width: 960px)');
  let collapsed=false;try{collapsed=localStorage.getItem('bts-sidebar-collapsed')==='1';}catch{}
  function apply(){
    document.body.classList.toggle('sidebar-collapsed',collapsed&&!mobile.matches);
    const open=mobile.matches?document.body.classList.contains('sidebar-open'):!collapsed;
    button.setAttribute('aria-expanded',String(open));button.setAttribute('aria-label',open?'Réduire le menu':'Développer le menu');button.title=button.getAttribute('aria-label');scrim.hidden=!mobile.matches||!open;
  }
  button.addEventListener('click',()=>{if(mobile.matches)document.body.classList.toggle('sidebar-open');else{collapsed=!collapsed;try{localStorage.setItem('bts-sidebar-collapsed',collapsed?'1':'0');}catch{}}apply();});
  scrim.addEventListener('click',()=>{document.body.classList.remove('sidebar-open');apply();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){document.body.classList.remove('sidebar-open');apply();}});
  mobile.addEventListener('change',apply);apply();
})();

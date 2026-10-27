(() => {
  const header=document.querySelector('.workspace-topbar'),button=header?.querySelector('.menu-toggle');if(!button)return;
  const sidebar=document.getElementById('workspace-sidebar'),scrim=document.querySelector('.sidebar-scrim'),mobile=matchMedia('(max-width: 960px)');
  const tooltip=document.createElement('div');tooltip.id='workspace-nav-tooltip';tooltip.className='workspace-nav-tooltip';tooltip.setAttribute('role','tooltip');tooltip.hidden=true;document.body.append(tooltip);
  let tooltipLink=null;
  function hideTooltip(){tooltip.hidden=true;tooltipLink?.removeAttribute('aria-describedby');tooltipLink=null;}
  function showTooltip(link){
    hideTooltip();if(!collapsed||mobile.matches)return;
    const rect=link.getBoundingClientRect();tooltip.textContent=link.dataset.navLabel;tooltip.hidden=false;
    tooltip.style.left=(rect.right+12)+'px';tooltip.style.top=Math.max(8,Math.min(innerHeight-tooltip.offsetHeight-8,rect.top+(rect.height-tooltip.offsetHeight)/2))+'px';
    link.setAttribute('aria-describedby',tooltip.id);tooltipLink=link;
  }
  sidebar.querySelectorAll('a[title],a[aria-label]').forEach(link=>{
    link.dataset.navLabel=link.getAttribute('aria-label')||link.title;link.setAttribute('aria-label',link.dataset.navLabel);link.removeAttribute('title');
    link.addEventListener('pointerenter',()=>showTooltip(link));link.addEventListener('pointerleave',hideTooltip);
    link.addEventListener('focus',()=>showTooltip(link));link.addEventListener('blur',hideTooltip);link.addEventListener('click',hideTooltip);
  });
  let collapsed=false;try{collapsed=localStorage.getItem('bts-sidebar-collapsed')==='1';}catch{}
  function apply(){
    hideTooltip();
    document.body.classList.toggle('sidebar-collapsed',collapsed&&!mobile.matches);
    const open=mobile.matches?document.body.classList.contains('sidebar-open'):!collapsed;
    button.setAttribute('aria-expanded',String(open));button.setAttribute('aria-label',open?'Réduire le menu':'Développer le menu');button.title=button.getAttribute('aria-label');scrim.hidden=!mobile.matches||!open;
  }
  button.addEventListener('click',()=>{if(mobile.matches)document.body.classList.toggle('sidebar-open');else{collapsed=!collapsed;try{localStorage.setItem('bts-sidebar-collapsed',collapsed?'1':'0');}catch{}}apply();});
  scrim.addEventListener('click',()=>{document.body.classList.remove('sidebar-open');apply();});
  document.addEventListener('keydown',e=>{if(e.key==='Escape'){const wasOpen=document.body.classList.contains('sidebar-open');document.body.classList.remove('sidebar-open');apply();if(wasOpen)button.focus();}});
  document.addEventListener('scroll',hideTooltip,true);window.addEventListener('resize',hideTooltip);
  mobile.addEventListener('change',()=>{document.body.classList.remove('sidebar-open');apply();});
  new ResizeObserver(()=>document.body.style.setProperty('--workspace-header-height',header.offsetHeight+'px')).observe(header);
  apply();
})();

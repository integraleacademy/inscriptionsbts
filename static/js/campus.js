(() => {
  const root=document.querySelector('[data-enrollments]'); if(!root)return;
  const checks=[...root.querySelectorAll('[data-select-student]')], all=root.querySelector('[data-select-all]'), bulk=root.querySelector('[data-assign-bulk]'), target=document.getElementById('bulk-promotion'), feedback=root.querySelector('[data-enrollment-feedback]');
  let busy=false;
  function selected(){return checks.filter(c=>c.checked)}
  function sync(){
    const chosen=selected(), groups=new Set(chosen.map(c=>c.closest('tr').dataset.bts+'|'+c.closest('tr').dataset.year));
    root.querySelector('[data-selected-count]').textContent=chosen.length+' étudiant'+(chosen.length>1?'s':'')+' sélectionné'+(chosen.length>1?'s':'');
    all.checked=!!checks.length&&chosen.length===checks.length;all.indeterminate=!!chosen.length&&!all.checked;
    [...target.options].forEach(o=>{o.disabled=!!o.value&&groups.size>0&&(groups.size>1||!groups.has(o.dataset.bts+'|'+o.dataset.year));});
    if(target.selectedOptions[0]?.disabled)target.value='';
    bulk.disabled=busy||!chosen.length||groups.size!==1||!target.value;
  }
  checks.forEach(c=>c.addEventListener('change',sync));target.addEventListener('change',sync);all.addEventListener('change',()=>{checks.forEach(c=>c.checked=all.checked);sync()});
  async function assign(ids,promotion){
    if(busy)return;
    feedback.hidden=false;
    if(!promotion){feedback.textContent='Choisissez une promotion.';return}
    busy=true;root.querySelectorAll('button,input,select').forEach(n=>n.disabled=true);feedback.textContent='Affectation en cours…';
    try{
      const r=await fetch('/admin/inscriptions/affecter',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':root.dataset.csrf},body:JSON.stringify({ids,promotion_id:promotion})});
      const answer=await r.json();if(!r.ok||!answer.ok)throw Error(answer.error||'Impossible d’enregistrer. Rechargez la page.');
      location.reload();
    }catch(e){feedback.textContent=e.message;busy=false;root.querySelectorAll('button,input,select').forEach(n=>n.disabled=false);sync()}
  }
  bulk.addEventListener('click',()=>assign(selected().map(c=>c.value),target.value));root.querySelectorAll('[data-assign-one]').forEach(b=>b.addEventListener('click',()=>{const r=b.closest('tr');assign([r.dataset.enrollmentId],r.querySelector('select').value)}));sync();
})();

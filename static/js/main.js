document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.tabs button').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.tabs button').forEach(b=>b.classList.remove('active'));
      document.querySelectorAll('.tab').forEach(t=>t.classList.remove('active'));
      btn.classList.add('active');
      document.getElementById(btn.dataset.tab).classList.add('active');
    });
  });
  const email = document.querySelector('input[name="email"]');
  const email2 = document.querySelector('input[name="email_confirm"]');
  if (email && email2){
    const check = () => {
      if (email.value && email2.value && email.value !== email2.value){
        email2.setCustomValidity("Les adresses e‑mail ne correspondent pas.");
      } else {
        email2.setCustomValidity("");
      }
    }
    email.addEventListener('input', check);
    email2.addEventListener('input', check);
  }
  const birth = document.querySelector('input[name="date_naissance"]');
  const minor = document.getElementById('minorFields');
  const updateMinor = () => {
    if (!birth || !birth.value) { minor.style.display = 'none'; return; }
    const d = new Date(birth.value);
    const today = new Date();
    let age = today.getFullYear() - d.getFullYear();
    const m = today.getMonth() - d.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < d.getDate())) age--;
    minor.style.display = (age < 18) ? 'block' : 'none';
    document.querySelector('input[name="est_mineur"]').value = (age < 18) ? '1' : '0';
  };
  if (birth){ birth.addEventListener('change', updateMinor); }
  const btsSelect = document.querySelector('select[name="bts"]');
  const mosBlock = document.getElementById('mosBlock');
  const mosAucun = document.getElementById('mosAucun');
  const updateMOS = () => { mosBlock.style.display = (btsSelect && btsSelect.value === 'MOS') ? 'block' : 'none'; };
  if (btsSelect){
    btsSelect.addEventListener('change', updateMOS);
    updateMOS();
  }
  document.querySelectorAll('input[name="mos_parcours"]').forEach(r => {
    r.addEventListener('change', () => {
      mosAucun.style.display = (r.value === 'aucun' && r.checked) ? 'block' : 'none';
    });
  });
  const table = document.querySelector('.admin-table');
  if (table){
    table.querySelectorAll('td[contenteditable="true"]').forEach(td => {
      td.addEventListener('blur', async () => {
        const tr = td.closest('tr'); const id = tr.dataset.id;
        const field = td.dataset.field; const value = td.textContent.trim();
        await fetch('/admin/update-field', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id, field, value}) });
      });
    });
    table.querySelectorAll('.status-select').forEach(sel => {
      sel.addEventListener('change', async () => {
        const tr = sel.closest('tr'); const id = tr.dataset.id; const value = sel.value;
        await fetch('/admin/update-status', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id, value}) });
      });
    });
    table.querySelectorAll('input.chk').forEach(chk => {
      chk.addEventListener('change', async () => {
        const tr = chk.closest('tr'); const id = tr.dataset.id;
        const field = chk.dataset.field; const value = chk.checked ? 1 : 0;
        await fetch('/admin/update-field', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id, field, value}) });
      });
    });
  }
});
let currentRowId = null;
function openActionsModal(id){
  currentRowId = id;
  const modal = document.getElementById('actionsModal');
  modal.classList.remove('hidden');
  document.getElementById('printLink').setAttribute('href','/admin/print/'+id);
  document.getElementById('reconfirmBtn').onclick = async () => {
    await fetch('/admin/reconfirm/'+id, {method:'POST'});
    alert('Reconfirmation envoyée et statut mis à jour.');
  };
  document.getElementById('deleteBtn').onclick = async () => {
    if (!confirm('Confirmer la suppression ?')) return;
    await fetch('/admin/delete/'+id, {method:'POST'});
    location.reload();
  };
  document.getElementById('saveCommentBtn').onclick = async () => {
    const value = document.getElementById('commentBox').value;
    await fetch('/admin/update-field', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({id: currentRowId, field:'commentaires', value}) });
    alert('Commentaire enregistré.');
  };
}
function closeActionsModal(){ document.getElementById('actionsModal').classList.add('hidden'); }

document.querySelectorAll(".tabs button").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tabs button").forEach(b => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach(tab => tab.classList.remove("active"));
    btn.classList.add("active");
    document.getElementById(btn.dataset.tab).classList.add("active");
  });
});


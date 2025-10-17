window.currentId = null;

// === Gestion fluide + verrouillage + icônes visuelles des onglets ===
document.addEventListener("DOMContentLoaded", () => {
  const tabButtons = document.querySelectorAll('.tabs button');
  const tabs = document.querySelectorAll('.tab');
  let currentStep = 0;

  // === 🔢 Barre de progression ===
  function updateProgressBar(index) {
    const progress = document.getElementById("progressBar");
    const info = document.getElementById("progressInfo");
    if (!progress || !info) return;
    const total = tabs.length;
    const targetPercent = ((index + 1) / total) * 100;
    progress.style.width = targetPercent + "%";
    info.textContent = `Étape ${index + 1} sur ${total} — ${Math.round(targetPercent)} % complété`;
  }

  function showStep(index) {
    tabs.forEach((tab, i) => {
      tab.style.display = (i === index) ? 'block' : 'none';
      tab.classList.toggle('active', i === index);
    });
    tabButtons.forEach((btn, i) => {
      btn.classList.toggle('active', i === index);
    });
    currentStep = index;
    updateProgressBar(index);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }
  showStep(0);

  // === Gestion du tableau admin ===
  const table = document.querySelector('.admin-table');
  if (table) {
    table.querySelectorAll('td[contenteditable="true"]').forEach(td => {
      td.addEventListener('blur', async () => {
        const tr = td.closest('tr');
        const id = tr.dataset.id;
        const field = td.dataset.field;
        const value = td.textContent.trim();
        await fetch('/admin/update-field', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id, field, value })
        });
      });
    });

    table.querySelectorAll('.status-select').forEach(sel => {
      sel.addEventListener('change', async () => {
        const tr = sel.closest('tr');
        const id = tr.dataset.id;
        const value = sel.value;
        await fetch('/admin/update-status', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id, value })
        });
      });
    });

    table.querySelectorAll('input.chk').forEach(chk => {
      chk.addEventListener('change', async () => {
        const tr = chk.closest('tr');
        const id = tr.dataset.id;
        const field = chk.dataset.field;
        const value = chk.checked ? 1 : 0;
        await fetch('/admin/update-field', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ id, field, value })
        });
      });
    });
  }

  // === 📎 Gestion des pièces justificatives (modale admin) ===
  const filesModal = document.getElementById("filesModal");
  if (filesModal) {
    const downloadAllBtn = document.getElementById("downloadAllBtn");
    if (downloadAllBtn) {
      downloadAllBtn.addEventListener("click", () => {
        if (!window.currentId) return;
        window.open(`/admin/files/download/${window.currentId}`, "_blank");
      });
    }

    // ✅ / ❌ Marquer une pièce conforme ou non conforme
    filesModal.addEventListener("click", async (e) => {
      const btn = e.target.closest(".btn.small");
      if (!btn) return;
      const decision = btn.textContent.includes("Conforme") ? "conforme" : "non_conforme";
      const filename = btn.dataset.filename;
      if (!window.currentId || !filename) return;

      btn.textContent = "⏳...";
      btn.disabled = true;

      const res = await fetch("/admin/files/mark", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: window.currentId, filename, decision })
      });

      const data = await res.json();
      if (data.ok) {
        showToast(
          decision === "conforme" ? "✅ Document conforme" : "❌ Document non conforme",
          decision === "conforme" ? "#28a745" : "#d9534f"
        );

        await refreshCandidateStatus(window.currentId);
        setTimeout(() => openFilesModal(window.currentId), 600);
      } else {
        alert("Erreur : " + (data.error || "inconnue"));
        btn.disabled = false;
        btn.textContent = decision === "conforme" ? "✅ Conforme" : "❌ Non conforme";
      }
    });
  }

  // === 📥 Badge "nouveau document" ===
  document.querySelectorAll("tr[data-id]").forEach(tr => {
    if (tr.dataset.nouveau === "1") {
      const badge = document.createElement("span");
      badge.textContent = "📥 Nouveau document déposé";
      badge.style.color = "#28a745";
      badge.style.fontWeight = "600";
      badge.style.marginLeft = "8px";
      tr.querySelector("td:last-child").appendChild(badge);
    }
  });
}); // ← cette accolade ferme bien le DOMContentLoaded maintenant ✅


// === Toast notification ===
function showToast(msg, color="#333") {
  const t=document.createElement("div");
  t.textContent=msg;
  Object.assign(t.style,{
    position:"fixed",bottom:"20px",right:"20px",background:color,color:"#fff",
    padding:"10px 16px",borderRadius:"8px",fontWeight:"600",boxShadow:"0 3px 8px rgba(0,0,0,.3)",
    zIndex:"9999",opacity:"0",transition:"opacity .3s"
  });
  document.body.appendChild(t);
  setTimeout(()=>t.style.opacity="1",50);
  setTimeout(()=>{t.style.opacity="0";setTimeout(()=>t.remove(),300)},2500);
}

// === Rafraîchit le statut du dossier ===
async function refreshCandidateStatus(id) {
  const row = document.querySelector(`tr[data-id='${id}']`);
  if (!row) return;
  const res = await fetch(`/admin/status/${id}`);
  const data = await res.json();
  if (data.ok && data.statut) {
    const select = row.querySelector(".status-select");
    if (select) {
      select.value = data.statut;
      select.style.background = "black";
      select.style.color = "white";
    }
  }
}

// === Ouvre la modale des pièces justificatives ===
function openFilesModal(id) {
  window.currentId = id;
  const modal = document.getElementById("filesModal");
  const list = document.getElementById("filesList");
  if (!modal || !list) return;
  modal.classList.remove("hidden");
  list.innerHTML = "<p>⏳ Chargement des pièces...</p>";

  fetch(`/admin/files/mark_seen/${id}`, { method: "POST" });
  fetch(`/admin/files/${id}`)
    .then(res => res.json())
    .then(files => {
      if (!files.length) {
        list.innerHTML = "<p>Aucune pièce justificative trouvée.</p>";
        return;
      }
      list.innerHTML = "";
      files.forEach(f => {
        const div = document.createElement("div");
        div.className = "file-item";
        div.innerHTML = `
          <div class="file-header">
            <strong>${f.label}</strong><br>
            <a href="/uploads/${encodeURIComponent(f.filename)}" target="_blank" rel="noopener noreferrer">${f.filename}</a>
          </div>
          <div class="file-actions">
            <button class="btn small ok" data-filename="${f.filename}" ${f.status === "conforme" ? "disabled" : ""}>✅ Conforme</button>
            <button class="btn small danger" data-filename="${f.filename}" ${f.status === "non_conforme" ? "disabled" : ""}>❌ Non conforme</button>
          </div>
        `;
        list.appendChild(div);
      });
    })
    .catch(err => {
      list.innerHTML = "<p style='color:red'>Erreur de chargement</p>";
      console.error(err);
    });
}

// === Ferme la modale des pièces justificatives ===
function closeFilesModal() {
  const modal = document.getElementById("filesModal");
  if (modal) modal.classList.add("hidden");
}

// === Ouvre / Ferme la modale des actions ===
function openActionsModal(id, commentaire = "") {
  window.currentId = id;
  const modal = document.getElementById("actionsModal");
  if (!modal) return;
  modal.classList.remove("hidden");

  const commentBox = document.getElementById("commentBox");
  if (commentBox) commentBox.value = commentaire;

  document.getElementById("printLink").onclick = () => window.open(`/admin/print/${id}`, "_blank");
  document.getElementById("deleteBtn").onclick = async () => {
    if (confirm("Supprimer définitivement cette fiche ?")) {
      await fetch(`/admin/delete/${id}`, { method: "POST" });
      showToast("🗑️ Fiche supprimée");
      setTimeout(() => location.reload(), 600);
    }
  };
  document.getElementById("saveCommentBtn").onclick = async () => {
    const value = commentBox.value.trim();
    await fetch("/admin/update-field", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id, field: "commentaires", value })
    });
    showToast("💾 Commentaire enregistré");
    closeActionsModal();
  };
}

function closeActionsModal() {
  const modal = document.getElementById("actionsModal");
  if (modal) modal.classList.add("hidden");
}

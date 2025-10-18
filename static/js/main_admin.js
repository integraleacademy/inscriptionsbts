// === Intégrale Academy – JS ADMIN SEUL ===
window.currentId = null;

document.addEventListener("DOMContentLoaded", () => {

  // =====================================================
  // 🧾 SECTION ADMIN
  // =====================================================
  const table = document.querySelector('.admin-table');
  if (table) {

    // 🔤 Modification champs inline
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
        showToast("💾 Sauvegardé", "#28a745");
      });
    });

    // 🔄 Changement de statut
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
        showToast("📊 Statut mis à jour", "#007bff");
      });
    });

    // ✅ Cases à cocher (labels)
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
        showToast("🔖 Étiquette mise à jour");
      });
    });

    // 🟢 Boutons d’action
    table.querySelectorAll('.action-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        const commentaire = btn.dataset.commentaire || "";
        openActionsModal(id, commentaire);
      });
    });

    // 📎 Boutons pièces justificatives
    table.querySelectorAll('.files-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        openFilesModal(id);
      });
    });
  } // ✅ FIN if(table)


  // =====================================================
  // 📁 MODALE DES PIÈCES JUSTIFICATIVES
  // =====================================================
  const filesModal = document.getElementById("filesModal");
  if (filesModal) {

    const downloadAllBtn = document.getElementById("downloadAllBtn");
    if (downloadAllBtn) {
      downloadAllBtn.addEventListener("click", () => {
        if (!window.currentId) return;
        window.open(`/admin/files/download/${window.currentId}`, "_blank");
      });
    }

    // 📨 Bouton "Enregistrer et notifier le candidat"
    const notifyBtn = document.getElementById("notifyNonConformesBtn");
    if (notifyBtn) {
      notifyBtn.addEventListener("click", async () => {
        if (!window.currentId) return;
        const commentaire = document.getElementById("commentaireNonConforme").value.trim();

        notifyBtn.disabled = true;
        notifyBtn.textContent = "⏳ Envoi en cours...";

        try {
          const res = await fetch("/admin/files/notify", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id: window.currentId, commentaire })
          });

          const data = await res.json();
          if (data.ok) {
            showToast("📩 Notification envoyée au candidat", "#007bff");
            setTimeout(() => closeFilesModal(), 1000);
          } else {
            alert("Erreur : " + (data.error || "notification impossible"));
          }
        } catch (err) {
          alert("Erreur réseau : " + err);
        } finally {
          notifyBtn.disabled = false;
          notifyBtn.textContent = "📩 Enregistrer et notifier le candidat";
        }
      });
    }

    // ✅ / ❌ Marquer une pièce conforme ou non conforme
    filesModal.addEventListener("click", async (e) => {
      const btn = e.target.closest(".btn.small");
      if (!btn) return;

      const decision = btn.textContent.includes("Conforme") ? "conforme" : "non_conforme";
      const filename = btn.dataset.filename;

      if (!window.currentId) {
        const tr = btn.closest("tr[data-id]");
        if (tr) window.currentId = tr.dataset.id;
      }

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

        // ✅ MAJ immédiate de la liste des pièces non conformes
        if (decision === "non_conforme") {
          const nonList = document.getElementById("nonConformesList");
          if (nonList) {
            const item = document.createElement("li");
            item.textContent = filename + " (" + new Date().toLocaleString() + ")";
            nonList.appendChild(item);
            const first = nonList.querySelector("li");
            if (first && first.textContent.includes("Aucune")) first.remove();
          }
        }

        await refreshCandidateStatus(window.currentId);


      } else {
        alert("Erreur : " + (data.error || "inconnue"));
        btn.disabled = false;
      }
    });


  } // ✅ FIN if(filesModal)

}); // ✅ FIN DOMContentLoaded



// =====================================================
// 🔔 FONCTIONS GLOBALES (utilisées par admin)
// =====================================================

function showToast(msg, color = "#333") {
  const t = document.createElement("div");
  t.textContent = msg;
  Object.assign(t.style, {
    position: "fixed", bottom: "20px", right: "20px", background: color,
    color: "#fff", padding: "10px 16px", borderRadius: "8px",
    fontWeight: "600", boxShadow: "0 3px 8px rgba(0,0,0,.3)",
    zIndex: "9999", opacity: "0", transition: "opacity .3s"
  });
  document.body.appendChild(t);
  setTimeout(() => t.style.opacity = "1", 50);
  setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 300); }, 2500);
}

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

function openFilesModal(id) {
  window.currentId = id;
  const modal = document.getElementById("filesModal");
  const list = document.getElementById("filesList");
  const nonList = document.getElementById("nonConformesList");
  if (!modal || !list) return;
  modal.classList.remove("hidden");
  list.innerHTML = "<p>⏳ Chargement des pièces...</p>";
  nonList.innerHTML = "<li>Aucune pièce non conforme</li>";

  fetch(`/admin/files/${id}`)
    .then(res => res.json())
    .then(files => {
      if (!files.length) {
        list.innerHTML = "<p>Aucune pièce justificative trouvée.</p>";
        return;
      }

      list.innerHTML = "";
      const nonConformes = [];
      let nouveauBlocAjoute = false; // ✅ évite le double affichage du bloc “Nouveau document déposé”

      files.forEach(f => {
        // 🆕 Si c’est un nouveau document déposé → bloc spécifique en haut une seule fois
        if (f.type === "nouveau") {
          if (!nouveauBlocAjoute) {
            const bloc = document.createElement("div");
            bloc.className = "file-item special";
            bloc.innerHTML = `
              <div class="file-header" style="background:#e8ffe8;border:1px solid #28a745;padding:8px;border-radius:6px;">
                <strong>${f.label}</strong><br>
                <a href="/uploads/${encodeURIComponent(f.filename)}" target="_blank">${f.filename}</a>
                <p style="margin:4px 0 0;color:#28a745;"><em>Déposé le ${f.horodatage}</em></p>
              </div>
            `;
            list.prepend(bloc);
            nouveauBlocAjoute = true;
          }
          return; // on ne traite pas les boutons conforme/non conforme ici
        }

        // 📎 Documents classiques
        const div = document.createElement("div");
        div.className = "file-item";
        div.innerHTML = `
          <div class="file-header">
            <strong>${f.label}</strong><br>
            <a href="/uploads/${encodeURIComponent(f.filename)}" target="_blank">${f.filename}</a>
            ${f.status === "non_conforme" ? `<p style="color:#d9534f;margin:4px 0 0;"><em>Non conforme le ${f.horodatage}</em></p>` : ""}
          </div>
          <div class="file-actions">
            <button class="btn small ok" data-filename="${f.filename}" ${f.status==="conforme"?"disabled":""}>✅ Conforme</button>
            <button class="btn small danger" data-filename="${f.filename}" ${f.status==="non_conforme"?"disabled":""}>❌ Non conforme</button>
          </div>
        `;
        list.appendChild(div);

        if (f.status === "non_conforme") {
          nonConformes.push(`${f.filename} (${f.horodatage})`);
        }
      });

      if (nonConformes.length) {
        nonList.innerHTML = nonConformes.map(n => `<li>${n}</li>`).join("");
      }
    })
    .catch(err => {
      list.innerHTML = "<p style='color:red'>Erreur de chargement des pièces.</p>";
      console.error(err);
    });

  // ✅ Réinitialise le flag "nouveau_doc" après consultation
  fetch(`/admin/update-field`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, field: "nouveau_doc", value: 0 })
  });

  // ✅ Supprime le badge “Nouveau document déposé” dans la table dès ouverture
  const tr = document.querySelector(`tr[data-id='${id}']`);
  if (tr) {
    const badge = tr.querySelector("span");
    if (badge && badge.textContent.includes("Nouveau document déposé")) {
      badge.remove();
    }
  }
}

function openActionsModal(id, commentaire = "") {
  window.currentId = id;
  const modal = document.getElementById("actionsModal");
  const commentBox = document.getElementById("commentBox");
  const saveBtn = document.getElementById("saveCommentBtn");
  const printLink = document.getElementById("printLink");
  const reconfirmBtn = document.getElementById("reconfirmBtn");
  const deleteBtn = document.getElementById("deleteBtn");
  const openFilesBtn = document.getElementById("openFilesFromActions");

  if (openFilesBtn) {
    openFilesBtn.onclick = () => {
      closeActionsModal();
      openFilesModal(id);
    };
  }

  if (!modal) return;
  modal.classList.remove("hidden");
  if (commentBox) commentBox.value = commentaire || "";

  if (printLink) {
    printLink.onclick = () => window.open(`/admin/print/${id}`, "_blank");
  }

  if (reconfirmBtn) {
    reconfirmBtn.onclick = async () => {
      if (!confirm("Confirmer l’envoi du mail de reconfirmation ?")) return;
      const res = await fetch(`/admin/reconfirm/${id}`, { method: "POST" });
      if (res.ok) showToast("📧 Mail de reconfirmation envoyé", "#007bff");
      closeActionsModal();
    };
  }

  if (deleteBtn) {
    deleteBtn.onclick = async () => {
      if (!confirm("⚠️ Supprimer définitivement cette fiche ?")) return;
      const res = await fetch(`/admin/delete/${id}`, { method: "POST" });
      if (res.ok) {
        showToast("🗑️ Fiche supprimée", "#d9534f");
        document.querySelector(`tr[data-id='${id}']`)?.remove();
      }
      closeActionsModal();
    };
  }

  if (saveBtn) {
    saveBtn.onclick = async () => {
      const value = commentBox.value.trim();
      await fetch("/admin/update-field", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, field: "commentaires", value })
      });
      showToast("💬 Commentaire sauvegardé", "#28a745");
      closeActionsModal();
    };
  }
}



function closeActionsModal() {
  const modal = document.getElementById("actionsModal");
  if (modal) modal.classList.add("hidden");
}

window.openFilesModal = openFilesModal;
window.openActionsModal = openActionsModal;





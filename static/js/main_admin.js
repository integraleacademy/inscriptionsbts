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

// 🔄 Changement de statut + mise à jour couleur + enregistrement date
table.querySelectorAll('.status-select').forEach(sel => {
  sel.addEventListener('change', async () => {
    const tr = sel.closest('tr');
    const id = tr.dataset.id;
    const value = sel.value;

    // 🟢 Couleur immédiate
    updateStatusColor(sel);

    // 💾 Envoi du nouveau statut
    const res = await fetch('/admin/update-status', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ id, value })
    });

    // ✅ Si changement validé, enregistre aussi la date correspondante
    if (res.ok) {
      let field = null;
      if (value === "validee") field = "date_validee";
      else if (value === "confirmee") field = "date_confirmee";
      else if (value === "reconfirmee") field = "date_reconfirmee";

      if (field) {
        await fetch('/admin/update-field', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            id,
            field,
            value: new Date().toISOString()
          })
        });
        console.log(`🕓 Date enregistrée pour ${field}`);
      }
    }

    showToast("📊 Statut mis à jour", "#007bff");
    tr.classList.add("status-updated");
    setTimeout(() => tr.classList.remove("status-updated"), 1500);
  });
});


    // ✅ Cases à cocher (étiquettes)
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

    // ⚙️ Boutons ACTIONS
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
  // 🎨 Appliquer la bonne couleur au select selon son statut
  // =====================================================
  function updateStatusColor(sel) {
    const val = sel.value;
    const root = getComputedStyle(document.documentElement);
    let color = root.getPropertyValue(`--${val}`).trim();
    if (!color) color = "#7d7d7d"; // gris par défaut
    sel.style.background = color;
    sel.style.color = (val === "confirmee") ? "#111" : "#fff";
  }

  window.updateStatusColor = updateStatusColor;


  // ✅ Initialisation des couleurs au chargement
  document.querySelectorAll('.status-select').forEach(sel => updateStatusColor(sel));

  // ✅ Ré-application de sécurité après 200ms
  setTimeout(() => {
    document.querySelectorAll('.status-select').forEach(sel => updateStatusColor(sel));
  }, 200);



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

  // 🔄 Met à jour immédiatement le statut dans le tableau admin
  const tr = document.querySelector(`tr[data-id='${window.currentId}']`);
  if (tr) {
    const select = tr.querySelector(".status-select");
    if (select) {
      select.value = "docs_non_conformes";
      updateStatusColor(select);
    }
  }

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

    // ✅ Bouton "Nouveau document contrôlé"
const markDocsCheckedBtn = document.getElementById("markDocsCheckedBtn");
if (markDocsCheckedBtn) {
  markDocsCheckedBtn.addEventListener("click", async () => {
    if (!window.currentId) return;
    markDocsCheckedBtn.disabled = true;
    markDocsCheckedBtn.textContent = "⏳ Mise à jour...";
    try {
      await fetch("/admin/update-field", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: window.currentId, field: "nouveau_doc", value: 0 })
      });
      // ✅ Enlève le badge côté interface
      const tr = document.querySelector(`tr[data-id='${window.currentId}']`);
      if (tr) {
  const badge = tr.querySelector("span");
  if (badge && badge.textContent.includes("Nouveau document déposé")) {
    badge.style.transition = "opacity 0.5s ease";
    badge.style.opacity = "0.3";
    badge.style.color = "#999";
    setTimeout(() => badge.remove(), 500);
  }
  markDocsCheckedBtn.style.background = "#28a745";
  markDocsCheckedBtn.style.color = "#fff";
  setTimeout(() => {
    markDocsCheckedBtn.style.background = "";
    markDocsCheckedBtn.style.color = "";
  }, 1500);
}

      showToast("✅ Document marqué comme contrôlé", "#28a745");
    } catch (err) {
      alert("Erreur : " + err);
    } finally {
      markDocsCheckedBtn.disabled = false;
      markDocsCheckedBtn.textContent = "✅ Nouveau document contrôlé";
    }
  });
}

    // 💾 Bouton "Enregistrer les nouveaux documents"
const mergeDocsBtn = document.getElementById("mergeDocsBtn");
if (mergeDocsBtn) {
  mergeDocsBtn.addEventListener("click", async () => {
    if (!window.currentId) return;
    mergeDocsBtn.disabled = true;
    mergeDocsBtn.textContent = "⏳ Enregistrement...";
    try {
      const res = await fetch("/admin/files/merge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: window.currentId })
      });
      const data = await res.json();
      if (data.ok) {
        showToast("💾 Nouveaux documents enregistrés", "#28a745");
        setTimeout(() => location.reload(), 800);
      } else {
        alert("Erreur : " + (data.error || "enregistrement impossible"));
      }
    } catch (err) {
      alert("Erreur réseau : " + err);
    } finally {
      mergeDocsBtn.disabled = false;
      mergeDocsBtn.textContent = "💾 Enregistrer les nouveaux documents";
    }
  });
}



// ✅ / ❌ Marquer une pièce conforme ou non conforme
filesModal.addEventListener("click", async (e) => {
  const btn = e.target.closest(".btn.small");
  if (!btn) return;

  const decision = btn.textContent.includes("Conforme") ? "conforme" : "non_conforme";
  const filename = btn.dataset.filename;
  const fileItem = btn.closest(".file-item");

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

    // 🎨 Feedback visuel immédiat dans la modale
    if (fileItem) {
      const header = fileItem.querySelector(".file-header");
      if (decision === "conforme") {
        header.style.background = "#e8ffe8";
        header.style.border = "1px solid #28a745";
        header.querySelector("em")?.remove();
        const p = document.createElement("p");
        p.style.margin = "4px 0 0";
        p.style.color = "#28a745";
        p.innerHTML = `<em>✅ Conforme le ${new Date().toLocaleString()}</em>`;
        header.appendChild(p);
      } else {
        header.style.background = "#ffeaea";
        header.style.border = "1px solid #d9534f";
        header.querySelector("em")?.remove();
        const p = document.createElement("p");
        p.style.margin = "4px 0 0";
        p.style.color = "#d9534f";
        p.innerHTML = `<em>❌ Non conforme le ${new Date().toLocaleString()}</em>`;
        header.appendChild(p);
      }

      // 🔒 Désactive les boutons après validation
      const buttons = fileItem.querySelectorAll(".btn.small");
      buttons.forEach(b => b.disabled = true);
    }

    // ✅ Met à jour le statut dans le tableau principal (persistant)
    await refreshCandidateStatus(window.currentId);

  } else {
    alert("Erreur : " + (data.error || "inconnue"));
    btn.disabled = false;
    btn.textContent = decision === "conforme" ? "✅ Conforme" : "❌ Non conforme";
  }
}); // ✅ FIN du addEventListener pour les boutons conforme / non conforme

} // ✅ FIN if(filesModal)

}); // ✅ FIN DOMContentLoaded


// ✉️ ENVOI DU CERTIFICAT DE SCOLARITÉ
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".btn-send-certificat");
  if (!btn) return;

  const id = btn.dataset.id;
  if (!id) return;

  btn.disabled = true;
  btn.textContent = "📤 Envoi en cours…";

  try {
    const res = await fetch(`/admin/send_certificat/${id}`);
    const data = await res.json();

    if (data.ok) {
      showToast("✉️ Certificat envoyé avec succès !", "#28a745");
      btn.textContent = "✅ Envoyé";
    } else {
      showToast("⚠️ " + (data.error || "Erreur inconnue"), "#dc3545");
      btn.textContent = "❌ Erreur";
    }
  } catch (err) {
    showToast("❌ Erreur d’envoi : " + err.message, "#dc3545");
    btn.textContent = "❌ Erreur";
  }

  setTimeout(() => {
    btn.disabled = false;
    btn.textContent = "✉️ Envoyer certificat";
  }, 4000);
});




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
    if (select) window.updateStatusColor(select);
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
      let nouveauBlocAjoute = false;

     const nouveaux = files.filter(f => f.type === "nouveau");
const anciens = files.filter(f => f.type !== "nouveau");

// 🔹 D’abord les nouveaux fichiers (bandeau vert)
nouveaux.forEach(f => {
  const bloc = document.createElement("div");
  bloc.className = "file-item special";
  bloc.innerHTML = `
    <div class="file-header" style="background:#e8ffe8;border:1px solid #28a745;padding:8px;border-radius:6px;margin-bottom:8px;">
      <strong>${f.label}</strong><br>
      <a href="/uploads/${encodeURIComponent(f.filename)}" target="_blank">${f.filename}</a>
      <p style="margin:4px 0 0;color:#28a745;"><em>Déposé le ${f.horodatage}</em></p>
    </div>
  `;
  list.appendChild(bloc);
});

// 🔹 Puis les fichiers normaux
anciens.forEach(f => {
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

  fetch(`/admin/update-field`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id, field: "nouveau_doc", value: 0 })
  });

  const tr = document.querySelector(`tr[data-id='${id}']`);
  if (tr) {
    const badge = tr.querySelector("span");
    if (badge && badge.textContent.includes("Nouveau document déposé")) badge.remove();
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
  const relancesBtn = document.getElementById("relancesBtn");
  const logsBtn = document.getElementById("logsBtn");
  const generationDocsBtn = document.getElementById("generationDocsBtn");

  if (openFilesBtn) {
    openFilesBtn.onclick = () => {
      closeActionsModal();
      openFilesModal(id);
    };
  }

  if (!modal) return;
  modal.classList.remove("hidden");
  if (commentBox) commentBox.value = commentaire || "";

  if (printLink) printLink.onclick = () => window.open(`/admin/print/${id}`, "_blank");

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

  // === ✉️ Boutons RELANCES / LOGS / DOCUMENTS ===
  if (relancesBtn) {
    relancesBtn.onclick = () => {
      closeActionsModal();
      openRelancesModal(id);
    };
  }

  if (logsBtn) {
    logsBtn.onclick = () => {
      closeActionsModal();
      openLogsModal(id);
    };
  }

  if (generationDocsBtn) {
    generationDocsBtn.onclick = () => {
      closeActionsModal();
      openGenerationDocsModal(id);
    };
  }
} // ✅ FIN openActionsModal



function closeActionsModal() {
  document.getElementById("actionsModal")?.classList.add("hidden");
}

function closeFilesModal() {
  document.getElementById("filesModal")?.classList.add("hidden");
}

function openRelancesModal(id) {
  window.currentId = id;
  document.getElementById("relancesModal")?.classList.remove("hidden");
}

function closeRelancesModal() {
  document.getElementById("relancesModal")?.classList.add("hidden");
}

function openLogsModal(id) {
  window.currentId = id;
  document.getElementById("logsModal")?.classList.remove("hidden");
  loadLogs(id);
}

function closeLogsModal() {
  document.getElementById("logsModal")?.classList.add("hidden");
}

function openGenerationDocsModal(id) {
  window.currentId = id;
  const modal = document.getElementById("generationDocsModal");
  modal?.classList.remove("hidden");

  // === 📜 Générer certificat DISTANCIEL
  const generateCertificatDistBtn = document.getElementById("generateCertificatDistBtn");
  if (generateCertificatDistBtn) {
    generateCertificatDistBtn.onclick = () => {
      if (!window.currentId) return alert("Aucun candidat sélectionné !");
      window.open(`/admin/generate_certificat/${window.currentId}`, "_blank");
    };
  }

  // === 🏫 Générer certificat PRÉSENTIEL
  const generateCertificatPresBtn = document.getElementById("generateCertificatPresBtn");
  if (generateCertificatPresBtn) {
    generateCertificatPresBtn.onclick = () => {
      if (!window.currentId) return alert("Aucun candidat sélectionné !");
      window.open(`/admin/generate_certificat_presentiel/${window.currentId}`, "_blank");
    };
  }

  // === ✉️ Envoyer certificat DISTANCIEL
  const sendCertificatDistBtn = document.getElementById("sendCertificatDistBtn");
  if (sendCertificatDistBtn) {
    sendCertificatDistBtn.onclick = async () => {
      if (!window.currentId) return alert("Aucun candidat sélectionné !");
      sendCertificatDistBtn.disabled = true;
      sendCertificatDistBtn.textContent = "📤 Envoi en cours…";
      try {
        const res = await fetch(`/admin/send_certificat/${window.currentId}`);
        const data = await res.json();
        if (data.ok) showToast("✉️ Certificat distanciel envoyé", "#28a745");
        else showToast("⚠️ " + (data.error || "Erreur inconnue"), "#dc3545");
      } catch (err) {
        showToast("❌ Erreur d’envoi : " + err.message, "#dc3545");
      } finally {
        setTimeout(() => {
          sendCertificatDistBtn.disabled = false;
          sendCertificatDistBtn.textContent = "✉️ Envoyer certificat Distanciel";
        }, 4000);
      }
    };
  }

  // === ✉️ Envoyer certificat PRÉSENTIEL
  const sendCertificatPresBtn = document.getElementById("sendCertificatPresBtn");
  if (sendCertificatPresBtn) {
    sendCertificatPresBtn.onclick = async () => {
      if (!window.currentId) return alert("Aucun candidat sélectionné !");
      sendCertificatPresBtn.disabled = true;
      sendCertificatPresBtn.textContent = "📤 Envoi en cours…";
      try {
        const res = await fetch(`/admin/send_certificat_presentiel/${window.currentId}`);
        const data = await res.json();
        if (data.ok) showToast("✉️ Certificat présentiel envoyé", "#007bff");
        else showToast("⚠️ " + (data.error || "Erreur inconnue"), "#dc3545");
      } catch (err) {
        showToast("❌ Erreur d’envoi : " + err.message, "#dc3545");
      } finally {
        setTimeout(() => {
          sendCertificatPresBtn.disabled = false;
          sendCertificatPresBtn.textContent = "✉️ Envoyer certificat Présentiel";
        }, 4000);
      }
    };
  }
}



// 🧩 ensuite seulement :
function closeGenerationDocsModal() {
  document.getElementById("generationDocsModal")?.classList.add("hidden");
}


// placeholder à venir
// =====================================================
// 🕓 CHARGEMENT DE L'HISTORIQUE DES LOGS — VERSION LISIBLE + DATES FR
// =====================================================
async function loadLogs(id) {
  const logsList = document.getElementById("logsList");
  if (!logsList) return;
  logsList.innerHTML = "<li>⏳ Chargement des logs...</li>";

  try {
    const res = await fetch(`/admin/logs/${id}`);
    if (!res.ok) throw new Error(`Erreur serveur (${res.status})`);
    const data = await res.json();

    if (!data.length) {
      logsList.innerHTML = "<li>Aucune action enregistrée pour ce candidat.</li>";
      return;
    }

    logsList.innerHTML = "";

    // 🗓️ Format date FR
// 🗓️ Format date FR avec fuseau horaire de Paris
const formatDateFR = (iso) => {
  try {
    const d = new Date(iso);
    return d.toLocaleString("fr-FR", {
      timeZone: "Europe/Paris",
      day: "2-digit",
      month: "long",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    }).replace(",", " à");
  } catch {
    return iso;
  }
};


    data.forEach(log => {
      let text = "";
      const t = log.type;
      const payload = log.payload || "";
      const dateFR = formatDateFR(log.created_at);

      // 🔍 Traduction et mise en forme
      if (t === "FIELD_UPDATE") {
        text = `📄 Mise à jour du champ <b>${payload.split(" / ")[0]?.replace("field: ", "")}</b> → ${payload.split(" / ")[1]?.replace("value: ", "")}`;
      } else if (t === "DOC_MARK") {
        const [file, decision] = payload.split(" / decision: ");
        text = `📎 Document <b>${file.split("/").pop()}</b> marqué : <span style="color:${decision === "conforme" ? "#28a745" : "#d9534f"}">${decision}</span>`;
      } else if (t === "DOCS_RENVOYES") {
        text = `📤 Documents renvoyés au candidat`;
  } else if (t === "MAIL_ENVOYE") {
  if (payload.includes("non_conformes")) {
    text = "✉️ Mail envoyé : Notification de pièces non conformes";
  } else if (payload.toLowerCase().includes("certificat")) {
    text = "✉️ Mail envoyé : Certificat de scolarité";
  } else {
    text = "✉️ Mail envoyé : Autre envoi";
  }
}
 else if (t === "NEW_DOC") {
        text = `📥 Nouveau document déposé`;
      } else {
        text = `🧩 ${t} — ${payload}`;
      }

      const li = document.createElement("li");
      li.innerHTML = `${text}<br><small style="color:#777">${dateFR}</small>`;
      logsList.appendChild(li);
    });
  } catch (err) {
    logsList.innerHTML = `<li style="color:red;">Erreur de chargement : ${err.message}</li>`;
  }
}

// === 🔍 Recherche instantanée Parcoursup ===
document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("searchInput");
  if (!input) return;

  input.addEventListener("input", () => {
    const query = input.value.trim();
    const url = new URL(window.location.href);
    
    if (query) {
      url.searchParams.set("search", query);
    } else {
      url.searchParams.delete("search");
    }
    
    // ⚡ Recharge juste le tableau sans recharger la page entière
    fetch(url)
      .then(res => res.text())
      .then(html => {
        const parser = new DOMParser();
        const doc = parser.parseFromString(html, "text/html");
        const newTable = doc.querySelector("table");
        const currentTable = document.querySelector("table");
        if (newTable && currentTable) currentTable.replaceWith(newTable);
      })
      .catch(err => console.error("Erreur recherche :", err));
  });
});

// === 🕓 Parcoursup : affichage visuel de l'historique des logs ===
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".btn-logs");
  if (!btn) return;

  const id = btn.dataset.id;
  const modal = document.getElementById("logsModal");
  const list  = document.getElementById("logsList");
  if (!modal || !list) return;

  modal.classList.remove("hidden");
  list.innerHTML = "<li>⏳ Chargement des logs...</li>";

  try {
    const res = await fetch(`/parcoursup/logs/${id}`, { headers: { "Accept": "application/json" } });
    if (!res.ok) throw new Error("HTTP " + res.status);
    const logs = await res.json();

    if (!Array.isArray(logs) || !logs.length) {
      list.innerHTML = "<li>Aucune action enregistrée pour ce candidat.</li>";
      return;
    }

    const icons = {
      mail: "📧",
      mail_status: "✉️",
      sms: "📱",
      sms_status: "💬",
      other: "🧩"
    };

    const html = logs.map(l => {
      const type = l.type || "other";
      const icon = icons[type] || "🧩";
      const date = l.date ? new Date(l.date).toLocaleString("fr-FR") : "";
      const event = l.event ? `<span class='log-event'>${l.event}</span>` : "";
      const dest = l.dest ? `<span class='log-dest'>${l.dest}</span>` : "";
      const message = (() => {
        if (type === "mail") return `Mail envoyé à <b>${l.dest}</b>`;
        if (type === "mail_status") {
          const evt = (l.event || "").toLowerCase();
          if (evt.includes("delivered")) return `📬 Mail <b>délivré</b>`;
          if (evt.includes("opened")) return `👀 Mail <b>ouvert</b>`;
          if (evt.includes("click")) return `🔗 Lien <b>cliqué</b>`;
          return `✉️ Évènement mail : ${evt}`;
        }
        if (type === "sms") return `SMS envoyé à <b>${l.dest}</b>`;
        if (type === "sms_status") {
          if (l.event === "delivered") return `✅ SMS <b>délivré</b>`;
          if (l.event === "failed") return `❌ SMS <b>échoué</b>`;
          return `💬 Statut SMS : ${l.event}`;
        }
        return `${type} ${event} ${dest}`;
      })();

      return `
        <li class="log-item">
          <div class="log-icon">${icon}</div>
          <div class="log-content">
            <div class="log-message">${message}</div>
            <div class="log-date">${date}</div>
          </div>
        </li>
      `;
    }).join("");

    list.innerHTML = `<ul class="timeline">${html}</ul>`;

  } catch (err) {
    list.innerHTML = `<li style="color:#c0392b;">Erreur de chargement : ${err.message}</li>`;
  }
});

// =====================================================
// 🔐 GESTION PORTAIL (Ouvrir / Fermer les inscriptions)
// =====================================================
document.addEventListener("DOMContentLoaded", () => {
  const btnPortal = document.getElementById("btnPortal");
  const portalModal = document.getElementById("portalModal");
  const savePortalBtn = document.getElementById("savePortalBtn");
  const msgBlock = document.getElementById("portalMessageBlock");
  const radios = document.querySelectorAll('input[name="portalStatus"]');
  const msgSelect = document.getElementById("portalMessage");
  const commentBox = document.getElementById("portalComment"); // 🆕

  if (!btnPortal) return;

  // 🔄 Ouvre la modale
  btnPortal.addEventListener("click", async () => {
    portalModal.classList.remove("hidden");

    // Récupère le statut actuel
    const res = await fetch("/get_portal_status");
    const data = await res.json();
    if (data.status === "closed") {
      radios.forEach(r => (r.value === "closed" ? (r.checked = true) : null));
      msgBlock.style.display = "block";
      if (commentBox) commentBox.value = data.comment || ""; // 🆕 affiche le commentaire existant
    } else {
      radios.forEach(r => (r.value === "open" ? (r.checked = true) : null));
      msgBlock.style.display = "none";
      if (commentBox) commentBox.value = "";
    }
  });

  // 🎛️ Affiche le champ message + commentaire seulement si "fermé"
  radios.forEach(radio => {
    radio.addEventListener("change", () => {
      msgBlock.style.display = radio.value === "closed" ? "block" : "none";
    });
  });

  // 💾 Enregistrement du statut + commentaire
  savePortalBtn.addEventListener("click", async () => {
    const selected = document.querySelector('input[name="portalStatus"]:checked');
    if (!selected) return alert("Veuillez choisir un état du portail.");
    const status = selected.value;
    const message = msgSelect.value;
    const comment = commentBox ? commentBox.value.trim() : ""; // 🆕 récupère le commentaire

    const res = await fetch("/set_portal_status", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, message, comment }) // 🆕 envoi du commentaire
    });
    const data = await res.json();

    if (data.ok) {
      alert("✅ Portail mis à jour : " + (status === "open" ? "OUVERT" : "FERMÉ"));
      portalModal.classList.add("hidden");
      location.reload();
    } else {
      alert("Erreur lors de la mise à jour du portail.");
    }
  });
});

// 🔙 Fermeture manuelle de la modale
function closePortalModal() {
  document.getElementById("portalModal").classList.add("hidden");
}

// =====================================================
// 🔍 Recherche instantanée ADMIN BTS (filtrage sur toutes les colonnes principales)
// =====================================================
document.addEventListener("DOMContentLoaded", () => {
  const input = document.getElementById("searchBTS");
  const tbody = document.querySelector(".admin-table tbody");

  if (!input || !tbody) return;

  input.addEventListener("input", () => {
    const q = input.value.trim().toLowerCase();

    tbody.querySelectorAll("tr").forEach(tr => {
      // 🔎 on prend tout le texte de la ligne (toutes les colonnes)
      const text = Array.from(tr.querySelectorAll("td"))
        .map(td => td.textContent.toLowerCase())
        .join(" ");

      // ✅ si la recherche est trouvée dans la ligne → on garde visible
      tr.style.display = text.includes(q) ? "" : "none";
    });
  });
});







window.openFilesModal = openFilesModal;
window.openActionsModal = openActionsModal;



























// === Intégrale Academy – JS ADMIN SEUL ===
window.currentId = null;

document.addEventListener("DOMContentLoaded", () => {

  // =====================================================
  // 🧾 SECTION ADMIN
  // =====================================================
  const table = document.querySelector('.admin-table');
  if (table) {

// ✏️ Édition inline des champs (mise à jour dynamique et feedback visuel)
table.querySelectorAll('td[contenteditable="true"]').forEach(td => {
  td.addEventListener('blur', async () => {
    const tr = td.closest('tr');
    const id = tr.dataset.id;
    const field = td.dataset.field;
    const value = td.textContent.trim();

    // 🟡 Feedback visuel immédiat
    td.style.background = "#fff3cd"; // jaune clair pendant la sauvegarde

    try {
      const res = await fetch('/admin/update-field', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ id, field, value })
      });

      const data = await res.json();

      if (data.ok) {
        td.style.background = "#d4edda"; // vert clair
        showToast("💾 Sauvegardé", "#28a745");
        await refreshRow(id);
        setTimeout(() => td.style.background = "", 800);
      } else {
        td.style.background = "#f8d7da"; // rouge clair
        showToast("❌ Erreur de sauvegarde", "#dc3545");
      }
    } catch (e) {
      td.style.background = "#f8d7da";
      showToast("⚠️ Erreur réseau", "#dc3545");
    }
  });

  // 🔹 Surbrillance quand on édite
  td.addEventListener('focus', () => td.classList.add('editing'));
  td.addEventListener('blur', () => td.classList.remove('editing'));
});


// 🔄 Changement de statut (binding initial)
table.querySelectorAll('.status-select').forEach(sel => {
  sel.addEventListener('change', () => onStatusChange(sel));
});




    // ⚙️ Boutons ACTIONS
    table.querySelectorAll('.action-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        const id = btn.dataset.id;
        const commentaire = btn.dataset.commentaire || "";
        openActionsModal(id, commentaire);
      });
    });

    table.querySelectorAll('.ypareo-neo-btn').forEach(btn => {
      btn.addEventListener('click', () => envoyerYpareoNeo(btn));
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
  await refreshRow(window.currentId);
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
      await refreshRow(window.currentId);
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

        // 🔄 met à jour la ligne instantanément sans reload
        await refreshCandidateRow(window.currentId);

        // ✅ ferme la modale après un petit délai
        setTimeout(() => closeFilesModal(), 800);
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
    await refreshRow(window.currentId);

  } else {
    alert("Erreur : " + (data.error || "inconnue"));
    btn.disabled = false;
    btn.textContent = decision === "conforme" ? "✅ Conforme" : "❌ Non conforme";
  }
}); // ✅ FIN du addEventListener pour les boutons conforme / non conforme

} // ✅ FIN if(filesModal)

  updateRowCount();


}); // ✅ FIN DOMContentLoaded


function marquerBoutonYpareoEnvoye(btn, couleur = "#6c757d") {
  if (!btn) return;
  btn.textContent = "✅ Envoyé YPAREO";
  btn.style.background = couleur;
  btn.title = "";
  btn.disabled = true;
  const errorDetail = btn.parentElement?.querySelector(".ypareo-error-detail");
  if (errorDetail) {
    errorDetail.textContent = "";
    errorDetail.style.display = "none";
  }
  const checkbox = btn.closest("tr")?.querySelector('[data-field="label_ypareo"]');
  if (checkbox) checkbox.checked = true;
}

async function rafraichirCompteurYpareoMass() {
  const btn = document.getElementById("btnMassYpareoNeo");
  if (!btn) return 0;
  try {
    const res = await fetch("/admin/ypareo-neo/count-confirmed", { cache: "no-store" });
    const data = await res.json();
    if (!res.ok || !data.ok) throw new Error(data.error || "Compteur indisponible");
    btn.textContent = `🚀 YPAREO NEO (${data.count})`;
    btn.disabled = data.count === 0;
    btn.title = data.count === 0
      ? "Aucun dossier en inscription confirmée à envoyer vers YPAREO NEO"
      : "Envoyer tous les dossiers en inscription confirmée vers YPAREO NEO";
    return data.count;
  } catch (err) {
    console.warn("Impossible de récupérer le nombre de dossiers YPAREO NEO :", err);
    return 0;
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const massYpareoBtn = document.getElementById("btnMassYpareoNeo");
  const modal = document.getElementById("ypareoMassConfirmModal");
  const countEl = document.getElementById("ypareoMassConfirmCount");
  const cancelBtn = document.getElementById("ypareoMassCancel");
  const confirmBtn = document.getElementById("ypareoMassConfirm");
  if (!massYpareoBtn || !modal || !countEl || !confirmBtn) return;

  rafraichirCompteurYpareoMass();

  cancelBtn?.addEventListener("click", () => modal.classList.add("hidden"));

  massYpareoBtn.addEventListener("click", async () => {
    massYpareoBtn.disabled = true;
    const count = await rafraichirCompteurYpareoMass();
    massYpareoBtn.disabled = count === 0;
    if (count === 0) {
      showToast("Aucun dossier confirmé à envoyer vers YPAREO NEO.", "#6c757d");
      return;
    }
    countEl.textContent = count;
    modal.classList.remove("hidden");
  });

  confirmBtn.addEventListener("click", async () => {
    modal.classList.add("hidden");
    ouvrirProgressionYpareo();
    document.getElementById("ypareoProgressSubtitle").textContent =
      "Envoi groupé des dossiers confirmés vers YPAREO NEO…";
    massYpareoBtn.disabled = true;
    const oldText = massYpareoBtn.textContent;
    massYpareoBtn.textContent = "⏳ Envoi YPAREO en cours…";

    const cursusTimer = window.setTimeout(() => definirEtapeYpareo("cursus"), 850);
    try {
      const res = await fetch("/admin/ypareo-neo/send-confirmed", {
        method: "POST",
        headers: { "Accept": "application/json" }
      });
      const data = await res.json().catch(() => ({}));
      window.clearTimeout(cursusTimer);
      definirEtapeYpareo("cursus");

      (data.sent_ids || []).forEach((id) => {
        const btn = document.querySelector(`.ypareo-neo-btn[data-id="${CSS.escape(String(id))}"]`);
        marquerBoutonYpareoEnvoye(btn, "#6c757d");
      });

      if (!res.ok || !data.ok) {
        const detail = data.errors?.length
          ? `${data.sent || 0}/${data.total || 0} envoyé(s). ${data.errors.length} erreur(s).`
          : (data.error || "Erreur lors de l’envoi groupé YPAREO NEO.");
        throw new Error(detail);
      }

      terminerProgressionYpareo(true, data.message || "Envoi groupé terminé.");
      showToast(`✅ ${data.sent} dossier(s) envoyé(s) vers YPAREO NEO`, "#28a745");
      await rafraichirCompteurYpareoMass();
    } catch (err) {
      window.clearTimeout(cursusTimer);
      terminerProgressionYpareo(false, err.message);
      showToast(`❌ ${err.message}`, "#dc3545");
    } finally {
      massYpareoBtn.textContent = oldText;
      await rafraichirCompteurYpareoMass();
    }
  });
});

async function envoyerYpareoNeo(btn) {
  const id = btn.dataset.id;
  if (!id || btn.disabled) return;
  const errorDetail = btn.parentElement.querySelector(".ypareo-error-detail");
  ouvrirProgressionYpareo();
  btn.disabled = true;
  btn.textContent = "⏳ Envoi…";
  btn.style.background = "#6c757d";
  if (errorDetail) errorDetail.style.display = "none";

  const cursusTimer = window.setTimeout(() => {
    definirEtapeYpareo("cursus");
  }, 850);

  try {
    const response = await fetch(`/admin/ypareo-neo/${encodeURIComponent(id)}`, {
      method: "POST",
      headers: { "Accept": "application/json" }
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) {
      throw new Error(data.error || `Erreur HTTP ${response.status}`);
    }
    window.clearTimeout(cursusTimer);
    definirEtapeYpareo("cursus");
    marquerBoutonYpareoEnvoye(btn, "#28a745");
    terminerProgressionYpareo(true);
    showToast(data.message || "✅ Candidat envoyé dans YPAREO", "#28a745");
  } catch (error) {
    window.clearTimeout(cursusTimer);
    btn.textContent = "❌ Erreur YPAREO";
    btn.style.background = "#dc3545";
    btn.title = error.message;
    btn.disabled = false;
    if (errorDetail) {
      errorDetail.textContent = error.message;
      errorDetail.style.display = "block";
    }
    terminerProgressionYpareo(false, error.message);
    showToast(`❌ ${error.message}`, "#dc3545");
  }
}

function ouvrirProgressionYpareo() {
  const modal = document.getElementById("ypareoProgressModal");
  const card = document.getElementById("ypareoProgressCard");
  const spinner = document.getElementById("ypareoProgressSpinner");
  const error = document.getElementById("ypareoProgressError");
  const close = document.getElementById("ypareoProgressClose");
  card?.classList.remove("is-success", "is-error");
  if (spinner) spinner.textContent = "";
  document.getElementById("ypareoProgressTitle").textContent =
    "Transmission en cours vers YPAREO NEO";
  document.getElementById("ypareoProgressSubtitle").textContent =
    "Création de la fiche apprenant et de son inscription à la formation…";
  document.getElementById("ypareoProgressNote").textContent =
    "Veuillez patienter et ne fermez pas cette page.";
  document.getElementById("ypareoPersonStep")?.classList.add("active");
  document.getElementById("ypareoPersonStep")?.classList.remove("done");
  document.getElementById("ypareoCursusStep")?.classList.remove("active", "done");
  document.getElementById("ypareoProgressLine")?.classList.remove("active");
  if (error) {
    error.textContent = "";
    error.style.display = "none";
  }
  if (close) close.style.display = "none";
  modal?.classList.remove("hidden");
}

function definirEtapeYpareo(etape) {
  if (etape !== "cursus") return;
  document.getElementById("ypareoPersonStep")?.classList.remove("active");
  document.getElementById("ypareoPersonStep")?.classList.add("done");
  document.getElementById("ypareoProgressLine")?.classList.add("active");
  document.getElementById("ypareoCursusStep")?.classList.add("active");
  const subtitle = document.getElementById("ypareoProgressSubtitle");
  if (subtitle) subtitle.textContent = "La personne est prête. Création de son cursus de formation…";
}

function terminerProgressionYpareo(succes, message = "") {
  const card = document.getElementById("ypareoProgressCard");
  const spinner = document.getElementById("ypareoProgressSpinner");
  const title = document.getElementById("ypareoProgressTitle");
  const subtitle = document.getElementById("ypareoProgressSubtitle");
  const note = document.getElementById("ypareoProgressNote");
  const error = document.getElementById("ypareoProgressError");
  const close = document.getElementById("ypareoProgressClose");

  card?.classList.add(succes ? "is-success" : "is-error");
  if (spinner) spinner.textContent = succes ? "✓" : "!";
  if (title) title.textContent = succes ? "Transmission YPAREO terminée" : "Échec de la transmission YPAREO";
  if (subtitle) {
    subtitle.textContent = succes
      ? "La personne et son cursus ont bien été créés dans YPAREO NEO."
      : "La synchronisation n’a pas pu être terminée.";
  }
  if (note) {
    note.textContent = succes
      ? "Les identifiants YPAREO ont été enregistrés sur le candidat."
      : "Corrigez le problème puis cliquez à nouveau sur Erreur YPAREO.";
  }
  document.getElementById("ypareoPersonStep")?.classList.remove("active");
  document.getElementById("ypareoPersonStep")?.classList.add("done");
  document.getElementById("ypareoProgressLine")?.classList.add("active");
  document.getElementById("ypareoCursusStep")?.classList.remove("active");
  if (succes) document.getElementById("ypareoCursusStep")?.classList.add("done");
  if (!succes && error) {
    error.textContent = message;
    error.style.display = "block";
  }
  if (close) close.style.display = "block";
}

document.getElementById("ypareoProgressClose")?.addEventListener("click", () => {
  document.getElementById("ypareoProgressModal")?.classList.add("hidden");
});


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
  const existingToasts = document.querySelectorAll(".toast-msg");
  const offset = existingToasts.length * 60; // décalage vertical entre chaque toast

  const t = document.createElement("div");
  t.className = "toast-msg";
  t.textContent = msg;

  Object.assign(t.style, {
    position: "fixed",
    bottom: `${20 + offset}px`, // empilement progressif
    right: "20px",
    background: color,
    color: "#fff",
    padding: "10px 16px",
    borderRadius: "8px",
    fontWeight: "600",
    boxShadow: "0 3px 8px rgba(0,0,0,.3)",
    zIndex: "9999",
    opacity: "0",
    transition: "opacity .3s, transform .3s",
    transform: "translateY(10px)"
  });

  document.body.appendChild(t);

  // Animation d’apparition
  setTimeout(() => {
    t.style.opacity = "1";
    t.style.transform = "translateY(0)";
  }, 50);

  // Disparition + suppression propre
  setTimeout(() => {
    t.style.opacity = "0";
    t.style.transform = "translateY(10px)";
    setTimeout(() => {
      t.remove();
      // Recalcule les positions des toasts restants
      document.querySelectorAll(".toast-msg").forEach((toast, i) => {
        toast.style.bottom = `${20 + i * 60}px`;
      });
    }, 300);
  }, 3000);
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
  const renvoiMailsBtn = document.getElementById("renvoiMailsBtn");
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
    if (res.ok) {
      showToast("📧 Mail de reconfirmation envoyé", "#007bff");
      await refreshRow(id);
    }
    closeActionsModal();
  };
}


if (deleteBtn) {
  deleteBtn.onclick = async () => {
    if (!confirm("⚠️ Supprimer définitivement cette fiche ?")) return;

    deleteBtn.disabled = true;
    deleteBtn.textContent = "⏳ Suppression...";

    try {
      const res = await fetch(`/admin/delete/${id}`, { method: "POST" });
      if (res.ok) {
        showToast("🗑️ Fiche supprimée avec succès", "#d9534f");
        const tr = document.querySelector(`tr[data-id='${id}']`);
        if (tr) {
          tr.style.transition = "opacity 0.6s ease, transform 0.4s ease";
          tr.style.opacity = "0";
          tr.style.transform = "translateX(-40px)";
          setTimeout(() => tr.remove(), 600);
        }
      } else {
        showToast("❌ Erreur lors de la suppression", "#dc3545");
      }
    } catch (err) {
      showToast("⚠️ Erreur réseau : " + err.message, "#dc3545");
    } finally {
      deleteBtn.disabled = false;
      deleteBtn.textContent = "🗑️ Supprimer le dossier";
      closeActionsModal();
    }
  };
}


if (saveBtn) {
  saveBtn.onclick = async () => {
    const value = commentBox.value.trim();
    saveBtn.disabled = true;
    saveBtn.textContent = "⏳ Sauvegarde...";

    try {
      const res = await fetch("/admin/update-field", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, field: "commentaires", value })
      });

      const data = await res.json();
      if (data.ok) {
        showToast("💬 Commentaire sauvegardé", "#28a745");
        // ✅ met à jour le dataset local pour éviter "0" au prochain affichage
const btn = document.querySelector(`.action-btn[data-id='${id}']`);
if (btn) btn.dataset.commentaire = value;
        await refreshRow(id);
      } else {
        showToast("⚠️ Erreur de sauvegarde", "#dc3545");
      }
    } catch (err) {
      showToast("❌ Erreur réseau : " + err.message, "#dc3545");
    } finally {
      saveBtn.disabled = false;
      saveBtn.textContent = "💾 Enregistrer";
    }
  };
}


  // === ✉️ Boutons RELANCES / LOGS / DOCUMENTS ===
// === ✉️ Boutons RENVOI MAILS / RELANCES / LOGS / DOCUMENTS ===
if (renvoiMailsBtn) {
  renvoiMailsBtn.onclick = () => {
    closeActionsModal();
    openRenvoiMailsModal(id);
  };
}

  const sendAPSBtn = document.getElementById("sendAPSBtn");

if (sendAPSBtn) {
  sendAPSBtn.onclick = async () => {
    if (!window.currentId) return;
    if (!confirm("Voulez-vous envoyer le mail APS à ce candidat ?")) return;

    sendAPSBtn.disabled = true;
    sendAPSBtn.textContent = "⏳ Envoi en cours…";

    try {
      const res = await fetch(`/admin/send_mail_aps/${window.currentId}`, {
        method: "POST"
      });

      const data = await res.json();

      if (res.ok && data.ok) {
        showToast("📩 Mail APS envoyé avec succès", "#28a745");
      } else {
        showToast("❌ Erreur : " + (data.error || "Impossible d'envoyer le mail"), "#dc3545");
      }
    } catch (err) {
      showToast("❌ Erreur réseau : " + err.message, "#dc3545");
    } finally {
      sendAPSBtn.disabled = false;
      sendAPSBtn.textContent = "📩 Envoyer mail APS";
      closeActionsModal();
    }
  };
}


if (relancesBtn) {
  relancesBtn.onclick = () => {
    closeActionsModal();
    openRelancesActionsModal(id);
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


// =====================================================
// ✉️📱 RENVOI MAILS (mail + SMS) – /admin/resend_mail_sms/<cid>
// =====================================================
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".renvoi-option");
  if (!btn) return;
  if (!window.currentId) {
    alert("Aucun candidat sélectionné.");
    return;
  }

  const action = btn.dataset.action;
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ Envoi en cours…";

  try {
    const res = await fetch(`/admin/resend_mail_sms/${window.currentId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    const data = await res.json();

    if (res.ok && data.ok) {
      showToast("✉️ Mail + SMS renvoyés", "#28a745");
    } else {
      alert("Erreur : " + (data.error || "Envoi impossible"));
    }
  } catch (err) {
    alert("Erreur réseau : " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
});

// =====================================================
// 🔔📱 RELANCES (mail + SMS de relance) – /admin/relance/<cid>
// =====================================================
document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".relance-option");
  if (!btn) return;
  if (!window.currentId) {
    alert("Aucun candidat sélectionné.");
    return;
  }

  const action = btn.dataset.action;
  const originalText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ Envoi en cours…";

  try {
    const res = await fetch(`/admin/relance/${window.currentId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action })
    });
    const data = await res.json();

    if (res.ok && data.ok) {
  showToast("✉️ Mail + SMS renvoyés", "#28a745");
  await refreshRow(window.currentId); // ✅ AJOUT
} else {
  alert("Erreur : " + (data.error || "Envoi impossible"));
}

  } catch (err) {
    alert("Erreur réseau : " + err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = originalText;
  }
});

// 🔔 Ajoute ou met à jour le badge relance dans le tableau
const tr = document.querySelector(`tr[data-id='${window.currentId}']`);
if (tr) {
  let badge = tr.querySelector(".badge-relance");
  if (!badge) {
    badge = document.createElement("span");
    badge.className = "badge-relance";
    badge.style.cssText = `
      background:#f4c45a;
      color:#111;
      padding:2px 6px;
      border-radius:6px;
      font-size:12px;
      margin-left:6px;
      display:inline-block;
      font-weight:600;
    `;
    badge.textContent = "🔔 Relancé";
    const cell = tr.querySelector("td:last-child");
    if (cell) cell.appendChild(badge);
  }
  badge.title = "Dernière relance : " + new Date().toLocaleString("fr-FR");
}



// =====================================================
// 🟢 MODALES – RENVOI MAILS & RELANCES
// =====================================================

function openRenvoiMailsModal(id) {
  window.currentId = id;
  const modal = document.getElementById("renvoiMailsModal");
  if (modal) modal.classList.remove("hidden");
}

function closeRenvoiMailsModal() {
  document.getElementById("renvoiMailsModal")?.classList.add("hidden");
}

function openRelancesActionsModal(id) {
  window.currentId = id;
  const modal = document.getElementById("relancesModal");
  if (modal) modal.classList.remove("hidden");
}

function closeRelancesActionsModal() {
  document.getElementById("relancesModal")?.classList.add("hidden");
}


window.openFilesModal = openFilesModal;
window.openActionsModal = openActionsModal;

// =====================================================
// 🧮 Affiche combien de candidats sont concernés par la relance candidature validée
// =====================================================
document.addEventListener("DOMContentLoaded", async () => {
  const massValidatedBtn = document.getElementById("btnMassValidatedRelance");
  if (!massValidatedBtn) return;

  try {
    const res = await fetch("/admin/count_validated_applications");
    const data = await res.json();
    if (data.ok) {
      massValidatedBtn.textContent = `🔔 RELANCER TOUTES LES CANDIDATURES VALIDEES (${data.count})`;
      massValidatedBtn.disabled = data.count === 0;
      if (data.count === 0) {
        massValidatedBtn.title = "Aucune candidature avec le statut Candidature validée";
      }
    }
  } catch (err) {
    console.warn("Impossible de récupérer le nombre de candidatures validées :", err);
  }
});

// =====================================================
// 🔔 RELANCE DE TOUTES LES CANDIDATURES VALIDÉES
// =====================================================
document.addEventListener("DOMContentLoaded", () => {
  const massValidatedBtn = document.getElementById("btnMassValidatedRelance");
  if (!massValidatedBtn) return;

  massValidatedBtn.addEventListener("click", async () => {
    const ok = confirm("⚠️ Envoyer la relance à toutes les personnes avec le statut 'Candidature validée' ?");
    if (!ok) return;

    massValidatedBtn.disabled = true;
    const oldText = massValidatedBtn.textContent;
    massValidatedBtn.textContent = "⏳ Envoi des relances en cours...";

    try {
      const res = await fetch("/admin/relance_all_validated", { method: "POST" });
      const data = await res.json();

      if (res.ok && data.ok) {
        showToast(`✅ ${data.sent} relances envoyées aux candidatures validées !`, "#28a745");
        setTimeout(() => location.reload(), 1500);
      } else {
        showToast("⚠️ " + (data.error || "Erreur lors de l’envoi des relances"), "#dc3545");
      }
    } catch (err) {
      showToast("❌ Erreur réseau ou serveur", "#dc3545");
    } finally {
      massValidatedBtn.disabled = false;
      massValidatedBtn.textContent = oldText;
    }
  });
});

// =====================================================
// 🧮 Affiche combien de candidats sont concernés par la reconfirmation
// =====================================================
document.addEventListener("DOMContentLoaded", async () => {
  const massBtn = document.getElementById("btnMassReconfirm");
  if (!massBtn) return;

  try {
    const res = await fetch("/admin/count_confirmed");
    const data = await res.json();
    if (data.ok) {
      massBtn.textContent = `📢 Envoyer reconfirmation à ${data.count} candidats confirmés`;
    } else {
      massBtn.textContent = "📢 Envoyer reconfirmation (aucun candidat confirmé)";
      massBtn.disabled = true;
    }
  } catch (err) {
    console.warn("Impossible de récupérer le nombre de candidats confirmés :", err);
  }
});


// =====================================================
// 📢 ENVOI DE RECONFIRMATION À TOUS LES CANDIDATS
// =====================================================
// === 📢 Reconfirmation à tous les candidats ===
document.addEventListener("DOMContentLoaded", () => {
  const massBtn = document.getElementById("btnMassReconfirm");
  if (!massBtn) return;

  massBtn.addEventListener("click", async () => {
    const ok = confirm("⚠️ Envoyer la reconfirmation à tous les candidats 'Inscription confirmée' ?");
    if (!ok) return;

    massBtn.disabled = true;
    const oldText = massBtn.textContent;
    massBtn.textContent = "⏳ Envoi en cours...";

    try {
      const res = await fetch("/admin/reconfirm_all", { method: "POST" });
      const data = await res.json();

      if (data.ok) {
        showToast(`✅ ${data.sent} reconfirmations envoyées et statuts mis à jour !`, "#28a745");
        document.querySelectorAll(".status-select").forEach(sel => {
  if (sel.value === "confirmee") {
    sel.value = "reconf_en_cours";
    updateStatusColor(sel);
  }
});
        setTimeout(() => location.reload(), 1500);
      } else {
        showToast("⚠️ " + (data.error || "Erreur lors de l’envoi"), "#dc3545");
      }
    } catch (err) {
      showToast("❌ Erreur réseau ou serveur", "#dc3545");
    }

    massBtn.disabled = false;
    massBtn.textContent = oldText;
  });
});

// =====================================================
// 🔄 Rafraîchit la ligne d’un candidat depuis le backend (statut, dates, badges…)
// =====================================================
async function refreshCandidateRow(id) {
  try {
    const tr = document.querySelector(`tr[data-id='${id}']`);
    if (!tr) return;

    const res = await fetch(`/admin/status/${id}`);
    const data = await res.json();
    if (!data.ok) return;

    // 🟢 Met à jour le statut dans le select
    const sel = tr.querySelector('.status-select');
    if (sel) {
      sel.value = data.statut;
      window.updateStatusColor(sel);
    }

    // 🕓 Met à jour les dates visibles (si colonnes présentes)
    if (data.date_validee) {
      const c = tr.querySelector('.col-date-validee');
      if (c) c.textContent = new Date(data.date_validee).toLocaleDateString('fr-FR');
    }
    if (data.date_confirmee) {
      const c = tr.querySelector('.col-date-confirmee');
      if (c) c.textContent = new Date(data.date_confirmee).toLocaleDateString('fr-FR');
    }
    if (data.date_reconfirmee) {
      const c = tr.querySelector('.col-date-reconfirmee');
      if (c) c.textContent = new Date(data.date_reconfirmee).toLocaleDateString('fr-FR');
    }

    // 🧩 Si le badge relance existe mais que le statut a changé → on l’enlève
    if (['confirmee', 'reconfirmee', 'validee'].includes(data.statut)) {
      const badge = tr.querySelector('.badge-relance');
      if (badge) badge.remove();
    }

    showToast('🔄 Ligne mise à jour', '#007bff');
  } catch (e) {
    console.error('Erreur refreshCandidateRow:', e);
  }
}

// =====================================================
// 🕓 Actualisation automatique de tout le tableau admin
// =====================================================
const isParcoursupPage = window.location.pathname.startsWith("/parcoursup");

document.addEventListener("DOMContentLoaded", () => {
  if (isParcoursupPage) return;

  const table = document.querySelector(".admin-table tbody");
  if (!table) return;

  let autoRefreshInterval = 60; // ⏱️ toutes les 60 secondes (modifiable)
  let lastUpdate = Date.now();

  async function refreshAdminTable() {
    try {
      const res = await fetch(window.location.href, { cache: "no-store" });
      const html = await res.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, "text/html");
      const newBody = doc.querySelector(".admin-table tbody");

      if (!newBody) return;

      // 🟡 Ne pas remplacer si l’utilisateur édite une cellule
      const isEditing = document.activeElement && document.activeElement.tagName === "TD" && document.activeElement.isContentEditable;
      if (isEditing) return;

      table.replaceWith(newBody);
      console.log("🔄 Tableau mis à jour automatiquement");

      // 🟢 Réapplique les couleurs de statuts
      newBody.querySelectorAll(".status-select").forEach(sel => updateStatusColor(sel));
      // 🧩 Rebinding après refresh automatique
newBody.querySelectorAll(".status-select").forEach(sel => {
  sel.addEventListener("change", () => onStatusChange(sel));
});


    } catch (err) {
      console.warn("Erreur d’actualisation automatique :", err);
    }
  }

  // 🔁 Actualisation automatique
  setInterval(() => {
    const now = Date.now();
    if (now - lastUpdate > autoRefreshInterval * 1000) {
      refreshAdminTable();
      lastUpdate = now;
    }
  }, 5000);
});

// =====================================================
// ⚙️ Panneau de contrôle Live admin (pause / reprise / timer)
// =====================================================
document.addEventListener("DOMContentLoaded", () => {
  const toggleBtn = document.getElementById("toggleLive");
  const manualBtn = document.getElementById("manualRefresh");
  const liveStatus = document.getElementById("liveStatus");
  const countdownEl = document.getElementById("countdown");

  if (!toggleBtn || !manualBtn) return;

  let liveEnabled = true;
  let countdown = 60; // secondes
  let interval;

  async function refreshAdminTableNow() {
    const table = document.querySelector(".admin-table tbody");
    if (!table) return;
    try {
      const res = await fetch(window.location.href, { cache: "no-store" });
      // 🚫 Empêche le refresh si une cellule est en édition
const editing = document.activeElement?.isContentEditable;
if (editing) {
  console.log("⏸️ Refresh annulé pendant édition");
  return;
}
      const html = await res.text();
      const parser = new DOMParser();
      const doc = parser.parseFromString(html, "text/html");
      const newBody = doc.querySelector(".admin-table tbody");
      if (!newBody) return;
      table.replaceWith(newBody);
      // 🧩 Réinitialise les écouteurs après un refresh manuel ou auto
setTimeout(() => {
  console.log("♻️ Rebinding après refresh");
  const checks = document.querySelectorAll("input.chk");
  const editable = document.querySelectorAll('td[contenteditable="true"]');

  // ✅ Cases à cocher (étiquettes)
  checks.forEach(chk => {
    chk.addEventListener("change", async () => {
      const tr = chk.closest("tr");
      const id = tr.dataset.id;
      const field = chk.dataset.field;
      const value = chk.checked ? 1 : 0;
      await fetch("/admin/update-field", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, field, value })
      });
      showToast("💾 Étiquette sauvegardée", "#28a745");
    });
  });

  // ✅ Champs éditables (nom, prénom, bts, etc.)
  editable.forEach(td => {
    td.addEventListener("blur", async () => {
      const tr = td.closest("tr");
      const id = tr.dataset.id;
      const field = td.dataset.field;
      const value = td.textContent.trim();
      await fetch("/admin/update-field", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, field, value })
      });
      showToast("💾 Sauvegardé", "#28a745");
    });
  });
}, 500);

      showToast("🔁 Tableau actualisé", "#007bff");
      if (window.refreshKPI) refreshKPI();

      newBody.querySelectorAll(".status-select").forEach(sel => updateStatusColor(sel));
      // 🧩 Rebinding après refresh
newBody.querySelectorAll(".status-select").forEach(sel => {
  sel.addEventListener("change", () => onStatusChange(sel));
});

    } catch (err) {
      console.warn("Erreur refresh manuel :", err);
    }
  }

  function startTimer() {
    clearInterval(interval);
    interval = setInterval(async () => {
      if (!liveEnabled) return;
      countdown--;
      countdownEl.textContent = `(${countdown}s)`;
      if (countdown <= 0) {
        await refreshAdminTableNow();
        countdown = 60;
      }
    }, 1000);
  }

  toggleBtn.addEventListener("click", () => {
    liveEnabled = !liveEnabled;
    liveStatus.textContent = liveEnabled ? "🟢 Auto ON" : "🔴 Auto OFF";
    toggleBtn.textContent = liveEnabled ? "⏸️ Pause" : "▶️ Reprendre";
    countdownEl.style.color = liveEnabled ? "#555" : "#999";
  });

  manualBtn.addEventListener("click", async () => {
    await refreshAdminTableNow();
    countdown = 60;
  });

  startTimer();
});

// =====================================================
// 🧭 Détection et insertion des nouveaux candidats en live
// =====================================================
async function checkNewCandidats() {
  if (isParcoursupPage) return;

  try {
    const res = await fetch("/admin/json", { cache: "no-store" });
    const data = await res.json();

    if (!data.ok || !Array.isArray(data.rows)) return;

    const tbody = document.querySelector(".admin-table tbody");
    if (!tbody) return;

    const existingIds = Array.from(tbody.querySelectorAll("tr")).map(tr => tr.dataset.id);
    const nouveaux = data.rows.filter(r => !existingIds.includes(r.id));

    if (nouveaux.length > 0) {
      nouveaux.forEach(r => {
        const tr = document.createElement("tr");
        tr.dataset.id = r.id;
        tr.innerHTML = `
          <td>${r.nom}</td>
          <td>${r.prenom}</td>
          <td>${r.bts}</td>
          <td>${r.mode}</td>
          <td>${r.tel}</td>
          <td>${r.email}</td>
          <td><select class="status-select"><option>${r.statut}</option></select></td>
          <td>—</td>
          <td style="text-align:center;">🆕</td>
        `;
        tr.style.background = "#e8ffe8";
        tr.style.transition = "background 1s";
        tbody.prepend(tr);
        setTimeout(() => (tr.style.background = ""), 1500);
      });

      showToast(`🆕 ${nouveaux.length} nouveau(x) candidat(s) ajouté(s)`, "#28a745");
      nouveaux.forEach(r => console.log("Nouveau candidat détecté:", r.nom, r.prenom));
    }
  } catch (err) {
    console.warn("Erreur checkNewCandidats:", err);
  }
}

// 🔁 vérifie toutes les 60 s (ou adapte à ton intervalle)
setInterval(checkNewCandidats, 60000);


// =====================================================
// ⚡ Rafraîchissement intelligent des lignes après actions – version stabilisée
// =====================================================
async function refreshRow(id) {
  const tr = document.querySelector(`tr[data-id='${id}']`);
  if (!tr) return;

  try {
    const res = await fetch(`/admin/row/${id}`);
    const data = await res.json();
    if (!data.ok || !data.row) return;

    // 🔁 Reconstruit uniquement les colonnes éditables et les étiquettes
    const html = `
      <td contenteditable="true" data-field="nom">${data.row.nom}</td>
      <td contenteditable="true" data-field="prenom">${data.row.prenom}</td>
      <td contenteditable="true" data-field="bts">${data.row.bts}</td>
      <td contenteditable="true" data-field="mode">${data.row.mode}</td>
      <td contenteditable="true" data-field="tel">${data.row.tel}</td>
      <td contenteditable="true" data-field="email">${data.row.email}</td>
      <td>
        <select class="status-select" data-field="statut">
          ${data.statuts.map(s => `
            <option value="${s.key}" ${s.key === data.row.statut ? "selected" : ""}>${s.label}</option>
          `).join("")}
        </select>
      </td>
      <td class="etiquettes" 
          style="display:flex;align-items:center;justify-content:center;gap:12px;flex-wrap:nowrap;white-space:nowrap;">
        <label><input type="checkbox" class="chk" data-field="label_aps" ${data.row.label_aps ? "checked" : ""}> APS</label>
        <label><input type="checkbox" class="chk" data-field="label_aut_ok" ${data.row.label_aut_ok ? "checked" : ""}> AUT OK</label>
        <label><input type="checkbox" class="chk" data-field="label_cheque_ok" ${data.row.label_cheque_ok ? "checked" : ""}> Chèque OK</label>
        <label><input type="checkbox" class="chk" data-field="label_ypareo" ${data.row.label_ypareo ? "checked" : ""}> YPAREO</label>
        <label><input type="checkbox" class="chk" data-field="label_carte_etudiante" ${data.row.label_carte_etudiante ? "checked" : ""}> Carte étudiante</label>
      </td>
    `;

    // 🧱 Remplace uniquement les cellules sauf la colonne "Actions"
    const temp = document.createElement("tr");
    temp.innerHTML = html.trim();
    const newCells = temp.querySelectorAll("td");
    const oldCells = tr.querySelectorAll("td");

    newCells.forEach((newTd, i) => {
      if (i < oldCells.length - 1) oldCells[i].innerHTML = newTd.innerHTML;
    });

    // 🎨 Applique la bonne couleur du statut
    const sel = tr.querySelector(".status-select");
    if (sel) updateStatusColor(sel);

    // 🧩 Réattache les cases à cocher
    tr.querySelectorAll("input.chk").forEach(chk => {
      chk.addEventListener("change", async () => {
        const field = chk.dataset.field;
        const value = chk.checked ? 1 : 0;
        try {
          await fetch("/admin/update-field", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ id, field, value })
          });
          showToast("💾 Étiquette sauvegardée", "#28a745");
        } catch {
          showToast("⚠️ Erreur réseau", "#dc3545");
        }
      });
    });

    // 🌈 Feedback visuel
    console.log("🔄 Ligne mise à jour");
    tr.style.transition = "background 0.5s";
    tr.style.background = "#e8ffe8";
    setTimeout(() => (tr.style.background = ""), 800);

    // 🪄 Aligne verticalement
    tr.style.verticalAlign = "middle";
    tr.querySelectorAll("td").forEach(td => (td.style.verticalAlign = "middle"));

    // 👉 MET À JOUR LES KPI IMMÉDIATEMENT
    await refreshKPI();
    
  } catch (err) {
    console.warn("Erreur refreshRow:", err);
  }
}


// =====================================================
// ⚙️ Délégation globale pour le bouton "Actions"
// =====================================================
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".action-btn");
  if (!btn) return;
  const id = btn.dataset.id;
  const commentaire = btn.dataset.commentaire || "";
  openActionsModal(id, commentaire);
});

// =====================================================
// 🟩 ACTIVATION INITIALE DES ÉTIQUETTES (checkboxes)
// =====================================================
document.addEventListener("DOMContentLoaded", () => {
  const checkboxes = document.querySelectorAll(".chk");
  console.log("✅ Initialisation des étiquettes :", checkboxes.length);

  checkboxes.forEach(chk => {
chk.addEventListener("change", async (e) => {
  let ligne = e.target.closest("tr");      // ✅ <-- ici : c’est bien "let ligne" et PAS "const tr"
  const id = ligne.dataset.id;
  const field = e.target.dataset.field;
  const value = e.target.checked ? 1 : 0;


      try {
        const res = await fetch("/admin/update-field", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ id, field, value })
        });
        const data = await res.json();
        if (data.ok) {
          console.log(`💾 ${field} mis à jour pour ${id}`);
          showToast("💾 Étiquette sauvegardée", "#28a745");
        } else {
          showToast("⚠️ Erreur de sauvegarde", "#dc3545");
        }
      } catch (err) {
        showToast("❌ Erreur réseau", "#dc3545");
        console.error(err);
      }
    });
  });
});

async function onStatusChange(sel) {
  const tr = sel.closest('tr');
  if (!tr) return;

  const id = tr.dataset.id;
  const value = sel.value;

  // 🟢 Couleur immédiate
  if (window.updateStatusColor) {
    window.updateStatusColor(sel);
  }

  // 💾 Envoi du nouveau statut au backend
  const res = await fetch('/admin/update-status', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ id, value })
  });

  if (!res.ok) {
    showToast("❌ Erreur de mise à jour du statut", "#dc3545");
    return;
  }

  const data = await res.json();

  // ✅ Met à jour visuellement les colonnes concernées sans reload
  if (data.ok) {
    // -- met à jour la couleur du select --
    if (window.updateStatusColor) {
      window.updateStatusColor(sel);
    }

    // -- met à jour les colonnes de date si elles existent --
    if (data.date_validee) {
      const cell = tr.querySelector(".col-date-validee");
      if (cell) cell.textContent = new Date(data.date_validee).toLocaleDateString("fr-FR");
    }
    if (data.date_confirmee) {
      const cell = tr.querySelector(".col-date-confirmee");
      if (cell) cell.textContent = new Date(data.date_confirmee).toLocaleDateString("fr-FR");
    }
    if (data.date_reconfirmee) {
      const cell = tr.querySelector(".col-date-reconfirmee");
      if (cell) cell.textContent = new Date(data.date_reconfirmee).toLocaleDateString("fr-FR");
    }

    // -- si le badge "relance" existe et que le candidat est confirmé/reconfirmé, on le supprime --
    if (["confirmee", "reconfirmee", "validee"].includes(data.statut)) {
      const badge = tr.querySelector(".badge-relance");
      if (badge) badge.remove();
    }

    // -- met à jour le texte de statut s’il y a une colonne dédiée --
    const colStatusText = tr.querySelector(".col-statut-text");
    if (colStatusText) {
      colStatusText.textContent = value.replace("_", " ");
    }

    await refreshRow(id);
    showToast("📊 Statut mis à jour avec succès", "#007bff");
    tr.classList.add("status-updated");
    setTimeout(() => tr.classList.remove("status-updated"), 1500);
  } else {
    showToast("⚠️ Erreur de réponse serveur", "#dc3545");
  }
}

// =====================================================
// 📊 CHARGEMENT DES STATISTIQUES ADMIN
// =====================================================
async function loadAdminStats() {
  try {
    const res = await fetch("/admin/stats");
    const data = await res.json();
    if (!data.ok) return;

    const s = data.stats;

    document.getElementById("st_pre").textContent = s.preinscription;
    document.getElementById("st_val").textContent = s.validee;
    document.getElementById("st_conf").textContent = s.confirmee;
    document.getElementById("st_reconf").textContent = s.reconf_en_cours;
    document.getElementById("st_reconf2").textContent = s.reconfirmee;
    document.getElementById("st_ann").textContent = s.annulee;
    document.getElementById("st_docs").textContent = s.docs_non_conformes;

  } catch (err) {
    console.error("Erreur stats admin :", err);
  }
}

// 🔄 Charge au démarrage
document.addEventListener("DOMContentLoaded", loadAdminStats);

function updateRowCount() {
    const tbody = document.querySelector(".admin-table tbody");
    if (!tbody) return;

    // On compte uniquement les lignes visibles
    const count = Array.from(tbody.querySelectorAll("tr"))
        .filter(tr => tr.style.display !== "none")
        .length;

    const el = document.getElementById("rowCount");
    if (el) {
        el.textContent = `📊 ${count} ligne${count > 1 ? "s" : ""} affichée${count > 1 ? "s" : ""}`;
    }
}

// 🟢 Recalcule le nombre de lignes après chaque rechargement lié aux filtres
document.addEventListener("DOMContentLoaded", () => {
    updateRowCount();
});

































































document.addEventListener("click", async (e) => {
  const btn = e.target.closest(".ypareo-af-finalize-btn");
  if (!btn) return;
  const id = btn.dataset.id;
  const wrapper = btn.closest(".ypareo-af-finalize");
  const input = wrapper?.querySelector(".ypareo-af-url-input");
  const errorDetail = btn.parentElement?.parentElement?.querySelector(".ypareo-error-detail");
  const oldText = btn.textContent;
  btn.disabled = true;
  btn.textContent = "⏳ Finalisation…";
  if (errorDetail) errorDetail.style.display = "none";
  try {
    const response = await fetch(`/admin/ypareo-neo/${encodeURIComponent(id)}/finaliser-af`, {
      method: "POST",
      headers: { "Accept": "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({ ypareo_af_url_affectation: input?.value || "" })
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok || !data.ok) throw new Error(data.error || `Erreur HTTP ${response.status}`);
    btn.textContent = "✅ AF rattachée";
    btn.style.background = "#28a745";
    wrapper?.remove();
    showToast(data.message || "✅ AF YPAREO finalisée", "#28a745");
  } catch (error) {
    btn.disabled = false;
    btn.textContent = oldText;
    if (errorDetail) {
      errorDetail.textContent = error.message;
      errorDetail.style.display = "block";
    }
    showToast(`❌ ${error.message}`, "#dc3545");
  }
});

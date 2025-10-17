window.currentId = null;
// === Gestion fluide + verrouillage + icônes visuelles des onglets ===
document.addEventListener("DOMContentLoaded", () => {

  const tabButtons = document.querySelectorAll('.tabs button');
  const tabs = document.querySelectorAll('.tab');
  let currentStep = 0;

  // === 🔢 Barre de progression (liée aux onglets) — avec texte correct et animation fluide ===
  function updateProgressBar(index) {
    const progress = document.getElementById("progressBar");
    const info = document.getElementById("progressInfo");
    if (!progress || !info) return;

    const total = tabs.length;
    const targetPercent = ((index + 1) / total) * 100;
    const currentWidth = parseFloat(progress.style.width) || 0;
    const step = (targetPercent - currentWidth) / 20;
    let currentPercent = currentWidth;

    const animate = () => {
      currentPercent += step;
      if ((step > 0 && currentPercent >= targetPercent) || (step < 0 && currentPercent <= targetPercent)) {
        currentPercent = targetPercent;
      } else {
        requestAnimationFrame(animate);
      }

      progress.style.width = currentPercent + "%";
      info.textContent = `Étape ${index + 1} sur ${total} — ${Math.round(((index + 1) / total) * 100)} % complété`;
    };

    animate();
  }

  // --- Fonction d’affichage des étapes ---
  function showStep(index) {
    tabs.forEach((tab, i) => {
      tab.style.display = (i === index) ? 'block' : 'none';
      tab.style.opacity = (i === index) ? '1' : '0';
      tab.classList.toggle('active', i === index);
    });

    tabButtons.forEach((btn, i) => {
      btn.classList.toggle('active', i === index);
      if (i < index) {
        btn.classList.add('completed');
        btn.classList.remove('locked');
      } else if (i === index) {
        btn.classList.remove('completed', 'locked');
      } else {
        btn.classList.add('locked');
        btn.classList.remove('completed');
      }
    });

    currentStep = index;
    updateProgressBar(index);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // --- Validation d’une étape ---
  function validateStep(stepIndex) {
    const currentTab = tabs[stepIndex];
    const inputs = currentTab.querySelectorAll('input, select, textarea');
    for (let input of inputs) {
      if (!input.checkValidity()) {
        input.reportValidity();
        return false;
      }
    }
    return true;
  }

  // --- Clic sur un onglet ---
  tabButtons.forEach((btn, i) => {
    btn.addEventListener('click', (e) => {
      e.preventDefault();
      if (i > currentStep) {
        alert("⚠️ Merci de compléter les étapes précédentes avant de continuer.");
        return;
      }
      showStep(i);
    });
  });

  // --- Étape suivante / précédente ---
  document.querySelectorAll('.next').forEach(btn => {
    btn.addEventListener('click', () => {
      if (validateStep(currentStep)) {
        currentStep++;
        if (currentStep >= tabs.length) currentStep = tabs.length - 1;
        showStep(currentStep);
      }
    });
  });

  document.querySelectorAll('.prev').forEach(btn => {
    btn.addEventListener('click', () => {
      currentStep--;
      if (currentStep < 0) currentStep = 0;
      showStep(currentStep);
    });
  });

  showStep(0); // affiche la première étape au chargement

  // === Vérification e-mail ===
  const email = document.querySelector('input[name="email"]');
  const email2 = document.querySelector('input[name="email_confirm"]');
  if (email && email2) {
    const check = () => {
      if (email.value && email2.value && email.value !== email2.value) {
        email2.setCustomValidity("⚠️ Les adresses e-mail ne correspondent pas.");
      } else {
        email2.setCustomValidity("");
      }
    };
    email.addEventListener('input', check);
    email2.addEventListener('input', check);
  }

  // === Affichage si mineur ===
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
  if (birth) birth.addEventListener('change', updateMinor);

  // === Validation fichiers PDF ===
  const form = document.querySelector('form');
  if (form) {
    form.addEventListener('submit', (e) => {
      const pdfOnlyFields = ['carte_vitale', 'cv', 'lm'];
      for (const name of pdfOnlyFields) {
        const input = form.querySelector(`input[name="${name}"]`);
        if (input && input.files.length > 0) {
          const file = input.files[0];
          if (!file.name.toLowerCase().endsWith('.pdf')) {
            e.preventDefault();
            alert(`❌ Le fichier "${file.name}" doit être au format PDF.`);
            return;
          }
        } else if (input && input.hasAttribute('required') && input.files.length === 0) {
          e.preventDefault();
          alert(`⚠️ Le champ "${name}" est obligatoire.`);
          return;
        }
      }
    });
  }

  // === Gestion ADMIN (tableau) ===
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

  // === Sélection visuelle du mode (présentiel / distanciel) ===
  const modeBtns = document.querySelectorAll('.mode-btn');
  modeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      modeBtns.forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
    });
  });

  // === 📎 Gestion des pièces justificatives (modale admin) ===
  const filesModal = document.getElementById("filesModal");
  if (filesModal) {

    // 📦 Télécharger toutes les pièces
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

  // 🔁 Rafraîchir le statut dans le tableau
  await refreshCandidateStatus(window.currentId);

  // 🔄 Rafraîchir visuellement la modale
  setTimeout(() => {
    openFilesModal(window.currentId);
  }, 500);
} else {
  alert("Erreur : " + (data.error || "inconnue"));
  btn.disabled = false;
  btn.textContent = decision === "conforme" ? "✅ Conforme" : "❌ Non conforme";
}


  // === 📥 Vérifie les "nouveaux documents" dans le tableau ===
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

}); // fin du DOMContentLoaded


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

function closeFilesModal() {
  const modal = document.getElementById("filesModal");
  if (modal) modal.classList.add("hidden");
}




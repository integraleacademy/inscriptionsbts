// === Intégrale Academy – JS global (Front + Admin) ===
window.currentId = null;

document.addEventListener("DOMContentLoaded", () => {

  // === Écran d’intro avant formulaire ===
  const intro = document.getElementById("intro-screen");
  const formContainer = document.querySelector(".tabs-form");

  if (intro && formContainer) {
    formContainer.style.display = "none";
    document.getElementById("startForm").addEventListener("click", () => {
      intro.style.display = "none";
      formContainer.style.display = "block";
      window.scrollTo({ top: 0, behavior: "smooth" });
    });
  }

  // =====================================================
  // 🌐 NAVIGATION FORMULAIRE PUBLIC
  // =====================================================
  const tabButtons = document.querySelectorAll('.tabs button');
  const tabs = document.querySelectorAll('.tab');
  const progress = document.getElementById("progressBar");
  const info = document.getElementById("progressInfo");
  let currentStep = 0;

  // === Création unique des cadenas (zéro doublon) ===
  tabButtons.forEach((btn) => {
    btn.querySelectorAll(".lock-icon").forEach(e => e.remove());
    const lockIcon = document.createElement("span");
    lockIcon.textContent = " 🔒";
    lockIcon.classList.add("lock-icon");
    btn.appendChild(lockIcon);
  });

  function refreshLocks() {
    tabButtons.forEach((btn, i) => {
      const icon = btn.querySelector(".lock-icon");
      if (i > currentStep) {
        btn.classList.add("locked");
        if (icon) icon.style.display = "inline";
      } else {
        btn.classList.remove("locked");
        if (icon) icon.style.display = "none";
      }
    });
  }

  // === Barre de progression ===
  function updateProgressBar(index) {
    if (!progress || !info) return;
    const total = tabs.length;
    const percent = ((index + 1) / total) * 100;
    progress.style.width = percent + "%";
    info.textContent = `Étape ${index + 1} sur ${total} — ${Math.round(percent)} % complété`;
  }

  // === Affichage d’une étape ===
  function showStep(index) {
    tabs.forEach((tab, i) => {
      tab.style.display = (i === index) ? 'block' : 'none';
      tab.classList.toggle('active', i === index);
    });
    tabButtons.forEach((btn, i) => {
      btn.classList.toggle('active', i === index);
      if (i < index) btn.classList.add('completed');
      else btn.classList.remove('completed');
    });
    currentStep = index;
    updateProgressBar(index);
    refreshLocks();
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // === Validation des champs ===
  function validateStep(stepIndex) {
    const currentTab = tabs[stepIndex];
    const inputs = currentTab.querySelectorAll('input, select, textarea');
    let valid = true;

    for (let input of inputs) {
      const style = window.getComputedStyle(input);
      const visible = style.display !== 'none' && style.visibility !== 'hidden';
      if (!visible) continue;
      if (!input.checkValidity()) {
        input.classList.add('invalid');
        input.reportValidity();
        valid = false;
      } else {
        input.classList.remove('invalid');
      }
    }

    // 🔎 Vérifie aussi le NIR sur la 1ʳᵉ étape
    if (stepIndex === 0 && typeof verifierNumSecu === "function") {
      const nirOK = verifierNumSecu();
      if (!nirOK) valid = false;
    }

    return valid;
  }

  // === Navigation avec clics sur onglets ===
  tabButtons.forEach((btn, i) => {
    btn.addEventListener("click", (e) => {
      e.preventDefault();
      if (i > currentStep) {
        alert("⚠️ Merci de compléter les étapes précédentes avant de continuer.");
        return;
      }
      showStep(i);
    });
  });

  // === Boutons Suivant / Précédent ===
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

  // === Vérif e-mail ===
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

  // === Bloc mineur ===
  const birth = document.querySelector('input[name="date_naissance"]');
  const blocResp = document.getElementById('bloc-resp-legal');
  const hiddenMineur = document.getElementById('est_mineur');
  const updateMinor = () => {
    if (!birth || !birth.value) return;
    const d = new Date(birth.value);
    const today = new Date();
    let age = today.getFullYear() - d.getFullYear();
    const m = today.getMonth() - d.getMonth();
    if (m < 0 || (m === 0 && today.getDate() < d.getDate())) age--;
    if (blocResp) blocResp.style.display = (age < 18) ? 'block' : 'none';
    if (hiddenMineur) hiddenMineur.value = (age < 18) ? '1' : '0';
  };
  if (birth) {
    birth.addEventListener('change', updateMinor);
    if (birth.value) updateMinor(); // ✅ met à jour si date déjà remplie
  }

  // === Sélection Présentiel / Distanciel ===
  const modeBtns = document.querySelectorAll('.mode-btn');
  modeBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      modeBtns.forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
      const radio = btn.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;
    });
  });

  // === Vérif fichiers PDF + NIR avant envoi ===
  const form = document.querySelector('#inscriptionForm');
  if (form) {
    form.addEventListener('submit', (e) => {
      // Vérifie NIR
      if (typeof verifierNumSecu === "function" && !verifierNumSecu()) {
        e.preventDefault();
        alert("❌ Votre numéro de sécurité sociale est incohérent. Veuillez le corriger avant de continuer.");
        showStep(0);
        return;
      }

      // Vérifie qu'un mode est choisi
      const modeSelected = document.querySelector('input[name="mode"]:checked');
      if (!modeSelected) {
        e.preventDefault();
        alert("⚠️ Merci de choisir un mode de formation.");
        return;
      }

      // Vérif fichiers PDF
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
        }
      }

      // === Affiche l’overlay de transmission ===
      const overlay = document.createElement("div");
      overlay.className = "sending-overlay";
      overlay.innerHTML = `
        <div class="sending-box">
          <div class="loader"></div>
          <h3>⏳ Pré-inscription en cours de transmission...</h3>
          <p>Merci de ne pas fermer la page pendant l’envoi.</p>
        </div>`;
      document.body.appendChild(overlay);
    });
  }

  // =====================================================
  // 💾 ENREGISTRER ET REPRENDRE PLUS TARD
  // =====================================================
  document.querySelectorAll('.btn.save').forEach(btn => {
    btn.addEventListener('click', async () => {
      const form = document.querySelector('#inscriptionForm');
      const formData = new FormData(form);
      formData.append('current_step', currentStep);

      try {
        const response = await fetch('/save_draft', {
          method: 'POST',
          body: formData
        });

        if (response.ok) {
          showFlash("✅ Votre demande a été enregistrée. Un e-mail vous a été envoyé pour la reprendre plus tard.", "success");
        } else {
          showFlash("❌ Erreur lors de l'enregistrement. Veuillez réessayer.", "error");
        }
      } catch {
        showFlash("❌ Une erreur est survenue. Vérifiez votre connexion.", "error");
      }
    });
  });

  function showFlash(message, type = "success") {
    const flash = document.getElementById("flashMessage");
    if (!flash) return;
    flash.textContent = message;
    flash.className = `flash-message ${type} visible`;
    setTimeout(() => {
      flash.classList.remove("visible");
      flash.classList.add("hidden");
    }, 6000);
  }

  // ✅ Rendez les fonctions accessibles globalement
  window.showStep = showStep;
  window.getCurrentStep = () => currentStep;

  refreshLocks();
  showStep(0);
});

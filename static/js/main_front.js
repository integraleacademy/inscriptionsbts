// === Intégrale Academy – JS global (Front + Admin) ===
window.currentId = null;

document.addEventListener("DOMContentLoaded", () => {

  // === Écran d’intro avant formulaire ===
const intro = document.getElementById("intro-screen");
const formContainer = document.querySelector(".tabs-form");

if (intro && formContainer) {
  formContainer.style.display = "none"; // cache le formulaire au départ
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

  // === Barre de progression ===
  function updateProgressBar(index) {
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

  // === Affichage des étapes ===
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
    refreshLocks(); // 🔒 maj des cadenas
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // === Validation des champs ===
function validateStep(stepIndex) {
  const currentTab = tabs[stepIndex];
  const inputs = currentTab.querySelectorAll('input, select, textarea');

  for (let input of inputs) {
    const style = window.getComputedStyle(input);
    const visible = style.display !== 'none' && style.visibility !== 'hidden';
    if (!visible) continue; // ignore les champs masqués

    if (!input.checkValidity()) {
      input.reportValidity();
      return false;
    }
  }
  return true;
}


  // === Cadenas sur les boutons d’étapes (version corrigée) ===
  tabButtons.forEach((btn, i) => {
    // Empêche la création de plusieurs icônes 🔒
    if (!btn.querySelector(".lock-icon")) {
      const lockIcon = document.createElement("span");
      lockIcon.textContent = " 🔒";
      lockIcon.classList.add("lock-icon");
      btn.appendChild(lockIcon);
    }

    btn.addEventListener("click", (e) => {
      e.preventDefault();
      if (i > currentStep) {
        btn.classList.add("locked");
        alert("⚠️ Merci de compléter les étapes précédentes avant de continuer.");
        return;
      }
      showStep(i);
    });
  });

  function refreshLocks() {
    tabButtons.forEach((btn, i) => {
      const icon = btn.querySelector(".lock-icon");
      if (!icon) return;
      if (i > currentStep) {
        btn.classList.add("locked");
        icon.style.display = "inline";
      } else {
        btn.classList.remove("locked");
        icon.style.display = "none";
      }
    });
  }

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
  if (birth) birth.addEventListener('change', updateMinor);

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

  // === Vérif fichiers PDF ===
  const form = document.querySelector('form');
  if (form) {
    form.addEventListener('submit', (e) => {
          // Vérifie qu'un mode de formation est choisi (présentiel / distanciel)
    const modeSelected = document.querySelector('input[name="mode"]:checked');
    if (!modeSelected) {
      e.preventDefault();
      alert("⚠️ Merci de choisir un mode de formation (présentiel ou distanciel).");
      return;
    }

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
    });
  }

  // =====================================================
  // 🎓 LOGIQUE SPÉCIFIQUE BTS MOS (CNAPS / APS)
  // =====================================================
  const btsSelect = document.querySelector('select[name="bts"]');
  const mosSection = document.getElementById('mos-section');
  const blocBacAutre = document.getElementById('bloc-bac-autre');
  const mosExplication = document.getElementById('mos-explication');
  const apsCheckbox = document.querySelector('input[name="aps_souhaitee"]');
  const apsBloc = document.getElementById('bloc-aps-session');

  // --- Afficher le bloc MOS quand le BTS MOS est choisi
  if (btsSelect) {
    btsSelect.addEventListener('change', () => {
      if (btsSelect.value === 'MOS') {
        mosSection.style.display = 'block';
      } else {
        mosSection.style.display = 'none';
      }
    });
  }

  // --- Afficher "autre bac" et CNAPS
  const bacRadios = document.querySelectorAll('input[name="bac_status"]');
  bacRadios.forEach(r => {
    r.addEventListener('change', () => {
      if (r.value === 'autre') {
        blocBacAutre.style.display = 'block';
      } else {
        blocBacAutre.style.display = 'none';
      }
      // Si CNAPS ou autre => explication MOS
      if (r.value === 'carte_cnaps' || r.value === 'autre') {
        mosExplication.style.display = 'block';
      } else {
        mosExplication.style.display = 'none';
      }
    });
  });

  // --- Bloc APS : apparition si case cochée
  if (apsCheckbox && apsBloc) {
    apsCheckbox.addEventListener('change', () => {
      apsBloc.style.display = apsCheckbox.checked ? 'block' : 'none';
    });
  }

 // =====================================================
// 💾 ENREGISTRER ET REPRENDRE PLUS TARD (avec bannière visuelle)
// =====================================================
document.querySelectorAll('.btn.save').forEach(btn => {
  btn.addEventListener('click', async () => {
    const form = document.querySelector('#inscriptionForm');
    const formData = new FormData(form);
    const flash = document.getElementById("flashMessage");

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
    } catch (e) {
      showFlash("❌ Une erreur est survenue. Vérifiez votre connexion.", "error");
    }
  });
});

// --- Fonction d’affichage du message dynamique ---
function showFlash(message, type = "success") {
  const flash = document.getElementById("flashMessage");
  if (!flash) return;
  flash.textContent = message;
  flash.className = `flash-message ${type} visible`;
  setTimeout(() => {
    flash.classList.remove("visible");
    flash.classList.add("hidden");
  }, 6000); // disparaît après 6 secondes
}



}); // ✅ fermeture DOMContentLoaded








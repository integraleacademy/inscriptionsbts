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
    injectSupportInto(tabs[index]);
    injectFooter(tabs[index]);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }

  // === Validation des champs (renforcée) ===
  function validateStep(stepIndex) {
    const currentTab = tabs[stepIndex];
    const inputs = currentTab.querySelectorAll('input, select, textarea');
    let valid = true;

    // Vérifie tous les champs visibles
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

    // 🔹 Étape 1 : vérif NIR
    if (stepIndex === 0 && typeof verifierNumSecu === "function") {
      if (!verifierNumSecu()) valid = false;
    }

// 🔹 Étape 2 : BTS + mode obligatoires
if (stepIndex === 1) {
  const bts = document.querySelector('select[name="bts"]');
  const mode = document.querySelector('input[name="mode"]:checked');

  if (!bts?.value) {
    alert("⚠️ Merci de choisir une formation BTS avant de continuer.");
    valid = false;
  }
  if (!mode) {
    alert("⚠️ Merci de choisir un mode de formation (présentiel ou distanciel).");
    valid = false;
  }

  // ✅ Une case “niveau de bac” doit être cochée
  const bacStatusChecked = document.querySelector('input[name="bac_status"]:checked');
  if (!bacStatusChecked) {
    alert("⚠️ Merci d’indiquer votre situation (Bac Pro MS, en cours, carte CNAPS ou autre).");
    valid = false;
  }

  // ✅ Si APS = "oui", une session doit être choisie
  const apsOui = document.querySelector('input[name="aps_souhaitee"][value="oui"]:checked');
  if (apsOui) {
    const apsSelected = document.querySelector('input[name="aps_session"]:checked');
    if (!apsSelected) {
      alert("⚠️ Merci de sélectionner une session APS avant de continuer.");
      valid = false;
    }
  }

  // ✅ Si APS = "non", la raison devient obligatoire
  const apsNon = document.querySelector('input[name="aps_souhaitee"][value="non"]:checked');
  if (apsNon) {
    const raison = document.querySelector('textarea[name="raison_aps"]');
    if (!raison || !raison.value.trim()) {
      alert("⚠️ Merci de préciser la raison pour laquelle vous ne souhaitez pas suivre la formation APS.");
      raison.focus();
      valid = false;
    }
  }
}
 

// 🔹 Étape 3 : bac + permis
if (stepIndex === 2) {
  const bacType = document.querySelector('select[name="bac_type"]');
  const bacAutre = document.querySelector('input[name="bac_autre"]');
  if (bacType && bacType.value === "Autre" && !bacAutre.value.trim()) {
    alert("⚠️ Merci de préciser votre type de bac.");
    bacAutre.focus();
    valid = false;
  }
  const permis = document.querySelector('select[name="permis_b"]');
  if (!permis?.value) {
    alert("⚠️ Merci d’indiquer si vous possédez le permis B.");
    valid = false;
  }

  // ✅ Étape 3 : type de bac obligatoire
  const bacTypeSelect = document.querySelector('select[name="bac_type"]');
  if (!bacTypeSelect?.value) {
    alert("⚠️ Merci de sélectionner le type de Bac obtenu.");
    valid = false;
  }
}



    // 🔹 Étape 4 : projet motivé complet
    if (stepIndex === 3) {
      const champs = ['projet_pourquoi', 'projet_objectif', 'projet_passions'];
      for (let nom of champs) {
        const field = document.querySelector(`textarea[name="${nom}"]`);
        if (!field?.value.trim()) {
          alert("⚠️ Merci de compléter toutes les réponses du projet motivé.");
          field.focus();
          valid = false;
          break;
        }
      }
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

      // ✅ Vérif téléphone
      const tel = document.querySelector('input[name="tel"]');
      if (tel && /^0{10}$/.test(tel.value)) {
        e.preventDefault();
        alert("⚠️ Numéro de téléphone invalide.");
        tel.focus();
        return;
      }

      // ✅ Vérif BTS choisi
      const btsSelect = document.querySelector('select[name="bts"]');
      if (btsSelect && !btsSelect.value) {
        e.preventDefault();
        alert("⚠️ Merci de sélectionner une formation BTS avant de continuer.");
        showStep(1);
        return;
      }

      // ✅ Vérif Bac “Autre” précisé
      const bacType = document.querySelector('select[name="bac_type"]');
      const bacAutre = document.querySelector('input[name="bac_autre"]');
      if (bacType && bacAutre && bacType.value === "Autre" && !bacAutre.value.trim()) {
        e.preventDefault();
        alert("⚠️ Merci de préciser votre type de bac.");
        bacAutre.focus();
        return;
      }

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
          // ✅ Vérif fichier vide
          if (file.size < 10 * 1024) {
            e.preventDefault();
            alert(`⚠️ Le fichier "${file.name}" semble vide ou corrompu.`);
            return;
          }
        }
      }

      // === Vérif spécifique APS ===
      const apsCheckbox = document.querySelector('input[name="aps_souhaitee"]');
      const apsSessions = document.querySelectorAll('input[name="aps_session"]');
      if (apsCheckbox && apsSessions.length > 0) {
        const apsSelected = Array.from(apsSessions).some(r => r.checked);
        if (apsCheckbox.checked && !apsSelected) {
          e.preventDefault();
          alert("⚠️ Merci de sélectionner une session APS avant de continuer.");
          const mosSection = document.getElementById('mos-section');
          if (mosSection) mosSection.scrollIntoView({ behavior: "smooth", block: "start" });
          return;
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

  // === Assistance globale (améliorée et centrée) ===
  function injectSupportInto(tab) {
    if (!tab.querySelector('.support-box')) {
      const box = document.createElement('div');
      box.className = 'support-box';
      box.innerHTML = `
        <div class="support-content">
          <h4>🧩 Besoin d’aide ?</h4>
          <p>Notre équipe est disponible pour vous accompagner :</p>
          <a href="https://assistance-alw9.onrender.com/" target="_blank" rel="noopener" class="support-btn">Cliquez ici</a>
          <p class="support-phone">📞 04&nbsp;22&nbsp;47&nbsp;07&nbsp;68</p>
        </div>
      `;
      tab.appendChild(box);
    }
  }


    // === Mention bas de page ===
  function injectFooter(tab) {
    if (!tab.querySelector('.footer-signature')) {
      const footer = document.createElement('div');
      footer.className = 'footer-signature';
      footer.innerHTML = `
        <p>❤️ Site internet créé et développé par <strong>Intégrale&nbsp;Group</strong></p>
      `;
      tab.appendChild(footer);
    }
  }

  // === Étape 3 : afficher / rendre obligatoire le champ "Autre bac" ===
  const bacTypeSelectEl = document.querySelector('select[name="bac_type"]');
  const blocBacAutreEl  = document.getElementById('bloc-bac-autre');
  const bacAutreInput   = document.querySelector('input[name="bac_autre"]');

  function toggleBacAutre() {
    if (!bacTypeSelectEl || !blocBacAutreEl || !bacAutreInput) return;
    const isAutre = bacTypeSelectEl.value === "Autre";
    blocBacAutreEl.style.display = isAutre ? "block" : "none";
    bacAutreInput.required = isAutre;
    if (!isAutre) bacAutreInput.value = "";
  }
  if (bacTypeSelectEl) {
    bacTypeSelectEl.addEventListener('change', toggleBacAutre);
    toggleBacAutre();
  }

  refreshLocks();
  showStep(0);
});



// =====================================================
// 🎓 LOGIQUE SPÉCIFIQUE BTS MOS (CNAPS / APS)
// =====================================================
const btsSelect = document.querySelector('select[name="bts"]');
const formationInfo = document.getElementById("formation-info");

if (btsSelect && formationInfo) {
  const infos = {
    "MOS": `
      <h4>🎓 BTS MOS – Management Opérationnel de la Sécurité</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38229</strong>.</p>
      <p>Ce BTS forme les futurs responsables d’équipes de sécurité privée (surveillance, prévention, sûreté, incendie...)</p>
      <p><strong>Durée :</strong> 2 ans — <strong>Examens officiels</strong> sous tutelle du Ministère de l’Éducation nationale.</p>
    `,
    "MCO": `
      <h4>🎓 BTS MCO – Management Commercial Opérationnel</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38362</strong>.</p>
      <p>Ce BTS prépare aux métiers du commerce, de la gestion et du management d’équipe dans tous les secteurs d’activité.</p>
    `,
    "PI": `
      <h4>🏡 BTS PI – Professions Immobilières</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38292</strong>.</p>
      <p>Ce BTS forme les futurs négociateurs, gestionnaires et conseillers immobiliers pour agences et syndics.</p>
    `,
    "CI": `
      <h4>🌍 BTS CI – Commerce International</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38365</strong>.</p>
      <p>Ce BTS ouvre à des carrières à l’international : import-export, prospection, négociation et logistique internationale.</p>
    `,
    "NDRC": `
      <h4>🤝 BTS NDRC – Négociation et Digitalisation de la Relation Client</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38368</strong>.</p>
      <p>Formation orientée sur la relation client, la vente et le marketing digital. Idéale pour les profils commerciaux modernes.</p>
    `,
    "CG": `
      <h4>📊 BTS CG – Comptabilité et Gestion</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38329</strong>.</p>
      <p>Ce BTS prépare aux métiers de la gestion comptable, du contrôle et de la finance d’entreprise.</p>
    `
  };

  btsSelect.addEventListener("change", () => {
    const val = btsSelect.value;
    if (infos[val]) {
      formationInfo.innerHTML = infos[val];
      formationInfo.style.display = "block";
    } else {
      formationInfo.style.display = "none";
      formationInfo.innerHTML = "";
    }

    // 🟢 Affiche le bloc MOS si sélectionné
    const mosSection = document.getElementById('mos-section');
    if (mosSection) mosSection.style.display = (val === 'MOS') ? 'block' : 'none';
  });
}

const blocBacAutre = document.getElementById('bloc-bac-autre');
const mosExplication = document.getElementById('mos-explication');
const apsCheckbox = document.querySelector('input[name="aps_souhaitee"]');
const apsBloc = document.getElementById('bloc-aps-session');

// --- Afficher "autre bac" et CNAPS ---
const bacRadios = document.querySelectorAll('input[name="bac_status"]');
bacRadios.forEach(r => {
  r.addEventListener('change', () => {
    if (r.value === 'autre') {
      blocBacAutre.style.display = 'block';
    } else {
      blocBacAutre.style.display = 'none';
    }
    if (r.value === 'carte_cnaps' || r.value === 'autre') {
      mosExplication.style.display = 'block';
    } else {
      mosExplication.style.display = 'none';
    }
  });
});

// === Bloc APS : apparition selon le choix Oui / Non ===
const apsRadios = document.querySelectorAll('input[name="aps_souhaitee"]');
const apsSessionBloc = document.getElementById('bloc-aps-session');
const raisonBloc = document.getElementById('raison-non-aps');
const raisonInput = document.querySelector('textarea[name="raison_aps"]');

apsRadios.forEach(radio => {
  radio.addEventListener('change', () => {
    if (radio.value === "oui") {
      apsSessionBloc.style.display = "block";
      raisonBloc.style.display = "none";
      raisonInput.required = false;
      apsSessionBloc.querySelectorAll('input[name="aps_session"]').forEach(r => r.required = true);
    } else if (radio.value === "non") {
      apsSessionBloc.style.display = "none";
      apsSessionBloc.querySelectorAll('input[name="aps_session"]').forEach(r => r.checked = false);
      raisonBloc.style.display = "block";
      raisonInput.required = true;
    }
  });
});






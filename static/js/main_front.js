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
  if (!tabs.length) return; // ✅ empêche toute exécution si tabs n’existe pas

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

  // ✅ Sécurise les appels (aucune erreur si tab inexistant)
  if (tabs[index]) {
    if (typeof injectSupportInto === "function") injectSupportInto(tabs[index]);
    if (typeof injectFooter === "function") injectFooter(tabs[index]);
  }

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
  // ✅ Ignore tous les champs qui ne sont pas dans l’onglet actif
const isInCurrentTab = input.closest('.tab') === currentTab;
if (!isInCurrentTab) continue;


  // ✅ Ignore les radios non requis OU sans attribut "name"
  if (input.type === "radio" && (!input.required || !input.name)) continue;

  // ✅ Ignore aussi les checkboxes non requis
  if (input.type === "checkbox" && !input.required) continue;

  if (!input.checkValidity()) {
    console.warn("⛔ Champ invalide détecté :", input.name || input.id);
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

// 🔹 Étape 2 : validation conditionnelle selon le BTS
if (stepIndex === 1) {
  const bts = document.querySelector('select[name="bts"]');
  const btsVal = bts?.value || "";
  const mode = document.querySelector('input[name="mode"]:checked');

  if (!btsVal) {
    alert("⚠️ Merci de choisir une formation BTS avant de continuer.");
    valid = false;
  }

  if (!mode) {
    alert("⚠️ Merci de choisir un mode de formation (présentiel ou distanciel).");
    valid = false;
  }

  // ✅ Les conditions suivantes ne concernent que le BTS MOS
  if (btsVal === "MOS") {
    const bacStatusChecked = document.querySelector('input[name="bac_status"]:checked');
    if (!bacStatusChecked) {
      alert("⚠️ Merci d’indiquer votre situation (Bac Pro MS, en cours, carte CNAPS ou autre).");
      valid = false;
    }

    const statut = bacStatusChecked?.value;

    // 🟡 Si le candidat a coché "autre", il doit choisir Oui ou Non APS
if (statut === "autre") {
  const apsOui = document.querySelector('input[name="aps_souhaitee"][value="oui"]:checked');
  const apsNon = document.querySelector('input[name="aps_souhaitee"][value="non"]:checked');
  if (!apsOui && !apsNon) {
    alert("⚠️ Merci d’indiquer si vous souhaitez suivre la formation APS.");
    valid = false;
  }
}


    // 🎯 Si carte CNAPS => pas de validation APS requise
    if (statut === "carte_cnaps") {
      const apsSessionBloc = document.getElementById('bloc-aps-session');
      if (apsSessionBloc) apsSessionBloc.style.display = "none";
      document.querySelectorAll('input[name="aps_session"]').forEach(r => {
        r.required = false;
        r.checked = false;
      });
      const raisonBloc = document.getElementById('raison-non-aps');
      const raisonInput = document.querySelector('textarea[name="raison_aps"]');
      if (raisonBloc) raisonBloc.style.display = "none";
      if (raisonInput) { raisonInput.required = false; raisonInput.value = ""; }

    } else {
      // 🟢 Sinon : vérif APS normale
      const apsOui = document.querySelector('input[name="aps_souhaitee"][value="oui"]:checked');
      const apsNon = document.querySelector('input[name="aps_souhaitee"][value="non"]:checked');

      if (apsOui) {
        const apsSelected = document.querySelector('input[name="aps_session"]:checked');
        if (!apsSelected) {
          alert("⚠️ Merci de sélectionner une session APS avant de continuer.");
          valid = false;
        }
      }

      if (apsNon) {
        const raison = document.querySelector('textarea[name="raison_aps"]');
        if (!raison || !raison.value.trim()) {
          alert("⚠️ Merci de préciser la raison pour laquelle vous ne souhaitez pas suivre la formation APS.");
          raison.focus();
          valid = false;
        }
      }
    }
  }
}

 

// 🔹 Étape 3 : bac + permis
if (stepIndex === 2) {
  const bacType = document.querySelector('select[name="bac_type"]');
  const bacAutre = document.querySelector('input[name="bac_autre"]');
  const permis = document.querySelector('select[name="permis_b"]');

  // === Vérif type de bac ===
  if (!bacType || !bacType.value) {
    alert("⚠️ Merci de sélectionner votre type de bac.");
    bacType?.focus();
    valid = false;
  } else if (bacType.value === "Autre" && (!bacAutre || !bacAutre.value.trim())) {
    alert("⚠️ Merci de préciser votre type de bac (champ 'Autre').");
    bacAutre?.focus();
    valid = false;
  }

  // === Vérif permis B ===
  if (!permis?.value) {
    alert("⚠️ Merci d’indiquer si vous possédez le permis B.");
    valid = false;
  }

    // === Vérif contrat d’apprentissage ===
  const entrepriseTrouvee = document.querySelector('input[name="entreprise_trouvee"]:checked');
  const recherchesCommencees = document.querySelector('input[name="recherches_commencees"]:checked');

  if (!entrepriseTrouvee) {
    alert("⚠️ Merci d’indiquer si vous avez déjà trouvé une entreprise pour votre alternance.");
    valid = false;
  }
  if (!recherchesCommencees) {
    alert("⚠️ Merci d’indiquer si vous avez déjà commencé vos recherches d’entreprise.");
    valid = false;
  }


  // ✅ Rajoute cette ligne pour bien retourner la validation
  return valid;
}





// 🔹 Étape 4 : projet motivé complet
if (stepIndex === 3) {
  let ok = true;

  // 🟢 Vérifie les champs texte obligatoires
  const champs = ['projet_pourquoi', 'projet_objectif', 'projet_passions'];
  for (let nom of champs) {
    const field = document.querySelector(`textarea[name="${nom}"]`);
    if (!field?.value.trim()) {
      alert("⚠️ Merci de compléter toutes les réponses du projet motivé.");
      field.focus();
      ok = false;
      break;
    }
  }

  // 🟡 Vérifie qu’au moins une case est cochée dans chaque groupe
  const groupes = ['qualites[]', 'motivation[]', 'valeurs[]', 'travail[]'];
  for (let g of groupes) {
    const checkboxes = document.querySelectorAll(`input[name="${g}"]`);
    const coche = Array.from(checkboxes).some(cb => cb.checked);
    if (!coche) {
      alert("⚠️ Merci de cocher au moins une réponse dans chaque partie du projet motivé.");
      ok = false;
      break;
    }
  }

  valid = ok;
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
// 💾 ENREGISTRER ET REPRENDRE PLUS TARD (corrigé JSON)
// =====================================================
document.querySelectorAll('.btn.save').forEach(btn => {
  btn.addEventListener('click', async () => {
    const form = document.querySelector('#inscriptionForm');
    const formData = new FormData(form);
    const data = Object.fromEntries(formData.entries());
    data.current_step = currentStep;

    try {
      const res = await fetch('/save_draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      });

      const responseData = await res.json();

      if (responseData && responseData.success) {
        showFlash("✅ Données enregistrées, vous pourrez reprendre plus tard !", "success");
      } else {
        showFlash("❌ Erreur lors de l’enregistrement. Vérifiez votre connexion.", "error");
      }
    } catch (err) {
      console.error("Erreur JS SaveDraft:", err);
      showFlash("⚠️ Une erreur est survenue pendant la sauvegarde.", "error");
    }
  });
});



function showFlash(message, type = "success") {
  // Supprime toute popup existante
  document.querySelectorAll(".flash-popup").forEach(el => el.remove());

  const popup = document.createElement("div");
  popup.className = `flash-popup ${type}`;
  popup.innerHTML = `
    <div class="flash-popup-content">
      <h3>${type === "success" ? "✅ Enregistré avec succès" : "⚠️ Information"}</h3>
      <p>${message}</p>
      <p style="font-size:13px; color:#555;">📩 Un lien de reprise a été envoyé à votre adresse e-mail.</p>
      <button class="btn primary" id="closeFlash">OK</button>
    </div>
  `;
  document.body.appendChild(popup);

  document.getElementById("closeFlash").addEventListener("click", () => {
    popup.classList.add("hide");
    setTimeout(() => popup.remove(), 300);
  });
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


// function injectFooter(tab) {
//   // ❌ Supprimé pour éviter doublon avec le footer global
// }


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
  // Efface automatiquement le champ "Autre" quand on change de type de bac
if (bacTypeSelectEl) {
  bacTypeSelectEl.addEventListener('change', () => {
    if (bacTypeSelectEl.value !== "Autre") {
      bacAutreInput.value = "";
    }
  });
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
    if (r.value === 'carte_cnaps') {
  // ✅ Déjà titulaire d'une carte CNAPS → on ne montre PAS le texte explicatif
  mosExplication.style.display = 'none';
} else if (r.value === 'autre') {
  // 🟡 Cas "autre" → on montre le texte et le bloc APS
  mosExplication.style.display = 'block';
} else {
  // ❌ Tous les autres cas → on masque aussi le texte
  mosExplication.style.display = 'none';
}

  });
});

// === Affichage conditionnel du bloc APS selon le choix "Aucun de ces cas" ===
bacRadios.forEach(r => {
  r.addEventListener('change', () => {
    const apsRadiosBloc = document.getElementById('bloc-aps-radios'); // le bloc "Souhaitez-vous suivre la formation APS ?"
    const apsSessionBloc = document.getElementById('bloc-aps-session');
    const raisonBloc = document.getElementById('raison-non-aps');
    const raisonInput = document.querySelector('textarea[name="raison_aps"]');
    const apsSouhaitee = document.querySelectorAll('input[name="aps_souhaitee"]');

    if (r.value === "autre") {
      // ✅ Cas "Aucun de ces cas" → on affiche le bloc APS
      if (apsRadiosBloc) apsRadiosBloc.style.display = "block";
    } else {
      // ❌ Tous les autres cas → on masque le bloc APS et on vide les choix
      if (apsRadiosBloc) apsRadiosBloc.style.display = "none";
      if (apsSessionBloc) apsSessionBloc.style.display = "none";
      if (raisonBloc) raisonBloc.style.display = "none";
      if (raisonInput) { raisonInput.value = ""; raisonInput.required = false; }
      apsSouhaitee.forEach(radio => { radio.checked = false; radio.required = false; });
      document.querySelectorAll('input[name="aps_session"]').forEach(r => { r.checked = false; r.required = false; });
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
    const apsOui = radio.value === "oui";
    const apsNon = radio.value === "non";

    // ✅ Si "Oui" → on affiche les sessions et cache le champ raison
    if (apsOui) {
      apsSessionBloc.style.display = "block";
      apsSessionBloc.querySelectorAll('input[name="aps_session"]').forEach(r => r.required = true);
      raisonBloc.style.display = "none";
      raisonInput.required = false;
      raisonInput.value = "";
    }

    // ❌ Si "Non" → on cache les sessions et on rend la raison obligatoire
    if (apsNon) {
      apsSessionBloc.style.display = "none";
      apsSessionBloc.querySelectorAll('input[name="aps_session"]').forEach(r => r.checked = false);
      raisonBloc.style.display = "block";
      raisonInput.required = true;
      raisonInput.focus();
    }
  });
});























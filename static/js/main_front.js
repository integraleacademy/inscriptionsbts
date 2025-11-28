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


// Vérifie tous les champs visibles
for (let input of inputs) {
  const style = window.getComputedStyle(input);
  const isInCurrentTab = input.closest('.tab') === currentTab;
  if (!isInCurrentTab) continue;

  if (input.name === "souhaite_accompagnement") continue;

  if (input.type === "radio" && (!input.required || !input.name)) continue;
  if (input.type === "checkbox" && !input.required) continue;

  // 🔥 BYPASS ADMIN pour ignorer la validation HTML
  if (input.name === "num_secu") {
    const nirValue = input.value.trim().toUpperCase();
    if (nirValue === "ADMIN") {
      input.classList.remove('invalid');
      continue; // ON SAUTE LA VALIDATION HTML
    }
  }

  if (!input.checkValidity()) {
    console.warn("⛔ Champ invalide détecté :", input.name || input.id);
    input.classList.add('invalid');
    input.reportValidity();
    valid = false;
  } else {
    input.classList.remove('invalid');
  }
}


    // 🔥 BYPASS ADMIN pour le NIR dans la validation HTML native
if (input.name === "num_secu") {
    const nirValue = input.value.trim().toUpperCase();
    if (nirValue === "ADMIN") {
        input.classList.remove('invalid');
        continue; // ⬅ ON SAUTE LA VALIDATION HTML
    }
}




// 🔹 Étape 1 : vérif NIR + BYPASS ADMIN
if (stepIndex === 0) {
  const nir = document.querySelector('input[name="num_secu"]')?.value?.trim().toUpperCase();
  if (nir === "ADMIN") {
    valid = true;  // 🔥 BYPASS
  } else if (typeof verifierNumSecu === "function" && !verifierNumSecu()) {
    valid = false;
  }
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

    // 🚫 COUPE TOUTE VALIDATION APS SI BTS ≠ MOS
  if (btsVal !== "MOS") {
    document.querySelectorAll('input[name="aps_souhaitee"]').forEach(r => r.required = false);
    document.querySelectorAll('input[name="aps_session"]').forEach(r => r.required = false);
    const raison = document.querySelector('textarea[name="raison_aps"]');
    if (raison) raison.required = false;

    return valid; // ⬅⬅⬅ OBLIGATOIRE : on arrête la validation ici
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

// === Validation IDF + Pôle Alternance ===
const chercheIDF = document.querySelector('input[name="cherche_idf"]:checked');
const accPA = document.querySelector('input[name="souhaite_accompagnement"]:checked');

if (!chercheIDF) {
  alert("⚠️ Merci d’indiquer si vous recherchez une entreprise en Île-de-France.");
  valid = false;
}

// Si cherche IDF = OUI → obligation de choisir OUI ou NON à Pôle Alternance
if (chercheIDF && chercheIDF.value === "oui") {
  if (!accPA) {
    alert("⚠️ Merci d’indiquer si vous souhaitez être accompagné par Pôle Alternance.");
    valid = false;
  }
}



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
// === Boutons Suivant / Précédent ===
document.querySelectorAll('.next').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!validateStep(currentStep)) return;

// 🧩 Étape 3 : modale Pôle Alternance
if (currentStep === 2) {

  const chercheIDF = document.querySelector('input[name="cherche_idf"]:checked');
  const accOui = document.querySelector('input[name="souhaite_accompagnement"][value="oui"]:checked');

  // 🎯 Modale UNIQUEMENT si :
  // - la personne cherche en IDF
  // - elle veut aussi l’accompagnement
  if (chercheIDF && chercheIDF.value === "oui" && accOui) {
    const modal = document.getElementById("modalPole");
    if (modal) modal.style.display = "flex";
    return; // on attend le clic OK
  }
}



    currentStep++;
    if (currentStep >= tabs.length) currentStep = tabs.length - 1;
    showStep(currentStep);
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

    // 🔄 Réinitialise tous les boutons
    modeBtns.forEach(b => {
      b.classList.remove('selected');
      b.classList.remove('disabled');
      b.querySelector('input[type="radio"]').checked = false;
    });

    // 🟢 Sélectionne celui cliqué
    btn.classList.add('selected');
    btn.querySelector('input[type="radio"]').checked = true;

    // 🔘 Grise les autres
    modeBtns.forEach(b => {
      if (b !== btn) b.classList.add('disabled');
    });
  });
});


// ===== Affichage automatique du Pôle Alternance selon la réponse "cherche_idf" =====
document.querySelectorAll("input[name='cherche_idf']").forEach(radio => {
  radio.addEventListener("change", () => {
    const box = document.querySelector(".pole-alternance-box");
    if (!box) return;

    if (radio.value === "oui") {
      box.style.display = "block";

      // ✨ Scroll automatique sur le bloc
      setTimeout(() => {
        box.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 150);

    } else {
      box.style.display = "none";

      // 🔄 Reset des choix d’accompagnement
      const accOui = document.querySelector("input[name='souhaite_accompagnement'][value='oui']");
      const accNon = document.querySelector("input[name='souhaite_accompagnement'][value='non']");
      if (accOui) accOui.checked = false;
      if (accNon) accNon.checked = false;
    }
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
 
// Vérifie NIR + BYPASS ADMIN
const nir = document.querySelector('input[name="num_secu"]')?.value?.trim().toUpperCase();
if (nir !== "ADMIN") {
  if (typeof verifierNumSecu === "function" && !verifierNumSecu()) {
    e.preventDefault();
    alert("❌ Votre numéro de sécurité sociale est incohérent. Veuillez le corriger avant de continuer.");
    showStep(0);
    return;
  }
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
    });
  }


// =====================================================
// 🤝 MODALE PÔLE ALTERNANCE (version finale corrigée)
// =====================================================
  const radioOui = document.querySelector('input[name="souhaite_accompagnement"][value="oui"]');

  if (radioOui) {
    // ✅ Crée la modale dynamiquement une seule fois
    const modalHTML = `
      <div id="modalPole" style="
        display:none;position:fixed;top:0;left:0;width:100%;height:100%;
        background:rgba(0,0,0,0.5);z-index:9999;align-items:center;justify-content:center;">
        <div style="
          background:white;padding:30px 40px;border-radius:14px;
          max-width:500px;width:90%;text-align:center;
          box-shadow:0 6px 20px rgba(0,0,0,0.2);animation:fadeIn .3s ease;">
          <h3 style="margin-top:0;">🤝 Pôle Alternance Île-de-France</h3>
          <p style="font-size:15px;line-height:1.6;color:#333;">
            Dès que nous aurons validé votre pré-inscription, nous transmettrons vos coordonnées
            à notre partenaire <strong>Pôle Alternance</strong>, qui vous contactera pour vous aider
            à trouver une entreprise.
          </p>
          <button id="closePole" style="
            margin-top:20px;background:#f4c45a;border:none;
            padding:10px 22px;border-radius:8px;cursor:pointer;
            font-weight:600;font-size:15px;">
            OK merci ❤️
          </button>
        </div>
      </div>
    `;
    document.body.insertAdjacentHTML("beforeend", modalHTML);

    const modal = document.getElementById("modalPole");
    const closeBtn = document.getElementById("closePole");

    // ❌ PLUS d'ouverture automatique au changement du radio
    // radioOui.addEventListener("change", () => { ... });

    // 🔴 Ferme la modale et passe à l’étape suivante
    if (closeBtn && modal) {
      closeBtn.addEventListener("click", () => {
        modal.style.display = "none";
        // ⏩ on avance d'une étape sans repasser par la validation
        currentStep = Math.min(currentStep + 1, tabs.length - 1);
        showStep(currentStep);
      });
    }
  }

  

// =====================================================
// 💾 ENREGISTRER ET REPRENDRE PLUS TARD (VERSION FINALE)
// =====================================================
document.querySelectorAll('.btn.save').forEach(btn => {
  btn.addEventListener('click', async () => {
    const form = document.querySelector('#inscriptionForm');
    const data = {};
    data["id"] = window.currentId || "{{ token|default('') }}"; 
    data["current_step"] = currentStep;

    // 🔥 Récupération de TOUTES les valeurs (vraiment tout)
    const fields = form.querySelectorAll('input, select, textarea');

    fields.forEach(field => {
      const name = field.name;
      if (!name) return;

      // Ignore fichiers
      if (field.type === "file") return;

      // 🔄 Checkboxes multiples : nom="qualites[]" etc.
      if (name.endsWith("[]")) {
        if (!data[name]) data[name] = [];
        if (field.checked) data[name].push(field.value);
        return;
      }

      // ✔ Radios : stocke la valeur cochée
      if (field.type === "radio") {
        if (field.checked) data[name] = field.value;
        return;
      }

      // ✔ Checkboxes simples
      if (field.type === "checkbox") {
        data[name] = field.checked ? 1 : 0;
        return;
      }

      // ✔ Champs classiques
      data[name] = field.value;
    });

    try {
      const res = await fetch('/save_draft', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ full_form: data })
      });

      const json = await res.json();

      if (json && json.success) {
        showFlash("💾 Votre brouillon a été sauvegardé avec succès.", "success");
      } else {
        showFlash("❌ Impossible d’enregistrer. Réessayez dans quelques instants.", "error");
      }
    } catch (e) {
      console.error(e);
      showFlash("⚠️ Une erreur de connexion empêche la sauvegarde.", "error");
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

  // === Plus d'infos sur le distanciel ===
const btnInfosDistanciel = document.getElementById("btnInfosDistanciel");
const infosDistanciel = document.getElementById("infosDistanciel");

if (btnInfosDistanciel && infosDistanciel) {
  btnInfosDistanciel.addEventListener("click", () => {
    const visible = infosDistanciel.style.display === "block";
    infosDistanciel.style.display = visible ? "none" : "block";
    
    btnInfosDistanciel.textContent = visible 
      ? "ℹ️ Plus d’informations sur le distanciel"
      : "🔽 Masquer les informations";

    if (!visible) {
      setTimeout(() => {
        infosDistanciel.scrollIntoView({ behavior: "smooth", block: "start" });
      }, 150);
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
      <h4>👮‍♀️ BTS MOS – Management Opérationnel de la Sécurité</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°41000</strong>.</p>
      <p>Ce BTS forme les futurs responsables d’équipes de sécurité privée (surveillance, prévention, sûreté, incendie) et les futurs gendarmes, policiers, pompiers, militaires. </p>
      <p><strong>Durée :</strong> 2 ans — <strong>Examen officiel</strong> organisé par le Ministère de l’Éducation nationale.</p>
    `,
    "MCO": `
      <h4>🎓 BTS MCO – Management Commercial Opérationnel</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38362</strong>.</p>
      <p>Ce BTS prépare aux métiers du commerce, de la gestion et du management d’équipe dans tous les secteurs d’activité.</p>
      <p><strong>Durée :</strong> 2 ans — <strong>Examen officiel</strong> organisé par le Ministère de l’Éducation nationale.</p>

    `,
    "PI": `
      <h4>🏡 BTS PI – Professions Immobilières</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38292</strong>.</p>
      <p>Ce BTS forme les futurs négociateurs, gestionnaires et conseillers immobiliers pour agences et syndics.</p>
      <p><strong>Durée :</strong> 2 ans — <strong>Examen officiel</strong> organisé par le Ministère de l’Éducation nationale.</p>

    `,
    "CI": `
      <h4>🌍 BTS CI – Commerce International</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38365</strong>.</p>
      <p>Ce BTS ouvre à des carrières à l’international : import-export, prospection, négociation et logistique internationale.</p>
      <p><strong>Durée :</strong> 2 ans — <strong>Examen officiel</strong> organisé par le Ministère de l’Éducation nationale.</p>

    `,
    "NDRC": `
      <h4>🤝 BTS NDRC – Négociation et Digitalisation de la Relation Client</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38368</strong>.</p>
      <p>Formation orientée sur la relation client, la vente et le marketing digital. Idéale pour les profils commerciaux modernes.</p>
      <p><strong>Durée :</strong> 2 ans — <strong>Examen officiel</strong> organisé par le Ministère de l’Éducation nationale.</p>

    `,
    "CG": `
      <h4>📝 BTS CG – Comptabilité et Gestion</h4>
      <p>✅ <strong>Diplôme Officiel BTS</strong> – niveau 5 (BAC +2), enregistré au <strong>RNCP n°38329</strong>.</p>
      <p>Ce BTS prépare aux métiers de la gestion comptable, du contrôle et de la finance d’entreprise.</p>
      <p><strong>Durée :</strong> 2 ans — <strong>Examen officiel</strong> organisé par le Ministère de l’Éducation nationale.</p>

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
}); // ✅ Fin du bloc APS


// =====================================================
// ✅ ÉTAPE 6 – RÉCAPITULATIF AUTOMATIQUE (corrigée)
// =====================================================
const lastNext = document.querySelector('#tab5 .next');
if (lastNext) {
  lastNext.addEventListener('click', () => {
    const recap = document.getElementById('recap-content');
    if (!recap) return;
    recap.innerHTML = ""; // reset

    // 🧾 Noms complets des BTS
    const BTS_LABELS = {
      "MCO": "BTS Management Commercial Opérationnel (MCO)",
      "MOS": "BTS Management Opérationnel de la Sécurité (MOS)",
      "PI":  "BTS Professions Immobilières (PI)",
      "CI":  "BTS Commerce International (CI)",
      "NDRC":"BTS Négociation et Digitalisation de la Relation Client (NDRC)",
      "CG":  "BTS Comptabilité et Gestion (CG)"
    };

    // 🏫 / 💻 Mode de formation lisible
    const MODE_LABELS = {
      "presentiel": "🏫 Formation en présentiel (Puget-sur-Argens, Var)",
      "distanciel": "💻 Formation 100% à distance en visioconférence ZOOM"
    };

    // --- Récupération des champs principaux ---
    const getValue = (selector) =>
      document.querySelector(selector)?.value?.trim() || "";

    const nom      = getValue('[name="nom"]');
    const prenom   = getValue('[name="prenom"]');
    const email    = getValue('[name="email"]');
    const tel      = getValue('[name="tel"]');
    const adresse  = getValue('[name="adresse"]');
    const cp       = getValue('[name="cp"]');
    const ville    = getValue('[name="ville"]');

    // 🎓 BTS (code + nom complet)
    const btsSelect = document.querySelector('select[name="bts"]');
    let btsCode = "";
    let btsLabel = "";
    if (btsSelect) {
      btsCode = btsSelect.value || "";
      const codeUpper = btsCode.toUpperCase();
      btsLabel = BTS_LABELS[codeUpper] || btsSelect.options[btsSelect.selectedIndex]?.text || "";
    }

    // 🎯 Mode de formation
    const modeChecked = document.querySelector('input[name="mode"]:checked');
    const modeValue   = modeChecked ? modeChecked.value : "";
    const modeLabel   = MODE_LABELS[modeValue] || (modeValue || "—");

    // 🎓 Baccalauréat
    const bacSelect = document.querySelector('select[name="baccalaureat"]');
    const bacText   = bacSelect
      ? (bacSelect.options[bacSelect.selectedIndex]?.text || "")
      : "";

    // 🤝 Accompagnement Pôle Alternance
    const accompagnement = document.querySelector('input[name="souhaite_accompagnement"]:checked');
    let accompagnementText = "—";
    if (accompagnement) {
      accompagnementText = (accompagnement.value === "oui")
        ? "Oui, je souhaite être accompagné pour trouver une entreprise"
        : "Non, je préfère chercher une entreprise par moi-même";
    }

    // --- Construction HTML du récap ---
    // --- Construction HTML du récap amélioré ---
let html = `
  <div class="recap-grid" style="display:flex;flex-wrap:wrap;gap:20px;justify-content:center;">
    
    <!-- 🧍‍♂️ INFOS PERSONNELLES -->
    <div style="
      flex:1 1 350px;
      background:white;
      border:1px solid #eee;
      border-radius:14px;
      padding:18px 22px;
      box-shadow:0 2px 8px rgba(0,0,0,0.05);
    ">
      <h4 style="margin-top:0;color:#333;">🧍‍♂️ Informations personnelles</h4>
      <p>👤 <strong>${prenom} ${nom}</strong></p>
      <p>📧 ${email}</p>
      <p>📱 ${tel}</p>
      <p>🏠 ${adresse || ""} ${cp || ""} ${ville || ""}</p>
    </div>

    <!-- 🎓 FORMATION -->
    <div style="
      flex:1 1 350px;
      background:white;
      border:1px solid #eee;
      border-radius:14px;
      padding:18px 22px;
      box-shadow:0 2px 8px rgba(0,0,0,0.05);
    ">
      <h4 style="margin-top:0;color:#333;">🎓 Formation choisie</h4>
      <p><strong>${btsLabel || "—"}</strong></p>
      <p>${modeLabel || "—"}</p>
      <p>🎓 Bac : ${bacText || "—"}</p>
      <p>🤝 Accompagnement Pôle Alternance : ${accompagnementText}</p>
    </div>
  </div>
`;


// --- Bloc APS automatique si BTS MOS + APS cochée ---
if (btsCode === "MOS") {
  const apsOui = document.querySelector('input[name="aps_souhaitee"][value="oui"]:checked');
  const apsSession = document.querySelector('input[name="aps_session"]:checked');
  if (apsOui) {
    html += `
      <div style="
        margin-top:40px;
        background:#fffbe6;
        border:1px solid #f4c45a;
        border-radius:10px;
        padding:18px;
        line-height:1.6;
        font-size:15px;
      ">
        <h4 style="margin-top:0;">🔒 Formation complémentaire APS</h4>
        <p>Vous avez sélectionné la formation <strong>Agent de Prévention et de Sécurité (APS)</strong>.</p>
        ${
          apsSession
            ? `<p><strong>Session choisie :</strong> ${apsSession.nextSibling.textContent.trim()}</p>`
            : ""
        }
        <p>Un e-mail vous sera envoyé expliquant la procédure pour la <strong>demande d’autorisation préalable d’entrée en formation auprès du CNAPS</strong> (Ministère de l’Intérieur).</p>
        <p>Vous recevrez également un <strong>mandat de prélèvement de 950 €</strong> (tarif spécial BTS au lieu de 1650 €) à compléter. Le prélèvement aura lieu <strong>le 1er jour de la formation</strong>.</p>
      </div>
    `;
  }
}



// --- Bloc explicatif Formation gratuite (design doré amélioré) ---
html += `
  <div style="
    margin-top:40px;
    background:linear-gradient(135deg,#fffaf0,#fff5dc);
    border:1px solid #f4c45a;
    border-radius:14px;
    padding:24px 26px;
    box-shadow:0 3px 10px rgba(244,196,90,0.25);
    line-height:1.7;
    font-size:15px;
  ">
    <h4 style="margin-top:0;color:#333;display:flex;align-items:center;gap:10px;">
      💚 <span>Formation gratuite (0 €)</span>
    </h4>
    <ul style="margin:0;padding-left:22px;">
      <li>📘 Aucun frais d’inscription ni de scolarité</li>
      <li>💼 Formation financée intégralement par l’État <strong>dans le cadre du contrat d’apprentissage</strong></li>
      <li>💰 Vous êtes rémunéré(e) selon votre âge et votre situation</li>
      <li>🎓 Diplôme d’État – Ministère de l’Éducation nationale</li>
    </ul>

  </div>
`;


    // --- Boutons ---
    // --- Boutons (version améliorée avec animation) ---
html += `
  <div style="margin-top:35px;text-align:center;display:flex;justify-content:center;gap:12px;flex-wrap:wrap;">
    <button id="btnRetour" style="
      background:#f2f2f2;
      border:none;
      color:#333;
      padding:11px 24px;
      border-radius:10px;
      cursor:pointer;
      font-weight:600;
      font-size:15px;
      transition:all 0.2s ease;
    ">⬅️ Modifier mes informations</button>

    <button id="btnEnvoyer" style="
      background:linear-gradient(135deg,#28a745,#34d058);
      border:none;
      color:white;
      padding:12px 28px;
      border-radius:10px;
      cursor:pointer;
      font-weight:600;
      font-size:16px;
      box-shadow:0 4px 10px rgba(40,167,69,0.3);
      transition:transform 0.2s ease, box-shadow 0.2s ease;
    ">📤 Envoyer mon dossier</button>
  </div>
`;


    recap.innerHTML = html;

    // 🔙 Retour
    const btnRetour = document.getElementById("btnRetour");
if (btnRetour) {
  btnRetour.addEventListener("click", (e) => {
    e.preventDefault(); // empêche d’envoyer le formulaire
    const overlay = document.querySelector(".sending-overlay");
    if (overlay) overlay.remove(); // supprime l’écran "envoi en cours" s’il existe
    showStep(4); // revient à l’étape précédente
  });
}


    // ✨ Hover sur bouton Envoyer
    const btnEnvoyer = document.getElementById("btnEnvoyer");
    if (btnEnvoyer) {
      btnEnvoyer.addEventListener("mouseenter", () => {
  btnEnvoyer.style.transform = "scale(1.05)";
  btnEnvoyer.style.boxShadow = "0 6px 14px rgba(40,167,69,0.4)";
});
btnEnvoyer.addEventListener("mouseleave", () => {
  btnEnvoyer.style.transform = "scale(1)";
  btnEnvoyer.style.boxShadow = "0 4px 10px rgba(40,167,69,0.3)";
});

      btnEnvoyer.addEventListener("click", (e) => {
        e.preventDefault();
        const overlay = document.createElement("div");
        overlay.className = "sending-overlay";
     overlay.innerHTML = `
  <div class="sending-box">
    <div class="loader"></div>
    <h3>⏳ Votre dossier est en cours d’envoi…</h3>
    <p>Merci de ne pas fermer cette page pendant la transmission.<br>
    ⏱️ L’opération prend généralement moins de 10 secondes.</p>
  </div>`;
        document.body.appendChild(overlay);
        setTimeout(() => document.getElementById("inscriptionForm").submit(), 800);
      });
    }

    // ✨ Animation d’apparition du récapitulatif
recap.style.opacity = 0;
recap.style.transition = "opacity 0.6s ease";
setTimeout(() => {
  recap.style.opacity = 1;
}, 100);


    // ✅ Passe à l’étape 6
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    const recapTab = document.getElementById('step6');
    if (recapTab) recapTab.classList.add('active');
    const info = document.getElementById('progressInfo');
    const bar  = document.getElementById('progressBar');
    if (info) info.textContent = "Étape 6 sur 6 — 100 % complété";
    if (bar)  bar.style.width = "100%";
    window.scrollTo({ top: 0, behavior: "smooth" });
  });
}

// =====================================================
// ♻️ APPLY DRAFT : remplissage automatique du formulaire
// =====================================================
function applyDraft() {
  if (!window.SAVED) return;

  const data = window.SAVED;
  const form = document.querySelector("#inscriptionForm");
  if (!form) return;

  const fields = form.querySelectorAll("input, select, textarea");

  fields.forEach(field => {
    const name = field.name;
    if (!name) return;

    // Si pas dans les données → on ignore
    if (!(name in data)) return;

    const value = data[name];

    // --- Checkboxes multiples → nom="xxx[]"
    if (name.endsWith("[]")) {
      if (Array.isArray(value)) {
        field.checked = value.includes(field.value);
      }
      return;
    }

    // --- Radios
    if (field.type === "radio") {
      field.checked = (field.value == value);
      return;
    }

    // --- Checkboxes simples
    if (field.type === "checkbox") {
      field.checked = (value == 1 || value === true);
      return;
    }

    // --- Autres champs
    field.value = value;
  });


  // =====================================================
  // 🔄 Réinjecte l’étape d’origine
  // =====================================================
  if ("current_step" in data) {
    const step = parseInt(data.current_step);
    if (!isNaN(step)) {
      setTimeout(() => {
        showStep(step);
      }, 200);
    }
  }

  // =====================================================
  // 🔧 TRIGGERS SPÉCIAUX (nécessaire pour tout réafficher)
  // =====================================================

  // ⮕ BTS change : affiche MOS / MCO / etc.
  const bts = document.querySelector('select[name="bts"]');
  if (bts) bts.dispatchEvent(new Event("change"));

  // ⮕ Bac status → affiche APS + "Autre bac"
  document.querySelectorAll('input[name="bac_status"]').forEach(r => {
    r.dispatchEvent(new Event("change"));
  });

  // ⮕ APS (oui/non)
  document.querySelectorAll('input[name="aps_souhaitee"]').forEach(r => {
    r.dispatchEvent(new Event("change"));
  });

  // ⮕ Recherche IDF
  const idf = document.querySelector("input[name='cherche_idf']:checked");
  if (idf) idf.dispatchEvent(new Event("change"));

  // ⮕ Date de naissance → maj mineur
  const birth = document.querySelector('input[name="date_naissance"]');
  if (birth) birth.dispatchEvent(new Event("change"));
}


// =====================================================
// 🚀 LANCEMENT AUTO quand la page charge
// =====================================================
document.addEventListener("DOMContentLoaded", () => {
  applyDraft();
});















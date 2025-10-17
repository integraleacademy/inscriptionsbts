// === Gestion fluide + verrouillage + icônes visuelles des onglets ===
document.addEventListener("DOMContentLoaded", () => {

const tabButtons = document.querySelectorAll('.tabs button');
const tabs = document.querySelectorAll('.tab');
let currentStep = 0;

// --- Fonction d’affichage des étapes ---
function showStep(index) {
  tabs.forEach((tab, i) => {
    if (i === index) {
      tab.classList.add('active');
      tab.style.display = 'block';
      tab.style.opacity = '1';
    } else {
      tab.classList.remove('active');
      tab.style.display = 'none';
      tab.style.opacity = '0';
    }
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
  if (birth) { birth.addEventListener('change', updateMinor); }



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

  // === Bloc MOS (déplacé depuis index.html) ===
const btsSelect = document.querySelector('select[name="bts"]');
const mosSection = document.getElementById('mos-section');
const mosExplication = document.getElementById('mos-explication');
const blocBacAutre = document.getElementById('bloc-bac-autre');
const blocApsSession = document.getElementById('bloc-aps-session');

if (btsSelect) {
  btsSelect.addEventListener('change', () => {
    if (btsSelect.value === 'MOS') {
      mosSection.style.display = 'block';
    } else {
      mosSection.style.display = 'none';
      mosExplication.style.display = 'none';
      blocBacAutre.style.display = 'none';
    }
  });
}

// --- Si "Aucun de ces cas" est coché ---
document.addEventListener('change', (e) => {
  if (e.target.name === 'bac_status') {
    if (e.target.value === 'autre') {
      mosExplication.style.display = 'block';
      blocBacAutre.style.display = 'block';
    } else {
      blocBacAutre.style.display = 'none';
      if (e.target.value === 'carte_cnaps') {
        mosExplication.style.display = 'none';
      }
    }
  }
  if (e.target.name === 'aps_souhaitee') {
    blocApsSession.style.display = e.target.checked ? 'block' : 'none';
  }
});

// === 🔢 Barre de progression (liée aux onglets) ===
// === 🔢 Barre de progression (liée aux onglets) — avec pourcentage animé ===
function updateProgressBar(index) {
  const progress = document.getElementById("progressBar");
  const info = document.getElementById("progressInfo");
  if (!progress || !info) return;

  const total = tabs.length;
  const targetPercent = (index / (total - 1)) * 100;
  const currentWidth = parseFloat(progress.style.width) || 0;
  const step = (targetPercent - currentWidth) / 20; // vitesse animation
  let currentPercent = currentWidth;

  const animate = () => {
    currentPercent += step;
    if ((step > 0 && currentPercent >= targetPercent) || (step < 0 && currentPercent <= targetPercent)) {
      currentPercent = targetPercent;
    } else {
      requestAnimationFrame(animate);
    }

    progress.style.width = currentPercent + "%";
    info.textContent = `Étape ${index + 1} sur ${total} — ${Math.round(currentPercent)} % complété`;
  };

  animate();
}


}); // 👈 fin du DOMContentLoaded



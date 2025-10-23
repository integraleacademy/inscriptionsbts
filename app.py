{% extends "base.html" %}
{% block body_class %}espace-candidat{% endblock %}
{% block content %}

<style>
/* === 🎨 STYLE ESPACE CANDIDAT === */
body.espace-candidat {
  background: linear-gradient(180deg, #fff 0%, #fff9e6 100%);
  font-family: "Segoe UI", system-ui, sans-serif;
  color: #222;
}

.candidat-container {
  max-width: 850px;
  margin: 40px auto;
  background: white;
  border-radius: 16px;
  box-shadow: 0 8px 25px rgba(0,0,0,0.1);
  padding: 35px 45px;
}

/* === En-tête === */
.header {
  text-align: center;
  margin-bottom: 30px;
}
.header img {
  max-height: 90px;
  display: block;
  margin: 0 auto 15px;
}
.header h1 {
  font-size: 28px;
  margin: 0;
  color: #111;
}
.header p {
  font-size: 16px;
  color: #555;
  margin-top: 5px;
}
.divider {
  width: 80px;
  height: 4px;
  background: #f4c45a;
  margin: 10px auto 25px;
  border-radius: 2px;
}

/* === Infos principales === */
.info-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 15px;
  margin-top: 25px;
}
.info-card {
  background: #fafafa;
  border: 1px solid #eee;
  border-radius: 10px;
  padding: 15px 20px;
}
.info-card h3 {
  margin: 0 0 5px 0;
  font-size: 14px;
  color: #777;
  text-transform: uppercase;
}
.info-card p {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  word-wrap: break-word;
  overflow-wrap: anywhere;
}

/* === Statut === */
.statut-section {
  text-align: center;
  margin-top: 40px;
  margin-bottom: 25px;
}
.statut-badge {
  display: inline-block;
  padding: 12px 22px;
  border-radius: 25px;
  font-weight: bold;
  font-size: 18px;
  color: white;
  box-shadow: 0 4px 10px rgba(0,0,0,0.15);
}
.statut-explication {
  font-size: 16px;
  margin-top: 10px;
  color: #333;
}

/* === Barre de progression === */
.progress-container {
  position: relative;
  width: 100%;
  margin: 35px auto 10px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  max-width: 650px;
  height: 70px;
}
.progress-line {
  position: absolute;
  top: 50%;
  left: 0;
  height: 6px;
  width: 100%;
  background: #ddd;
  border-radius: 4px;
  transform: translateY(-50%);
  z-index: 0;
}
.progress-line-fill {
  position: absolute;
  top: 50%;
  left: 0;
  height: 6px;
  background: linear-gradient(90deg, #f4c45a, #f1b233);
  border-radius: 4px;
  transform: translateY(-50%);
  z-index: 1;
  transition: width 1s ease-in-out;
}
.progress-step {
  position: relative;
  z-index: 2;
  width: 42px;
  height: 42px;
  border-radius: 50%;
  background: #eee;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 20px;
  color: #888;
  transition: all 0.3s ease;
  transform: translateY(-10%);
}
.progress-step.active {
  background: #f4c45a;
  color: #111;
  transform: scale(1.1);
  box-shadow: 0 0 10px rgba(244,196,90,0.6);
}
.progress-labels {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
  color: #555;
  max-width: 650px;
  margin: 10px auto 0;
}

/* === Commentaire === */
.commentaire-block {
  background: #fdf8e7;
  border-left: 5px solid #f4c45a;
  padding: 15px 20px;
  border-radius: 8px;
  margin-top: 30px;
}
.commentaire-block h3 {
  margin: 0 0 10px 0;
  font-size: 18px;
}
.commentaire-block p {
  margin: 0;
  color: #444;
  line-height: 1.5;
}

/* === Infos utiles === */
.info-box {
  background: #f8f8f8;
  border-left: 4px solid #f4c45a;
  padding: 12px 18px;
  margin-top: 25px;
  border-radius: 8px;
  color: #333;
  font-size: 14px;
}

/* === Assistance === */
.assistance {
  text-align: center;
  margin-top: 40px;
  font-size: 15px;
}
.assistance a {
  color: #1a73e8;
  font-weight: bold;
  text-decoration: none;
}
.assistance a:hover {
  text-decoration: underline;
}

/* === Responsive === */
@media (max-width:600px){
  .candidat-container { padding: 25px 20px; }
  .progress-labels { font-size: 11px; }
  .info-card p { font-size: 14px; }
}
</style>

<div class="candidat-container">
  <div class="header">
    <img src="{{ url_for('static', filename='logo.png') }}" alt="Logo Intégrale Academy">
    <h1>🎓 Espace Candidat</h1>
    <div class="divider"></div>
    <p>Bienvenue {{ row.prenom }} {{ row.nom }}</p>
  </div>

  <div class="info-grid">
    <div class="info-card"><h3>Numéro de dossier</h3><p>{{ row.numero_dossier }}</p></div>
    <div class="info-card"><h3>Formation</h3><p>{{ row.bts_label }}</p></div>
    <div class="info-card"><h3>Mode</h3><p>{{ row.mode_label }}</p></div>
    <div class="info-card"><h3>Email</h3><p>{{ row.email }}</p></div>
  </div>

  <div class="statut-section">
    <span class="statut-badge" style="
      background:
      {% if statut == 'preinscription' %}gray
      {% elif statut == 'validee' %}#007bff
      {% elif statut == 'confirmee' %}#f4c45a
      {% elif statut == 'reconfirmee' %}#2ecc71
      {% elif statut == 'docs_non_conformes' %}#e74c3c
      {% else %}#555{% endif %};
    ">
      {% if statut == "preinscription" %}🕓 Pré-inscription en attente
      {% elif statut == "validee" %}✅ Candidature validée
      {% elif statut == "confirmee" %}🎓 Inscription confirmée
      {% elif statut == "reconf_en_cours" %}🔄 Reconfirmation en cours
      {% elif statut == "reconfirmee" %}💚 Reconfirmée
      {% elif statut == "docs_non_conformes" %}⚠️ Documents non conformes
      {% elif statut == "annulee" %}❌ Annulée
      {% else %}🗂️ En cours
      {% endif %}
    </span>
    <p class="statut-explication">{{ explication_statut }}</p>
  </div>

  <!-- === Barre de progression === -->
  <div class="progress-container">
    <div class="progress-line"></div>
    <div class="progress-line-fill" id="progressFill"></div>
    <div class="progress-step" id="step1">🕓</div>
    <div class="progress-step" id="step2">✅</div>
    <div class="progress-step" id="step3">🎓</div>
    <div class="progress-step" id="step4">💚</div>
  </div>
  <div class="progress-labels">
    <span>Pré-inscription</span>
    <span>Validée</span>
    <span>Confirmée</span>
    <span>Reconfirmée</span>
  </div>

  {% if commentaire %}
  <div class="commentaire-block">
    <h3>💬 Message de l’administration</h3>
    <p>{{ commentaire }}</p>
  </div>
  {% endif %}

  <div class="info-box">
    ℹ️ Vous pouvez consulter l’avancement de votre dossier à tout moment depuis cette page.
  </div>

  <div class="assistance">
    <p>❓ Une question ? <a href="https://assistance-alw9.onrender.com/" target="_blank">Contactez l’assistance</a> ou appelez le <strong>04 22 47 07 68</strong>.</p>
  </div>
</div>

<script>
/* === Script progression dynamique === */
document.addEventListener("DOMContentLoaded", () => {
  const statut = "{{ statut }}";
  const steps = ["preinscription","validee","confirmee","reconfirmee"];
  const activeIndex = steps.indexOf(statut);
  const fill = document.getElementById("progressFill");
  const stepElems = [document.getElementById("step1"), document.getElementById("step2"), document.getElementById("step3"), document.getElementById("step4")];

  stepElems.forEach((el, i) => {
    if (i <= activeIndex) el.classList.add("active");
  });

  const percent = activeIndex >= 0 ? (activeIndex / (steps.length - 1)) * 100 : 0;
  fill.style.width = percent + "%";
});
</script>

{% endblock %}

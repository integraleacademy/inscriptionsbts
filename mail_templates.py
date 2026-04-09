# =====================================================
# ✉️ TEMPLATES E-MAILS – Intégrale Academy (version finale unifiée)
# =====================================================

import os
import unicodedata
from flask import render_template_string

BASE_TEMPLATE_PATH = os.path.join("templates", "email_base.html")


def _normalize_mode_text(value: str) -> str:
    raw = (value or "").strip().lower()
    return "".join(
        c for c in unicodedata.normalize("NFD", raw)
        if unicodedata.category(c) != "Mn"
    )

def mail_html(template_name, **kwargs):
    """Retourne le HTML complet d’un mail avec logo et design unifié."""

    # === Variables de base ===
    prenom = kwargs.get("prenom", "") or ""
    lien_espace = kwargs.get("lien_espace", "#") or "#"
    lien_confirmation = kwargs.get("lien_confirmation", "#") or "#"

    # --- Mapping BTS (AUTO) ---
    bts_raw = (kwargs.get("bts_label", "") or "").strip().upper()
    try:
        from app import BTS_LABELS   # import local éviter boucle import
        bts_label = BTS_LABELS.get(bts_raw, bts_raw)
    except:
        bts_label = bts_raw

    # 🔹 Variables pour le récap
    numero_dossier   = kwargs.get("numero_dossier", "") or ""
    form_nom         = kwargs.get("form_nom", "") or ""
    form_prenom      = kwargs.get("form_prenom", "") or ""
    form_email       = kwargs.get("form_email", "") or ""
    form_tel         = kwargs.get("form_tel", "") or ""
    form_mode_label_raw = kwargs.get("form_mode_label", "") or ""
    mode = _normalize_mode_text(form_mode_label_raw)

    if "pres" in mode:
        form_mode_label = "En présentiel à Puget-sur-Argens (Var – 83)"
    elif "dist" in mode:
        form_mode_label = "100% en ligne à distance en visioconférence ZOOM"
    else:
        form_mode_label = form_mode_label_raw




    # === Logo dynamique (utilise BASE_URL si définie sur Render) ===
    BASE_URL = os.getenv("BASE_URL", "https://inscriptionsbts.onrender.com").rstrip("/")
    logo_url = f"{BASE_URL}/static/logo-integrale.png"

    # === Contenu des modèles ===
    templates = {
 "accuse_reception": {
    "title": "Accusé de réception de votre candidature",
    "content": f"""
        <p>Bonjour {prenom},</p>

        <!-- ✉️ INTRO SELON PRÉSENTIEL / DISTANCIEL -->
        <p>
        Nous avons bien reçu votre candidature concernant notre <strong>{bts_label}</strong> en alternance,
        {"<strong>en présentiel (Puget sur Argens, Var)</strong>" if "présentiel" in form_mode_label.lower() or "puget" in form_mode_label.lower() else "<strong>100% en ligne à distance en visioconférence ZOOM</strong>"}.
        Nous vous confirmons que votre candidature a bien été prise en compte et que nous allons étudier
        votre dossier dans les prochains jours.
        </p>

        <p>
        Notre commission d'admission se réunit toutes les semaines et traite les dossiers par ordre d'arrivée.
        Vous recevrez donc une réponse (<strong>avis Favorable</strong> ou <strong>avis Défavorable</strong>) dans un délai maximum de
        <strong>10 à 15 jours</strong>. La réponse sera envoyée par <strong>mail</strong> et par <strong>SMS</strong>.
        </p>

        <!-- 🧾 RÉCAP DU DOSSIER -->
        <table width="100%" cellpadding="0" cellspacing="0"
            style="background:#fef8e1;border:1px solid #f5dd9b;border-radius:10px;padding:14px 18px;margin:18px 0;">
          <tr>
            <td style="font-weight:600;padding-bottom:8px;font-size:15px;">
              📄 Récapitulatif de votre candidature :
            </td>
          </tr>
          <tr>
            <td style="padding-left:4px;font-size:14px;line-height:1.6;">
              <div><strong>Numéro de dossier :</strong> {numero_dossier}</div>
              <div><strong>Nom :</strong> {form_nom}</div>
              <div><strong>Prénom :</strong> {form_prenom}</div>
              <div><strong>Email :</strong> {form_email}</div>
              <div><strong>Téléphone :</strong> {form_tel}</div>
              <div><strong>Formation :</strong> {bts_label}</div>
              <div><strong>Mode :</strong> {form_mode_label}</div>
            </td>
          </tr>
        </table>

        <!-- 🔗 REDIRECTION UNIQUE -->
        <p style="margin-top:15px;margin-bottom:6px;font-weight:600;font-size:15px;">
          📌 Suivez les étapes de votre inscription directement depuis votre Espace Candidat :
        </p>

        <p style="text-align:center;margin-top:0;">
            <a href="{lien_espace}" class="btn">🔑 Ouvrir mon espace candidat</a>
        </p>
    """
        +

        # === BLOC DISTANCIEL SI MODE DISTANCE ===
        (
        """
        <div style="background:#f3f7ff;border-left:4px solid #2b6cff;padding:18px;margin-top:28px;border-radius:10px;">
          <h3 style="margin:0 0 10px 0;color:#2b6cff;">💻 Comment se déroule la formation 100% en ligne à distance ?</h3>

          <p style="margin:0 0 10px 0;">
          <strong>ÉCOLE 100 % en ligne :</strong><br>
          Cette formation se déroule entièrement en visio-conférence (ZOOM) avec des formateurs expérimentés.
          Les étudiants suivent un emploi du temps fixe, se connectent à des horaires précis et interagissent en temps réel.
          </p>

          <p style="margin:0 0 10px 0;">Ce n’est pas une plateforme e-learning : tout se déroule en direct comme dans une vraie classe.</p>

          <p style="margin:0 0 10px 0;">Deux années entièrement à distance (aucun déplacement). Les devoirs sont transmis via l’espace étudiant.</p>

          <p style="margin:0 0 10px 0;">L’examen final se déroule dans un lycée public.</p>

          <p style="margin:0;"><strong>ENTREPRISE :</strong><br> En présentiel dans l’entreprise (alternance).</p>
        </div>
        """
        if "distance" in form_mode_label.lower() or "en ligne" in form_mode_label.lower() or "dist" in form_mode_label.lower()
        else ""
        )
        +

        """
<!-- ❓ FAQ COMPACTE – VERSION TEXTES DE CLÉMENT -->
<div style="margin-top:32px;padding:18px;background:#fafafa;border-radius:10px;border:1px solid #eee;">
  <h3 style="margin-top:0;color:#444;">❓ Questions fréquentes</h3>

  <p><strong>J'ai des questions est-il possible d'échanger avec vous ?</strong><br>
  Bien sûr, nous serons ravis de répondre à toutes vos questions lors d'un rendez-vous téléphonique.
  Pour réserver un rendez-vous téléphonique vous pouvez nous contacter au
  <strong>04 22 47 07 68</strong>.</p>

  <p><strong>Dois-je obligatoirement signer un contrat d'apprentissage avant septembre 2026 ?</strong><br>
  Vous aurez jusqu’au mois de <strong>décembre 2026</strong> pour trouver une entreprise d’accueil et signer
  un contrat d’apprentissage. Pas d'inquiétude : la plupart des contrats d’apprentissage se concrétisent
  après la rentrée entre septembre et novembre. Vous pourrez donc commencer les cours au mois de septembre,
  même si vous n'avez pas encore signé de contrat d'apprentissage.</p>

  <p><strong>Avez-vous un réseau d'entreprises partenaires ?</strong><br>
  En effet, nous travaillons avec un réseau d'entreprises partenaires et nous pourrons vous mettre en relation
  selon votre profil et votre situation géographique. Dès que votre inscription aura été validée,
  nous vous accompagnerons dans la recherche d'une entreprise pour la signature de votre contrat
  d'apprentissage.</p>

  <p><strong>La formation est-elle payante ?</strong><br>
  La formation est totalement gratuite pour les apprentis. Elle est prise en charge par l'État lors de
  la signature du contrat d'apprentissage avec l'entreprise.</p>

  <p><strong>Quels sont les prérequis ?</strong><br>
  Vous devez être titulaire d'un <strong>baccalauréat</strong> ou un autre diplôme de niveau 4.</p>

  <p><strong>Quels sont vos agréments officiels ?</strong><br>
  Notre Centre de Formation des Apprentis (CFA) est agréé par le Ministère de l'Éducation Nationale
  (UAI Paris : 0756548K - UAI Côte d'Azur : 0831774C) et par le Préfet de la Région PACA
  (NDA 93830600283). Nous sommes certifiés QUALIOPI, le label qui atteste de la qualité des formations
  proposées. Découvrez tous nos agréments en
  <a href="https://www.integraleacademy.com/ecole" style="color:#f4c45a;">cliquant-ici</a>.</p>

  <p><strong>Vos diplômes sont-ils reconnus par l'État ?</strong><br>
  Les diplômes que nous proposons (Brevet de Technicien Supérieur BTS) sont des diplômes officiels délivrés
  par le Ministère de l'Éducation Nationale. L'examen se déroulera en fin de 2ème année dans un lycée public.</p>
</div>



<div style="margin-top:28px;padding:14px 18px;border-radius:10px;
            background:#fff3d6;border:1px solid #f4c45a;">
  <p style="margin:0;font-size:15px;color:#000;text-align:center;">
    📘 Découvrez notre BTS en détails — 
    <a href="https://www.integraleacademy.com/dossiersbts"
       style="color:#000;font-weight:600;text-decoration:underline;">
       télécharger le dossier de présentation
    </a>
  </p>
</div>



<!-- 🆘 ASSISTANCE – VERSION ÉPURÉE & PROPRE -->
<div style="margin-top:28px;padding:18px;border-radius:10px;
            background:#f8faff;border:1px solid #dce6f5;text-align:center;">

  <p style="margin:0 0 12px 0;font-size:15px;color:#444;">
    Vous avez des questions ?  
    Appelez-nous au <strong>04 22 47 07 68</strong><br>
    ou contactez l’assistance :
  </p>

  <a href="https://assistance-alw9.onrender.com/"
     style="display:inline-block;background:#000;color:#fff;
            padding:10px 18px;border-radius:8px;font-weight:600;
            text-decoration:none;font-size:15px;">
    🆘 Contacter l’assistance
  </a>
</div>


<p style="margin-top:30px;">
    À très bientôt,<br>
    <strong>L’équipe Intégrale Academy</strong>
</p>
    """
},




   "candidature_validee": {
    "title": "Votre candidature est validée",
    "content": f"""
        <p>Bonjour {prenom},</p>

        <!-- ✉️ INTRO SELON PRÉSENTIEL / DISTANCIEL -->
        <p>
        🎉 <strong>J'ai une bonne nouvelle !</strong><br>
        Je fais suite à votre candidature concernant notre <strong>{bts_label}</strong> en alternance,
        {"<strong>en présentiel (Puget sur Argens, Var)</strong>" if "présentiel" in form_mode_label.lower() or "puget" in form_mode_label.lower() else "<strong>en 100% en ligne à distance en visioconférence ZOOM</strong>"}.
        <br><br>
        Après avoir étudié votre dossier, j'ai le plaisir de vous informer que <strong>notre commission a décidé de donner un AVIS FAVORABLE ✅</strong> à votre demande d'admission au sein de notre école Intégrale Academy. <br> 
        Il ne vous reste plus qu'à confirmer votre inscription pour intégrer notre école.<br> 
        A bientôt, Clément VAILLANT - Directeur Intégrale Academy
        </p>

        <!-- 🔔 MISE AU POINT IMPORTANTE -->
        <div style="background:#fff7d6;padding:18px;border-radius:10px;border:1px solid #f5e2a0;font-size:15px;line-height:1.5;margin-top:20px;">
            <p style="margin:0 0 8px 0;">
                📍 <strong>Prochaine étape :</strong>
            </p>

            <p style="margin:0 0 12px 0;">
                                Votre candidature a été validée, mais <a href="{lien_confirmation}" style="color:#000;text-decoration:underline;font-weight:600;">votre inscription n’est pas encore confirmée</a>.<br>
                Pour intégrer notre école, vous devez confirmer votre inscription en cliquant sur le bouton ci-dessous :
            </p>

            <div style="text-align:center;margin-top:18px;">
                                <a href="{lien_confirmation}" class="btn"
                style="display:inline-block;background:#f4c45a;color:#000;padding:12px 22px;border-radius:8px;
                        font-weight:600;text-decoration:none;font-size:15px;">
                    ✨ Confirmer mon inscription
                </a>
            </div>
        </div>

        <!-- 🧾 RÉCAP DU DOSSIER -->
        <table width="100%" cellpadding="0" cellspacing="0"
            style="background:#fef8e1;border:1px solid #f5dd9b;border-radius:10px;padding:14px 18px;margin:22px 0;">
          <tr>
            <td style="font-weight:600;padding-bottom:8px;font-size:15px;">
              📄 Récapitulatif de votre candidature :
            </td>
          </tr>
          <tr>
            <td style="padding-left:4px;font-size:14px;line-height:1.6;">
              <div><strong>Numéro de dossier :</strong> {numero_dossier}</div>
              <div><strong>Nom :</strong> {form_nom}</div>
              <div><strong>Prénom :</strong> {form_prenom}</div>
              <div><strong>Email :</strong> {form_email}</div>
              <div><strong>Téléphone :</strong> {form_tel}</div>
              <div><strong>Formation :</strong> {bts_label}</div>
              <div><strong>Mode :</strong> {form_mode_label}</div>
            </td>
          </tr>
        </table>

        <!-- 🔗 REDIRECTION UNIQUE -->
        <p style="margin-top:15px;margin-bottom:6px;font-weight:600;font-size:15px;">
          📌 Suivez les étapes de votre inscription directement depuis votre Espace Candidat :
        </p>

        <p style="text-align:center;margin-top:0;">
            <a href="{lien_espace}" class="btn">🔑 Ouvrir mon espace candidat</a>
        </p>
    """
    +

    # === BLOC DISTANCIEL SI MODE DISTANCE ===
    (
    """
    <div style="background:#f3f7ff;border-left:4px solid #2b6cff;padding:18px;margin-top:28px;border-radius:10px;">
      <h3 style="margin:0 0 10px 0;color:#2b6cff;">💻 Comment se déroule la formation 100% en ligne à distance ?</h3>

      <p style="margin:0 0 10px 0;">
      <strong>ÉCOLE 100 % en ligne :</strong><br>
      Cette formation se déroule entièrement en visio-conférence (ZOOM) avec des formateurs expérimentés.
      Les étudiants suivent un emploi du temps fixe, se connectent à des horaires précis et interagissent en temps réel.
      </p>

      <p style="margin:0 0 10px 0;">Ce n’est pas une plateforme e-learning : tout se déroule en direct comme dans une vraie classe.</p>

      <p style="margin:0 0 10px 0;">Deux années entièrement à distance (aucun déplacement). Les devoirs sont transmis via l’espace étudiant.</p>

      <p style="margin:0 0 10px 0;">L’examen final se déroule dans un lycée public.</p>

      <p style="margin:0;"><strong>ENTREPRISE :</strong><br> En présentiel dans l’entreprise (alternance).</p>
    </div>
    """
    if "distance" in form_mode_label.lower() or "en ligne" in form_mode_label.lower() or "dist" in form_mode_label.lower()
    else ""
    )
    +

    """
<!-- ❓ FAQ COMPACTE – VERSION TEXTES DE CLÉMENT -->
<div style="margin-top:32px;padding:18px;background:#fafafa;border-radius:10px;border:1px solid #eee;">
  <h3 style="margin-top:0;color:#444;">❓ Questions fréquentes</h3>

  <p><strong>J'ai des questions est-il possible d'échanger avec vous ?</strong><br>
  Bien sûr, nous serons ravis de répondre à toutes vos questions lors d'un rendez-vous téléphonique.
  Pour réserver un rendez-vous téléphonique vous pouvez nous contacter au
  <strong>04 22 47 07 68</strong>.</p>

  <p><strong>Dois-je obligatoirement signer un contrat d'apprentissage avant septembre 2026 ?</strong><br>
  Vous aurez jusqu’au mois de <strong>décembre 2026</strong> pour trouver une entreprise d’accueil et signer
  un contrat d’apprentissage. Pas d'inquiétude : la plupart des contrats d’apprentissage se concrétisent
  après la rentrée entre septembre et novembre. Vous pourrez donc commencer les cours au mois de septembre,
  même si vous n'avez pas encore signé de contrat d'apprentissage.</p>

  <p><strong>Avez-vous un réseau d'entreprises partenaires ?</strong><br>
  En effet, nous travaillons avec un réseau d'entreprises partenaires et nous pourrons vous mettre en relation
  selon votre profil et votre situation géographique. Dès que votre inscription aura été validée,
  nous vous accompagnerons dans la recherche d'une entreprise pour la signature de votre contrat
  d'apprentissage.</p>

  <p><strong>La formation est-elle payante ?</strong><br>
  La formation est totalement gratuite pour les apprentis. Elle est prise en charge par l'État lors de
  la signature du contrat d'apprentissage avec l'entreprise.</p>

  <p><strong>Quels sont les prérequis ?</strong><br>
  Vous devez être titulaire d'un <strong>baccalauréat</strong> ou un autre diplôme de niveau 4.</p>

  <p><strong>Quels sont vos agréments officiels ?</strong><br>
  Notre Centre de Formation des Apprentis (CFA) est agréé par le Ministère de l'Éducation Nationale
  (UAI Paris : 0756548K - UAI Côte d'Azur : 0831774C) et par le Préfet de la Région PACA
  (NDA 93830600283). Nous sommes certifiés QUALIOPI, le label qui atteste de la qualité des formations
  proposées. Découvrez tous nos agréments en
  <a href="https://www.integraleacademy.com/ecole" style="color:#f4c45a;">cliquant-ici</a>.</p>

  <p><strong>Vos diplômes sont-ils reconnus par l'État ?</strong><br>
  Les diplômes que nous proposons (Brevet de Technicien Supérieur BTS) sont des diplômes officiels délivrés
  par le Ministère de l'Éducation Nationale. L'examen se déroulera en fin de 2ème année dans un lycée public.</p>
</div>

<div style="margin-top:28px;padding:14px 18px;border-radius:10px;
            background:#fff3d6;border:1px solid #f4c45a;">
  <p style="margin:0;font-size:15px;color:#000;text-align:center;">
    📘 Découvrez notre BTS en détails — 
    <a href="https://www.integraleacademy.com/dossiersbts"
       style="color:#000;font-weight:600;text-decoration:underline;">
       télécharger le dossier de présentation
    </a>
  </p>
</div>

<div style="margin-top:28px;padding:18px;border-radius:10px;
            background:#f8faff;border:1px solid #dce6f5;text-align:center;">

  <p style="margin:0 0 12px 0;font-size:15px;color:#444;">
    Vous avez des questions ?  
    Appelez-nous au <strong>04 22 47 07 68</strong><br>
    ou contactez l’assistance :
  </p>

  <a href="https://assistance-alw9.onrender.com/"
     style="display:inline-block;background:#000;color:#fff;
            padding:10px 18px;border-radius:8px;font-weight:600;
            text-decoration:none;font-size:15px;">
    🆘 Contacter l’assistance
  </a>
</div>

<p style="margin-top:30px;">
    À très bientôt,<br>
    <strong>L’équipe Intégrale Academy</strong>
</p>
    """
}, 

"inscription_confirmee": {
    "title": "Inscription confirmée BTS en alternance",
    "content": f"""

<p>Bonjour {prenom},</p>

<p style="line-height:1.6;">
    Nous vous remercions d'avoir confirmé votre inscription. 
    🎉 C'est désormais <strong>officiel</strong> : vous êtes inscrit(e) en  
    <strong>{bts_label}</strong> en alternance,<br>
    {"<strong>en présentiel (Puget sur Argens, Var)</strong>" if "présentiel" in form_mode_label.lower() or "puget" in form_mode_label.lower() else "<strong>100% en ligne à distance en visioconférence ZOOM</strong>"}.
</p>

<!-- 🔔 BLOC PROCHAINE ÉTAPE -->
<div style="background:#fff9e6;padding:20px;border-radius:12px;
            border:1px solid #f1d28b;margin:25px 0;">
    
    <p style="margin:0 0 10px 0;font-size:16px;font-weight:700;color:#6a4d00;">
        📍 Prochaine étape :
    </p>

    <p style="margin:0;line-height:1.6;">
        Vous allez recevoir prochainement par courrier  
        <strong>votre carte étudiante</strong> ainsi que  
        <strong>votre certificat de scolarité</strong>. N'hésitez pas à nous contacter au 04 22 47 07 68 si vous avez la moindre question.
    </p>
</div>

<!-- 🧾 RÉCAP DU DOSSIER -->
<table width="100%" cellpadding="0" cellspacing="0"
    style="background:#fef8e1;border:1px solid #f5dd9b;border-radius:10px;padding:14px 18px;margin:22px 0;">
  <tr>
    <td style="font-weight:600;padding-bottom:8px;font-size:15px;">
      📄 Récapitulatif de votre candidature :
    </td>
  </tr>
  <tr>
    <td style="padding-left:4px;font-size:14px;line-height:1.6;">
      <div><strong>Numéro de dossier :</strong> {numero_dossier}</div>
      <div><strong>Nom :</strong> {form_nom}</div>
      <div><strong>Prénom :</strong> {form_prenom}</div>
      <div><strong>Email :</strong> {form_email}</div>
      <div><strong>Téléphone :</strong> {form_tel}</div>
      <div><strong>Formation :</strong> {bts_label}</div>
      <div><strong>Mode :</strong> {form_mode_label}</div>
    </td>
  </tr>
</table>

<!-- 🔗 REDIRECTION UNIQUE -->
<p style="margin-top:15px;margin-bottom:6px;font-weight:600;font-size:15px;">
  📌 Suivez les étapes de votre inscription directement depuis votre Espace Candidat :
</p>

<p style="text-align:center;margin-top:0;">
    <a href="{lien_espace}" class="btn">🔑 Ouvrir mon espace candidat</a>
</p>
    """
    +

    # === BLOC DISTANCIEL SI MODE DISTANCE ===
    (
    """
    <div style="background:#f3f7ff;border-left:4px solid #2b6cff;padding:18px;margin-top:28px;border-radius:10px;">
      <h3 style="margin:0 0 10px 0;color:#2b6cff;">💻 Comment se déroule la formation 100% en ligne à distance ?</h3>

      <p style="margin:0 0 10px 0;">
      <strong>ÉCOLE 100 % en ligne :</strong><br>
      Cette formation se déroule entièrement en visio-conférence (ZOOM) avec des formateurs expérimentés.
      Les étudiants suivent un emploi du temps fixe, se connectent à des horaires précis et interagissent en temps réel.
      </p>

      <p style="margin:0 0 10px 0;">Ce n’est pas une plateforme e-learning : tout se déroule en direct comme dans une vraie classe.</p>

      <p style="margin:0 0 10px 0;">Deux années entièrement à distance (aucun déplacement). Les devoirs sont transmis via l’espace étudiant.</p>

      <p style="margin:0 0 10px 0;">L’examen final se déroule dans un lycée public.</p>

      <p style="margin:0;"><strong>ENTREPRISE :</strong><br> En présentiel dans l’entreprise (alternance).</p>
    </div>
    """
    if "distance" in form_mode_label.lower() or "en ligne" in form_mode_label.lower() or "dist" in form_mode_label.lower()
    else ""
    )
    +

    """
<!-- ❓ FAQ COMPACTE – VERSION TEXTES DE CLÉMENT -->
<div style="margin-top:32px;padding:18px;background:#fafafa;border-radius:10px;border:1px solid #eee;">
  <h3 style="margin-top:0;color:#444;">❓ Questions fréquentes</h3>

  <p><strong>J'ai des questions est-il possible d'échanger avec vous ?</strong><br>
  Bien sûr, nous serons ravis de répondre à toutes vos questions lors d'un rendez-vous téléphonique.
  Pour réserver un rendez-vous téléphonique vous pouvez nous contacter au
  <strong>04 22 47 07 68</strong>.</p>

  <p><strong>Dois-je obligatoirement signer un contrat d'apprentissage avant septembre 2026 ?</strong><br>
  Vous aurez jusqu’au mois de <strong>décembre 2026</strong> pour trouver une entreprise d’accueil et signer
  un contrat d'apprentissage. Pas d'inquiétude : la plupart des contrats d’apprentissage se concrétisent
  après la rentrée entre septembre et novembre. Vous pourrez donc commencer les cours au mois de septembre,
  même si vous n'avez pas encore signé de contrat d'apprentissage.</p>

  <p><strong>Avez-vous un réseau d'entreprises partenaires ?</strong><br>
  En effet, nous travaillons avec un réseau d'entreprises partenaires et nous pourrons vous mettre en relation
  selon votre profil et votre situation géographique. Dès que votre inscription aura été validée,
  nous vous accompagnerons dans la recherche d'une entreprise pour la signature de votre contrat
  d'apprentissage.</p>

  <p><strong>La formation est-elle payante ?</strong><br>
  La formation est totalement gratuite pour les apprentis. Elle est prise en charge par l'État lors de
  la signature du contrat d'apprentissage avec l'entreprise.</p>

  <p><strong>Quels sont les prérequis ?</strong><br>
  Vous devez être titulaire d'un <strong>baccalauréat</strong> ou un autre diplôme de niveau 4.</p>

  <p><strong>Quels sont vos agréments officiels ?</strong><br>
  Notre Centre de Formation des Apprentis (CFA) est agréé par le Ministère de l'Éducation Nationale
  (UAI Paris : 0756548K - UAI Côte d'Azur : 0831774C) et par le Préfet de la Région PACA
  (NDA 93830600283). Nous sommes certifiés QUALIOPI, le label qui atteste de la qualité des formations
  proposées. Découvrez tous nos agréments en
  <a href="https://www.integraleacademy.com/ecole" style="color:#f4c45a;">cliquant-ici</a>.</p>

  <p><strong>Vos diplômes sont-ils reconnus par l'État ?</strong><br>
  Les diplômes que nous proposons (Brevet de Technicien Supérieur BTS) sont des diplômes officiels délivrés
  par le Ministère de l'Éducation Nationale. L'examen se déroulera en fin de 2ème année dans un lycée public.</p>
</div>

<div style="margin-top:28px;padding:14px 18px;border-radius:10px;
            background:#fff3d6;border:1px solid #f4c45a;">
  <p style="margin:0;font-size:15px;color:#000;text-align:center;">
    📘 Découvrez notre BTS en détails — 
    <a href="https://www.integraleacademy.com/dossiersbts"
       style="color:#000;font-weight:600;text-decoration:underline;">
       télécharger le dossier de présentation
    </a>
  </p>
</div>

<div style="margin-top:28px;padding:18px;border-radius:10px;
            background:#f8faff;border:1px solid #dce6f5;text-align:center;">

  <p style="margin:0 0 12px 0;font-size:15px;color:#444;">
    Vous avez des questions ?  
    Appelez-nous au <strong>04 22 47 07 68</strong><br>
    ou contactez l’assistance :
  </p>

  <a href="https://assistance-alw9.onrender.com/"
     style="display:inline-block;background:#000;color:#fff;
            padding:10px 18px;border-radius:8px;font-weight:600;
            text-decoration:none;font-size:15px;">
    🆘 Contacter l’assistance
  </a>
</div>

<p style="margin-top:30px;">
    À très bientôt,<br>
    <strong>L’équipe Intégrale Academy</strong>
</p>
    """
},


        "reconfirmation": {
            "title": "Reconfirmation d’inscription",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Merci de confirmer à nouveau votre inscription pour le <strong>{bts_label}</strong>.</p>
                <p style="text-align:center;margin:25px 0;">
                  <a href="{lien_espace}" class="btn">Reconfirmer mon inscription ✅</a>
                </p>
                <p>À très bientôt chez Intégrale Academy.</p>
            """
        },
        "reconfirmation_demandee": {
            "title": "Reconfirmation demandée",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Merci de confirmer à nouveau votre inscription pour la rentrée à venir.</p>
                <p><a href="{lien_espace}" class="btn">Reconfirmer mon inscription</a></p>
            """
        },
        "reconfirmation_validee": {
            "title": "Reconfirmation validée",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Votre reconfirmation d’inscription a bien été enregistrée ✅.</p>
                <p>À très bientôt pour la rentrée chez Intégrale Academy.</p>
            """
        },
"docs_non_conformes": {
    "title": "Documents non conformes ⚠️",
    "content": f"""

        <p>Bonjour {prenom},</p>

        <p style="margin-top:10px;line-height:1.6;">
            Je reviens vers vous concernant votre Pré-inscription <strong>{bts_label}</strong>.
        </p>

        <p style="margin-top:10px;line-height:1.6;">
            Certains documents que vous nous avez transmis ne sont pas conformes.
        </p>

        <p style="margin-top:10px;line-height:1.6;">
            Afin que nous puissions étudier votre dossier, nous vous remercions de bien vouloir nous transmettre dès que possible de nouveaux documents.  
            Pour transmettre de nouveaux documents, cliquez ici :
        </p>

        <p style="margin-top:8px;line-height:1.6;color:#444;">
            👉 Le <strong>motif de non-conformité</strong> vous sera indiqué automatiquement lorsque vous cliquerez sur le bouton ci-dessous.
        </p>

        <div style="text-align:center;margin:28px 0;">
            <a href="{lien_espace}"
               style="display:inline-block;background:#000;color:#fff;
                      padding:12px 22px;border-radius:8px;font-weight:600;
                      text-decoration:none;font-size:15px;">
                📤 Envoyer mes nouveaux documents
            </a>
        </div>

        <p style="margin-top:25px;">
            Merci,<br>
            <strong>L’équipe Intégrale Academy</strong>
        </p>

    """
},


"reprendre_plus_tard": {
    "title": "Reprendre ma pré-inscription 📝",
    "content": f"""

        <p>Bonjour {prenom},</p>

        <p style="margin-top:10px;line-height:1.6;">
            Nous vous remercions de l'intérêt porté à nos BTS en alternance.  
            Vous avez commencé votre Pré-inscription mais vous n'avez pas terminé ?  
            Pas de soucis 😉  
            Vous pourrez reprendre votre pré-inscription à tout moment en cliquant sur le bouton ci-dessous :
        </p>

        <div style="text-align:center;margin:28px 0;">
            <a href="{lien_espace}"
               style="display:inline-block;background:#000;color:#fff;
                      padding:12px 22px;border-radius:8px;font-weight:600;
                      text-decoration:none;font-size:15px;">
                🔄 Reprendre ma pré-inscription
            </a>
        </div>

        <p style="margin-top:25px;">
            À bientôt 👋,<br>
            <strong>L’équipe Intégrale Academy</strong>
        </p>

    """
},

        "certificat": {
            "title": "Votre certificat de scolarité",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Veuillez trouver en pièce jointe votre certificat de scolarité pour le <strong>{bts_label}</strong>.</p>
                <p>Conservez-le précieusement.</p>
            """
        },
        "certificat_presentiel": {
            "title": "Certificat de scolarité (présentiel)",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Veuillez trouver en pièce jointe votre certificat de scolarité pour le <strong>{bts_label}</strong>.</p>
                <p>À très bientôt sur le campus !</p>
            """
        },
        "bienvenue": {
    "title": "Bienvenue à Intégrale Academy 🎓",
    "content": f"""
        <p>Bonjour {prenom},</p>

        <p>
            Nous sommes ravis de vous accueillir au sein d’<strong>Intégrale Academy</strong>.
        </p>

        <p>
            Votre inscription au <strong>{bts_label}</strong> est désormais finalisée.
        </p>

        <div style="text-align:center;margin:30px 0 20px 0;">
            <a href="{lien_espace}" class="btn"
               style="display:inline-block;background:#000;color:#fff;
                      padding:12px 22px;border-radius:8px;font-weight:600;
                      text-decoration:none;font-size:15px;">
                Accéder à mon espace
            </a>
        </div>

        <p style="margin-top:25px;">
            À très bientôt,<br>
            <strong>L’équipe Intégrale Academy</strong>
        </p>
    """
},

        "parcoursup_import": {
            "title": "Votre candidature Parcoursup – Intégrale Academy",
            "content": f"""
                <p>Bonjour {prenom},</p>

                <p>
                  🎓 Nous avons bien reçu votre candidature Parcoursup concernant notre
                  <strong>{bts_label}</strong>,
                  {"en présentiel à Puget sur Argens (Var, 83)" if "pres" in mode or "puget" in mode else "100% en ligne à distance en visioconférence (ZOOM)"}.
                </p>

                <table width="100%" cellpadding="0" cellspacing="0" style="margin:14px 0 16px 0;background:#0f172a;border-radius:10px;">
                  <tr>
                    <td style="padding:12px 14px;color:#ffffff;font-size:14px;line-height:1.5;">
                      <strong>⚠️ ACTION REQUISE :</strong> Si vous souhaitez intégrer notre école, vous devez à présent compléter votre dossier de pré-inscription
                      <a href="{lien_espace}" style="color:#f4c45a;font-weight:700;text-decoration:underline;">en cliquant ici</a>.
                    </td>
                  </tr>
                </table>

                <div style="margin:16px 0 20px 0;padding:14px 16px;border-radius:10px;background:#fff4f4;border:1px solid #f5b4b4;">
                  <p style="margin:0;font-size:14px;line-height:1.6;color:#8b1d1d;">
                    <strong>ℹ️ Information importante :</strong>
                    si vous avez déjà complété votre dossier d’inscription, merci de ne pas tenir compte de ce message.
                  </p>
                </div>

                <div style="margin:20px 0;padding:16px 18px;border-radius:10px;background:#f6fbff;border:1px solid #dbeafe;">
                  <p style="margin:0 0 10px 0;font-size:15px;"><strong>📌 Prochaine étape obligatoire :</strong></p>
                  <p style="margin:0;font-size:14px;line-height:1.6;">
                    ✅ Ce qui se passe ensuite :
                  </p>
                  <ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;font-size:14px;">
                    <li>Vous complétez votre dossier de pré-inscription.</li>
                    <li>Notre commission étudie votre dossier (environ 10 jours).</li>
                    <li>Vous recevez une réponse par email et SMS.</li>
                    <li>En cas d’avis favorable, vous devrez confirmer votre inscription.</li>
                  </ul>
                </div>

                <p style="text-align:center;margin:26px 0 18px 0;">
                  <a href="{lien_espace}" style="display:inline-block;background:#f4c45a;color:#000;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;">
                    👉 Compléter ma pré-inscription
                  </a>
                </p>

                <div style="margin:20px 0;padding:16px 18px;border-radius:10px;background:#fffaf0;border:1px solid #f5dd9b;">
                  <p style="margin:0 0 8px 0;font-size:15px;"><strong>🗂️ Préparez ces éléments pour aller plus vite :</strong></p>
                  <ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;font-size:14px;">
                    <li>Pièce d’identité en cours de validité</li>
                    <li>Diplôme (ou justificatif de niveau 4 / baccalauréat)</li>
                    <li>CV à jour</li>
                    <li>Coordonnées complètes (email + téléphone)</li>
                  </ul>
                </div>

                <p style="margin-top:20px;margin-bottom:6px;">
                  💬 Besoin d’aide pour finaliser votre dossier ?<br>
                  Contactez-nous au <strong>04 22 47 07 68</strong>.
                </p>

                <p style="margin-top:24px;">À très bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },
        "parcoursup_import_rectificatif_presentiel": {
            "title": "Rectificatif — Votre candidature Parcoursup (présentiel)",
            "content": f"""
                <p>Bonjour {prenom},</p>

                <div style="margin:12px 0 16px 0;padding:12px 14px;border-radius:10px;background:#fff4e5;border:1px solid #f4c45a;color:#7a4d00;">
                  <strong>⚠️ Rectificatif :</strong> une erreur s’est glissée dans notre précédent email.
                  Votre candidature est bien enregistrée <strong>en présentiel à Puget sur Argens (Var, 83)</strong>.
                </div>

                <p>
                  🎓 Nous avons bien reçu votre candidature Parcoursup concernant notre
                  <strong>{bts_label}</strong>,
                  en présentiel à Puget sur Argens (Var, 83).
                </p>

                <table width="100%" cellpadding="0" cellspacing="0" style="margin:14px 0 16px 0;background:#0f172a;border-radius:10px;">
                  <tr>
                    <td style="padding:12px 14px;color:#ffffff;font-size:14px;line-height:1.5;">
                      <strong>⚠️ ACTION REQUISE :</strong> Si vous souhaitez intégrer notre école, vous devez à présent compléter votre dossier de pré-inscription
                      <a href="{lien_espace}" style="color:#f4c45a;font-weight:700;text-decoration:underline;">en cliquant ici</a>.
                    </td>
                  </tr>
                </table>

                <div style="margin:16px 0 20px 0;padding:14px 16px;border-radius:10px;background:#fff4f4;border:1px solid #f5b4b4;">
                  <p style="margin:0;font-size:14px;line-height:1.6;color:#8b1d1d;">
                    <strong>ℹ️ Information importante :</strong>
                    si vous avez déjà complété votre dossier d’inscription, merci de ne pas tenir compte de ce message.
                  </p>
                </div>

                <div style="margin:20px 0;padding:16px 18px;border-radius:10px;background:#f6fbff;border:1px solid #dbeafe;">
                  <p style="margin:0 0 10px 0;font-size:15px;"><strong>📌 Prochaine étape obligatoire :</strong></p>
                  <p style="margin:0;font-size:14px;line-height:1.6;">
                    ✅ Ce qui se passe ensuite :
                  </p>
                  <ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;font-size:14px;">
                    <li>Vous complétez votre dossier de pré-inscription.</li>
                    <li>Notre commission étudie votre dossier (environ 10 jours).</li>
                    <li>Vous recevez une réponse par email et SMS.</li>
                    <li>En cas d’avis favorable, vous devrez confirmer votre inscription.</li>
                  </ul>
                </div>

                <p style="text-align:center;margin:26px 0 18px 0;">
                  <a href="{lien_espace}" style="display:inline-block;background:#f4c45a;color:#000;padding:12px 18px;border-radius:8px;text-decoration:none;font-weight:700;font-size:15px;">
                    👉 Compléter ma pré-inscription
                  </a>
                </p>

                <div style="margin:20px 0;padding:16px 18px;border-radius:10px;background:#fffaf0;border:1px solid #f5dd9b;">
                  <p style="margin:0 0 8px 0;font-size:15px;"><strong>🗂️ Préparez ces éléments pour aller plus vite :</strong></p>
                  <ul style="margin:8px 0 0 18px;padding:0;line-height:1.7;font-size:14px;">
                    <li>Pièce d’identité en cours de validité</li>
                    <li>Diplôme (ou justificatif de niveau 4 / baccalauréat)</li>
                    <li>CV à jour</li>
                    <li>Coordonnées complètes (email + téléphone)</li>
                  </ul>
                </div>

                <p style="margin-top:20px;margin-bottom:6px;">
                  💬 Besoin d’aide pour finaliser votre dossier ?<br>
                  Contactez-nous au <strong>04 22 47 07 68</strong>.
                </p>

                <p style="margin-top:24px;">À très bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },
        "parcoursup_relance": {
            "title": "Relance – Votre dossier Parcoursup",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Nous n’avons pas encore reçu votre confirmation Parcoursup pour le BTS <strong>{bts_label}</strong>.</p>
                <p>Merci de finaliser votre pré-inscription dès que possible :</p>
                <p style="text-align:center;margin:25px 0;">
                  <a href="{lien_espace}" style="background:#f4c45a;color:black;padding:10px 16px;border-radius:6px;text-decoration:none;font-weight:bold;">
                    👉 Finaliser ma pré-inscription
                  </a>
                </p>
                <p>Bien cordialement,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },

        # =====================================================
        # 🔔 RELANCES (mail + SMS)
        # =====================================================
  "relance_candidature_validee": {
    "title": "Votre candidature est validée",
    "content": f"""
        <p>Bonjour {prenom},</p>

        <!-- ✉️ INTRO SELON PRÉSENTIEL / DISTANCIEL -->
     <p>
    🔄 Je reviens vers vous suite à mon précédent mail.<br>
    Vous n'avez pas encore confirmé votre inscription pour intégrer notre <strong>{bts_label}</strong> 🎓.<br>
    Nous avons un nombre limité de places : si vous souhaitez intégrer notre école, pensez à confirmer votre inscription ⚠️.
</p>


        <!-- 🔔 MISE AU POINT IMPORTANTE -->
        <div style="background:#fff7d6;padding:18px;border-radius:10px;border:1px solid #f5e2a0;font-size:15px;line-height:1.5;margin-top:20px;">
            <p style="margin:0 0 8px 0;">
                📍 <strong>Prochaine étape :</strong>
            </p>

            <p style="margin:0 0 12px 0;">
                                Votre candidature a été validée, mais <a href="{lien_confirmation}" style="color:#000;text-decoration:underline;font-weight:600;">votre inscription n’est pas encore confirmée</a>.<br>
                Pour intégrer notre école, vous devez confirmer votre inscription en cliquant sur le bouton ci-dessous :
            </p>

            <div style="text-align:center;margin-top:18px;">
                                <a href="{lien_confirmation}" class="btn"
                style="display:inline-block;background:#f4c45a;color:#000;padding:12px 22px;border-radius:8px;
                        font-weight:600;text-decoration:none;font-size:15px;">
                    ✨ Confirmer mon inscription
                </a>
            </div>
        </div>

        <!-- 🧾 RÉCAP DU DOSSIER -->
        <table width="100%" cellpadding="0" cellspacing="0"
            style="background:#fef8e1;border:1px solid #f5dd9b;border-radius:10px;padding:14px 18px;margin:22px 0;">
          <tr>
            <td style="font-weight:600;padding-bottom:8px;font-size:15px;">
              📄 Récapitulatif de votre candidature :
            </td>
          </tr>
          <tr>
            <td style="padding-left:4px;font-size:14px;line-height:1.6;">
              <div><strong>Numéro de dossier :</strong> {numero_dossier}</div>
              <div><strong>Nom :</strong> {form_nom}</div>
              <div><strong>Prénom :</strong> {form_prenom}</div>
              <div><strong>Email :</strong> {form_email}</div>
              <div><strong>Téléphone :</strong> {form_tel}</div>
              <div><strong>Formation :</strong> {bts_label}</div>
              <div><strong>Mode :</strong> {form_mode_label}</div>
            </td>
          </tr>
        </table>

        <!-- 🔗 REDIRECTION UNIQUE -->
        <p style="margin-top:15px;margin-bottom:6px;font-weight:600;font-size:15px;">
          📌 Suivez les étapes de votre inscription directement depuis votre Espace Candidat :
        </p>

        <p style="text-align:center;margin-top:0;">
            <a href="{lien_espace}" class="btn">🔑 Ouvrir mon espace candidat</a>
        </p>
    """
    +

    # === BLOC DISTANCIEL SI MODE DISTANCE ===
    (
    """
    <div style="background:#f3f7ff;border-left:4px solid #2b6cff;padding:18px;margin-top:28px;border-radius:10px;">
      <h3 style="margin:0 0 10px 0;color:#2b6cff;">💻 Comment se déroule la formation 100% en ligne à distance ?</h3>

      <p style="margin:0 0 10px 0;">
      <strong>ÉCOLE 100 % en ligne :</strong><br>
      Cette formation se déroule entièrement en visio-conférence (ZOOM) avec des formateurs expérimentés.
      Les étudiants suivent un emploi du temps fixe, se connectent à des horaires précis et interagissent en temps réel.
      </p>

      <p style="margin:0 0 10px 0;">Ce n’est pas une plateforme e-learning : tout se déroule en direct comme dans une vraie classe.</p>

      <p style="margin:0 0 10px 0;">Deux années entièrement à distance (aucun déplacement). Les devoirs sont transmis via l’espace étudiant.</p>

      <p style="margin:0 0 10px 0;">L’examen final se déroule dans un lycée public.</p>

      <p style="margin:0;"><strong>ENTREPRISE :</strong><br> En présentiel dans l’entreprise (alternance).</p>
    </div>
    """
    if "distance" in form_mode_label.lower() or "en ligne" in form_mode_label.lower() or "dist" in form_mode_label.lower()
    else ""
    )
    +

    """
<!-- ❓ FAQ COMPACTE – VERSION TEXTES DE CLÉMENT -->
<div style="margin-top:32px;padding:18px;background:#fafafa;border-radius:10px;border:1px solid #eee;">
  <h3 style="margin-top:0;color:#444;">❓ Questions fréquentes</h3>

  <p><strong>J'ai des questions est-il possible d'échanger avec vous ?</strong><br>
  Bien sûr, nous serons ravis de répondre à toutes vos questions lors d'un rendez-vous téléphonique.
  Pour réserver un rendez-vous téléphonique vous pouvez nous contacter au
  <strong>04 22 47 07 68</strong>.</p>

  <p><strong>Dois-je obligatoirement signer un contrat d'apprentissage avant septembre 2026 ?</strong><br>
  Vous aurez jusqu’au mois de <strong>décembre 2026</strong> pour trouver une entreprise d’accueil et signer
  un contrat d’apprentissage. Pas d'inquiétude : la plupart des contrats d’apprentissage se concrétisent
  après la rentrée entre septembre et novembre. Vous pourrez donc commencer les cours au mois de septembre,
  même si vous n'avez pas encore signé de contrat d'apprentissage.</p>

  <p><strong>Avez-vous un réseau d'entreprises partenaires ?</strong><br>
  En effet, nous travaillons avec un réseau d'entreprises partenaires et nous pourrons vous mettre en relation
  selon votre profil et votre situation géographique. Dès que votre inscription aura été validée,
  nous vous accompagnerons dans la recherche d'une entreprise pour la signature de votre contrat
  d'apprentissage.</p>

  <p><strong>La formation est-elle payante ?</strong><br>
  La formation est totalement gratuite pour les apprentis. Elle est prise en charge par l'État lors de
  la signature du contrat d'apprentissage avec l'entreprise.</p>

  <p><strong>Quels sont les prérequis ?</strong><br>
  Vous devez être titulaire d'un <strong>baccalauréat</strong> ou un autre diplôme de niveau 4.</p>

  <p><strong>Quels sont vos agréments officiels ?</strong><br>
  Notre Centre de Formation des Apprentis (CFA) est agréé par le Ministère de l'Éducation Nationale
  (UAI Paris : 0756548K - UAI Côte d'Azur : 0831774C) et par le Préfet de la Région PACA
  (NDA 93830600283). Nous sommes certifiés QUALIOPI, le label qui atteste de la qualité des formations
  proposées. Découvrez tous nos agréments en
  <a href="https://www.integraleacademy.com/ecole" style="color:#f4c45a;">cliquant-ici</a>.</p>

  <p><strong>Vos diplômes sont-ils reconnus par l'État ?</strong><br>
  Les diplômes que nous proposons (Brevet de Technicien Supérieur BTS) sont des diplômes officiels délivrés
  par le Ministère de l'Éducation Nationale. L'examen se déroulera en fin de 2ème année dans un lycée public.</p>
</div>

<div style="margin-top:28px;padding:14px 18px;border-radius:10px;
            background:#fff3d6;border:1px solid #f4c45a;">
  <p style="margin:0;font-size:15px;color:#000;text-align:center;">
    📘 Découvrez notre BTS en détails — 
    <a href="https://www.integraleacademy.com/dossiersbts"
       style="color:#000;font-weight:600;text-decoration:underline;">
       télécharger le dossier de présentation
    </a>
  </p>
</div>

<div style="margin-top:28px;padding:18px;border-radius:10px;
            background:#f8faff;border:1px solid #dce6f5;text-align:center;">

  <p style="margin:0 0 12px 0;font-size:15px;color:#444;">
    Vous avez des questions ?  
    Appelez-nous au <strong>04 22 47 07 68</strong><br>
    ou contactez l’assistance :
  </p>

  <a href="https://assistance-alw9.onrender.com/"
     style="display:inline-block;background:#000;color:#fff;
            padding:10px 18px;border-radius:8px;font-weight:600;
            text-decoration:none;font-size:15px;">
    🆘 Contacter l’assistance
  </a>
</div>

<p style="margin-top:30px;">
    À très bientôt,<br>
    <strong>L’équipe Intégrale Academy</strong>
</p>
    """
}, 
        "relance_reconfirmation": {
            "title": "Relance – Reconfirmez votre inscription à Intégrale Academy",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Nous n’avons pas encore reçu votre <strong>reconfirmation</strong> d’inscription pour le <strong>{bts_label}</strong>.</p>
                <p>Merci de valider dès maintenant votre présence à la rentrée :</p>
                <p style="text-align:center;margin:25px 0;">
                    <a href="{lien_espace}" class="btn">🔁 Reconfirmer mon inscription</a>
                </p>
                <p>Sans validation rapide, votre dossier pourrait être suspendu.</p>
                <p>À très bientôt,<br><b>L’équipe Intégrale Academy</b></p>
            """
        },
        "relance_docs_non_conformes": {
            "title": "Relance – Documents à compléter",
            "content": f"""
                <p>Bonjour {prenom},</p>
                <p>Certains documents de votre dossier pour le <strong>{bts_label}</strong> sont encore manquants ou non conformes ⚠️.</p>
                <p>Merci de les renvoyer dès que possible afin que votre dossier puisse être validé :</p>
                <p style="text-align:center;margin:25px 0;">
                    <a href="{lien_espace}" class="btn">📎 Envoyer mes nouvelles pièces</a>
                </p>
                <p>Notre équipe reste disponible si besoin d’aide.<br><b>Intégrale Academy</b></p>
            """
        },

       "demande_aps": {
            "title": "Formation Agent de sécurité privée – Dossier CNAPS à compléter",
            "content": f"""
                <p>Bonjour {prenom},</p>

                <p>
                Je fais suite à votre inscription en <strong>BTS Management Opérationnel de la Sécurité (MOS)</strong>.<br>
                Vous avez indiqué que vous souhaitiez intégrer la formation <strong>Agent de Prévention et de Sécurité (APS)</strong>.
                </p>

                <p>
                Cette formation se déroulera dans nos locaux <strong>Intégrale Academy à Puget-sur-Argens (VAR)</strong>,
                aux dates suivantes :
                </p>

                <p style="font-size:16px;font-weight:600;color:#000;">
                    📅 <strong>{kwargs.get("aps_session", "")}</strong>
                </p>

                <p>
                Cette formation vous permettra d'obtenir la carte professionnelle
                <strong>“Agent de surveillance humaine et de gardiennage”</strong>,
                délivrée par le <strong>CNAPS (Ministère de l’Intérieur)</strong>.
                </p>

                <div style="background:#fff8e6;padding:15px 18px;border-radius:10px;border-left:5px solid #f4c45a;margin:25px 0;">
                    <h3 style="margin-top:0;color:#c27a00;">🔐 Autorisation préalable d’entrée en formation</h3>
                    <p style="margin-bottom:10px;">
                        La formation APS est strictement réglementée par le Ministère de l'intérieur.
                        Avant votre entrée en formation, vous devez obtenir une
                        <strong>autorisation préalable d’entrée en formation</strong>.
                    </p>

                    <p>
                        Le CNAPS procède pour cela à une vérification de vos antécédents judiciaires
                        et réalise une enquête administrative.
                    </p>

                    <p style="margin-top:12px;font-weight:600;">
                        👉 Merci de compléter ce formulaire :
                    </p>

                    <p style="text-align:center;margin-top:10px;">
                        <a href="https://cnapsv5-1.onrender.com/"
                        style="background:#f4c45a;color:#000;padding:12px 20px;border-radius:8px;
                                font-weight:600;text-decoration:none;display:inline-block;">
                            📩 Compléter ma demande CNAPS
                        </a>
                    </p>
                </div>

                <div style="background:#eef6ff;padding:15px 18px;border-radius:10px;border-left:5px solid #4e8fff;margin:25px 0;">
                    <h3 style="margin-top:0;color:#1f5fbf;">💳 Financement de la formation</h3>

                    <p>
                        Nous proposons cette formation au tarif exceptionnel de
                        <strong>950 € (au lieu de 1650 €)</strong> pour les étudiants inscrits en BTS MOS.
                    </p>

                    <p style="margin-top:10px;">
                        Vous allez recevoir dans les prochains jours un 
                        <strong>mandat de prélèvement</strong> émis par notre banque <strong>QONTO</strong>.
                        Nous vous remercions de bien vouloir compléter ce mandat avec vos coordonnées bancaires. ⚠️ Votre inscription sera validée dès que le mandat de prélèvement sera validé.
                    </p>

                    <p style="margin-top:10px;">
                        ✔️ <strong>Rassurez vous :</strong> Le prélèvement sera effectué
                        <strong>uniquement le 1er jour de votre formation (pas avant)</strong>.
                    </p>
                </div>

                <p>
                    Je reste à votre disposition si vous avez la moindre question.<br>
                    <br>
                    <strong>Clément VAILLANT</strong><br>
                    Directeur – Intégrale Academy
                </p>
            """
        },


        # =====================================================
        # 🤝 MAIL PÔLE ALTERNANCE – Notification interne
        # =====================================================
        "pole_alternance": {
            "title": "Nouveau candidat – accompagnement Pôle Alternance",
            "content": f"""
                <p>Bonjour Clément 👋,</p>
                <p>Un nouveau candidat a indiqué souhaiter être accompagné par le <strong>Pôle Alternance Île-de-France</strong>.</p>
                <p>Voici les documents transmis :</p>
                <ul>
                  <li>📄 <strong>CV</strong> en pièce jointe</li>
                  <li>📝 <strong>Lettre de motivation</strong> en pièce jointe</li>
                  <li>📋 <strong>Fiche PDF du candidat</strong> également jointe</li>
                </ul>
                <p style="margin-top:20px;">
                  Ce dossier est prêt à être transmis à votre contact au Pôle Alternance.
                </p>
                <p>Bonne journée ☀️<br><b>L’équipe Intégrale Academy</b></p>
            """
        }
    }  # 👈 FIN du dictionnaire templates

    # === Sécurité : vérifie que le modèle existe ===
    tpl = templates.get(template_name)
    if not tpl:
        return f"<p>Modèle inconnu : {template_name}</p>"

    # === Lecture du modèle de base ===
    try:
        with open(BASE_TEMPLATE_PATH, encoding="utf-8") as f:
            base_html = f.read()
    except FileNotFoundError:
        return tpl["content"]

    # === Rendu final complet ===
    return render_template_string(
        base_html,
        email_title=tpl["title"],
        email_content=tpl["content"],
        logo_url=logo_url
    )
# 👈 ICI on ferme correctement mail_html()



# ==========================================================
# 🧩 Fonction de compatibilité pour l'ancien système
# ==========================================================
def get_mail_context(row, lien_espace="#"):
    return {
        "prenom": row.get("prenom", ""),
        "bts_label": row.get("bts", ""),
        "lien_espace": lien_espace,
        "lien_confirmation": row.get("lien_confirmation", "#"),
        "numero_dossier": row.get("numero_dossier", ""),
        "form_nom": row.get("nom", row.get("form_nom", "")),
        "form_prenom": row.get("prenom", row.get("form_prenom", "")),
        "form_email": row.get("email", row.get("form_email", "")),
        "form_tel": row.get("tel", row.get("form_tel", "")),
        "form_mode_label": row.get("mode", row.get("form_mode_label", "")),
    }





# Plateforme d'inscriptions BTS — Intégrale Academy

Application Flask prête à déployer (Render, Railway, VPS…).

## Fonctionnalités
- Page publique : **Confirmation d'inscription BTS** (Nom, Prénom, Email, Téléphone, BTS).
- Sauvegarde des demandes dans un fichier JSON persistant.
- Envoi d'un **accusé de réception** automatique (inscription en attente de validation).
- Espace **Admin** (mot de passe) :
  - Statuts : **EN ATTENTE DE VALIDATION** (orange) → **INSCRIPTION VALIDÉE** (vert)
  - Bouton pour **valider** l'inscription (envoie le mail de validation)
  - Boutons pour **télécharger** :
    - **Certificat de scolarité** (Word) à partir d'un modèle `.docx`
    - **Lettre d'accompagnement** (Word) à partir d'un modèle `.docx`
- Design simple, propre, couleurs Intégrale Academy (`#F4C45A`).

## Variables d'environnement à définir
- `SECRET_KEY` : clé Flask (par ex. générée aléatoirement)
- `ADMIN_PASSWORD` : mot de passe pour l'admin
- `FROM_EMAIL` : adresse Gmail d'envoi (ex: ecole@integraleacademy.com)
- `EMAIL_PASSWORD` : mot de passe d'application Gmail
- `DATA_DIR` : (optionnel) dossier persistant, par défaut `/data`
- `BCC_EMAIL` : (optionnel) email en copie cachée de tous les envois

## Modèles Word (.docx)
Placez vos modèles dans `templates_docx/` :
- `certificat_modele.docx`
- `lettre_modele.docx`

Utilisez ces variables dans le document (avec `{{ ... }}`) :
- `{{ NOM }}`, `{{ PRENOM }}`, `{{ MAIL }}`, `{{ TELEPHONE }}`
- `{{ BTS }}` (MOS, MCO, NDRC, CI)
- `{{ DATE_DU_JOUR }}` (format JJ/MM/AAAA)
- `{{ ANNEE_SCOLAIRE }}` (ex. 2025-2026)

> Vous pouvez ajouter d'autres variables : elles sont toutes listées dans le code (fonction `_template_context`).

## Lancer en local
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt

export SECRET_KEY="change-me"
export ADMIN_PASSWORD="admin"
export FROM_EMAIL="ecole@integraleacademy.com"
export EMAIL_PASSWORD="votre_mot_de_passe_application"
# export DATA_DIR="$(pwd)/data"

python app.py
# http://127.0.0.1:5000
```

## Déploiement Render (exemple)
- Créez un Web Service
- Build Command: `pip install -r requirements.txt`
- Start Command: `python app.py`
- Ajoutez un **Persistent Disk** monté sur `/data` et définissez `DATA_DIR=/data`

---

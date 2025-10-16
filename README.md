# Plateforme Pré‑inscriptions BTS 2026 – Intégrale Academy

Flask app prête à déployer sur Render (disk persistant) pour gérer :
- Formulaire public de **pré‑inscription**
- Attribution **numéro de dossier** automatique (`2026BTSDDMM####`)
- **E-mails** automatiques (accusé de réception, validation, confirmation, reconfirmation)
- **Espace admin**: tableau, statuts, recherche, filtres, export CSV/JSON, PDF fiche, logs, étiquettes `APS / AUT OK / Chèque OK`
- **Upload** pièces justificatives

## Lancer en local
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
flask --app app run --debug
```
## Déploiement Render
- Connectez le repo, Render détecte `render.yaml`.
- Configurez `MAIL_USERNAME`, `MAIL_PASSWORD`, `ADMIN_PASSWORD` dans le dashboard Render.
- Un disque persistant de 1GB est monté sur `/opt/render/project/src/data`.

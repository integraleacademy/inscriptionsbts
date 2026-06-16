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

### Configuration YPAREO NEO

Les variables YPAREO déclarées dans `render.yaml` ont `sync: false` : leurs
valeurs doivent être renseignées dans **Render > Environment** avec les
identifiants de votre instance YPAREO.

Variables communes obligatoires :

- `YPAREO_API_URL`
- `YPAREO_AUTH_ENDPOINT`
- `YPAREO_AUTH_TOKEN`
- `YPAREO_APPRENANTS_ENDPOINT`
- `YPAREO_CURSUS_ENDPOINT`

Variables communes optionnelles :

- `YPAREO_ID_ORGANISME`, à renseigner seulement si l’API de votre instance le
  demande.
- `YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE`

Si `YPAREO_ID_SITUATION_AVANT_APPRENTISSAGE` est vide ou absente, le champ
`idSituationAvantApprentissage` n’est pas envoyé dans le payload cursus. Si elle
est renseignée, sa valeur doit être l’identifiant numérique YPAREO de la
situation à affecter aux nouveaux cursus.

Une variable d’identifiant de formation est également obligatoire pour chaque
BTS synchronisé :

- `YPAREO_ID_FORMATION_BTS_MOS`
- `YPAREO_ID_FORMATION_BTS_MCO`
- `YPAREO_ID_FORMATION_BTS_NDRC`
- `YPAREO_ID_FORMATION_BTS_PI`
- `YPAREO_ID_FORMATION_BTS_CI`

Après ajout ou modification d’une variable dans Render, redéployez le service.
Si la personne a déjà été créée mais que le cursus a échoué, relancer la
synchronisation réutilise son `ypareo_id` et tente uniquement de créer le
cursus.

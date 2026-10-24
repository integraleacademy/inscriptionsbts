# Plateforme Admissions BTS 2027 – Intégrale Academy

Flask app prête à déployer sur Render (disk persistant) pour gérer :
- Formulaire public de **pré‑inscription**
- Attribution **numéro de dossier** automatique (`2027BTSDDMM####`)
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


## Campagne septembre 2027

- Ouverture publique : **1er décembre 2026 à 10 h Europe/Paris**, soit
  `2026-12-01T09:00:00Z`. Cette date est centralisée dans `campaign.py`.
- `/` présente la clôture 2026, les six BTS, un décompte synchronisé sur
  l’heure serveur et un lien calendrier. À l’ouverture, le bouton mène à
  `/candidature` (sept étapes, reprise par e-mail et récapitulatif).
- Les routes de création, de sauvegarde et de reprise sont bloquées côté
  serveur avant l’ouverture. L’aperçu `/candidature?preview=1` exige une
  session administrateur et désactive les envois dans l’interface.
- L’administration permet une suspension manuelle de la campagne 2027.
  L’ancien fichier de réglages 2026 ne modifie pas son calendrier.
- Une migration additive crée `candidats.rentree_annee` (2026 par défaut
  pour l’historique). Les nouveaux dossiers portent explicitement 2027.
  Les dossiers, fichiers, identifiants et liens historiques sont conservés.
- Les filtres, statistiques, exports et opérations groupées de l’administration
  utilisent la rentrée sélectionnée. Les certificats et messages suivent
  l’année du dossier, et les anciennes sessions APS ne sont plus proposées.

### Action de formation YPAREO MOS 2027

Avant d’envoyer la nouvelle promotion vers YPAREO, renseigner les trois
paramètres métier correspondant à l’action de formation créée dans YPAREO :

- `YPAREO_BTS_MOS_2027_ACTION_FORMATION_ID`
- `YPAREO_BTS_MOS_2027_DATE_DEBUT` (`AAAA-MM-JJ`)
- `YPAREO_BTS_MOS_2027_DATE_FIN` (`AAAA-MM-JJ`)

Le logiciel refuse un rattachement 2027 avec la configuration 2026.
Les dates et identifiants ne sont pas déduits du calendrier précédent.

### Vérification

`python -m pytest -q tests test_gestionstagiaires_api.py`

Tests de la frontière horaire, des restrictions avant ouverture, des
brouillons, des justificatifs, des cohortes, des e-mails, des certificats
et de la configuration YPAREO. Les envois externes sont simulés.
Le parcours a également été vérifié dans Chromium à 1440 et 390 px,
avec candidature complète, erreurs de validation, mineur/responsable légal,
reprise, suivi candidat, filtres, actualisation et menus d’administration.

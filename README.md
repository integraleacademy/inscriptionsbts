# Plateforme de gestion des BTS – Intégrale Academy

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
- Sur le service existant `inscriptionsbts`, les commits de `main` déclenchent le déploiement.
- Le service utilise `BREVO_API_KEY`, `SENDER_EMAIL`, `BASE_URL`, `SECRET_KEY`,
  `LOGIN_EMAIL` et `LOGIN_PASSWORD`. Les valeurs se configurent dans Render.
- Les données du service existant sont conservées sur son disque persistant `/data`.

## Campagne septembre 2027

- Ouverture publique : **1er décembre 2026 à 10 h Europe/Paris**, soit
  `2026-12-01T09:00:00Z`. Cette date est centralisée dans `campaign.py`.
- `/` présente uniquement la clôture 2026, un décompte synchronisé sur
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

### Gestion des candidatures et aperçu

- La plateforme s’appelle « Plateforme de gestion des BTS ».
- Chaque ligne mène à `/admin/candidat/<id>` : informations modifiables,
  projet, documents, communications, historique et suivi. Les actions
  individuelles ne sont plus dispersées dans le tableau.
- Le menu se réduit sur ordinateur et conserve sa position après rechargement.
- Après connexion à `/admin`, « Aperçu du formulaire » ouvre les sept étapes
  sans saisie obligatoire. La case « Tester les contrôles de saisie » permet
  de vérifier les validations. Aucun dossier ne peut être envoyé en aperçu.
- La vérification NIR (clé, année, mois, sexe, Corse) fonctionne en direct et
  côté serveur. Les quatre groupes de profil et les contrôles de pièces du
  formulaire 2026 sont conservés. Les six pièces restent proposées.
- Les suggestions utilisent les communes de l’API Géo, le géocodage IGN et
  Photon pour les villes étrangères. Pays et nationalités sont proposés
  localement. En cas d’indisponibilité, la saisie manuelle reste possible.
- Les boutons et routes de synchronisation YPAREO NEO ont été supprimés.
  Les anciennes colonnes restent en base pour conserver les historiques ;
  aucune configuration de synchronisation n’est requise.

### Vérification

`python -m pytest -q tests test_gestionstagiaires_api.py`

Tests de la frontière horaire, des restrictions avant ouverture, des
brouillons, des justificatifs, des cohortes, des e-mails, des certificats
du NIR, des champs 2026 et des fiches candidat. Les envois externes sont simulés.
Le parcours a également été vérifié dans Chromium à 1440 et 390 px,
avec candidature complète, erreurs de validation, mineur/responsable légal,
reprise, suivi candidat, filtres, actualisation et menus d’administration.

## Importer les matières depuis un référentiel officiel

Dans **Matières → Importer un référentiel**, choisir la promotion et la session
d’examen, puis laisser l’assistant rechercher le BTS ou fournir un lien officiel
(Légifrance, ministère, académie, France compétences). L’analyse OpenAI s’effectue
en arrière-plan ; l’aperçu est disponible pendant 24 heures dans la même session
administrateur. Le BTS MOS propose le lien de l’arrêté du 2 mars 2020.

La connexion utilise `OPENAI_API_KEY` si cette variable est définie. Sinon,
l’administrateur peut enregistrer sa clé via **Paramètres → OpenAI**. Cette clé est
chiffrée en base avec une clé dérivée de `SECRET_KEY` (stable, au moins 20
caractères, distincte de la valeur de développement). Une rotation de
`SECRET_KEY` nécessite de saisir à nouveau la clé API. Aucune clé n’est renvoyée
au navigateur. L’API est facturée sur le projet OpenAI configuré, séparément de
ChatGPT. Le modèle par défaut est `gpt-5.5` ; `OPENAI_REFERENCE_MODEL` permet de
choisir un modèle compatible Responses, web_search, Structured Outputs et mode
arrière-plan. Le projet doit autoriser la création et la lecture de réponses.

Seuls l’intitulé/code du diplôme, la session d’examen, la date de consultation et
le lien officiel sont envoyés à OpenAI : aucune donnée d’étudiant, de formateur ou
de candidature. Le mode arrière-plan conserve une réponse chez le fournisseur
(`store=true`). Les résultats doivent référencer une URL officielle effectivement
retournée par la recherche ; les informations proposées restent à vérifier.

L’aperçu permet de cocher/décocher les matières et de modifier leurs noms,
coefficients, unités, objectifs, contenus, modalités d’examen et horaires
hebdomadaires. Les épreuves facultatives et les doublons sont décochés par défaut.
Les formateurs et volumes annuels sont facultatifs lors de l’import, à compléter
avant la planification. Les horaires scolaires ne sont jamais convertis en
volumes annuels d’apprentissage. Les données sont ajoutées uniquement lors de la
validation de la sélection, dans une transaction atomique et idempotente ; les
matières existantes ne sont pas écrasées. Les métadonnées et l’extraction originale
sont conservées à part dans `planning_subject_details`, sans migration destructive
de `planning_subjects`. Elles restent éditables dans la fiche matière.

Les tests `tests/test_subject_references.py` simulent OpenAI et ne consomment
aucun crédit API. Le parcours navigateur simulé est couvert par
`tests/subject_references_frontend.cjs` (jsdom ; rendu automatique de la vraie page et catalogue de test associé).

Les paramètres OpenAI se trouvent dans **Paramètres → OpenAI** (`/admin/parametres`). La clé existante est conservée. Les résultats asynchrones demandent la liste complète des sources à chaque récupération ; une matière non sourcée reste visible mais ne bloque pas les autres. Les anciennes analyses bloquées par le contrôle des sources peuvent être récupérées en rouvrant l’import dans la même session, pendant 24 heures, sans nouvelle génération.

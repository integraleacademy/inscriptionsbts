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

## Catalogue de matières par diplôme

Une matière possède une fiche commune et peut être rattachée à plusieurs diplômes
(par exemple MOS et MCO). La page **Matières** permet de rechercher, filtrer par
diplôme et trier par nom, diplôme ou nombre de diplômes. Les coefficients,
objectifs, contenus, horaires scolaires et sources sont enregistrés séparément
pour chaque BTS dans la même fiche.

Les tables `planning_subject_catalog` et `planning_subject_diplomas` portent ce
catalogue. La migration regroupe les anciens libellés identiques, reprend leurs
diplômes et leurs métadonnées, et conserve les données originales. Les anciennes
lignes de `planning_subjects` deviennent les préparations des plannings, liées
au catalogue par `planning_subject_catalog_links` : leurs identifiants,
formateurs, volumes annuels et cours sont inchangés. Une préparation reste propre
à sa promotion, et n’est pas créée automatiquement à l’import d’un référentiel.

Dans un planning, **Préparer une matière du catalogue** propose les matières du
BTS de la promotion. Le formateur et le volume annuel se règlent ici, indépendamment
des autres promotions. Une matière utilisée dans un planning ne peut pas être
supprimée du catalogue ni détachée du diplôme concerné.

## Importer les matières depuis un référentiel officiel

Dans **Matières → Importer un référentiel**, choisir le diplôme et la session
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
Les formateurs et volumes annuels se règlent dans chaque planning, après l’import.
Les horaires scolaires ne sont jamais convertis en
volumes annuels d’apprentissage. Les données sont ajoutées uniquement lors de la
validation de la sélection, dans une transaction atomique et idempotente ; les
matières existantes ne sont pas écrasées. Une matière déjà présente pour un autre
diplôme est réutilisée et reçoit les informations du BTS analysé. Les métadonnées
et l’extraction originale sont conservées dans `planning_subject_diplomas` ; les
anciennes copies restent dans `planning_subject_details`. Elles restent éditables
par diplôme dans la fiche matière.

Les tests `tests/test_subject_references.py` simulent OpenAI et ne consomment
aucun crédit API. Le parcours navigateur simulé est couvert par
`tests/subject_references_frontend.cjs` (jsdom ; rendu automatique de la vraie page et catalogue de test associé).

Les paramètres OpenAI se trouvent dans **Paramètres → OpenAI** (`/admin/parametres`). La clé existante est conservée. Les résultats asynchrones demandent la liste complète des sources à chaque récupération ; une matière non sourcée reste visible mais ne bloque pas les autres. Les textes générés trop longs sont abrégés dans les champs, avec leur version intégrale consultable avant et après l’import. Les anciennes analyses bloquées par le contrôle des sources ou des textes peuvent être récupérées en rouvrant l’import dans la même session, pendant 24 heures, sans nouvelle génération.


## Carte étudiante depuis une fiche BTS

Dans **Fiche candidat → Documents → Carte étudiante**, prévisualiser ou générer
le PDF avec l’identité, la date de naissance et la photo cadrée de la fiche.
Les dates proposées couvrent l’année scolaire courante dans la promotion de
deux ans de l’étudiant ; elles restent modifiables avant chaque génération.
L’adresse de l’établissement suit le parcours : Puget pour le présentiel,
Paris pour le distanciel, comme les certificats de scolarité.

Le modèle fourni `Carte Etudiante-Bureautique.pdf` est conservé sans modification
dans `assets/student_cards/carte_etudiante_original.pdf`. Les champs proviennent
du modèle de saisie numérique fourni en parallèle. Le PDF est statique et prêt
à imprimer, sans formulaire interactif, et la signature du titulaire est laissée
vierge. Deux formats sont disponibles : A4 de deux pages avec repères de découpe
(100 %, recto verso sur le bord long), ou deux faces au format original 86 × 54 mm.
La photo enregistrée est insérée sans recadrage supplémentaire. La génération
est réservée aux administrateurs, sans envoi ni modification de l’étiquette
« Carte étudiante envoyée ». Aucun PDF nominatif n’est stocké dans les fichiers
publics. Les informations ou photos manquantes sont signalées avant impression.

Validation : `python -m pytest -q tests/test_student_cards.py tests/test_candidate_editor.py`.

## Espace entreprise et assiduité

- **Connexion → Espace entreprise** (`/entreprise/connexion`) : compte distinct
  de l’étudiant, du formateur et de l’équipe. Onglets **Mes alternants**,
  **Planning**, **Absences et retards** ; affichage adapté au mobile.
- Dans **Entreprises** (`/admin/entreprises`), créer l’entreprise et son contact,
  rattacher les étudiants confirmés, définir la période de rattachement et le
  tuteur, puis cliquer sur **Envoyer l’invitation**. La création et le rattachement
  n’envoient aucun e-mail. Une adresse correspond à un compte entreprise.
- L’activation permet de choisir un mot de passe (12 caractères minimum). Les
  liens sont à usage unique : 72 h pour l’activation, 30 min pour un compte déjà
  activé. Récupération de mot de passe, limitation des tentatives, jetons CSRF,
  sessions de 8 h liées à la version du compte et pages privées sans traceurs.
  Changer l’e-mail exige une nouvelle invitation. Désactiver le compte révoque
  immédiatement ses sessions et invitations. Aucune configuration supplémentaire
  à `SECRET_KEY`, `BASE_URL` et l’envoi de mail existants n’est nécessaire.
- Un étudiant ne peut être rattaché qu’à une entreprise à la fois. Pour le
  transférer, retirer l’ancien rattachement puis créer le nouveau avec sa date
  de début. Le retrait coupe immédiatement la visibilité. La date de fin ferme
  l’accès à l’alternant à son expiration. Les inscriptions annulées sont exclues.
- Le planning provient de la promotion actuellement affectée : cours, matières,
  salles, formateurs, jours école/entreprise, vacances et fermetures. Export PDF
  hebdomadaire. Les jours et événements hors période de rattachement sont masqués,
  y compris dans les exports. Aucun horaire de travail en entreprise n’est déduit.
- **Absences et retards** (`/admin/assiduite`) permet à l’équipe de saisir un
  événement constaté, sa date, son créneau et son justificatif (en attente,
  justifié, non justifié), puis de le corriger ou le retirer. Le registre est
  initialement vide ; il ne constitue ni un système d’émargement ni un taux de
  présence. Les créneaux en double, chevauchants, inversés ou futurs sont rejetés.
  Les mises à jour concurrentes sont détectées. L’historique technique conserve
  les corrections ; les justificatifs médicaux et motifs privés ne sont pas
  recueillis dans ce registre ni exposés à l’entreprise.
- Le compte entreprise peut filtrer le relevé mensuel par alternant et l’exporter
  en CSV (UTF-8, point-virgule, cellules protégées contre les formules). Les accès
  sont revérifiés côté serveur pour chaque page et chaque téléchargement.
- Schéma SQLite additif, sans modification des comptes ou dossiers existants :
  `companies`, `company_students`, `company_tokens`, `company_requests`,
  `student_attendance`, `company_audit`. Données conservées sur le disque existant.

Validation : `python -m pytest -q tests/test_company_portal.py`. Les e-mails sont
simulés dans les tests, avec vérifications de cloisonnement entre entreprises,
CSRF, activation/récupération, révocation, limites temporelles, exports,
chevauchements et corrections du registre.

### Recherche et import d’une entreprise par SIRET

Dans **Ajouter une entreprise**, ou dans **Informations et coordonnées de
l’entreprise** sur une fiche existante, saisir les 14 chiffres du SIRET. Après
l’aperçu, **Importer ces informations** remplit les champs ; **Créer l’espace
entreprise** ou **Enregistrer** conserve les données. Aucun envoi d’invitation
n’est déclenché par la recherche ou l’import. Le contact, l’e-mail de connexion
et le téléphone doivent être saisis par l’équipe.

La recherche côté serveur utilise l’[API publique de l’Annuaire des entreprises](https://recherche-entreprises.api.gouv.fr/docs/),
sans clé ni abonnement supplémentaire. Seul le SIRET est envoyé. L’établissement
doit correspondre exactement ; l’adresse du siège ne remplace jamais celle d’un
établissement secondaire. Une fermeture est signalée. Les données non diffusables
ne sont pas importées. Une indisponibilité laisse la saisie manuelle accessible.

L’import comprend les données administratives disponibles : nom, raison sociale,
enseigne, SIREN/SIRET, adresse, forme juridique, activité APE/NAF et libellé,
état administratif, dates de création, effectifs et année de référence, TVA,
conventions collectives, dirigeants (noms et fonctions), siège et informations
d’organisme de formation lorsqu’elles existent. Les champs d’identification et
d’adresse restent modifiables. Un relevé des informations officielles conserve
la source et la date de consultation. Il est supprimé si le SIRET change sans
nouvel import. Les dates de naissance des dirigeants ne sont pas recueillies.

La prévisualisation signée expire après deux heures. Les données ne sont
enregistrées qu’avec le formulaire, soumis aux protections administrateur, CSRF
et version existantes. La migration ajoute des colonnes à `companies` sans
modifier les comptes, mots de passe ou rattachements.

`reference_data/company_nomenclatures.json` contient les libellés publics de
l’[Annuaire des entreprises](https://github.com/annuaire-entreprises-data-gouv-fr/site/tree/main/src/utils/helpers/formatting/metadata)
(catégories juridiques, NAF rév. 2 et NAF 2025 ; consultés le 25 octobre 2026).
Les codes inconnus restent affichés. La NAF 2025 est utilisée pour les libellés
de l’activité principale à partir de 2027.

Tests : `tests/test_company_registry.py` (API simulée, établissement exact,
permissions, erreurs et persistance) et `tests/company_registry_frontend.cjs`
(jsdom, prend le chemin d’une page admin rendue ; recherche différée, réponse
obsolète, import explicite et conservation du contact).

### Présentation de l’accès entreprise

Les pages de connexion, récupération et activation utilisent les composants
et les thèmes quotidiens des accès étudiant/formateur (`daily-login.css`).
L’illustration dédiée est enregistrée dans
`static/admissions/company-space-illustration.webp`, générée avec l’outil
intégré imagegen puis encodée en WebP pour le site.

Consigne de génération :

Révision : redessin de l’illustration entreprise à partir des références directes
`daily/trainer-sun.webp` et `daily/student-sun.webp`, sans modifier ces dernières.

> Use case: style-transfer. Edit target = image 1 (the employer mentor and apprentice at a desk). Style references = image 2 (the trainer at a planning board) and image 3 (students collaborating). Redraw image 1 completely in EXACTLY the same visual language as references 2 and 3, so it feels painted by their same illustrator for the same educational series. The two references are the authoritative style: simple rounded friendly cartoon facial features, large expressive eyes, short clean bold contours, broad flat colour areas and sparse crisp cel shading, simple grouped hair shapes, uncluttered fabric folds, bright clean blues and greens, sunny cream and pale wood, clearly drawn plants/windows. Remove the target's fine realistic hair strands, narrow realistic eyes, sculpted faces, detailed folds, blurred photographic background, depth-of-field and glossy rendering. Keep the business story: an adult female tutor and adult male apprentice smiling as they review a weekly plan at a wooden office desk, with a laptop, notebooks, green plants and blue-framed windows. Loosen the crop a little to match the spacious medium composition of the reference illustrations. Both characters should look clearly adult but have the rounded simplified warmth of reference 3; anatomically correct hands. Full-bleed standalone landscape 3:2 illustration. No text, logos, UI, watermark, outer border, or written labels. The final must match references 2 and 3 much more closely than the original image 1.

### Administration des entreprises

L’annuaire propose une recherche (nom, contact, ville, SIRET), des filtres d’accès,
un tri et une pagination de 20 entreprises. La création dispose de sa propre page.
Les fiches se répartissent en cinq onglets : vue d’ensemble, coordonnées, données
officielles, alternants et accès. Les onglets fonctionnent avec des liens directs
et préservent les champs saisis lors des changements d’onglet en JavaScript.
L’import SIRET reste explicite, signé et limité aux données de l’entreprise.

Tests complémentaires : `tests/test_company_workspace.py` (routes, filtres,
comptages, pagination, autorisations et validation), `tests/company_admin_frontend.cjs`
(jsdom, prend une fiche entreprise rendue ; clavier, historique, conservation
des champs et protection des modifications non enregistrées).

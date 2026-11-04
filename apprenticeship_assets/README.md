# Dossiers d’apprentissage

## Références et documents

- `cerfa_10103-14.pdf` : formulaire officiel 10103*14, téléchargé le 4 novembre 2026 depuis <https://www.formulaires.service-public.gouv.fr/gf/cerfa_10103.do>. Les champs du formulaire sont remplis avec pypdf ; les signatures ne sont jamais fabriquées.
- `convergence-v2.json` : schémas nécessaires au dépôt V2, extraits du Swagger officiel <https://www.cfadock.fr/portail_developpeur/swagger/ApiCfaOpco/v1/swagger.json> (info.version 3.0.4). Portail : <https://www.cfadock.fr/portail_developpeur>.
- Le Swagger emploie `employeurV2` dans une liste de champs obligatoires, mais `employeur` dans les propriétés et exemples. `apprenticeship_data.py` normalise uniquement cette incohérence.
- La convention PDF est produite à partir des parties, de la formation, des coûts et des clauses saisis dans le dossier. Elle doit être relue et complétée avant signature.

## Parcours

Le bouton « Créer un dossier » crée un dossier local en recette, sans appel d’écriture à un OPCO. La synthèse historique reste accessible dans la fiche étudiant. Le nouvel espace global rassemble les dossiers locaux et les relevés OPCO existants, avec filtres et suivi des échéances.

Chaque dossier dispose d’un identifiant interne de six caractères, distinct du `numeroInterne` attribué par l’OPCO. Les données disponibles de l’étudiant, de sa promotion et de son entreprise sont préremplies. Les codes réglementaires, salaires, volumes et coûts manquants restent à compléter.

Les documents signés sont rattachés à une révision du contenu. Une modification des informations utilisées dans les PDF impose une nouvelle signature ; les notes internes et confirmations de signature ne modifient pas cette révision. L’interface conserve les anciens documents. Les dossiers transmis sont figés : un avenant fait l’objet d’un nouveau dossier.

## Connexions Convergence

Les connexions se règlent dans « Contrats d’apprentissage > Connexions OPCO ». Chaque OPCO et environnement dispose de ses propres accès chiffrés. Les hôtes sont limités aux domaines de l’OPCO, sans redirection HTTP. La connexion AKTO de recette réutilise la clé du réglage AKTO existant et les variables serveur `AKTO_RECETTE_CLIENT_ID` / `AKTO_RECETTE_CLIENT_SECRET`. Les connexions de production EP, Mobilités et Opcommerce déjà configurées sont également réutilisables.

Le dépôt nécessite tous les champs obligatoires, les clauses de convention et les attestations, les deux PDF signés de la révision courante, puis une confirmation du numéro de dossier et de l’environnement. Il utilise exactement `POST /v2/dossiers` : le CERFA dématérialisé et la convention dans le champ JSON `PostDossierRequestV2`, plus la convention signée dans `fichier`. Le CERFA signé est conservé localement ; il n’existe pas de type CERFA dans l’énumération de `/v1/documents`, cet endpoint n’est donc pas appelé pour ce PDF.

Les transmissions ne sont ni automatiques ni réessayées automatiquement. Une réponse indéterminée ou une interruption laisse le dossier bloqué pour vérification et récupération par référence OPCO. Un accusé de réception doit contenir `numeroInterne`. Une référence Intégrale Academy ne doit jamais être envoyée à sa place.

La récupération utilise `GET /v2/dossiers`, avec le numéro interne OPCO ou le couple numéro externe / DECA. Nom, prénom et date de naissance doivent correspondre à la fiche étudiant avant import. Les statuts et échéances sont récupérés à la demande. Une échéance OPCO est en lecture seule ; les prévisions saisies manuellement restent identifiées. Un règlement absent n’est pas assimilé à zéro. Un échéancier absent ou invalide ne remplace pas le dernier relevé exploitable.

## Stockage et vérification

Les tables SQLite ajoutées sont indépendantes des contrats historiques. Données détaillées, PDF et accès API sont chiffrés avec le mécanisme existant dérivé de `SECRET_KEY` : préserver cette clé et les sauvegardes du disque `/data`. Les accès exigent une session administrateur, les écritures un jeton CSRF, et les mises à jour une version courante pour éviter l’écrasement entre deux fenêtres.

Tests : `python -m pytest -q tests/test_apprenticeship.py tests/test_akto_recette.py tests/test_opco_convergence.py`. La nouvelle suite utilise uniquement des personnes fictives et des réponses OPCO simulées. Elle couvre notamment l’idempotence, l’authentification, le chiffrement, la concurrence, les champs et widgets du CERFA, l’invalidation des signatures, le multipart officiel, les erreurs de transmission et les échéances.

Une qualification réelle avec l’OPCO reste nécessaire avant le premier dépôt de production. Les tests ne constituent pas une validation d’accrochage Convergence ni une vérification cryptographique des signatures des PDF déposés.

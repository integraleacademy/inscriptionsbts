# Planning et salles partagées

Le registre des salles BTS est la source de vérité pour les cours, événements et sessions de plateformegestion. Les écritures BTS et les réservations des sessions prennent le même verrou SQLite `BEGIN IMMEDIATE`. Les événements ponctuels restent hors volume des matières et hors duplication hebdomadaire.

## Configuration

Configurer le même `SHARED_ROOMS_TOKEN` aléatoire dans les deux services, `SESSION_ROOMS_URL=https://plateformegestion.onrender.com` côté BTS et `BTS_ROOMS_URL=https://inscriptionsbts.onrender.com` côté sessions. Conserver le secret uniquement dans Render. Déployer les deux versions puis appeler une seule fois `POST /api/shared-rooms/bootstrap` sur la plateforme des sessions avec `Authorization: Bearer <secret>`. Le bouton d’administration peut appeler `/admin/planning/api/rooms/bootstrap` avec son CSRF. Tant que cette initialisation n’est pas terminée, les nouvelles réservations de salles sont bloquées.

La synchronisation initiale prend les verrous du fichier sessions.json, importe les salles nommées et les réservations existantes. Les conflits historiques restent affichés en rouge, sans suppression de données. Les adresses de centres ne sont pas des salles : ces sessions sont à affecter depuis `/admin/salles`. Sans planning détaillé, choisir les jours et horaires dans le formulaire. Les réservations de sessions nommées sans horaires sont conservées sur la journée entière par prudence.

## Cohérence et récupération

Le stockage JSON des sessions prépare les réservations avant l’écriture atomique et confirme après le remplacement durable. Les créneaux précédents et nouveaux restent occupés entre ces étapes. Une panne n’autorise donc pas un double usage. Une validation refusée laisse la session inchangée. Une confirmation perdue conserve temporairement les deux réservations.

« Actualiser les sessions » réconcilie les confirmations en attente avec le fichier source, sous verrou. Ne jamais effacer une réservation en attente directement : vérifier la version persistée sur la plateforme source. Les anciens libellés des salles sont gardés comme alias lors d’un renommage. Toute réaffectation d’un cours commun concerne toutes ses promotions.

## Vérification

`python -m pytest -q tests/test_planning_rooms_events.py` couvre les limites, événements, conflits, transactions, versions et réservations simultanées. La plateforme source possède `tests/test_shared_rooms.py` et les tests du stockage atomique. Les routes machine exigent le secret ; les mutations de l’interface exigent une session admin et un CSRF.

## Source des sessions et correction de périmètre

Seule la liste `/sessions` (fichier `sessions.json`) alimente le registre externe. Le module indépendant `/planning` et sa table `formations` sont exclus : ni lecture, ni réservation, ni modification depuis la liaison. La migration `sessions_only_v1` retire uniquement leurs copies `formation:*` du registre BTS, en conservant les vrais cours, événements, sessions et salles. Elle conserve le nombre de copies retirées pour vérification. L’API refuse toute nouvelle référence `formation:*`.

Les cartes du calendrier modifient les salles sur `/admin/salles` : formulaire de session dans la même page, ou dialogue pour un cours / événement BTS. Aucun clic sur une réservation ne renvoie vers l’ancien éditeur de formation.

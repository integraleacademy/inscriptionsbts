# Contrats d’apprentissage dans les fiches étudiantes

Une seule vérification automatique démarre chaque jour à **8 h, heure de Paris**,
même sans visite du site. Elle recherche les contrats des inscriptions confirmées ou
reconfirmées et actualise tous les contrats déjà rattachés, avec leurs échéanciers.
L’ouverture d’une fiche ou de la liste des inscriptions lit uniquement les données
enregistrées. Le bouton « Actualiser l’affichage » de la liste reste une lecture locale.
La recherche et l’actualisation manuelles d’un contrat restent possibles dans sa fiche.
Aucune écriture n’est faite dans WEDOF ni dans les affectations d’entreprises locales.

## Configuration

Réutiliser le compte WEDOF existant : configurer `WEDOF_API_KEY` côté serveur ou
renseigner la clé dans `/admin/parametres#wedof`. La seconde méthode chiffre la clé
avec `SECRET_KEY` (stable et d’au moins 20 caractères). Ne jamais committer une clé.
Les permissions du compte WEDOF et les connexions OPCO déterminent les données reçues.
Le stockage SQLite utilise la base persistante existante de l’application.

## Passage quotidien

`wedof_daily_sync.py` démarre dans le service web Render, sur le même disque que la
base SQLite. L’horaire utilise `Europe/Paris` et suit les changements d’heure. La
première installation programme le prochain 8 h ; ensuite, un redémarrage après
l’horaire reprend le passage du jour s’il n’a pas déjà été terminé.

Une file persistante et un verrou partagé de 120 secondes empêchent plusieurs
workers de traiter la même étape. Les dossiers terminés restent terminés après un
redémarrage ou un déploiement. Les pauses imposées par WEDOF suspendent puis
reprennent ce même passage. Une indisponibilité réseau ou une erreur de connexion
interrompt le passage jusqu’au lendemain, en conservant les données précédentes.
Une actualisation manuelle en cours fait attendre la file sans l’annuler.
Les retraits volontaires restent exclus du rattachement automatique.

Le traitement est borné à une étape à la fois ; il ne parcourt pas le catalogue
global WEDOF. `WEDOF_DAILY_SYNC_DISABLED=1` désactive le worker pour les tests.
Les dates et états des passages sont stockés dans `student_wedof_daily_runs` et
les étapes dans `student_wedof_daily_items`. Les logs de début et de fin ne
contiennent aucune identité ni clé API.

## Lectures et limitation

OpenAPI officielle vérifiée le 26 octobre 2026 : https://www.wedof.fr/api/doc.json.
Authentification `X-Api-Key`, hôte fixe https://www.wedof.fr/api, redirections interdites.

- Découverte : `GET /registrationFolders?findOtherFoldersOfAttendee=<email>` ; si
  aucun dossier compatible n’est trouvé, une recherche ciblée `query=<nom>` est faite.
  Les noms, prénoms et dates de naissance sont contrôlés localement. Les contrats
  sont ensuite demandés uniquement pour les références exactes des dossiers trouvés.
  Au maximum cinq dossiers et une page par dossier sont lus ; un résultat incomplet
  ou plusieurs contrats empêchent tout rattachement automatique.
- Identifiant WEDOF : `GET /workingContracts/{id}`.
- Référence dossier de formation : `GET /workingContracts` filtré par
  `registrationFolderExternalId`, `financer`, `state=all`, page 1 et limit 100.
- Numéro OPCO/DECA : l’API ne documente aucun filtre sur ces deux numéros. Une page
  de résumés de l’OPCO choisi est lue ; seules les correspondances exactes sont
  conservées dans l’aperçu temporaire. La page suivante exige un clic explicite.
  Aucun scan en boucle et aucun dossier non sélectionné n’est importé.
- Aperçu : relecture du contrat sélectionné, puis dossier de formation associé et
  `GET /workingContracts/{id}/raw` pour les données CFA Dock et échéances.
- Actualisation : mêmes lectures ciblées pendant le passage du matin. Les actions
  manuelles réutilisent un résultat réussi pendant 30 minutes ; le passage du matin
  vérifie les données à partir de son heure de démarrage. Le GET de la liste reste
  une lecture locale. Les POST de découverte manuelle exigent la session admin,
  le CSRF et `origin: "interactive"` ; les anciens scripts ouverts dans un onglet
  ne peuvent donc plus relancer de recherches automatiques.
  Chaque étape est bornée (au plus trois lectures externes). Les résultats réussis,
  même vides, restent affichés entre deux passages quotidiens. Les erreurs manuelles
  sont conservées une minute ; une relance explicite peut retenter un échec,
  mais respecte toujours une pause imposée par WEDOF.
  La découverte reprend l’étape interrompue tant que ses résultats restent valides.
  Une modification de l’identité ou de la clé invalide ce cache.

Chaque lecture est sans retry, timeout connexion 3 s / lecture 5 s. Une opération
WEDOF à la fois, verrou SQLite partagé entre workers. Les anciens plafonds internes
de 100 lectures par heure et 500 par jour sont supprimés, et leurs erreurs déjà
enregistrées sont invalidées dès la prochaine lecture. Une protection contre les
rafales reste limitée à 100 lectures sur une minute glissante.

La [documentation WEDOF](https://www.wedof.fr/api/doc/structure), vérifiée le
29 octobre 2026, indique des limites à la minute, variables selon l’offre et le type
d’appel. Les réponses `429` et `X-RateLimit-Remaining: 0` enregistrent une pause
partagée entre fiches et workers, liée à l’empreinte de la clé. Le délai vient de
`Retry-After` (secondes ou date HTTP), `X-RateLimit-Reset` ou `X-RateLimit-Retry-At` ;
à défaut, il est d’une minute. Une relance ne contourne pas cette pause. Le délai
restant est affiché, sans annoncer à tort une conservation de l’erreur 30 minutes.
Les compteurs du fournisseur prennent ainsi en compte l’usage du compte partagé
avec d’autres sites. Pas de retry immédiat d’une requête réseau en échec.

## Liste des inscriptions

Les six KPI sont calculés après tous les filtres : effectif, avec contrat, sans
contrat identifié, contrat à vérifier, sans promotion et distanciel. Un étudiant
ayant plusieurs contrats est compté une seule fois. « Avec contrat » indique un
rattachement existant, y compris un contrat en instruction ou historique : l’état
WEDOF (engagé, en instruction, rompu, etc.) est affiché séparément et ne prétend pas
indiquer un emploi en cours. « Sans contrat identifié » exige une recherche complète
et réussie, sans résultat, encore valide pour l’identité et la connexion courantes.
Une erreur, un résultat ambigu, un retrait volontaire ou une absence de recherche
reste « À vérifier ». Les trois catégories partitionnent l’effectif filtré.

Les filtres de la liste n’influencent pas le périmètre du passage quotidien.
Le bouton d’actualisation relit les résultats et tous les KPI avec les mêmes filtres.
Le GET `/admin/inscriptions/donnees` ne lit que
les données locales, exige la session administrateur et interdit le cache. La clé
WEDOF et les informations d’identité utilisées pour la vérification ne sont pas
incluses dans sa réponse.

Les portraits utilisent la route privée existante de la fiche, avec le recadrage
enregistré. Les initiales restent affichées en l’absence de fichier utilisable.

## Intégrité

Aperçus limités à 30 minutes, liés à la session admin, à l’étudiant et à la clé.
CSRF sur toutes les mutations. Un contrat unique n’est rattaché automatiquement que
si nom et prénom correspondent, avec en plus soit l’e-mail exact, soit la date de
naissance exacte. Toute date de naissance connue contradictoire bloque le lien.
Le contrat et son dossier sont relus avant le rattachement ; la fiche et la clé
sont revérifiées dans la transaction finale. Les cas ambigus sont proposés via
l’aperçu manuel existant. Le retrait volontaire d’un lien suspend la découverte
jusqu’au clic explicite « Rechercher maintenant » ou au changement de fiche/clé.
Références et identités sont contrôlées. Un désaccord
sur l’identité ou la date de naissance bloque le rattachement ; une identité absente
exige une vérification manuelle explicite. Un contrat ne peut appartenir qu’à une fiche.
Les écritures ne touchent jamais aux informations de candidature existantes.

Les données brutes CERFA, NIR, IBAN et URL externes ne sont pas conservés.
Les erreurs HTTP sont remplacées par des messages neutres. Les pages privées et les
réponses JSON sont non mises en cache ; les traceurs publics sont exclus de l’admin.

Les échéances absentes ou partielles restent inconnues. Les totaux ne sont calculés
que si tous les montants nécessaires sont présents, en centimes. Une ouverture à
facturation n’est jamais présentée comme un retard de paiement. Les frais annexes
ne sont pas ajoutés aux montants de formation. En cas d’échec, l’ancien échéancier
est conservé mais marqué « À vérifier ». Aucun envoi de facture n’est effectué.

## Présentation et situation de l’étudiant

Le contrat dispose de cinq sous-onglets indépendants : vue d’ensemble, contrat et
formation, entreprise et tuteur, échéancier, frais annexes. La navigation au clavier
et la sélection lors d’une actualisation sont conservées. L’échéancier devient une
liste de cartes avec libellés sur petit écran. Les filtres et badges utilisent des
codes distincts : réglée (vert), à venir (bleu), ouverte à facturation (orange),
en instruction (violet), à vérifier (rouge orangé), inconnu (gris). Les états et
les icônes restent lisibles sans se reposer uniquement sur la couleur.

Le pourcentage de règlement utilise le total de l’échéancier, jamais l’engagement
OPCO, et reste absent si les données sont incomplètes ou périmées. La prochaine
échéance à suivre est la première échéance non soldée disposant d’une date
d’ouverture ; ce repère ne prétend pas constituer une échéance de paiement.

`candidate_statuses.py` calcule le statut affiché « En entreprise » à partir d’un
rattachement local en cours ou d’un contrat WEDOF engagé, démarré et non terminé
ni rompu. Les dates sont évaluées en Europe/Paris. La déclaration « entreprise
trouvée » seule n’est pas une preuve de rattachement. Les dossiers annulés, non
conformes ou non encore examinés conservent leur statut d’inscription.

Ce statut est partagé par le badge de la fiche, la liste, ses filtres et ses KPI.
L’étape d’inscription stockée ne change pas : les campagnes de reconfirmation, les
accès aux espaces et les notifications continuent d’utiliser le statut d’admission.
Aucun message n’est envoyé par une mise à jour de l’affichage.

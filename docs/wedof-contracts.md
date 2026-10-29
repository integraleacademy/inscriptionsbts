# Contrats d’apprentissage dans les fiches étudiantes

L’onglet administrateur « Contrat d’apprentissage » recherche automatiquement le contrat
lorsqu’il est ouvert sur une fiche sans contrat. Le rattachement manuel reste disponible.
La page Inscriptions lance également cette recherche pour les étudiants concernés par
ses filtres, un étudiant et une étape à la fois. Elle réutilise les mêmes contrôles
d’identité, caches, limites de lecture et suspensions de rattachement. Les erreurs
de connexion ou de quota interrompent la file ; le bouton « Vérifier les contrats »
permet de reprendre les dossiers encore à vérifier sans effacer les contrats trouvés.
Il ne modifie jamais WEDOF et n’importe aucun dossier globalement. Il ne modifie pas
non plus les affectations d’entreprises locales.

## Configuration

Réutiliser le compte WEDOF existant : configurer `WEDOF_API_KEY` côté serveur ou
renseigner la clé dans `/admin/parametres#wedof`. La seconde méthode chiffre la clé
avec `SECRET_KEY` (stable et d’au moins 20 caractères). Ne jamais committer une clé.
Les permissions du compte WEDOF et les connexions OPCO déterminent les données reçues.
Le stockage SQLite utilise la base persistante existante de l’application.

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
- Actualisation : mêmes lectures ciblées, au plus une fois par 30 minutes et par
  contrat après une réussite ; un échec autorise une nouvelle tentative après une
  minute, sous réserve du délai WEDOF. Le GET de la liste reste une lecture du cache local ;
  la découverte utilise des POST avec CSRF depuis la fiche ou la liste filtrée.
  Chaque requête traite une étape bornée (au plus trois lectures externes). Les
  résultats de découverte réussis, même vides, sont conservés 30 minutes entre
  les sessions admin. Les erreurs sont conservées une minute ; une relance manuelle
  peut retenter un échec, mais respecte toujours une pause imposée par WEDOF.
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
avec d’autres sites. Aucun retry réseau automatique ni attente bloquante.

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

La recherche conserve les autres filtres même lorsque le filtre contrat masque les
étudiants non encore vérifiés. Les résultats et tous les KPI sont relus à chaque
découverte, avec les mêmes filtres. Le GET `/admin/inscriptions/donnees` ne lit que
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
jusqu’au clic explicite « Rechercher automatiquement » ou au changement de fiche/clé.
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

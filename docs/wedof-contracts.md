# Contrats d’apprentissage dans les fiches étudiantes

L’onglet administrateur « Contrat d’apprentissage » recherche automatiquement le contrat
lorsqu’il est ouvert sur une fiche sans contrat. Le rattachement manuel reste disponible.
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
  contrat, y compris après échec. Le GET de la liste reste une lecture du cache local ;
  la découverte utilise des POST avec CSRF à l’ouverture du seul onglet concerné.
  Chaque requête traite une étape bornée (au plus trois lectures externes). Les
  résultats de découverte, même vides ou en erreur, sont conservés 30 minutes entre
  les sessions admin. Une modification de l’identité ou de la clé invalide ce cache.

Chaque lecture est sans retry, timeout connexion 3 s / lecture 5 s. Une opération
WEDOF à la fois, verrou SQLite partagé entre workers. Plafonds internes locaux :
100 lectures par heure et 500 par jour. Ils ne représentent pas le quota du compte
WEDOF partagé avec d’autres sites.

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

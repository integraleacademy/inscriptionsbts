# Convention de mobilité Londres

La fiche `/admin/candidat/<id>#londres` permet de préparer la convention des candidats en présentiel, de générer le PDF et le Word, puis d’envoyer explicitement le PDF en signature électronique Yousign à l’entreprise, à l’apprenti et au représentant légal pour un mineur. Une copie signée peut aussi être déposée manuellement. La génération seule ne déclenche aucun e-mail.

Le préremplissage utilise uniquement l’entreprise et les contrats WEDOF rattachés au candidat. En présence de plusieurs contrats, l’administrateur choisit le contrat. Les données restent modifiables avant génération. Le budget est enregistré pour le suivi, sans ajouter de clause financière au modèle.

Chaque génération conserve un instantané des informations, les empreintes SHA-256 et des fichiers distincts dans `DATA_DIR/voyage_londres`. Les tables `london_mobility_settings` et `london_mobility_versions` sont créées de manière additive. Les anciennes versions ne sont jamais écrasées ; les suppressions depuis le tableau voyage sont bloquées pour ces archives. Un voyage peut toujours être annulé. Les conventions déjà produites dans Gestion Stagiaires restent dans ses archives.

## Modèle

`assets/london_mobility/convention_mobilite.dotx` reprend le modèle de Gestion Stagiaires, avec ses clauses, son annexe pédagogique, son identité visuelle et les signatures déjà présentes dans le modèle. Les exports sont à relire et à faire signer par les parties. Le dépôt manuel confirme uniquement qu’une copie signée a été fournie ; il ne vérifie pas de signature électronique.

Le PDF est rempli à partir d’un fond exporté de ce même modèle. Aucun appel réseau ni LibreOffice n’est nécessaire à la génération en production. Après modification du modèle, reconstruire et contrôler visuellement les huit pages des variantes majeure et mineure :

```sh
python scripts/build_london_mobility.py
```

La compilation locale utilise LibreOffice, PyMuPDF et python-docx ; `SOFFICE` peut préciser le chemin de LibreOffice. Commiter le modèle, les deux PDF et `manifest.json` ensemble. Le modèle Word est vérifié par empreinte avant génération.

## Vérification

```sh
python -m pytest tests/test_london_mobility.py tests/test_voyage_londres.py tests/test_admissions_2027.py tests/test_candidate_editor.py
```

Les tests utilisent des candidats fictifs et n’envoient aucun message. Ils couvrent les fichiers réellement produits, les révisions concurrentes, le préremplissage, les contrôles de dates, les mineurs, les permissions, le dépôt signé et la conservation des archives.

## Signature électronique

Après génération, relire le PDF et compléter les coordonnées du signataire de l’entreprise. L’e-mail de l’apprenti et celui du représentant légal sont préremplis depuis la fiche et restent modifiables avant envoi. Chaque destinataire utilise une adresse distincte et reçoit son invitation puis son code personnel par e-mail. Les signatures CFA/Kaplan présentes dans le modèle restent inchangées.

L’envoi nécessite une confirmation explicite. La demande, ses destinataires et le PDF sont figés dans `london_mobility_signatures`. Chaque mutation distante est enregistrée avant l’appel. Après un délai d’attente, actualiser le suivi : ne jamais recréer aveuglément une demande. Un téléversement ou un ajout de signataire dont le résultat reste incertain impose l’annulation du brouillon. Les relances manuelles sont limitées aux destinataires encore notifiés, avec un délai de 30 minutes entre deux relances.

Un verrou par candidat protège les opérations concurrentes. La génération d’une autre version et le dépôt manuel sont bloqués tant qu’une demande est active. Une annulation explicite permet de corriger les destinataires ou la convention. Les originaux et les demandes précédentes restent conservés.

Le suivi peut être actualisé par bouton. Il est aussi vérifié automatiquement dans l’onglet et par un fil de fond lancé à la première requête de l’application (contrôle toutes les 90 secondes au plus par demande). Le PDF signé est récupéré uniquement après confirmation de toutes les signatures et vérification des documents et des identités de la demande. L’archivage est transactionnel et ne remplace pas les fichiers originaux. Le statut « Transmise OPCO » reste conservé.

Configuration Render, sur **inscriptionsbts** :

- `YOUSIGN_API_KEY` : clé API de production, conservée exclusivement dans les secrets Render.
- `YOUSIGN_BASE_URL=https://api.yousign.app/v3` (valeur par défaut).
- `YOUSIGN_ENV=production` (valeur par défaut).

Aucun webhook n’est requis pour ce suivi autonome. Aucun appel ne passe par Gestion Stagiaires. Pour un environnement de test isolé uniquement, utiliser une clé sandbox avec `YOUSIGN_ENV=sandbox` et l’URL `https://api-sandbox.yousign.app/v3`. L’interface affiche alors le mode test.

Le workflow `london-mobility.yml` exécute les tests de génération et signature avec une fausse API, puis le vrai formulaire Chromium en 1440 et 390 pixels. Il vérifie notamment les boutons `name="action"` qui masquent `form.action`, la validation du SIRET, la confirmation d’envoi, les signatures d’un mineur et l’archivage. Aucun message réel n’est envoyé par ces tests.

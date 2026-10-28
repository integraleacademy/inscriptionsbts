# Convention de mobilité Londres

La fiche `/admin/candidat/<id>#londres` permet de préparer la convention des candidats en présentiel, de générer le PDF et le Word, puis de déposer une copie PDF signée. La signature électronique Yousign n’est pas déclenchée par ce module.

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

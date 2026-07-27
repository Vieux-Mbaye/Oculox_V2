# Environnement De Développement Oculox

## Objectif

Le répertoire `dev/` contient exclusivement les éléments développés localement autour d'Oculox/Malcolm.

Les fichiers Malcolm d'origine restent à leur emplacement habituel, à la racine du dépôt. Cette séparation permet de :

- comparer facilement notre travail avec le projet d'origine ;
- mettre à jour Malcolm sans mélanger les changements locaux avec le code amont ;
- identifier clairement ce qui a été ajouté par l'équipe ;
- tester une modification avant de l'intégrer définitivement ;
- revenir à la configuration d'origine sans supprimer ni réécrire ses fichiers.

## Organisation

```text
dev/
├── phase1/       # étude détaillée de l'existant
├── compose/      # surcharges Docker Compose locales
├── config/       # modèles de variables de développement
├── scripts/      # commandes automatisées et reproductibles
├── tests/        # scénarios et contrôles de validation
├── monitoring/   # définitions de métriques et tableaux de bord
└── docs/         # décisions et procédures de développement
```

## Règle Fondamentale

Une modification locale doit d'abord être ajoutée dans `dev/`.

Par exemple, pour modifier le service Logstash, on ne commence pas par réécrire le service dans `docker-compose.yml`. On ajoute uniquement la propriété à surcharger dans :

```text
dev/compose/docker-compose.dev.yml
```

Docker Compose fusionne ensuite le fichier d'origine et la surcharge :

```bash
docker compose \
  --project-directory . \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  config
```

Le premier fichier constitue la base. Le deuxième contient seulement nos différences.

## Fichiers Versionnés Et Fichiers Locaux

Les éléments suivants sont versionnés :

- fichiers Compose dédiés ;
- modèles `*.env.example` sans secret ;
- scripts ;
- tests ;
- documentation ;
- définitions de monitoring.

Les éléments suivants ne doivent pas être versionnés :

- mots de passe ;
- clés privées ;
- certificats propres à une installation ;
- fichiers `.env` réels ;
- résultats volumineux ;
- captures PCAP ;
- bases de données et index OpenSearch.

## État Initial

Le fichier `dev/compose/docker-compose.dev.yml` est volontairement neutre. Il permet de valider l'organisation sans modifier le comportement actuel de Malcolm.

Les changements fonctionnels seront ajoutés progressivement, avec un test et une explication associés.


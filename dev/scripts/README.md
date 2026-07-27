# Scripts De Développement

Les scripts placés ici doivent rendre une opération reproductible.

Un script doit :

- commencer par `set -euo pipefail` lorsqu'il s'agit de Bash ;
- calculer ses chemins à partir de son propre emplacement ;
- refuser une entrée invalide ;
- ne contenir aucun mot de passe ;
- afficher clairement l'opération réalisée ;
- proposer un mode de vérification avant toute action destructive.

## Script Initial

`validate-compose.sh` fusionne le Compose d'origine avec notre surcharge et demande à Docker Compose de vérifier le résultat.

Il ne démarre aucun conteneur.

```bash
./dev/scripts/validate-compose.sh
```

## Gestion Des Modes De La Plateforme

`platform-mode.sh` évite de conserver inutilement toute la plateforme en mémoire :

```bash
./dev/scripts/platform-mode.sh status
./dev/scripts/platform-mode.sh check
./dev/scripts/platform-mode.sh core
./dev/scripts/platform-mode.sh full
./dev/scripts/platform-mode.sh stop
```

Le mode `core` ne démarre qu'OpenSearch et Logstash. Le mode `full` est réservé aux tests complets.

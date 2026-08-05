# Scripts De Développement

Les scripts placés ici doivent rendre une opération reproductible.

Un script doit :

- commencer par `set -euo pipefail` lorsqu'il s'agit de Bash ;
- calculer ses chemins à partir de son propre emplacement ;
- refuser une entrée invalide ;
- ne contenir aucun mot de passe ;
- afficher clairement l'opération réalisée ;
- proposer un mode de vérification avant toute action destructive.

## Gestion Intégrée Oculox

Le lanceur racine `./oculox` orchestre les scripts de ce répertoire. Il fournit
une procédure commune aux rôles Principal et Hedgehog :

```bash
./oculox install principal --server-name <nom-DNS-ou-IP>
./oculox install hedgehog --principal-host <nom-DNS-ou-IP> \
  --collector-name <nom> --bundle <répertoire>
./oculox start
./oculox restart [service...]
./oculox status
./oculox logs [service...]
./oculox pull
./oculox stop
./oculox validate
```

`install` appelle d'abord l'installateur et la génération des secrets officiels
Malcolm. Il applique ensuite les ajouts Oculox et démarre le profil complet.
Les commandes `start`, `stop` et `status` chargent systématiquement le Compose
officiel et la surcharge Oculox.

## Audit Du Dépôt

`audit-dev-repository.sh` exécute les contrôles statiques et de sécurité avant
une livraison. Il ne démarre aucun conteneur et ne supprime aucune donnée :

```bash
./dev/scripts/audit-dev-repository.sh
```

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

## Préparation De La Phase 6

```bash
./dev/scripts/prepare-phase6.sh
```

Ce script exécute deux opérations reproductibles :

1. `render-filebeat-ha-config.py` part des cinq configurations Filebeat
   officielles et génère leurs variantes à deux destinations ;
2. `generate-beats-pki.sh` crée une autorité locale et les certificats serveur
   et client nécessaires au TLS mutuel.

Les résultats sont écrits dans `dev/generated/`, répertoire ignoré par Git.
Les configurations officielles et les secrets ne sont donc ni remplacés ni
versionnés.

Le mode réduit complet de la phase 6 se lance avec :

```bash
./dev/scripts/platform-mode.sh dual-ingest
```

## Contrôles De La Phase 7

`collect-phase7-state.sh` affiche la santé des conteneurs, le type et
l'occupation des files de chaque pipeline, les registres Filebeat et
l'occupation du disque :

```bash
./dev/scripts/collect-phase7-state.sh
```

Le script continue son diagnostic lorsqu'une API Logstash est momentanément
indisponible. Il ne modifie aucune donnée.

`check-beats-certificates.sh` vérifie la chaîne de confiance, les identités, les
SAN et l'échéance des certificats. Son argument facultatif est le seuil d'alerte
en jours :

```bash
./dev/scripts/check-beats-certificates.sh 90
```

La conception, les résultats et la procédure de rotation sont documentés dans
`dev/docs/08_phase7_persistance_reprise_certificats.md`.

## Supervision - Phase 8

`collect-platform-metrics.py` interroge Docker, Filebeat, Logstash et
OpenSearch et produit un instantané JSON atomique. `monitor-platform.sh`
répète cette opération et `summarize-monitoring.py` consolide les maxima.

```bash
./dev/scripts/monitor-platform.sh controle 60 5
./dev/scripts/monitor-platform.sh benchmark 60 5 lightweight
```

Le mode `lightweight` évite les statistiques OpenSearch détaillées pendant un
benchmark. Il conserve les contrôles indispensables et réduit l'effet de la
supervision sur la charge mesurée.

## Modes De Comparaison - Phase 10

Deux modes réduits supplémentaires garantissent un test non ambigu :

```bash
./dev/scripts/platform-mode.sh single-ingest
./dev/scripts/platform-mode.sh dual-ingest
```

`single-ingest` arrête explicitement `logstash-2`. Le mode double démarre les
deux destinations et la configuration Filebeat avec `loadbalance: true`.

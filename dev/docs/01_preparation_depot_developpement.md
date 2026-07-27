# Phase 2 - Préparation Du Dépôt De Développement

## 1. Objectif

La phase 2 prépare un environnement propre, reproductible et versionné pour les développements Oculox.

Le but n'est pas encore de modifier Logstash ou de créer un cluster. Le but est d'abord d'établir une méthode de travail qui permette de savoir :

- quels fichiers viennent de Malcolm ;
- quels fichiers ont été ajoutés par l'équipe ;
- comment reproduire une configuration ;
- comment vérifier une modification ;
- comment revenir à la base d'origine.

## 2. Pourquoi Conserver Les Fichiers Malcolm D'origine ?

Les fichiers situés à la racine, notamment `docker-compose.yml`, `docker-compose-dev.yml`, `config/`, `logstash/` et `filebeat/`, représentent le produit de référence.

Les modifier directement dès le début créerait plusieurs difficultés :

- il deviendrait difficile de distinguer le code officiel du code local ;
- une mise à jour amont provoquerait davantage de conflits Git ;
- une erreur locale pourrait casser le fonctionnement de référence ;
- un autre développeur ne saurait pas rapidement ce qui a changé ;
- revenir à la configuration d'origine serait plus risqué.

Conserver l'origine ne signifie pas qu'elle est intouchable pour toujours. Cela signifie qu'une modification directe doit être exceptionnelle, justifiée, testée et documentée.

## 3. Principe Des Fichiers Dédiés

Un fichier dédié contient uniquement notre intention locale.

Pour Docker Compose :

```text
docker-compose.yml
        +
dev/compose/docker-compose.dev.yml
        |
        v
configuration finale fusionnée
```

Le fichier d'origine reste complet. La surcharge ne contient que les différences.

Exemple :

```yaml
services:
  logstash:
    environment:
      EXEMPLE_VARIABLE: "valeur"
```

Docker Compose recherche le service `logstash` dans la base puis ajoute ou remplace uniquement la propriété indiquée.

## 4. Pourquoi Ne Pas Utiliser Directement `docker-compose.override.yml` ?

Docker Compose charge automatiquement un fichier nommé `docker-compose.override.yml` dans certains usages.

Cette automatisation peut rendre le comportement moins visible : un développeur peut lancer `docker compose up` sans se rendre compte qu'une surcharge est appliquée.

Le fichier choisi est donc :

```text
dev/compose/docker-compose.dev.yml
```

Il doit être indiqué explicitement :

```bash
docker compose \
  --project-directory . \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  config
```

Cette méthode rend la configuration utilisée visible dans la commande.

## 5. Rôle De Chaque Répertoire

| Répertoire | Rôle | Exemple futur |
|---|---|---|
| `phase1/` | Compréhension de l'existant | étude Filebeat et Logstash |
| `compose/` | Surcharges d'orchestration | deuxième service Logstash |
| `config/` | Modèles de variables locales | adresses des nœuds Logstash |
| `scripts/` | Automatisation reproductible | démarrage et contrôle de santé |
| `tests/` | Validation fonctionnelle | test de répartition Filebeat |
| `monitoring/` | Mesure et observabilité | workers et backpressure Logstash |
| `docs/` | Décisions et procédures | choix d'architecture résiliente |

## 6. Reproductibilité

Un environnement est reproductible lorsqu'un autre développeur peut obtenir le même comportement à partir :

- du dépôt Git ;
- des modèles de configuration ;
- d'une procédure documentée ;
- des mêmes versions d'images ;
- de commandes de validation connues.

Les secrets et données volumineuses ne sont pas placés dans Git. Leur mode de création ou de fourniture doit cependant être documenté.

## 7. Versionnement Git

Git doit enregistrer les choix techniques, pas l'état temporaire d'une machine.

À versionner :

```text
configuration déclarative
scripts
tests
documentation
requêtes de monitoring
```

À ne pas versionner :

```text
secrets
clés privées
fichiers .env réels
PCAP
logs
résultats volumineux
index OpenSearch
```

Le fichier `dev/.gitignore` applique cette séparation aux nouveaux dossiers.

## 8. Validation Initiale

La surcharge initiale contient :

```yaml
services: {}
```

Elle est syntaxiquement valide mais ne change aucun service. Cela permet de tester la méthode de fusion avant d'introduire un changement réel.

La validation s'effectue avec :

```bash
./dev/scripts/validate-compose.sh
```

Résultat attendu :

```text
Configuration Docker Compose valide.
```

Cette commande ne démarre aucun conteneur. Elle vérifie uniquement que Docker Compose peut construire une configuration finale cohérente.

## 9. Méthode À Suivre Pour Chaque Changement

Chaque évolution devra suivre cet ordre :

1. décrire le besoin ;
2. identifier le comportement d'origine ;
3. écrire la différence dans `dev/` ;
4. valider la syntaxe ;
5. examiner la configuration fusionnée ;
6. démarrer uniquement les services concernés ;
7. exécuter les tests ;
8. examiner les métriques ;
9. documenter le résultat ;
10. créer un commit Git ciblé.

## 10. Résultat De La Phase

La structure de développement est créée sans déplacement ni modification des fichiers Malcolm d'origine.

Le dépôt possède maintenant :

- une zone dédiée aux surcharges Compose ;
- une convention pour les variables locales ;
- un emplacement pour les scripts et tests ;
- une séparation entre définitions de monitoring et données générées ;
- un script de validation initial ;
- des règles empêchant le versionnement des secrets et artefacts volumineux.

Cette base permettra d'ajouter progressivement une architecture à plusieurs Logstash sans mélanger le développement avec le produit de référence.


# Tests De Développement

Ce répertoire contiendra les contrôles associés aux changements locaux.

Les tests seront organisés en trois niveaux :

1. validation statique de la syntaxe Compose et des configurations ;
2. contrôle de santé des services après démarrage ;
3. tests fonctionnels du chemin Filebeat vers Logstash puis OpenSearch.

Les résultats volumineux seront placés dans `tests/results/`, qui n'est pas versionné.

Chaque test devra préciser :

- son objectif ;
- ses prérequis ;
- la commande exécutée ;
- le résultat attendu ;
- les critères de réussite et d'échec.

## Générateur D'Événements Déterministes

`generate-phase6-events.py` produit des événements Zeek synthétiques dotés
d'un marqueur unique. Il est également réutilisé en phase 7 afin de comparer un
nombre connu d'événements émis avec le comptage exact retrouvé dans OpenSearch.
La réutilisation du même générateur évite de dupliquer du code de test.

## Résilience - Phase 9

```bash
./dev/tests/run-phase9-resilience.sh phase9_$(date -u +%Y%m%d_%H%M%S)
```

La campagne arrête et redémarre volontairement les composants ciblés, mais ne
supprime aucun volume. Elle valide la distribution, le basculement, la reprise
des queues, le registre Filebeat et la conservation des données.

## Comparaison Locale - Phase 10

```bash
./dev/tests/run-phase10-benchmark.sh phase10_$(date -u +%Y%m%d_%H%M%S)
```

Le script compare localement un et deux Logstash avec 50 000 événements
identiques. Il
redémarre chaque mode depuis un état Compose propre, vérifie le nombre exact de
documents et conserve les métriques dans `tests/results/phase10/`.

Ce test vérifie le fonctionnement et donne une tendance comparative sur la
machine de développement. Il ne définit pas la capacité de production, qui
sera mesurée sur un serveur cible représentatif.

Les générateurs utilisent un fichier Zeek stable avec l'option `--append`.
Des noms de fichiers uniques créeraient des champs dynamiques dans Malcolm et
fausseraient le benchmark en provoquant une explosion du mapping OpenSearch.

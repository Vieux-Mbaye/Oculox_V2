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


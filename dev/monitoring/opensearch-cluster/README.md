# Supervision du cluster OpenSearch

Ce repertoire recevra les definitions versionnees de supervision du cluster :

```text
metriques et requetes
seuils d'alerte
specifications de tableaux de bord
healthchecks du cluster et du proxy
```

Les controles devront distinguer la sante du cluster, la sante de chaque noeud
et la disponibilite de l'endpoint client. Ils couvriront notamment le cluster
manager, les shards non affectes, la heap, le GC, les watermarks disque, les
rejets, les pending tasks et les snapshots.

Les donnees collectees et exports runtime resteront dans les repertoires deja
ignores `dev/monitoring/data/` et `dev/monitoring/exports/`.

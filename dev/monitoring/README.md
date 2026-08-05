# Monitoring De Développement

Ce répertoire contiendra les éléments de supervision nécessaires pour évaluer les changements :

- requêtes Prometheus ;
- tableaux de bord dédiés ;
- règles d'alerte ;
- scripts de collecte de métriques ;
- définition des indicateurs de capacité.

Les données brutes et exports générés sont placés dans `monitoring/data/` ou `monitoring/exports/`. Ces répertoires ne sont pas versionnés.

Les définitions et requêtes restent versionnées afin que deux développeurs puissent observer la plateforme de la même manière.

## Utilisation

```bash
# Un instantané complet
python3 dev/scripts/collect-platform-metrics.py \
  --label manuel --output /tmp/oculox.json

# Une série de 60 secondes, intervalle de 5 secondes
./dev/scripts/monitor-platform.sh controle 60 5

# Variante légère destinée aux benchmarks
./dev/scripts/monitor-platform.sh charge 60 5 lightweight
```

`thresholds.yml` contient les seuils appliqués. `prometheus-queries.md`
prépare une future exposition Prometheus sans prétendre qu'un serveur
Prometheus est déjà fourni par cet environnement réduit.
`dashboard-specification.md` définit les panneaux à créer une fois les
datasources réellement disponibles.

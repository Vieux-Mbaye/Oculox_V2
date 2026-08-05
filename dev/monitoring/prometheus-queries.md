# Référentiel Prometheus Pour Oculox

## Portée

La supervision locale actuelle repose sur les API Docker, Filebeat, Logstash
et OpenSearch. Les requêtes ci-dessous préparent une intégration ultérieure à
Prometheus. Elles supposent que cAdvisor, Node Exporter et un export des
métriques applicatives sont effectivement déployés ; elles ne constituent pas
une preuve qu'un serveur Prometheus est déjà actif dans ce dépôt.

## CPU Des Conteneurs

```promql
sum by (name) (
  rate(container_cpu_usage_seconds_total{name=~"oculox-(logstash|logstash-2|filebeat|opensearch)-1"}[5m])
) * 100
```

## Mémoire Des Conteneurs

```promql
container_memory_working_set_bytes{name=~"oculox-(logstash|logstash-2|filebeat|opensearch)-1"}
```

## RAM Disponible Sur L'Hôte

```promql
100 * node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes
```

## Disque Utilisé

```promql
100 * (
  1 - node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}
      / node_filesystem_size_bytes{fstype!~"tmpfs|overlay"}
)
```

## Alertes Recommandées

- RAM utilisée supérieure à 85 % pendant 5 minutes ;
- disque utilisé supérieur à 80 % ;
- conteneur absent ou unhealthy ;
- OpenSearch différent de `green` ;
- heap JVM supérieure à 85 % ;
- file persistante supérieure à 60 % ;
- `worker_utilization` supérieure à 85 % avec croissance continue de la file ;
- augmentation des échecs ou retries Filebeat.

Les noms exacts des métriques Filebeat, Logstash et OpenSearch dépendront de
l'exporteur retenu. Ils devront être vérifiés dans `/metrics` avant de créer
des règles définitives.

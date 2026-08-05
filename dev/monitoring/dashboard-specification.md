# Spécification Du Tableau De Bord Oculox

## Objectif

Ce document définit le tableau de bord à construire lorsque Prometheus et les
exporteurs seront intégrés. Il évite de créer aujourd'hui un JSON Grafana lié
à des noms de datasource qui n'existent pas encore.

## Bandeau De Santé

| Panneau | Valeur | Seuil |
|---|---|---|
| État OpenSearch | green/yellow/red | alerte si différent de green |
| Logstash disponibles | 0, 1 ou 2 | critique si 0, dégradé si 1 |
| Filebeat | healthy/unhealthy | critique si unhealthy |
| RAM hôte | pourcentage | avertissement 85 %, critique 95 % |
| Disque hôte | pourcentage | avertissement 80 %, critique 90 % |

## Ingestion

- événements Filebeat publiés, acquittés, échoués et réessayés ;
- `events.in` et `events.out` de chaque Logstash ;
- distribution en pourcentage entre les deux instances ;
- débit de documents indexés dans OpenSearch.

## Pipelines Logstash

Une ligne par pipeline et par instance :

- utilisation des workers ;
- backpressure ;
- événements dans la file persistante ;
- octets occupés dans la file ;
- latence de traitement.

## Ressources

- CPU et mémoire des quatre conteneurs réduits ;
- heap JVM des deux Logstash et d'OpenSearch ;
- entrées/sorties disque ;
- trafic réseau interconteneurs ;
- charge et mémoire disponible de l'hôte.

## Règle De Lecture

Un worker élevé n'est pas à lui seul une panne. L'alerte devient prioritaire
si l'utilisation élevée s'accompagne d'une croissance continue de la file,
de retries Filebeat ou d'une divergence durable entre événements reçus et
documents indexés.

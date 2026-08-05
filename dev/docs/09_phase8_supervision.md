# Phase 8 - Supervision De La Chaîne D'Ingestion

## 1. Objet

Cette phase met en place une supervision reproductible de la chaîne réduite :

```text
Fichiers Zeek
→ Filebeat
→ logstash / logstash-2
→ OpenSearch
```

L'objectif n'est pas seulement de savoir si un conteneur est démarré. Il faut
également voir si les événements progressent, si une file se remplit, si les
workers saturent et si l'hôte dispose encore de suffisamment de RAM et de
disque.

## 2. Éléments Livrés

| Fichier | Fonction |
|---|---|
| `dev/monitoring/thresholds.yml` | Seuils d'avertissement et seuils critiques |
| `dev/scripts/collect-platform-metrics.py` | Produit un instantané JSON de la plateforme |
| `dev/scripts/monitor-platform.sh` | Répète la collecte pendant une durée définie |
| `dev/scripts/summarize-monitoring.py` | Consolide les instantanés dans un résumé |
| `dev/monitoring/prometheus-queries.md` | Référentiel de requêtes pour une future intégration Prometheus |
| `dev/monitoring/dashboard-specification.md` | Panneaux, indicateurs et règles de lecture du futur tableau de bord |

Les données générées sont écrites dans `dev/monitoring/data/`. Elles ne sont
pas versionnées afin de ne pas alourdir le dépôt.

## 3. Métriques Et Signification

### 3.1 Filebeat

Les compteurs `published`, `acked`, `failed`, `dropped` et `retry` permettent
de distinguer ce qui a été lu de ce qui a réellement été confirmé par
Logstash. Un événement acquitté a été accepté par la destination. Cela ne
prouve pas encore son indexation finale ; le comptage OpenSearch complète la
preuve.

### 3.2 Logstash

La collecte interroge l'API locale `:9600` de chaque instance.

| Indicateur | Lecture |
|---|---|
| `events.in` / `events.out` | Nombre d'événements entrés et sortis du pipeline |
| `worker_utilization` | Pourcentage du temps pendant lequel les workers travaillent |
| `queue_backpressure` | Temps de pression subi à l'entrée du pipeline |
| `queue.events_count` | Événements actuellement conservés dans la file persistante |
| heap JVM | Mémoire Java réellement utilisée par Logstash |

Une valeur CPU Docker supérieure à `100 %` est normale sur une machine
multicœur. Par exemple, `333 %` correspond approximativement à 3,33 cœurs
pleinement occupés.

### 3.3 OpenSearch

Le contrôle vérifie l'état du cluster, les shards non assignés et, en mode
complet, les statistiques JVM, disque, index et thread pools. Le mode
`lightweight` conserve le contrôle de santé mais évite la requête détaillée
`_nodes/stats`. Ce mode est utilisé pendant les benchmarks afin que la mesure
ne perturbe pas la charge observée.

### 3.4 Hôte Et Conteneurs

La RAM, le disque, la charge système, le CPU et la mémoire de chaque conteneur
sont collectés. Les seuils retenus sont :

| Ressource | Avertissement | Critique |
|---|---:|---:|
| RAM hôte | 85 % | 95 % |
| Disque hôte | 80 % | 90 % |
| File Logstash | 60 % | 85 % |
| Workers Logstash | 85 % | à diagnostiquer selon la durée |

## 4. Utilisation

Instantané détaillé :

```bash
python3 dev/scripts/collect-platform-metrics.py \
  --label controle_manuel \
  --output /tmp/oculox-controle.json
```

Surveillance de 5 minutes toutes les 10 secondes :

```bash
./dev/scripts/monitor-platform.sh controle_5min 300 10
```

Surveillance légère pendant un benchmark :

```bash
./dev/scripts/monitor-platform.sh benchmark 300 5 lightweight
```

Le résumé se trouve dans :

```text
dev/monitoring/data/<RUN_ID>/summary.json
```

## 5. Validation Sous Charge

Une injection contrôlée de `10 000` événements a été exécutée le 28 juillet
2026. Les `10 000` documents ont été retrouvés dans OpenSearch et son état est
resté `green`.

| Indicateur | Résultat |
|---|---:|
| Durée observée | 36,331 s |
| Instantanés exploitables | 4 |
| CPU maximal `logstash` | 333,22 % |
| CPU maximal `logstash-2` | 374,18 % |
| CPU maximal OpenSearch | 88,80 % |
| Heap maximale `logstash` | 78 % |
| Heap maximale `logstash-2` | 56 % |
| RAM hôte au début | 89,671 % |
| RAM hôte à la fin | 91,652 % |
| Disque hôte à la fin | 60,305 % |

La supervision a donc correctement observé la montée en charge et généré les
avertissements RAM attendus. Aucun conteneur n'est devenu unhealthy et aucune
file persistante n'a atteint un seuil critique.

## 6. Diagnostic Recommandé

1. vérifier d'abord la santé des conteneurs et d'OpenSearch ;
2. comparer `events.in` et `events.out` sur les deux Logstash ;
3. contrôler les files persistantes et la backpressure ;
4. contrôler les erreurs et retries Filebeat ;
5. vérifier la heap Java et la RAM de l'hôte ;
6. comparer le marqueur injecté avec le nombre exact de documents indexés.

Une forte utilisation des workers sans croissance durable des files peut être
une charge normale. Une file qui augmente continuellement, des événements non
acquittés ou un cluster non `green` caractérisent en revanche un incident.

## 7. Conclusion

La phase 8 est validée. La supervision fournit des preuves horodatées,
exploitables par machine, conteneur et pipeline. La limite actuelle est la RAM
de l'hôte : deux JVM Logstash et OpenSearch placent régulièrement la machine
au-dessus de 90 % de mémoire utilisée.

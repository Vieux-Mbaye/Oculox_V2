# Résultats de validation des clients, de l'ingestion et de la résilience

## Périmètre validé

Validation exécutée le 13 août 2026 avec :

- Oculox Core sur la machine locale `192.168.1.174` ;
- le cluster OpenSearch dédié sur `192.168.1.241` ;
- trois nœuds OpenSearch conteneurisés sur la VM dédiée ;
- aucun accès aux serveurs `10.5.6.3` et `10.5.6.4`.

Ce banc valide Core et le cluster distant. La validation d'un Hedgehog installé
sur une troisième VM reste nécessaire avant la mise en production finale.

## Configuration distante du Core

Un bundle Core neuf a été généré sur la VM cluster, contrôlé avec son fichier
`SHA256SUMS`, transféré sur Core, puis importé avec :

```bash
./oculox configure-opensearch-remote --bundle /tmp/oculox-core-opensearch
```

État obtenu :

```text
OPENSEARCH_PRIMARY=opensearch-remote
OPENSEARCH_URL=https://192.168.1.241:9200
OPENSEARCH_SSL_CERTIFICATE_VERIFICATION=true
```

La CA OpenSearch est installée dans
`nginx/ca-trust/oculox-opensearch-ca.crt`. Les identités limitées sont sous
`dev/generated/opensearch-clients/`, avec des permissions `600`. Le Compose
d'exécution exclut le service OpenSearch local.

## Validation de tous les clients

La commande suivante a terminé avec `CLIENT_CONNECTIVITY_RESULT=PASS` :

```bash
./oculox verify clients --output dev/generated/validation/client-connectivity/current/report.json
```

Les contrôles ont validé :

- Logstash 1 et Logstash 2, sept pipelines chacun, compte `oculox_logstash` ;
- Arkime et Arkime Live, compte `oculox_arkime` ;
- Dashboards, compte `oculox_dashboards` ;
- dashboards-helper, compte `oculox_dashboards_helper` ;
- API et pcap-monitor, compte `oculox_api` ;
- la CA distante dans les magasins de confiance des conteneurs ;
- la route Nginx, avec accès anonyme refusé en HTTP `401` ;
- une création, écriture, lecture et suppression directe par Arkime ;
- cinq configurations Filebeat utilisant `logstash:5044` et
  `logstash-2:5044`, `loadbalance: true`, mTLS et aucune sortie OpenSearch
  directe.

## Ingestion de bout en bout

Le PCAP de référence contient `48 087` paquets et possède le SHA-256 suivant :

```text
9aebc7fbf298bc75d13e7a94fceb80622cad16c061e19b0c2467006d06ca21e9
```

Le rapport `dev/generated/validation/ingestion/current/final.json` a retourné
`INGESTION_RESULT=PASS` :

| Mesure | Delta observé |
|---|---:|
| Événements reçus par Logstash 1 | +352 |
| Événements reçus par Logstash 2 | +440 |
| Documents OpenSearch | +867 |
| Documents `malcolm_beats_*` | +4 |
| Sessions `arkime_sessions3-*` | +955 |
| Nouveaux rejets d'indexation | 0 |
| Nouveaux échecs d'indexation | 0 |

Les paquets, événements, documents de pipelines et sessions Arkime ne sont pas
les mêmes objets. Leurs nombres ne doivent donc pas être comparés comme s'ils
devaient être identiques.

## Pannes pendant l'ingestion

Chaque nœud a été arrêté séparément pendant l'injection du même PCAP. Le Core,
Filebeat, les deux Logstash et le proxy sont restés actifs. Après chaque test,
le nœud a été réintégré et le retour à `green` a été attendu.

| Nœud arrêté | Filebeat publié/acquitté | Logstash 1 `in` | Logstash 2 `in` | Documents | Sessions Arkime | Rejets nouveaux | Résultat |
|---|---:|---:|---:|---:|---:|---:|---|
| `opensearch-1` | 12/12 | +6 900 | +1 620 | +1 290 | +1 283 | 0 | PASS |
| `opensearch-2` | 27/27 | +156 | +202 | +827 | +855 | 0 | PASS |
| `opensearch-3` | 76/76 | +6 678 | +1 290 | +857 | +936 | 0 | PASS |

Le rapport consolidé se trouve dans :

```text
dev/generated/validation/opensearch-failover/summary.json
```

Il retourne `INGESTION_FAILOVER_RESULT=PASS`. L'état final contrôlé est :

```text
status=green
number_of_nodes=3
number_of_data_nodes=3
unassigned_shards=0
```

Lorsque le nœud qui portait le rôle de cluster manager a été arrêté, certaines
requêtes de mesure ont expiré pendant la réélection. Après stabilisation du
quorum, elles ont réussi. Filebeat a conservé puis acquitté les événements et
les rapports ne montrent aucun nouveau rejet d'indexation.

## Files persistantes Logstash

Les sept pipelines de chaque Logstash déclarent une file `persisted`. Pendant
la perte d'un seul nœud OpenSearch, `events_count` est resté à zéro : le cluster
à deux nœuds continuait d'accepter les écritures, donc aucun backlog n'était
nécessaire. La persistance est configurée et disponible pour une indisponibilité
plus longue du stockage.

## Limites de la preuve

Le test prouve l'acquittement de tous les événements publiés par Filebeat,
l'activité des deux Logstash, la croissance des index et l'absence de nouveaux
rejets. Il ne prétend pas établir une égalité entre paquets et documents ni une
absence mathématique de doublons applicatifs, car Zeek, Suricata et Arkime
produisent des objets différents à partir du même trafic.

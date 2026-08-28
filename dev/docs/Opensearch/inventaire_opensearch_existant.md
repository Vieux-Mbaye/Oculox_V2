# Étape d'inventaire - Baseline OpenSearch mono-noeud Oculox

## 1. Objet du rapport

Ce document établit la référence technique de l'OpenSearch mono-noeud utilisé
par Oculox avant la construction du cluster à trois noeuds.

La collecte a été réalisée le 10 août 2026 sur la machine locale de
développement, à partir du dépôt :

```text
/home/kakashi_/ICSHUB/Oculox
```

Référence Git observée :

```text
branche       : main
commit        : f219cab965eeea32cc12475c9184d485d05bd7cb
date commit   : 2026-08-10T10:42:31Z
sujet         : Fix exposed ports with dual Logstash
```

La baseline couvre :

- les consommateurs d'OpenSearch ;
- la configuration produite par l'installateur interactif ;
- l'état du cluster et des noeuds ;
- les index, aliases, templates, shards et replicas ;
- les politiques ISM ;
- les comptes, rôles et associations de rôles ;
- les certificats et autorités de certification ;
- la heap, la RAM, le CPU et le disque ;
- les volumes documentaires ;
- les repositories et snapshots ;
- un test réel de création et de restauration d'un snapshot.

## 2. Méthode et périmètre

La configuration déclarative a d'abord été analysée sans démarrer Oculox.
Comme aucun conteneur Oculox n'était actif, seul le service `opensearch` a été
démarré pour collecter les preuves runtime :

```bash
docker compose --profile malcolm up -d opensearch
```

Les autres services Oculox n'ont pas été démarrés. Cette méthode évite de
charger inutilement la machine tout en permettant d'interroger le stockage
persistant existant.

Après la collecte et le test de restauration, le conteneur OpenSearch a été
arrêté. La machine locale a ainsi retrouvé son état initial, sans plateforme
Oculox active.

Les appels OpenSearch utilisent le fichier de connexion déjà généré :

```text
.opensearch.primary.curlrc
```

Son contenu, le mot de passe, les hashes et les clés privées ne sont pas
reproduits dans ce rapport.

## 3. Résumé exécutif

| Contrôle | Résultat |
|---|---|
| Version OpenSearch | `3.7.0` |
| Image Oculox/Malcolm | `ghcr.io/idaholab/malcolm/opensearch:26.07.1` |
| Nom du cluster | `docker-cluster` |
| UUID du cluster | `j4AI38i9S32ETumgLGdV6g` |
| Mode | `discovery.type=single-node` |
| Santé | `green` |
| Noeuds | `1` |
| Noeuds data | `1` |
| Cluster manager | `opensearch` |
| Shards actifs annoncés par la santé | `51` |
| Shards non affectés | `0` |
| Index visibles par `_cat/indices` | `41` |
| Shards primaires des index visibles | `43` |
| Replicas des index visibles | `0` |
| Documents applicatifs retournés par `_count` | `668 179` |
| Sessions Arkime | `657 306` |
| Heap configurée | `4 Gio` |
| Heap observée | environ `1,47 Gio / 4 Gio`, soit `34 %` |
| Stockage Lucene visible | `202 102 920` octets |
| Repository de snapshots | `logs`, type `fs` |
| Snapshot antérieur à la étape | aucun |
| Snapshot de preuve | `baseline-opensearch-20260810`, `SUCCESS` |
| Test de restauration | `33 679 / 33 679`, conforme |

Conclusion : le mono-noeud est fonctionnel et sain, mais il n'offre aucune
redondance. Les templates et les index ont tous `number_of_replicas=0`. La
validation TLS complète vers l'API est désactivée et les certificats OpenSearch
internes actuels ne sont pas adaptés au futur cluster.

## 4. Configuration mono-noeud actuelle

### 4.1 Stockage primaire

Le fichier `config/opensearch.env` contient :

```text
OPENSEARCH_PRIMARY=opensearch-local
OPENSEARCH_URL=https://opensearch:9200
OPENSEARCH_SSL_CERTIFICATE_VERIFICATION=false
```

Le Principal utilise donc son conteneur OpenSearch local. L'adresse
`opensearch` est un nom de service Docker, pas un endpoint réseau stable
accessible depuis une autre VM.

### 4.2 Mémoire Java

```text
OPENSEARCH_JAVA_OPTS=-server -Xmx4g -Xms4g ...
```

La heap minimale et maximale sont fixées à `4 Gio`.

### 4.3 Mode de découverte

```text
discovery.type=single-node
```

Ce paramètre désactive la formation d'un cluster multinoeud. Il devra être
retiré dans la future configuration.

### 4.4 Paramètres de shards et de disque

```text
cluster.default_number_of_replicas=0
cluster.max_shards_per_node=2500
cluster.routing.allocation.disk.threshold_enabled=false
cluster.routing.allocation.node_initial_primaries_recoveries=8
```

Conséquences :

- aucun replica n'est créé par défaut ;
- les protections par seuils disque sont désactivées ;
- la limite est de `2500` shards par noeud ;
- cette configuration est orientée mono-noeud et doit être revue pour le
  cluster.

### 4.5 Stockage persistant

| Hôte | Conteneur | Usage |
|---|---|---|
| `./opensearch` | `/usr/share/opensearch/data` | données et keystore |
| `./opensearch-backup` | `/opt/opensearch/backup` | repository de snapshots |
| `./.opensearch.primary.curlrc` | `/var/local/curlrc/.opensearch.primary.curlrc` | compte de service |
| `./nginx/ca-trust` | `/var/local/ca-trust` | autorités supplémentaires |

Les données et snapshots résident actuellement sur le même système de fichiers
physique. Le snapshot protège une suppression logique, mais pas la perte du
disque ou de la VM.

## 5. Inventaire des consommateurs de `OPENSEARCH_URL`

### 5.1 Profil Principal `malcolm`

L'analyse du Compose effectif identifie les services suivants :

| Service | Type de consommation | Contrat à préserver |
|---|---|---|
| `logstash` | écriture directe | indexation des événements enrichis, authentification et TLS |
| `arkime` | lecture et écriture directes | métadonnées de sessions Arkime |
| `arkime-live` | écriture directe | métadonnées de capture live |
| `dashboards` | lecture et écriture directes | index Dashboards, recherches et visualisations |
| `dashboards-helper` | administration | templates, objets, détecteurs, alertes et repository |
| `api` | lecture directe | API Oculox et informations de santé |
| `pcap-monitor` | lecture directe | suivi des PCAP et de l'état des sessions |
| `nginx-proxy` | proxy HTTP | publication contrôlée de certaines API OpenSearch |
| `filebeat` | environnement transmis | la sortie événementielle normale reste Logstash |
| `opensearch` | auto-référence | initialisation et scripts post-démarrage |

Le second Logstash Oculox, ajouté par la couche de résilience, applique le même
contrat de sortie que le premier :

```text
hosts => OPENSEARCH_URL
user/password => compte de service OpenSearch
index => métadonnée calculée par le pipeline
document_id => date + event.hash
```

Le `document_id` déterministe contribue à limiter les doublons lors des
réémissions.

### 5.2 Profil collecteur `hedgehog`

Le Compose effectif transmet `OPENSEARCH_URL` à :

| Service | Rôle |
|---|---|
| `arkime` | métadonnées d'analyse hors ligne |
| `arkime-live` | métadonnées de capture live |
| `pcap-monitor` | suivi de traitement |
| `filebeat` | environnement disponible, tandis que les journaux sont envoyés aux deux Logstash du Principal |

Le futur endpoint du cluster doit donc être joignable au minimum par Oculox
Core. Si Arkime reste exécuté sur le collecteur Hedgehog avec écriture directe,
il doit également pouvoir joindre l'endpoint OpenSearch distant.

### 5.3 Consommateurs hors Compose

Les principaux fichiers concernés sont :

```text
logstash/pipelines/output/99_opensearch_output.conf
arkime/etc/config.ini
arkime/etc/wise.ini.example
arkime/scripts/initarkime.sh
arkime/scripts/live_capture.sh
dashboards/opensearch_dashboards.yml
dashboards/scripts/index-init.sh
dashboards/scripts/index-refresh.py
dashboards/scripts/shared-object-creation.sh
dashboards/scripts/opensearch_index_size_prune.py
dashboards/scripts/opensearch_read_only.py
api/project/config.py
shared/bin/opensearch_status.sh
shared/bin/pcap_watcher.py
container-health-scripts/opensearch.sh
container-health-scripts/dashboards.sh
nginx/nginx_opensearch_upstream.conf
scripts/control.py
```

Ces fichiers devront être couverts par les tests de raccordement au cluster
distant.

## 6. Santé et identité du cluster

Commande :

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_cluster/health?pretty'
```

Résultat synthétique :

```text
cluster_name                         docker-cluster
status                               green
number_of_nodes                      1
number_of_data_nodes                 1
discovered_cluster_manager           true
active_primary_shards                51
active_shards                        51
relocating_shards                    0
initializing_shards                  0
unassigned_shards                    0
number_of_pending_tasks              0
active_shards_percent_as_number      100.0
```

Identité de l'instance :

```text
node name       : opensearch
cluster UUID    : j4AI38i9S32ETumgLGdV6g
OpenSearch      : 3.7.0
Lucene          : 10.4.0
node roles      : dimr
cluster manager : oui
```

Les rôles abrégés `dimr` indiquent notamment data, ingest, cluster manager et
remote-cluster-client.

## 7. Index, shards, replicas et documents

### 7.1 Résumé

```text
index visibles       : 41
shards primaires     : 43
replicas             : 0
documents Lucene     : 672 785
stockage Lucene      : 202 102 920 octets
documents applicatifs: 668 179
```

Le nombre de documents Lucene peut être supérieur à `_count`, car certains
documents imbriqués sont comptabilisés par Lucene mais pas comme événements
applicatifs indépendants.

### 7.2 Index de trafic et autres journaux

| Index | Primaires | Replicas | Documents Lucene | Taille octets |
|---|---:|---:|---:|---:|
| `arkime_sessions3-260414` | 1 | 0 | 57 616 | 19 286 718 |
| `arkime_sessions3-260727` | 1 | 0 | 13 000 | 3 074 522 |
| `arkime_sessions3-260728` | 1 | 0 | 240 002 | 64 720 298 |
| `arkime_sessions3-260729` | 1 | 0 | 313 000 | 75 276 696 |
| `arkime_sessions3-260807` | 1 | 0 | 33 679 | 28 858 044 |
| `arkime_sessions3-700101` | 1 | 0 | 9 | 15 623 |
| `arkime_sessions3-initial` | 1 | 0 | 0 | 208 |
| `malcolm_beats_suricata_260807` | 1 | 0 | 978 | 1 383 651 |
| `malcolm_beats_zeek_260807` | 1 | 0 | 285 | 257 047 |
| `malcolm_beats_initial` | 1 | 0 | 0 | 208 |

Comptages applicatifs vérifiés :

```text
arkime_sessions3-*                 657 306
malcolm_beats_suricata_260807          489
malcolm_beats_zeek_260807               285
malcolm_beats_* total                    774
```

### 7.3 Index Arkime de référence

| Index | Primaires | Replicas | Documents Lucene |
|---|---:|---:|---:|
| `arkime_configs_v50` | 1 | 0 | 0 |
| `arkime_dstats_v30` | 2 | 0 | 87 |
| `arkime_fields_v30` | 1 | 0 | 4 062 |
| `arkime_files_v30` | 2 | 0 | 27 |
| `arkime_history_v1-26w31` | 1 | 0 | 103 |
| `arkime_hunts_v30` | 1 | 0 | 0 |
| `arkime_lookups_v30` | 1 | 0 | 0 |
| `arkime_notifiers_v40` | 1 | 0 | 0 |
| `arkime_parliament_v50` | 1 | 0 | 0 |
| `arkime_queries_v30` | 1 | 0 | 1 |
| `arkime_sequence_v30` | 1 | 0 | 3 |
| `arkime_shareables_v60` | 1 | 0 | 0 |
| `arkime_stats_v30` | 1 | 0 | 3 |
| `arkime_users_v30` | 1 | 0 | 1 |
| `arkime_views_v40` | 1 | 0 | 9 |

### 7.4 Index système principaux

| Index | Primaires | Replicas | Documents Lucene |
|---|---:|---:|---:|
| `.kibana_1` | 1 | 0 | 3 046 |
| `.kibana_2` | 1 | 0 | 3 093 |
| `.opendistro_security` | 1 | 0 | 9 |
| `.plugins-ml-config` | 1 | 0 | 1 |
| `.ql-datasources` | 1 | 0 | 0 |

Des index `top_queries-*` et un index d'historique du plugin Anomaly Detection
sont également présents. Ils devront être inclus dans la stratégie de migration
ou explicitement régénérés.

### 7.5 Index auxiliaires et plugins

| Index | Primaires | Replicas | Documents Lucene |
|---|---:|---:|---:|
| `opensearch-ad-plugin-result-dummy-history-2026.07.27-1` | 1 | 0 | 123 |
| `top_queries-2026.07.27-44544` | 1 | 0 | 633 |
| `top_queries-2026.07.28-44545` | 1 | 0 | 635 |
| `top_queries-2026.07.29-44546` | 1 | 0 | 180 |
| `top_queries-2026.07.30-44568` | 1 | 0 | 298 |
| `top_queries-2026.08.01-74267` | 1 | 0 | 63 |
| `top_queries-2026.08.02-74268` | 1 | 0 | 31 |
| `top_queries-2026.08.05-74271` | 1 | 0 | 479 |
| `top_queries-2026.08.06-74272` | 1 | 0 | 387 |
| `top_queries-2026.08.07-74273` | 1 | 0 | 916 |
| `top_queries-2026.08.10-74297` | 1 | 0 | 14 |

Les sections 7.2 à 7.5 couvrent les 41 index visibles retournés par
`_cat/indices` au moment de la collecte.

## 8. Aliases

Les aliases fonctionnels observés sont :

| Alias | Cible ou motif de cibles |
|---|---|
| `.kibana` | `.kibana_2` |
| `malcolm_network` | tous les `arkime_sessions3-*` existants |
| `malcolm_other` | tous les `malcolm_beats_*` existants |
| `arkime_configs` | `arkime_configs_v50` |
| `arkime_dstats` | `arkime_dstats_v30` |
| `arkime_fields` | `arkime_fields_v30` |
| `arkime_files` | `arkime_files_v30` |
| `arkime_hunts` | `arkime_hunts_v30` |
| `arkime_lookups` | `arkime_lookups_v30` |
| `arkime_notifiers` | `arkime_notifiers_v40` |
| `arkime_parliament` | `arkime_parliament_v50` |
| `arkime_queries` | `arkime_queries_v30` |
| `arkime_sequence` | `arkime_sequence_v30` |
| `arkime_shareables` | `arkime_shareables_v60` |
| `arkime_stats` | `arkime_stats_v30` |
| `arkime_users` | `arkime_users_v30` |
| `arkime_views` | `arkime_views_v40` |
| `.opendistro-anomaly-results` | historique des résultats Anomaly Detection |
| `opensearch-ad-plugin-result-dummy` | index factice du plugin Anomaly Detection |

Les aliases `malcolm_network` et `malcolm_other` sont des contrats importants
pour les recherches et les tableaux de bord.

## 9. Templates

### 9.1 Templates composables

| Template | Pattern | Shards | Replicas |
|---|---|---:|---:|
| `malcolm_template` | `arkime_sessions3-*` | 1 | 0 |
| `malcolm_beats_template` | `malcolm_beats_*` | 1 | 0 |
| `arkime_stats_template` | `arkime_stats_*` | non forcé | non forcé |

### 9.2 Templates historiques

| Template | Ordre | Pattern | Shards | Replicas |
|---|---:|---|---:|---:|
| `arkime_sessions3_ecs_template` | 1 | `arkime_sessions3-*` | non forcé | non forcé |
| `arkime_sessions3_template` | 99 | `arkime_sessions3-*` | 1 | 0 |
| `arkime_history_v1_template` | 0 | `arkime_history_v1-*` | 1 | 0 |

Les templates du futur cluster devront définir au moins un replica pour les
index devant survivre à la perte d'un noeud.

## 10. Politiques ISM

La configuration générée indique :

```text
INDEX_MANAGEMENT_ENABLED=true
INDEX_MANAGEMENT_OPTIMIZATION_PERIOD=30d
INDEX_MANAGEMENT_RETENTION_TIME=90d
INDEX_MANAGEMENT_OLDER_SESSION_REPLICAS=0
INDEX_MANAGEMENT_HISTORY_RETENTION_WEEKS=13
INDEX_MANAGEMENT_SEGMENTS=1
INDEX_MANAGEMENT_HOT_WARM_ENABLED=true
```

Cependant, l'API runtime retourne :

```text
total_policies=0
```

Il existe donc un écart entre l'intention configurée et l'état du cluster. La
étape de construction devra déterminer si `dashboards-helper` recrée les
politiques au démarrage complet, puis exporter et tester les politiques
effectivement obtenues.

## 11. Utilisateurs, rôles et autorisations

### 11.1 Compte interne

Un seul utilisateur interne est présent :

```text
malcolm_internal
backend role: admin
reserved: true
```

Le mot de passe est stocké dans `.opensearch.primary.curlrc`. Il n'est pas
présent dans ce rapport.

Le rôle backend `admin` donne actuellement accès à `all_access` et à
`security_rest_api_full_access`. Ce compte est donc beaucoup plus privilégié
qu'un simple compte d'indexation. Le futur cluster devra prévoir des comptes de
service à privilèges minimaux.

### 11.2 Rôles

Le plugin Security expose `56` rôles. Les rôles directement importants pour
Oculox sont notamment :

```text
all_access
capture_service_access
dashboards_read_access
dashboards_read_write_access
dashboards_all_apps_read_access
index_management_full_access
kibana_server
logstash
manage_snapshots
readall
readall_and_monitor
security_rest_api_full_access
snapshot_management_full_access
snapshot_management_read_access
```

Inventaire exhaustif :

```text
alerting_ack_alerts
alerting_full_access
alerting_read_access
all_access
anomaly_full_access
anomaly_read_access
asynchronous_search_full_access
asynchronous_search_read_access
capture_service_access
cross_cluster_replication_follower_full_access
cross_cluster_replication_leader_full_access
cross_cluster_search_remote_full_access
dashboards_all_apps_read_access
dashboards_read_access
dashboards_read_write_access
flow_framework_full_access
flow_framework_read_access
forecast_full_access
forecast_read_access
index_management_full_access
ip2geo_datasource_full_access
ip2geo_datasource_read_access
kibana_server
kibana_user
knn_full_access
knn_read_access
logstash
ltr_full_access
ltr_read_access
manage_snapshots
ml_full_access
ml_read_access
notebooks_full_access
notebooks_read_access
notifications_full_access
notifications_read_access
observability_full_access
observability_read_access
own_index
point_in_time_full_access
ppl_full_access
query_assistant_access
query_insights_full_access
readall
readall_and_monitor
reports_full_access
reports_instances_read_access
reports_read_access
search_relevance_full_access
search_relevance_read_access
security_analytics_ack_alerts
security_analytics_full_access
security_analytics_read_access
security_rest_api_full_access
snapshot_management_full_access
snapshot_management_read_access
```

### 11.3 Mappings importants

```text
backend role admin           -> all_access
backend role admin           -> security_rest_api_full_access
backend role admin           -> security_manager
backend role capture_service -> capture_service_access
backend role read_access     -> rôles de lecture Dashboards et plugins
backend role read_write_access -> rôles d'écriture Dashboards et plugins
```

### 11.4 Authentification applicative

```text
NGINX_AUTH_MODE=basic
ROLE_BASED_ACCESS=false
```

Keycloak est présent dans le Compose mais n'est pas l'autorité d'identité
active de cette baseline.

## 12. TLS, certificats et autorités

### 12.1 PKI OpenSearch actuelle

Le conteneur génère sa propre PKI OpenSearch interne lorsque
`OPENSEARCH_SKIP_SELF_SIGNED_KEY_GEN` n'est pas positionné à `true`.

Chaîne observée :

```text
CA:
  subject = CN=opensearch, OU=ca, O=Malcolm, ST=ID, C=US

Serveur/noeud:
  subject = CN=opensearch-node, OU=node, O=Malcolm, ST=ID, C=US
  EKU     = serverAuth, clientAuth

Administrateur:
  subject = CN=opensearch-admin, OU=admin, O=Malcolm, ST=ID, C=US
  EKU     = serverAuth, clientAuth
```

Validité observée :

```text
notBefore = 2026-08-10 14:48:00 UTC
notAfter  = 2036-08-07 14:48:00 UTC
```

Vérification de chaîne :

```text
server.crt: OK
admin.crt : OK
```

Le certificat serveur ne contient pas de SAN. Une vérification stricte avec le
nom `localhost` échoue, car le certificat porte uniquement
`CN=opensearch-node`. Cela explique la configuration actuelle :

```text
OPENSEARCH_SSL_CERTIFICATE_VERIFICATION=false
transport enforce_hostname_verification=false
transport resolve_hostname=false
```

Cette PKI est générée dans le conteneur et n'est pas montée comme ensemble de
certificats persistants distincts. Elle ne convient pas au cluster : chaque
noeud devra avoir une identité et une clé privée uniques, avec des SAN valides.

### 12.2 PKI Beats actuelle

La PKI d'ingestion Oculox est distincte :

```text
subject = O=Oculox, OU=Ingestion PKI, CN=Oculox Beats CA
issuer  = O=Oculox, OU=Ingestion PKI, CN=Oculox Beats CA
```

Elle protège Filebeat vers les deux Logstash. Elle ne signe pas les
certificats OpenSearch et doit rester indépendante pendant la construction du
cluster.

### 12.3 Conclusion PKI pour la étape suivante

Le cluster devra introduire une PKI OpenSearch dédiée comprenant :

```text
CA OpenSearch
certificat opensearch-1
certificat opensearch-2
certificat opensearch-3
certificat endpoint stable
certificat administrateur
```

Les certificats de noeuds doivent contenir `serverAuth` et `clientAuth`, leurs
noms DNS dans les SAN et des DN cohérents avec `plugins.security.nodes_dn`.

## 13. Ressources observées

### 13.1 Hôte de développement

```text
CPU logique     : 12
RAM totale      : environ 30 Gio
RAM disponible  : environ 18 Gio au début du test
swap            : 511 Mio, inutilisée
disque          : 477 Gio
disque utilisé  : 296 Gio, soit 63 %
disque libre    : environ 178 Gio
système fichiers: btrfs sur NVMe
```

### 13.2 Processus OpenSearch

Échantillon observé après démarrage :

```text
heap utilisée         : 1 473 263 528 octets
heap maximale         : 4 294 967 296 octets
heap utilisée         : 34 %
CPU processus API     : 16 % à l'instant de la mesure
CPU conteneur         : environ 25 % à l'instant de la mesure
RAM conteneur         : environ 5,04 Gio
descripteurs ouverts  : 1 234 / 65 535
espace disponible API : 190 539 395 072 octets
```

Le `ram.percent=98` remonté par OpenSearch représente la mémoire Linux utilisée,
y compris le cache de pages. Il ne signifie pas à lui seul que la machine est
en manque de mémoire ; la valeur `available` de l'hôte doit être observée en
parallèle.

## 14. Snapshots et restauration

### 14.1 État initial

Repository déclaré :

```json
{
  "logs": {
    "type": "fs",
    "settings": {
      "compress": "false",
      "location": "logs"
    }
  }
}
```

Avant le test, le repository ne contenait aucun snapshot.

### 14.2 Création du snapshot de preuve

Commande :

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  -X PUT -H 'Content-Type: application/json' \
  'https://localhost:9200/_snapshot/logs/baseline-opensearch-20260810?wait_for_completion=true' \
  -d '{
    "indices":"arkime_sessions3-260807",
    "ignore_unavailable":false,
    "include_global_state":false,
    "metadata":{"purpose":"Oculox OpenSearch cluster étape d'inventaire baseline"}
  }'
```

Résultat :

```text
snapshot   : baseline-opensearch-20260810
UUID       : PDc8Y5MuTJ6E_WdkxcR0pA
état       : SUCCESS
index      : arkime_sessions3-260807
shards     : 1 total, 1 réussi, 0 échec
durée      : 800 ms
```

### 14.3 Vérification du repository

Commande :

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  -X POST 'https://localhost:9200/_snapshot/logs/_verify?pretty'
```

Résultat : le noeud `opensearch` peut écrire et lire dans le repository.

### 14.4 Restauration réelle

Le snapshot a été restauré sous le nom temporaire :

```text
baseline_restore_arkime_sessions3_260807
```

Comparaison :

```text
index original : 33 679 documents
index restauré : 33 679 documents
écart          : 0
```

Après comparaison, seul l'index temporaire a été supprimé. Le snapshot de
preuve est conservé dans :

```text
opensearch-backup/logs/
```

Le cluster est revenu à `green`, sans index temporaire et sans shard non
affecté.

## 15. Valeurs produites ou pilotées par l'installateur interactif

| Choix interactif | Valeur runtime | Fichier ou effet |
|---|---|---|
| Profil | `malcolm` | `config/process.env` |
| Document store primaire | `opensearch-local` | `config/opensearch.env` |
| URL primaire | `https://opensearch:9200` | `config/opensearch.env` |
| Vérification SSL distante | `false` | `config/opensearch.env` |
| Mémoire OpenSearch | `4g` | `OPENSEARCH_JAVA_OPTS` |
| Stockage par défaut | utilisé | bind mounts `./opensearch` et `./opensearch-backup` |
| Gestion d'index Arkime | activée | `config/arkime.env` |
| Rétention Arkime | `90d` | `config/arkime.env` |
| Optimisation | `30d` | `config/arkime.env` |
| Replicas des anciens index | `0` | `config/arkime.env` |
| Repository de snapshots | `logs` | `config/dashboards-helper.env` |
| Identifiants internes | générés | `.opensearch.primary.curlrc` |

En mode `opensearch-local`, l'URL est calculée automatiquement par
l'installateur. En mode `opensearch-remote`, l'URL et la validation TLS
deviennent des champs visibles et obligatoires.

## 16. Alertes et écarts à traiter avant le cluster

### Critiques

1. Tous les index et templates utilisent zéro replica.
2. Le certificat serveur actuel ne possède pas de SAN.
3. La validation TLS des clients est désactivée.
4. Les certificats OpenSearch sont générés pour un seul noeud et ne sont pas
   adaptés à trois identités distinctes.
5. Le compte `malcolm_internal` possède le backend role `admin` et des droits
   trop larges pour un compte d'indexation.

### Importants

1. `cluster.routing.allocation.disk.threshold_enabled=false` désactive les
   protections de disque.
2. `INDEX_MANAGEMENT_ENABLED=true` mais aucune politique ISM n'est active.
3. Les snapshots résident sur le même disque que les données.
4. Le nom `https://opensearch:9200` n'est valable que dans le réseau Docker du
   Principal.
5. Le plugin signale des permissions trop permissives sur certains fichiers de
   configuration et certificats internes.
6. Le salt de conformité/field masking n'est pas explicitement fixé.
7. Certains plugins signalent des dépendances absentes ; leur impact doit être
   vérifié selon les fonctions réellement utilisées.

### À préserver pendant la migration

1. Les mappings et templates Malcolm/Arkime.
2. Les aliases `malcolm_network`, `malcolm_other` et les aliases Arkime.
3. Les index Dashboards et Arkime de référence.
4. Le comportement de `document_id` de Logstash.
5. Les rôles de lecture, écriture et capture.
6. Le repository et la procédure de restauration.
7. La compatibilité OpenSearch `3.7.0` avec l'image Oculox `26.07.1`.

## 17. Critères de preuve de la étape d'inventaire

| Preuve attendue | État | Preuve obtenue |
|---|---|---|
| Cluster mono-noeud sain | PASS | `green`, 1 noeud, 0 shard non affecté |
| Liste des index | PASS | 41 index visibles inventoriés |
| Liste des aliases | PASS | aliases Malcolm, Arkime et Dashboards relevés |
| Templates exportés | PASS | 3 composables et 3 historiques relevés |
| Politiques relevées | PASS avec écart | configuration activée, API runtime à 0 politique |
| Shards et replicas | PASS | 43 primaires visibles, 0 replica |
| Utilisateurs et rôles | PASS | 1 compte interne, 56 rôles, mappings relevés |
| Certificats et CA | PASS | chaînes, DN, dates et EKU contrôlés |
| Ressources | PASS | heap, CPU, RAM, disque et descripteurs relevés |
| Documents de référence | PASS | 668 179 documents applicatifs |
| Repository vérifié | PASS | repository `logs` vérifiable par le noeud |
| Snapshot testable | PASS | création `SUCCESS`, restauration 33 679/33 679 |
| Liste des composants clients | PASS | Principal, Hedgehog et scripts inventoriés |

## 18. Commandes de reproduction

### Santé

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_cluster/health?pretty'
```

### Noeuds

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_cat/nodes?v'
```

### Index

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_cat/indices?v&s=index'
```

### Aliases

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_cat/aliases?v&s=alias,index'
```

### Templates

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_index_template?pretty'

docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_template?pretty'
```

### Politiques ISM

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_plugins/_ism/policies?size=100&pretty'
```

### Comptage applicatif

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_all/_count?pretty'
```

### Repository et snapshots

```bash
docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_snapshot?pretty'

docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_snapshot/logs/_all?pretty'
```

### Ressources

```bash
docker stats --no-stream oculox-opensearch-1

docker exec oculox-opensearch-1 curl -sS \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  'https://localhost:9200/_nodes/stats/jvm,process,fs,os?pretty'
```

## 19. Décision de sortie de étape

La étape d'inventaire est validée.

La baseline est suffisamment complète pour engager la étape de préparation hôte de préparation
de la VM dédiée. Les paramètres mono-noeud ne doivent pas être copiés tels quels
dans le cluster. Les changements obligatoires sont :

```text
retirer discovery.type=single-node
créer trois identités de noeuds
activer les replicas
réactiver les seuils disque
activer la validation TLS stricte
utiliser un endpoint DNS stable
séparer les droits des comptes de service
placer les snapshots hors des volumes de données
```

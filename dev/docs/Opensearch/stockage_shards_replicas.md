# Étape stockage - Shards, replicas, ISM et disque

## 1. Resultat

La Étape stockage a ete appliquee et validee le 12 aout 2026 sur le cluster dedie
`192.168.1.241`. Aucun serveur `10.5.6.3` ou `10.5.6.4` n'a ete utilise.

```text
cluster=oculox-opensearch
status=green
nodes=3
unassigned_shards=0
default_primary_shards=1
minimum_replicas=1
disk_watermarks=75%/85%/90%
ism_action_validation=true
replica_survives_primary_node_loss=PASS
cluster_recovery_green=PASS
```

## 2. Decision sur les shards primaires

La baseline comporte 43 shards primaires pour environ 668 000 documents. Le
plus gros shard applicatif mesure environ 75 Mo. Ces tailles ne justifient pas
une multiplication des primaires. Le choix retenu est donc :

```text
number_of_shards: 1
number_of_replicas: 1
```

Le nombre de shards primaires est un reglage statique d'un index. Il ne sera
augmente qu'apres mesure d'un debit ou d'une taille de shard qui le justifie.
Le nombre de replicas est dynamique et peut etre ajuste sans recreer l'index.

La documentation OpenSearch confirme que la valeur par defaut est un primaire
et un replica, et que `index.number_of_replicas` est dynamique :

https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/index-settings/

## 3. Strategie de replicas

Le cluster porte maintenant le reglage persistant suivant :

```json
"cluster.default_number_of_replicas": "1"
```

L'applicateur controle aussi tous les index existants, y compris les index
caches et systeme. Un index a zero replica passe a un. Un index qui possede
deja deux replicas, comme certains index Security, reste a deux.

Les templates suivants sont controles explicitement :

```text
malcolm_template
malcolm_beats_template
arkime_stats_template
arkime_sessions3_ecs_template
arkime_sessions3_template
arkime_history_v1_template
```

S'ils existent, le script recupere leur corps complet, change uniquement
`index.number_of_replicas`, puis renvoie le template. Il ne remplace donc ni les
mappings, ni les aliases, ni les priorites. Ce point est important car plusieurs
templates composables concurrents ne sont pas fusionnes : le template de plus
haute priorite est applique.

Les templates Malcolm peuvent aussi imposer
`index.routing.allocation.total_shards_per_node`. Cette limite, utile dans un
contexte mono-noeud, peut rendre un replica impossible a placer sur trois
noeuds. L'applicateur la passe a `-1` et fait de meme pour les index existants.
OpenSearch reste charge de l'equilibrage ; `same_shard` interdit toujours de
placer un primaire et sa copie sur le meme noeud, et les watermarks protegent
le disque.

Lors du test de cette étape, ces six templates n'etaient pas encore presents
sur le cluster dedie. C'est normal avant la restauration et le demarrage des
composants Oculox. Leur statut est consigne comme
`pending-oculox-bootstrap`. Il faudra reexecuter l'applicateur apres leur
creation ou apres la restauration ; il est idempotent.

Documentation officielle des templates :

https://docs.opensearch.org/latest/im-plugin/index-templates/

## 4. Politiques ISM

Trois politiques sont versionnees et actives :

| Politique | Index | Optimisation | Retention | Replicas |
|---|---|---:|---:|---:|
| `arkime_sessions` | `arkime_sessions3-*` | force merge a 30 jours | 90 jours | 1 |
| `arkime_history` | `arkime_history_v*` | aucune | 91 jours | 1 |
| `oculox_malcolm_beats` | `malcolm_beats_*` | force merge a 30 jours | 90 jours | 1 |

Les deux politiques Arkime reprennent la structure et les motifs employes par
la commande officielle `db.pl ... ism`. Le replica reste a un dans l'etat
ancien ; il n'est plus ramene a zero. La politique Beats est separee parce que
ces index ne sont pas geres par Arkime.

ISM rattache automatiquement la politique aux nouveaux index grace a
`ism_template`. L'applicateur rattache egalement les index deja existants, ce
qui couvre une restauration. Les motifs restent limites aux prefixes
applicatifs ; aucune politique large `*` ne peut toucher
`.opendistro_security`.

La validation des actions ISM est activee :

```json
"plugins.index_state_management.action_validation.enabled": "true"
```

Documentation officielle :

https://docs.opensearch.org/latest/im-plugin/ism/policies/

Source officielle Arkime `db.pl` :

https://github.com/arkime/arkime/blob/main/db/db.pl

## 5. Aliases

Pour chaque index applicatif deja present, le script garantit :

```text
arkime_sessions3-* -> malcolm_network
malcolm_beats_*    -> malcolm_other
```

Il controle aussi les aliases Arkime observes dans la baseline :

```text
arkime_configs arkime_dstats arkime_fields arkime_files arkime_hunts
arkime_lookups arkime_notifiers arkime_parliament arkime_queries
arkime_sequence arkime_shareables arkime_stats arkime_users arkime_views
```

Ces aliases ne sont pas inventes avant le bootstrap Arkime. Leur absence est
signalee comme `pending-oculox-bootstrap`; Arkime doit d'abord creer les index
versionnes correspondants.

## 6. Protections disque

Les protections disque, auparavant desactivees dans le mono-noeud, sont
reactivees avec :

```text
low         = 75%
high        = 85%
flood_stage = 90%
refresh     = 30s
```

Sur les 185 Gio vus par OpenSearch, cela represente approximativement :

| Seuil | Espace libre restant | Effet |
|---|---:|---|
| `low` 75 % | 46 Gio | ne plus allouer de nouveaux replicas sur le noeud |
| `high` 85 % | 28 Gio | tenter de deplacer les shards hors du noeud |
| `flood_stage` 90 % | 18 Gio | bloquer en lecture seule les index concernes |

Ces seuils sont volontairement plus conservateurs que les valeurs OpenSearch
par defaut de 85/90/95 %. Le flood stage protege le stockage avant saturation.

Limite physique importante : les trois volumes Docker sont distincts, mais ils
resident actuellement sur le meme disque de la meme VM. Les replicas protegent
donc contre la perte d'un conteneur ou d'un noeud OpenSearch, pas contre la
perte de la VM ou du disque physique. La protection contre ce risque exige des
snapshots sur un stockage externe et, a terme, des noeuds sur des machines ou
disques independants.

Documentation officielle des seuils disque :

https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/cluster-settings/

## 7. Sauvegarde avant modification

Chaque execution cree un repertoire horodate en mode `0700` sous :

```text
dev/generated/opensearch-cluster/storage-policy/backups/
```

Il contient l'etat anterieur des :

```text
cluster settings
index settings
templates composables
templates historiques
aliases
politiques ISM
```

Les fichiers sont en mode `0600` et ignores par Git. Les deux sauvegardes du
test runtime sont `20260812T115314Z` et `20260812T115316Z` sur la VM.

## 8. Commandes operateur

Depuis `/opt/oculox/opensearch-cluster` sur la VM :

```bash
./dev/scripts/opensearch-cluster/apply-storage-policy.py
python3 dev/tests/opensearch-cluster/test_storage_policy_static.py
./dev/tests/opensearch-cluster/test_storage_policy_runtime.sh
```

Le test runtime cree un index temporaire avec un primaire et un replica. Il
arrete ensuite le noeud portant le primaire, lit le document depuis le replica,
redemarre le noeud, attend `green`, puis supprime l'index de test.

Verification manuelle des reglages :

```bash
set -a
source dev/generated/opensearch-cluster/security/accounts.env
set +a

CA=dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt
ENDPOINT=https://192.168.1.241:9200

curl --cacert "$CA" \
  -u "oculox_platform_admin:$OCULOX_PLATFORM_ADMIN_PASSWORD" \
  "$ENDPOINT/_cluster/settings?flat_settings=true&pretty"

curl --cacert "$CA" \
  -u "oculox_platform_admin:$OCULOX_PLATFORM_ADMIN_PASSWORD" \
  "$ENDPOINT/_cat/indices?format=json&h=health,index,pri,rep,docs.count,store.size"

curl --cacert "$CA" \
  -u "oculox_platform_admin:$OCULOX_PLATFORM_ADMIN_PASSWORD" \
  "$ENDPOINT/_plugins/_ism/policies?pretty"
```

## 9. Fichiers de reference

```text
dev/config/opensearch-cluster/storage-policy/cluster-settings.json
dev/config/opensearch-cluster/storage-policy/arkime-sessions-policy.json
dev/config/opensearch-cluster/storage-policy/arkime-history-policy.json
dev/config/opensearch-cluster/storage-policy/malcolm-beats-policy.json
dev/scripts/opensearch-cluster/apply-storage-policy.py
dev/tests/opensearch-cluster/test_storage_policy_static.py
dev/tests/opensearch-cluster/test_storage_policy_runtime.sh
```

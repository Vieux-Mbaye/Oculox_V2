# Étape de découverte - Decouverte et amorcage OpenSearch

## 1. Objet

Cette étape configure la decouverte des trois noeuds et l'election initiale du
cluster manager. Elle separe :

- la decouverte permanente, necessaire a chaque demarrage ;
- l'amorcage initial, necessaire uniquement lorsque les trois volumes sont
  vides.

Le cluster n'a pas encore ete demarre. Le transport inter-noeuds OpenSearch
exige une PKI valide, qui sera construite en étape PKI.

## 2. Configuration permanente

Le fichier suivant contient les parametres communs aux trois services :

```text
dev/compose/opensearch-cluster/compose.yml
```

Configuration rendue :

```text
cluster.name=oculox-opensearch
discovery.type absent
discovery.seed_hosts=opensearch-1:9300,opensearch-2:9300,opensearch-3:9300
transport.port=9300
```

Le mode `single-node` de l'installation mono-noeud n'est pas transmis aux
services. OpenSearch utilise donc sa decouverte multi-noeud par defaut.

## 3. Configuration d'amorcage initial

L'override suivant ajoute la liste initiale aux trois services :

```text
dev/compose/opensearch-cluster/compose.bootstrap.yml
```

Valeur commune :

```text
cluster.initial_cluster_manager_nodes=opensearch-1,opensearch-2,opensearch-3
```

Les trois valeurs correspondent exactement aux trois `node.name` :

```text
opensearch-1
opensearch-2
opensearch-3
```

Les hostnames de `discovery.seed_hosts` correspondent egalement aux noms de
services Docker, avec le port transport explicite `9300`.

## 4. Pourquoi deux fichiers Compose

`cluster.initial_cluster_manager_nodes` sert a creer le tout premier cluster
et a elire son premier cluster manager. Apres cette election, le `cluster_uuid`
et la configuration de vote sont conserves dans les volumes de donnees.

Le premier demarrage d'un cluster vide utilisera :

```bash
docker compose \
  --env-file dev/config/opensearch-cluster/cluster.env.example \
  -f dev/compose/opensearch-cluster/compose.yml \
  -f dev/compose/opensearch-cluster/compose.bootstrap.yml \
  up -d
```

Cette commande est documentee mais ne doit pas encore etre executee avant la
étape PKI.

Les redemarrages ulterieurs utiliseront seulement :

```text
compose.yml
```

Cette separation evite de presenter en permanence une configuration d'amorcage
a des noeuds qui appartiennent deja a un cluster forme.

## 5. Source unique des listes

Les valeurs sont definies une seule fois dans :

```text
dev/config/opensearch-cluster/cluster.env.example
```

```dotenv
OPENSEARCH_DISCOVERY_SEED_HOSTS=opensearch-1:9300,opensearch-2:9300,opensearch-3:9300
OPENSEARCH_INITIAL_CLUSTER_MANAGER_NODES=opensearch-1,opensearch-2,opensearch-3
```

Les trois services lisent ces memes variables. Aucune liste n'est maintenue
separement par noeud.

## 6. Test statique automatise

Le test suivant analyse la configuration JSON produite par Docker Compose :

```bash
./dev/tests/opensearch-cluster/test_discovery_config.py
```

Il verifie :

1. le nom unique du cluster ;
2. l'absence du mode `single-node` ;
3. l'absence de `discovery.type`, donc le mode multi-noeud par defaut ;
4. les trois seed hosts et leur port `9300` ;
5. l'identite des listes sur les trois services ;
6. la correspondance exacte entre la liste initiale et les `node.name` ;
7. l'absence de la configuration d'amorcage dans les redemarrages ordinaires.

Resultat local :

```text
cluster_name=oculox-opensearch
seed_hosts=opensearch-1:9300,opensearch-2:9300,opensearch-3:9300
initial_cluster_manager_nodes=opensearch-1,opensearch-2,opensearch-3
identical_configuration=3/3
DISCOVERY_CONFIG_RESULT=PASS
DISCOVERY_RUNTIME_RESULT=PENDING_PKI
```

Le test structurel de étape de topologie Compose continue egalement a passer.

## 7. Validation sur la VM cible

Les deux Compose et le fichier d'environnement ont ete copies temporairement
dans `/tmp` sur `192.168.1.241`. Docker Compose `5.4.0` a produit le meme rendu
pour les trois services :

```text
opensearch-1 | oculox-opensearch | seed list complete | bootstrap list complete
opensearch-2 | oculox-opensearch | seed list complete | bootstrap list complete
opensearch-3 | oculox-opensearch | seed list complete | bootstrap list complete
```

Apres validation :

```text
conteneurs crees       : 0
volumes crees          : 0
reseaux cluster crees  : 0
```

Le repertoire temporaire a ete supprime.

## 8. Preuves runtime encore attendues

Les preuves suivantes exigent le demarrage reel des trois JVM :

```text
un seul cluster_uuid
trois noeuds presents
un cluster manager elu
cluster green
zero shard non affecte
```

Elles ne peuvent pas etre simulees par `docker compose config`. Elles seront
collectees apres la étape PKI, lorsque les certificats transport et HTTP seront
montes. Demarrer maintenant obligerait soit a desactiver Security, soit a
utiliser la PKI mono-noeud automatique ; ces deux solutions contrediraient le
plan de securite.

## 9. Commandes de preuve apres la PKI

Une fois le cluster demarre et les identifiants disponibles, les controles
porteront au minimum sur :

```text
GET /
GET /_cluster/health
GET /_cat/nodes?v&h=name,ip,node.role,cluster_manager
GET /_cluster/state/cluster_manager_node
GET /_cat/shards?v
```

Les trois noeuds devront retourner le meme `cluster_uuid`. Un seul noeud devra
porter le marqueur de cluster manager.

## 10. Sources officielles

- Amorcage OpenSearch :
  `https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/bootstrapping/`
- Decouverte et seed hosts :
  `https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/discovery/`
- Parametres de formation :
  `https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/settings/`

## 11. Decision de sortie

La configuration statique de étape de découverte est validee localement et sur la VM
cible. Les trois noeuds disposent de listes identiques et coherentes.

La étape de découverte restera ouverte pour ses preuves runtime jusqu'au premier demarrage
securise apres la étape PKI. La prochaine action correcte est donc la creation de
la PKI OpenSearch, pas le demarrage du Compose actuel.

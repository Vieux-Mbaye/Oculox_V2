# Étape d'inventaire0 - Validation autonome du cluster

## 1. Resultat

La validation autonome a ete executee le 12 aout 2026 sur le cluster dedie
`192.168.1.241`, avant toute connexion d'Oculox Core ou Hedgehog.

```text
cluster_uuid=Qia-ZGlDTSyRYduLFlhLLg
initial_manager=opensearch-3
primary_node=opensearch-2
replica_node=opensearch-1
manager_after_failure=opensearch-1
documents_before_restart=5
documents_after_restart=5
cluster_uuid_after_restart=Qia-ZGlDTSyRYduLFlhLLg
status_final=green
nodes_final=3
unassigned_shards_final=0
CLUSTER_RESILIENCE_RESULT=PASS
```

Aucun serveur `10.5.6.3` ou `10.5.6.4` n'a ete utilise.

## 2. Scenario execute

### Creation, ecriture et recherche

Le test a cree un index temporaire avec :

```text
1 shard primaire
1 replica
wait_for_active_shards=all
```

Trois documents ont ete ecrits. Une lecture par identifiant et une recherche
sur les trois documents ont reussi.

### Placement des copies

L'API `_cat/shards` a montre :

```text
primaire -> opensearch-2
replica  -> opensearch-1
```

Les deux copies etaient donc sur des noeuds differents.

### Perte du noeud data portant le primaire

`opensearch-2` a ete arrete. Le replica a ete promu et le cluster a continue :

```text
lecture d'un document existant = PASS
ecriture d'un quatrieme document = PASS
compte de documents = 4
```

Apres le retour d'`opensearch-2`, le test a attendu simultanement :

```text
green
3 noeuds
0 shard non affecte
0 shard en deplacement
```

### Perte du cluster manager elu

Le manager initial `opensearch-3` a ete arrete. Les deux noeuds restants ont
conserve la majorite et ont elu `opensearch-1`. Une cinquieme ecriture a reussi
apres cette election.

L'ancien manager a ensuite rejoint le cluster et l'etat est revenu a `green`.

### Perte de deux noeuds et quorum

Le test a arrete simultanement le manager alors elu, `opensearch-1`, et
`opensearch-2`. Il ne restait qu'un votant sur trois.

Les appels d'etat et d'ecriture ont expire sans reponse exploitable. Ce blocage
est attendu : une decision OpenSearch exige plus de la moitie des votants, donc
deux votes dans une configuration de trois. Le noeud isole ne peut pas s'elire
lui-meme ni accepter une operation qui exige un etat de cluster valide. Cela
empeche deux partitions d'ecrire chacune de leur cote.

Apres le redemarrage des deux noeuds, le cluster est revenu a `green` et
l'ecriture tentee sans quorum n'etait pas presente.

La documentation officielle confirme qu'un cluster de trois votants tolere la
perte d'un noeud, mais pas la perte de deux :

https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/voting-quorums/

### Redemarrage complet

Le test a execute :

```bash
docker compose down
docker compose up -d
```

L'option `-v` n'est jamais utilisee. Les conteneurs et reseaux sont recrees,
mais les trois volumes nommes sont conserves.

Avant et apres ce redemarrage :

```text
cluster_uuid = Qia-ZGlDTSyRYduLFlhLLg
documents    = 5
```

Cela prouve que les noeuds ont rejoint le cluster existant depuis leurs volumes
persistants au lieu d'amorcer un nouveau cluster vide.

## 3. Securite du test

Le script possede un `trap` de recuperation. En cas d'erreur, d'interruption ou
de sortie inattendue, il execute les actions suivantes :

```text
recreation/demarrage de tous les services Compose
attente du retour de l'API
suppression de l'index de test si present
conservation des volumes nommes
```

Le test n'emploie aucune de ces operations destructives :

```text
docker compose down -v
docker volume rm
```

Le journal de la derniere execution est conserve en `0600` sous :

```text
dev/generated/opensearch-cluster/cluster-resilience/last-run.txt
```

## 4. Commandes

Depuis `/opt/oculox/opensearch-cluster` sur la VM :

```bash
python3 dev/tests/opensearch-cluster/test_cluster_resilience_static.py
./dev/tests/opensearch-cluster/test_cluster_resilience_runtime.sh
```

Etat final manuel :

```bash
set -a
source dev/generated/opensearch-cluster/security/accounts.env
set +a

CA=dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt
ENDPOINT=https://192.168.1.241:9200

curl --cacert "$CA" \
  -u "oculox_platform_admin:$OCULOX_PLATFORM_ADMIN_PASSWORD" \
  "$ENDPOINT/_cluster/health?pretty"

curl --cacert "$CA" \
  -u "oculox_platform_admin:$OCULOX_PLATFORM_ADMIN_PASSWORD" \
  "$ENDPOINT/_cat/master?v"

curl --cacert "$CA" \
  -u "oculox_platform_admin:$OCULOX_PLATFORM_ADMIN_PASSWORD" \
  "$ENDPOINT/_cluster/state?filter_path=metadata.cluster_coordination.last_committed_config&pretty"
```

## 5. Fichiers

```text
dev/tests/opensearch-cluster/test_cluster_resilience_runtime.sh
dev/tests/opensearch-cluster/test_cluster_resilience_static.py
dev/tests/opensearch-cluster/README.md
dev/docs/Opensearch/validation_resilience_cluster.md
dev/generated/opensearch-cluster/cluster-resilience/last-run.txt
```

Le dernier fichier est genere a l'execution et reste hors Git.

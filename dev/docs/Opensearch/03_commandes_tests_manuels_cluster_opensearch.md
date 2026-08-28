# Commandes de tests manuels du cluster OpenSearch

## 1. Conditions du test

Executer ces commandes sur la VM du cluster, depuis la racine du depot :

```bash
cd /opt/oculox/opensearch-cluster
```

Les commandes utilisent :

```text
endpoint : https://192.168.1.241:9200
utilisateur : oculox_platform_admin
CA : dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt
Compose : dev/compose/opensearch-cluster/compose.yml
environnement : dev/config/opensearch-cluster/cluster.env.example
```

`curl` demande le mot de passe du compte administrateur. Ne pas placer ce mot
de passe directement dans la commande et ne pas utiliser `curl -k`.

Avant de commencer, verifier que personne n'effectue une maintenance ou une
ingestion importante. Les tests de panne arretent volontairement des noeuds.

Ne jamais ajouter `-v` a `docker compose down`. Cette option supprimerait les
volumes et les donnees.

## 2. Test automatise recommande

Le script automatise cree un index temporaire, effectue les pannes, redemarre
les noeuds et supprime l'index de test. Il possede aussi une procedure de
recuperation si une verification echoue.

Controle statique :

```bash
python3 dev/tests/opensearch-cluster/test_cluster_resilience_static.py
```

Test runtime complet :

```bash
./dev/tests/opensearch-cluster/test_cluster_resilience_runtime.sh
```

Resultat final attendu :

```text
CLUSTER_RESILIENCE_RESULT=PASS
```

Le journal est conserve ici :

```text
dev/generated/opensearch-cluster/cluster-resilience/last-run.txt
```

## 3. Verifier les conteneurs

```bash
./oculox cluster status
```

Attendu :

```text
opensearch-1       healthy
opensearch-2       healthy
opensearch-3       healthy
opensearch-endpoint healthy
```

## 4. Verifier la sante generale

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cluster/health?pretty"
```

Attendu :

```text
status = green
number_of_nodes = 3
number_of_data_nodes = 3
unassigned_shards = 0
```

## 5. Voir les noeuds et le cluster manager

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cat/nodes?v&h=name,ip,node.role,master"
```

L'asterisque `*` indique le cluster manager actuellement elu.

Afficher seulement le manager :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cat/master?v&h=node,id,ip"
```

## 6. Voir l'identite et la configuration de vote

Afficher le `cluster_uuid` :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/?filter_path=cluster_name,cluster_uuid,version.number&pretty"
```

Noter le `cluster_uuid` pour le comparer apres le redemarrage complet.

Afficher les identifiants internes des noeuds votants :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cluster/state?filter_path=metadata.cluster_coordination.last_committed_config&pretty"
```

Avec trois votants, deux votes sont necessaires pour obtenir la majorite.

## 7. Creer un index de test

Supprimer un ancien index de test s'il existe :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X DELETE "https://192.168.1.241:9200/test-manuel"
```

Une reponse `404` est normale si l'index n'existait pas.

Creer un index avec un shard primaire et un replica :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X PUT "https://192.168.1.241:9200/test-manuel?wait_for_active_shards=all" -H "Content-Type: application/json" -d '{"settings":{"number_of_shards":1,"number_of_replicas":1},"mappings":{"properties":{"numero":{"type":"integer"},"message":{"type":"keyword"}}}}'
```

Attendu :

```text
acknowledged=true
shards_acknowledged=true
```

Verifier les reglages :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/test-manuel/_settings?pretty"
```

## 8. Ecrire des documents

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X PUT "https://192.168.1.241:9200/test-manuel/_doc/1?refresh=wait_for&wait_for_active_shards=all" -H "Content-Type: application/json" -d '{"numero":1,"message":"premier-document"}'
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X PUT "https://192.168.1.241:9200/test-manuel/_doc/2?refresh=wait_for&wait_for_active_shards=all" -H "Content-Type: application/json" -d '{"numero":2,"message":"deuxieme-document"}'
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X PUT "https://192.168.1.241:9200/test-manuel/_doc/3?refresh=wait_for&wait_for_active_shards=all" -H "Content-Type: application/json" -d '{"numero":3,"message":"troisieme-document"}'
```

Chaque reponse doit indiquer deux copies reussies :

```text
_shards.total=2
_shards.successful=2
```

## 9. Lire et rechercher

Lire un document par son identifiant :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/test-manuel/_doc/1?pretty"
```

Rechercher tous les documents :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X GET "https://192.168.1.241:9200/test-manuel/_search?pretty" -H "Content-Type: application/json" -d '{"query":{"match_all":{}}}'
```

Compter les documents :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/test-manuel/_count?pretty"
```

Attendu : `count=3`.

## 10. Verifier le placement primaire/replica

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cat/shards/test-manuel?v&h=index,shard,prirep,state,node"
```

Exemple sain :

```text
test-manuel 0 p STARTED opensearch-2
test-manuel 0 r STARTED opensearch-1
```

`p` signifie primaire et `r` signifie replica. Ils doivent etre `STARTED` sur
deux noeuds differents.

## 11. Tester la perte du noeud primaire

Lire la colonne `node` de la ligne `p` dans la commande precedente, puis
executer une seule des commandes suivantes selon le noeud qui porte le
primaire.

Si le primaire est sur `opensearch-1` :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml stop opensearch-1
```

Si le primaire est sur `opensearch-2` :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml stop opensearch-2
```

Si le primaire est sur `opensearch-3` :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml stop opensearch-3
```

Verifier que le document reste lisible :

```bash
curl --max-time 10 --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/test-manuel/_doc/1?pretty"
```

Verifier que le replica a ete promu primaire :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cat/shards/test-manuel?v&h=index,shard,prirep,state,node"
```

Ecrire pendant la panne :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X PUT "https://192.168.1.241:9200/test-manuel/_doc/4?refresh=wait_for" -H "Content-Type: application/json" -d '{"numero":4,"message":"document-ecrit-pendant-la-panne"}'
```

Redemarrer exactement le noeud arrete. Exemple pour `opensearch-2` :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml start opensearch-2
```

Attendre son retour puis verifier la sante :

```bash
sleep 30
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cluster/health?wait_for_status=green&timeout=120s&pretty"
```

## 12. Tester l'election d'un nouveau cluster manager

Identifier le manager actuel :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cat/master?v&h=node"
```

Arreter uniquement ce noeud. Exemple si le resultat est `opensearch-3` :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml stop opensearch-3
```

Attendre l'election :

```bash
sleep 15
```

Afficher le nouveau manager :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cat/master?v&h=node"
```

Le nom doit etre different du noeud arrete.

Verifier que l'ecriture fonctionne encore :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X PUT "https://192.168.1.241:9200/test-manuel/_doc/5?refresh=wait_for" -H "Content-Type: application/json" -d '{"numero":5,"message":"document-ecrit-apres-election"}'
```

Redemarrer le noeud arrete. Exemple pour `opensearch-3` :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml start opensearch-3
```

Attendre le retour a `green` :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cluster/health?wait_for_status=green&timeout=120s&pretty"
```

## 13. Tester la perte du quorum

Cette operation arrete deux noeuds. Relever d'abord le manager actuel, puis
choisir un autre noeud. Ne jamais arreter le troisieme.

Exemple si le manager est `opensearch-1`, avec `opensearch-2` comme second
noeud arrete :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml stop opensearch-1 opensearch-2
```

Attendre la detection de la panne :

```bash
sleep 15
```

Tester la sante avec un delai maximal :

```bash
curl --max-time 10 --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cluster/health?pretty"
```

Tester une ecriture qui ne doit pas reussir :

```bash
curl --max-time 10 --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X PUT "https://192.168.1.241:9200/test-manuel/_doc/quorum-test?refresh=wait_for" -H "Content-Type: application/json" -d '{"numero":99,"message":"ne-doit-pas-etre-valide-sans-quorum"}'
```

Un timeout, une reponse `503` ou une autre reponse non `2xx` est attendu. Le
cluster ne doit pas accepter l'ecriture avec un seul votant disponible.

Redemarrer immediatement les deux noeuds arretes :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml start opensearch-1 opensearch-2
```

Attendre le retour a `green` :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cluster/health?wait_for_status=green&timeout=180s&pretty"
```

Verifier que l'ecriture sans quorum n'a pas ete validee :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/test-manuel/_doc/quorum-test?pretty"
```

Attendu : `found=false` ou HTTP `404`.

## 14. Tester un redemarrage complet

Afficher et noter l'UUID avant l'arret :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/?filter_path=cluster_uuid&pretty"
```

Arreter les conteneurs sans supprimer les volumes :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml down
```

Redemarrer sans le fichier bootstrap :

```bash
docker compose --env-file dev/config/opensearch-cluster/cluster.env.example -f dev/compose/opensearch-cluster/compose.yml up -d
```

Attendre le cluster :

```bash
sleep 60
```

Verifier la sante :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cluster/health?wait_for_status=green&timeout=180s&pretty"
```

Afficher l'UUID apres redemarrage :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/?filter_path=cluster_uuid&pretty"
```

L'UUID doit etre identique a celui note avant l'arret.

Verifier que les cinq documents existent toujours :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/test-manuel/_count?pretty"
```

Attendu : `count=5`.

## 15. Supprimer l'index de test

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X DELETE "https://192.168.1.241:9200/test-manuel"
```

Attendu :

```text
acknowledged=true
```

## 16. Controle final obligatoire

```bash
./oculox cluster status
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cluster/health?pretty"
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cat/shards?v&h=index,shard,prirep,state,node" | grep UNASSIGNED
```

La derniere commande ne doit afficher aucune ligne. Le resultat final attendu
est :

```text
3 noeuds
cluster green
0 shard UNASSIGNED
endpoint healthy
```

## 17. Diagnostic si le cluster reste yellow

Lister les shards non affectes :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.241:9200/_cat/shards?v&h=index,shard,prirep,state,node,unassigned.reason" | grep UNASSIGNED
```

Demander a OpenSearch pourquoi une copie ne peut pas etre placee :

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin -X POST "https://192.168.1.241:9200/_cluster/allocation/explain?pretty" -H "Content-Type: application/json" -d '{"index":"NOM_INDEX","shard":NUMERO_SHARD,"primary":false}'
```

Remplacer manuellement `NOM_INDEX` et `NUMERO_SHARD` avec les valeurs obtenues
dans la commande precedente.

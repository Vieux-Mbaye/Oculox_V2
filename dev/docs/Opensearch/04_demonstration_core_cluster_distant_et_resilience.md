# Démonstration Oculox avec un cluster OpenSearch distant

## Objectif

Ce guide fournit les commandes à présenter pour prouver que :

1. Oculox Core utilise `192.168.1.241:9200` et non un OpenSearch local ;
2. tous les clients utilisent TLS et leurs comptes de service ;
3. Filebeat répartit ses événements entre deux Logstash ;
4. un PCAP est analysé, ingéré et indexé ;
5. l'ingestion continue lorsqu'un nœud OpenSearch est arrêté ;
6. le cluster revient à trois nœuds et à l'état `green`.

Les commandes sont volontairement écrites sur une seule ligne. Ne placez
jamais un mot de passe dans une commande projetée ou dans l'historique shell.

## Comprendre les commandes `./oculox`

`./oculox` est le lanceur d'exploitation interne du projet Oculox. Ce n'est ni
une commande Linux standard, ni une commande officielle OpenSearch, ni une
commande fournie directement par Malcolm. Le fichier exécutable se trouve à la
racine du dépôt :

```text
/home/kakashi_/ICSHUB/Oculox/oculox
```

Son rôle est de fournir une seule interface pour appeler les scripts
d'installation, de démarrage, de configuration et de validation du projet.
Par exemple :

```text
./oculox start          -> prépare le Compose Oculox et démarre la plateforme
./oculox status         -> demande à Docker Compose l'état des services
./oculox cluster status -> appelle le gestionnaire du cluster OpenSearch
./oculox verify clients -> lance les tests Python des clients OpenSearch
./oculox verify ingestion -> lance le test Python du chemin d'ingestion
```

Pour `verify ingestion`, le lanceur délègue réellement le travail au fichier
versionné suivant :

```text
dev/tests/opensearch-cluster/validate-ingestion-path.py
```

Ce script ne fabrique pas manuellement les résultats. Il lit les compteurs
Filebeat et Logstash dans leurs API Docker, mesure les fichiers Zeek et
Suricata sur le disque, interroge OpenSearch en HTTPS et écrit les observations
dans un rapport JSON.

Réponse courte à donner en réunion :

> `./oculox` est notre CLI d'exploitation Oculox. Pour cette démonstration,
> elle exécute un validateur Python versionné dans le dépôt. Le validateur
> collecte automatiquement les métriques des composants avant et après le
> test, puis produit un rapport JSON vérifiable. Ce n'est pas une commande
> officielle Malcolm : c'est notre test d'acceptation et de non-régression.

Cette approche est professionnelle si le script reste versionné, relisible,
reproductible et retourne un code d'erreur en cas d'échec. Le rapport JSON doit
être présenté comme une preuve du banc testé, pas comme une certification
officielle de l'éditeur.

## 1. Montrer le cluster distant

Sur la VM `192.168.1.241` :

```bash
cd /opt/oculox/opensearch-cluster
```

```bash
./oculox cluster status
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin 'https://192.168.1.241:9200/_cluster/health?pretty'
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin 'https://192.168.1.241:9200/_cat/nodes?v&h=name,ip,node.role,master'
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin 'https://192.168.1.241:9200/_cat/master?v&h=node,id,ip'
```

Preuve attendue : `green`, trois nœuds, un seul manager marqué `*` et zéro
shard non affecté.

## 2. Montrer que Core utilise le cluster distant

Sur Core local :

```bash
cd /home/kakashi_/ICSHUB/Oculox
```

```bash
grep -E '^(OPENSEARCH_PRIMARY|OPENSEARCH_URL|OPENSEARCH_SSL_CERTIFICATE_VERIFICATION)=' config/opensearch.env
```

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'NAMES|opensearch|logstash|filebeat|arkime|dashboards'
```

Le premier résultat doit montrer `opensearch-remote`, l'URL `.241` et la
vérification TLS à `true`. La liste Docker doit montrer les clients Oculox mais
aucun conteneur OpenSearch local.

```bash
curl --config dev/generated/opensearch-clients/api.curlrc --cacert nginx/ca-trust/oculox-opensearch-ca.crt 'https://192.168.1.241:9200/_cluster/health?pretty'
```

Cette commande utilise la CA et le compte de service API installés par le
bundle. Elle ne contient ni `-k` ni mot de passe visible.

## 3. Prouver les clients, les comptes et Filebeat

```bash
./oculox verify clients --output dev/generated/validation/client-connectivity/demo/report.json
```

Cette commande ne démarre pas Oculox et n'injecte aucun PCAP. Elle vérifie que
les clients déjà démarrés sont correctement configurés pour utiliser le
cluster OpenSearch distant. Le mot `clients` désigne ici les composants Oculox
qui lisent ou écrivent dans OpenSearch : Logstash, Arkime, Dashboards,
dashboards-helper, API et pcap-monitor.

La commande exécute le programme Python :

```text
dev/tests/opensearch-cluster/validate-client-connectivity.py
```

L'option `--output` indique où conserver la preuve JSON. Le répertoire est créé
automatiquement, le fichier reçoit les permissions `600` et la commande
retourne un code différent de zéro si au moins un contrôle échoue.

### Contrôle 1 : rôle et endpoint distant

Le validateur lit `dev/generated/deployment.env` pour déterminer si la machine
est un Core `principal` ou un collecteur `hedgehog`. Il lit ensuite
`dev/generated/opensearch-clients/deployment.env` et exige un endpoint en
`https://`. Enfin, il vérifie la présence de la CA dans :

```text
nginx/ca-trust/oculox-opensearch-ca.crt
```

Cela répond aux questions : « quel rôle cette machine joue-t-elle ? », « vers
quel cluster doit-elle aller ? » et « possède-t-elle la CA nécessaire pour
faire confiance au certificat du cluster ? ».

### Contrôle 2 : présence et santé des conteneurs

Pour un Core, les services attendus sont :

```text
logstash
logstash-2
arkime
arkime-live
dashboards
dashboards-helper
pcap-monitor
api
```

Le script recherche chaque conteneur grâce à son label Docker Compose. Il
vérifie ensuite que le conteneur est en cours d'exécution et que son
healthcheck vaut `healthy`, lorsqu'un healthcheck est défini. Un conteneur
absent, arrêté ou `unhealthy` produit un `FAIL`.

### Contrôle 3 : bon compte monté dans chaque client

Chaque composant ne doit pas utiliser le compte administrateur. Le script
vérifie que le fichier d'identité prévu est réellement monté dans le
conteneur :

| Composant | Identité attendue |
|---|---|
| Logstash 1 et 2 | `logstash.curlrc` |
| Arkime et Arkime Live | `arkime.curlrc` |
| Dashboards | `dashboards.curlrc` |
| dashboards-helper | `dashboards-helper.curlrc` |
| API et pcap-monitor | `api.curlrc` |

Les fichiers se trouvent sous `dev/generated/opensearch-clients/`. Le contrôle
du montage prouve que Docker présente le bon secret au bon service, et pas
seulement que le fichier existe sur l'hôte.

### Contrôle 4 : authentification réelle auprès d'OpenSearch

Pour chaque identité, le validateur appelle réellement :

```text
GET /_plugins/_security/authinfo
```

La connexion TLS est validée avec la CA Oculox. Le script exige une réponse
HTTP `200` et vérifie que le nom renvoyé par OpenSearch correspond exactement
au compte contenu dans le fichier `.curlrc`. Par exemple, le fichier
`logstash.curlrc` doit être reconnu par OpenSearch comme `oculox_logstash`.

Cette étape prouve en même temps que l'adresse est joignable, que TLS est
accepté, que le mot de passe est correct et que le plugin Security reconnaît
le bon utilisateur. Elle ne vérifie cependant pas toutes les permissions du
rôle ; les droits nécessaires sont ensuite exercés par les tests spécifiques.

### Contrôle 5 : pipelines des deux Logstash

Le script interroge l'API interne de chaque Logstash sur le port `9600` :

```text
GET /_node/stats/pipelines
```

Il exige que l'API réponde et qu'au moins un pipeline soit chargé. Sur le Core
actuel, sept pipelines sont attendus par instance. Cela prouve que Logstash ne
se contente pas d'avoir un processus actif : ses pipelines de traitement sont
bien initialisés.

### Contrôle 6 : répartition Filebeat et mTLS

Le validateur ouvre tous les fichiers YAML présents dans
`dev/generated/filebeat/`. Pour chacun, il exige :

```text
hosts = logstash:5044 et logstash-2:5044
loadbalance = true
ssl.enabled = true
ssl.verification_mode = full
CA, certificat client et clé client renseignés
aucune sortie directe output.elasticsearch ou output.opensearch
```

Ce contrôle prouve que Filebeat doit distribuer les événements entre les deux
Logstash et utiliser un certificat client mTLS. Il s'agit ici d'un contrôle de
configuration. Les connexions effectives et les compteurs d'événements sont
prouvés par les journaux Filebeat et par le test d'ingestion de la section 5.

### Contrôle 7 : route Nginx

Sur un Core, le script appelle `https://127.0.0.1/` et accepte les codes HTTP
normaux de la plateforme, notamment `200`, une redirection, `401` ou `403`.
Un `401` est normal si la page exige une authentification. Ce contrôle prouve
que Nginx répond ; il ne prouve pas à lui seul l'ingestion OpenSearch.

### Contrôle 8 : écriture directe Arkime

Arkime écrit ses sessions directement dans OpenSearch, sans passer par
Logstash. Le validateur réalise donc un vrai cycle avec le compte
`oculox_arkime` :

1. création d'un index temporaire avec un primaire et un replica ;
2. écriture d'un document ;
3. lecture du compteur et vérification de la présence d'un document ;
4. suppression de l'index temporaire.

Les codes attendus sont affichés sous cette forme :

```text
create=200 write=201 read=200 delete=200
```

Cette opération prouve que le rôle Arkime possède les droits réellement
nécessaires pour créer, écrire, lire et nettoyer ses données sur le cluster
distant. L'index de validation est supprimé à la fin.

### Lecture du résultat

Chaque ligne affichée commence par `PASS` ou `FAIL`. Le résultat global :

```text
CLIENT_CONNECTIVITY_RESULT=PASS
```

signifie que tous les contrôles précédents ont réussi. Le rapport JSON contient
le rôle, l'endpoint, l'heure, le détail de chaque contrôle et le résultat
global. Il peut être relu avec :

```bash
jq . dev/generated/validation/client-connectivity/demo/report.json
```

Cette commande ne prouve pas qu'un PCAP complet a été analysé et indexé. Cette
preuve appartient au test `./oculox verify ingestion` présenté dans la section
5.

Résultat attendu :

```text
CLIENT_CONNECTIVITY_RESULT=PASS
```

```bash
grep -R -nE 'hosts:|loadbalance:|certificate_authorities:|certificate:|key:' dev/generated/filebeat
```

```bash
docker logs oculox-filebeat-1 2>&1 | grep -E 'Connection to backoff.*(logstash|logstash-2).*established' | tail -20
```

La configuration doit contenir les deux destinations Logstash,
`loadbalance: true` et les fichiers mTLS. Les journaux doivent montrer les deux
connexions établies.

## 4. Montrer les files persistantes Logstash

```bash
docker exec oculox-logstash-1 curl -s http://127.0.0.1:9600/_node/stats/pipelines | jq '[.pipelines | to_entries[] | {pipeline:.key,type:.value.queue.type,events:.value.queue.events_count,max_bytes:.value.queue.max_queue_size_in_bytes}]'
```

```bash
docker exec oculox-logstash-2-1 curl -s http://127.0.0.1:9600/_node/stats/pipelines | jq '[.pipelines | to_entries[] | {pipeline:.key,type:.value.queue.type,events:.value.queue.events_count,max_bytes:.value.queue.max_queue_size_in_bytes}]'
```

Chaque pipeline doit afficher `type: persisted`.

## 5. Démontrer une ingestion complète

Créer le répertoire de preuve :

```bash
mkdir -p dev/generated/validation/boss-demo/ingestion
```

Prendre la référence avant injection :

```bash
./oculox verify ingestion baseline --output dev/generated/validation/boss-demo/ingestion/baseline.json
```

Injecter le PCAP du banc local :

```bash
./oculox verify ingestion inject --pcap pcap/processed/mnetsniff-wlo1_1786618984.pcap --run-id boss-demo-ingestion --output dev/generated/validation/boss-demo/ingestion/collector.json --wait 300 --allow-core
```

Cette commande effectue les opérations suivantes :

1. elle relève la taille totale et le nombre de fichiers Zeek et Suricata ;
2. elle relève les compteurs Filebeat ;
3. elle copie le PCAP dans `pcap/upload` avec l'identifiant `run-id` ;
4. pcap-monitor détecte le fichier et déclenche son traitement ;
5. Zeek et Suricata analysent le PCAP et écrivent leurs journaux ;
6. Filebeat lit ces journaux et les envoie aux deux Logstash ;
7. le script attend la consommation du PCAP et le mouvement des compteurs ;
8. il calcule les différences entre les mesures avant et après.

Un extrait de rapport peut ressembler à ceci :

```json
{
  "zeek": {
    "files_delta": 0,
    "bytes_delta": 3694
  },
  "suricata": {
    "files_delta": 0,
    "bytes_delta": 6351
  },
  "filebeat": {
    "published": 24,
    "acked": 24,
    "failed": 0
  }
}
```

### Signification de `zeek.files_delta`

`files_delta` est la différence entre le nombre de fichiers présents après le
test et avant le test. La valeur `0` ne signifie pas que Zeek n'a rien produit.
Elle signifie qu'aucun nouveau fichier n'a été créé pendant la fenêtre de
mesure. Zeek a pu continuer à écrire dans un fichier qui existait déjà.

### Signification de `zeek.bytes_delta`

`bytes_delta: 3694` signifie que la taille totale des journaux Zeek a augmenté
de `3 694` octets. Cette augmentation prouve que Zeek a ajouté des données à
ses journaux pendant le traitement.

### Signification des mesures Suricata

Les valeurs Suricata se lisent de la même manière. `files_delta: 0` signifie
que Suricata a réutilisé un fichier existant. `bytes_delta: 6351` signifie que
ses journaux ont grandi de `6 351` octets.

### Signification de `filebeat.published`

`published: 24` signifie que, pendant la fenêtre observée, Filebeat a présenté
`24` événements à sa sortie Logstash. Ce sont des événements de journaux, pas
des paquets réseau et pas nécessairement `24` documents OpenSearch définitifs.

### Signification de `filebeat.acked`

`acked: 24` signifie que Logstash a accusé réception des `24` événements. Le
fait que `published` et `acked` soient égaux indique que tous les événements
présentés pendant cette observation ont été acceptés par la sortie.

### Signification de `filebeat.failed`

`failed: 0` signifie qu'aucun échec de publication n'a été comptabilisé pendant
la fenêtre. Une preuve saine est donc :

```text
published > 0
acked = published
failed = 0
```

Ces trois valeurs prouvent le passage Filebeat vers Logstash. Elles ne prouvent
pas à elles seules l'indexation dans OpenSearch. C'est la commande `finalize`
suivante qui vérifie ensuite les compteurs des deux Logstash, la croissance des
index OpenSearch, les sessions Arkime et les rejets d'indexation.

Finaliser la mesure :

```bash
./oculox verify ingestion finalize --baseline dev/generated/validation/boss-demo/ingestion/baseline.json --collector-report dev/generated/validation/boss-demo/ingestion/collector.json --output dev/generated/validation/boss-demo/ingestion/final.json
```

Afficher uniquement les preuves importantes :

```bash
jq '{result,packets:.collector.packets,filebeat:.collector.filebeat,logstash_delta,opensearch_delta,checks}' dev/generated/validation/boss-demo/ingestion/final.json
```

Résultat attendu : `INGESTION_RESULT=PASS`, les deux deltas Logstash positifs,
des documents et sessions en augmentation, zéro nouveau rejet.

## 6. Démontrer une panne pendant l'ingestion

Cette démonstration utilise deux terminaux. Choisissez un seul nœud pour la
présentation ; les trois ont déjà été testés dans le rapport consolidé.

### Terminal Core, avant la panne

```bash
mkdir -p dev/generated/validation/boss-demo/failover/opensearch-1
```

```bash
./oculox verify ingestion baseline --output dev/generated/validation/boss-demo/failover/opensearch-1/baseline.json
```

Lancer ensuite l'injection :

```bash
./oculox verify ingestion inject --pcap pcap/processed/mnetsniff-wlo1_1786618984.pcap --run-id boss-demo-failover-opensearch-1 --output dev/generated/validation/boss-demo/failover/opensearch-1/collector.json --wait 300 --allow-core
```

### Terminal cluster, pendant l'injection

```bash
cd /opt/oculox/opensearch-cluster
```

```bash
docker compose --env-file dev/generated/opensearch-cluster/cluster.env -f dev/compose/opensearch-cluster/compose.yml stop opensearch-1
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin 'https://192.168.1.241:9200/_cluster/health?pretty'
```

La santé peut être `yellow`, mais `number_of_nodes` doit valoir `2`, un manager
doit rester découvert et les écritures doivent continuer.

```bash
curl http://127.0.0.1:8404/stats
```

La page HAProxy doit montrer `opensearch-1` indisponible et les deux autres
backends disponibles.

### Terminal Core, validation pendant la panne

Après la fin de l'injection :

```bash
./oculox verify ingestion finalize --baseline dev/generated/validation/boss-demo/failover/opensearch-1/baseline.json --collector-report dev/generated/validation/boss-demo/failover/opensearch-1/collector.json --output dev/generated/validation/boss-demo/failover/opensearch-1/final.json
```

```bash
jq '{result,filebeat:.collector.filebeat,logstash_delta,opensearch_delta,checks}' dev/generated/validation/boss-demo/failover/opensearch-1/final.json
```

Le résultat attendu est `PASS`, avec `published = acked`, les deux Logstash
actifs, des documents indexés et aucun nouveau rejet.

### Terminal cluster, réintégration

```bash
docker compose --env-file dev/generated/opensearch-cluster/cluster.env -f dev/compose/opensearch-cluster/compose.yml start opensearch-1
```

```bash
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin 'https://192.168.1.241:9200/_cluster/health?wait_for_status=green&wait_for_nodes=3&timeout=180s&pretty'
```

Le résultat final doit être `green`, trois nœuds et zéro shard non affecté.

## 7. Montrer les preuves déjà obtenues sur les trois nœuds

Sur Core :

```bash
./oculox verify failover --reports-dir dev/generated/validation/opensearch-failover --output dev/generated/validation/opensearch-failover/summary.json
```

```bash
jq '{result,scenarios,final_cluster}' dev/generated/validation/opensearch-failover/summary.json
```

Résultat attendu :

```text
INGESTION_FAILOVER_RESULT=PASS
```

## 8. Ce que ces preuves permettent d'affirmer

Vous pouvez affirmer que Core joint un endpoint OpenSearch distant avec
validation de CA, que les applications utilisent des comptes limités, que
Filebeat distribue ses événements aux deux Logstash, qu'un PCAP produit des
événements et des sessions réellement indexés, et que la perte de chacun des
trois nœuds a été tolérée individuellement avant un retour à l'état `green`.

Vous ne devez pas affirmer qu'un paquet correspond à un document ni que ce banc
local remplace le futur test réseau d'une VM Hedgehog séparée.

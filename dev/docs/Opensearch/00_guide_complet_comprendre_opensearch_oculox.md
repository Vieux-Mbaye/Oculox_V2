# Comprendre OpenSearch dans Oculox, du mono-noeud au cluster securise

> Ce guide conserve les etapes historiques du developpement. Ses constats
> intermediaires ne sont pas l'etat actuel. Pour les VM neuves et la PKI EJBCA,
> suivre [la procedure actuelle](../../ejbca/docs/installation_3_vm_et_bundles.md).

## 1. Objectif de ce guide

Ce document explique le travail OpenSearch depuis les bases jusqu'a la fin de
la étape Security. Il doit permettre de comprendre :

- ce qu'OpenSearch stocke et comment il le stocke ;
- comment Oculox utilise actuellement son OpenSearch mono-noeud ;
- pourquoi un cluster de trois noeuds a ete cree ;
- le role de chaque fichier ajoute au depot ;
- ce qui se passe au premier demarrage et aux redemarrages suivants ;
- comment TLS, la PKI et le plugin Security s'articulent ;
- comment verifier chaque resultat sans deviner ;
- ce qui est termine et ce qui ne l'est pas encore.

Le depot de reference est :

```text
/home/kakashi_/ICSHUB/Oculox
```

Le cluster de developpement est actuellement deploye sur :

```text
VM                 : 192.168.1.241
repertoire VM      : /opt/oculox/opensearch-cluster
nom du cluster     : oculox-opensearch
version OpenSearch : 3.7.0
nombre de noeuds   : 3
```

## Sommaire

1. Objectif et perimetre du guide
2. Bases : document, index, shard, replica, noeud et cluster
3. Trajet des donnees Oculox
4. OpenSearch mono-noeud existant
5. Pourquoi un cluster separe
6. Étape d'inventaire : baseline
7. Étape de préparation hôte : preparation de la VM
8. Étape d'organisation : organisation du depot
9. Étape de topologie Compose : Compose du cluster
10. Étape de découverte : decouverte et amorcage
11. Étape PKI : PKI et TLS
12. Premier demarrage reel
13. Étape Security : comptes, roles et Security
14. Etat actuel exact
15. Tests statiques locaux
16. Verifications sur la VM
17. Requetes API securisees
18. Test Security runtime
19. Commandes dangereuses
20. Interpretation des resultats
21. Carte des fichiers
22. Documentation officielle
23. Parcours d'apprentissage

Important : le cluster est forme de trois conteneurs sur une seule VM. Il
tolere la perte d'un conteneur ou d'un processus OpenSearch si les replicas
sont correctement configures. Il ne tolere pas encore la perte de la VM, de
son disque physique ou de l'hyperviseur.

## 2. Les bases d'OpenSearch

### 2.1 Qu'est-ce qu'OpenSearch ?

OpenSearch est un moteur distribue d'indexation et de recherche. Oculox lui
envoie principalement :

- les sessions reseau produites par Zeek et Arkime ;
- les alertes Suricata ;
- les autres journaux traites par Logstash ;
- les objets necessaires a OpenSearch Dashboards ;
- des templates, mappings, aliases et politiques de gestion.

OpenSearch expose une API REST HTTPS. Les applications envoient des requetes
HTTP comme :

```text
GET  /_cluster/health
GET  /arkime_sessions3-*/_search
POST /malcolm_beats_suricata_260811/_doc
PUT  /_index_template/malcolm_template
```

### 2.2 Document

Un document est un objet JSON indexe. Exemple simplifie :

```json
{
  "@timestamp": "2026-08-11T14:00:00Z",
  "event.provider": "suricata",
  "source.ip": "10.5.6.10",
  "destination.ip": "10.5.6.20",
  "alert.signature": "Example alert"
}
```

OpenSearch construit des structures de recherche autour de ce document. C'est
ce qui permet ensuite de rechercher rapidement une adresse IP, une signature
ou une periode.

### 2.3 Index

Un index est un ensemble logique de documents. Dans Oculox, les principaux
motifs sont declares dans `config/opensearch.env.example` :

- `arkime_sessions3-*`, ligne 45 : sessions reseau ;
- `malcolm_beats_*`, ligne 63 : autres journaux ;
- `ARKIME_NETWORK_INDEX_PATTERN`, ligne 77 : motif utilise par Arkime.

Le caractere `*` signifie que plusieurs index datés correspondent au meme
motif, par exemple :

```text
arkime_sessions3-260811
malcolm_beats_suricata_260811
malcolm_beats_zeek_260811
```

### 2.4 Mapping et template

Le mapping definit le type des champs : date, adresse IP, mot-cle, nombre,
texte, etc. Un template applique automatiquement des mappings et des
parametres aux nouveaux index correspondant a un motif.

Exemple conceptuel :

```text
template malcolm_beats_template
          |
          +-- motif : malcolm_beats_*
          +-- @timestamp est une date
          +-- source.ip est une adresse IP
          +-- nombre de shards et replicas
```

Sans template coherent, un meme champ peut etre interprete differemment selon
les index, ce qui casse des recherches ou visualisations.

### 2.5 Alias

Un alias est un nom logique pointant vers un ou plusieurs index. La baseline a
identifie notamment :

```text
malcolm_network -> arkime_sessions3-*
malcolm_other   -> malcolm_beats_*
```

Une application peut rechercher l'alias sans connaitre tous les index dates.

### 2.6 Shard primaire

Un index est divise en shards primaires. Un shard est une partition physique
de l'index et correspond a une instance Lucene.

Avec un index configure ainsi :

```json
{
  "number_of_shards": 1,
  "number_of_replicas": 1
}
```

OpenSearch cree :

```text
1 shard primaire
1 copie replica de ce shard
```

### 2.7 Replica

Un replica est une copie d'un shard primaire, placee sur un autre noeud. Si le
noeud portant le primaire disparait, OpenSearch peut promouvoir le replica.

Regle fondamentale : OpenSearch ne place pas le replica sur le meme noeud que
son primaire. Sur un mono-noeud, `number_of_replicas=1` rend donc le cluster
jaune, car la copie ne peut etre affectee nulle part.

### 2.8 Noeud

Un noeud est une instance OpenSearch, donc ici un processus Java dans un
conteneur Docker. Chaque noeud possede :

- un `node.name` ;
- un identifiant interne persiste dans son volume ;
- une heap Java ;
- des roles ;
- un certificat TLS ;
- un repertoire de donnees qui lui est propre.

### 2.9 Cluster

Un cluster est un groupe de noeuds partageant :

- le meme `cluster.name` ;
- le meme `cluster_uuid` apres formation ;
- un etat de cluster commun ;
- les mappings, templates et index ;
- les informations d'affectation des shards ;
- la configuration du plugin Security.

Un cluster n'est pas un quatrieme conteneur orchestrateur. Les noeuds
OpenSearch s'organisent eux-memes par election et consensus.

### 2.10 Cluster manager

Parmi les noeuds eligibles, un seul est elu cluster manager a un instant donne.
Il maintient l'etat de reference du cluster :

- presence des noeuds ;
- creation et suppression des index ;
- mappings et templates ;
- affectation des shards ;
- changements de configuration.

Il ne transporte pas obligatoirement toutes les requetes des clients. Dans
notre cluster de developpement, chaque noeud a les roles :

```text
cluster_manager,data,ingest,remote_cluster_client
```

Cette valeur est dans `dev/compose/opensearch-cluster/compose.yml`, ligne 9.

### 2.11 Les deux ports importants

```text
9200/tcp : API REST HTTPS pour Logstash, Arkime, Dashboards et l'administration
9300/tcp : transport interne entre les noeuds OpenSearch
```

Ils sont declares dans le Compose du cluster aux lignes 7-8. Le port 9300 ne
doit jamais etre traite comme une API applicative.

### 2.12 Couleurs de sante

```text
green  : tous les shards primaires et replicas sont affectes
yellow : tous les primaires sont affectes, mais des replicas manquent
red    : au moins un shard primaire manque, certaines donnees sont indisponibles
```

`green` ne signifie pas automatiquement que toute l'application Oculox
fonctionne. Cela prouve uniquement l'etat d'affectation des shards du cluster.

## 3. Trajet des donnees Oculox

Le trajet principal est :

```text
capteurs et journaux
        |
        v
Filebeat du Core ou du Hedgehog
        |
        | mTLS Beats, ports 5044 et 5045
        v
Logstash 1 et Logstash 2
        |
        | HTTPS OpenSearch, port 9200
        v
OpenSearch
        |
        +--> OpenSearch Dashboards
        +--> API Oculox
        +--> pcap-monitor
        +--> recherches Arkime
```

Deux PKI differentes interviennent :

```text
PKI Beats      : Filebeat <-> Logstash
PKI OpenSearch : clients <-> OpenSearch et noeud <-> noeud
```

Elles ne doivent pas etre confondues. La creation du cluster OpenSearch ne
remplace pas le mTLS Filebeat/Logstash deja construit.

Arkime et Arkime Live peuvent aussi ecrire directement dans OpenSearch. C'est
pourquoi ils ont besoin de leur propre compte de service OpenSearch.

## 4. OpenSearch mono-noeud existant dans Oculox

### 4.1 Declaration du service

Le service actuel commence dans `docker-compose.yml`, lignes 4-74.

Points importants :

| Lignes | Configuration | Signification |
|---:|---|---|
| 4-6 | service et image | un seul service `opensearch`, image Malcolm 26.07.1 |
| 17-23 | reseau et env files | connexion au reseau Oculox et chargement des variables |
| 24-33 | memlock et capacites | limitation du swap de la heap Java |
| 34-67 | montages | CA, identifiants, donnees, snapshots et keystore |
| 68-73 | healthcheck | verification periodique du conteneur |
| 74 | stop grace period | jusqu'a trois minutes pour un arret propre |

Le stockage est un bind mount :

```text
./opensearch -> /usr/share/opensearch/data
```

Il apparait dans `docker-compose.yml`, lignes 53-57. Si le conteneur est
recree, les donnees restent sur l'hote. Si ce repertoire est supprime, le
cluster mono-noeud perd ses donnees.

### 4.2 Variables de connexion

Le contrat est dans `config/opensearch.env.example`, lignes 1-41 :

```text
OPENSEARCH_PRIMARY=opensearch-local
OPENSEARCH_URL=https://opensearch:9200
OPENSEARCH_CREDS_CONFIG_FILE=/var/local/curlrc/.opensearch.primary.curlrc
OPENSEARCH_SSL_CERTIFICATE_VERIFICATION=false
```

Interpretation :

- `opensearch-local` demande a Oculox d'utiliser son conteneur interne ;
- `opensearch` est le nom DNS du service Docker, pas l'IP de la machine ;
- le fichier `.curlrc` fournit les identifiants aux composants ;
- la verification TLS complete est actuellement desactivee.

Le fichier reel `config/opensearch.env` est genere par l'installateur a partir
du `.example`. Il peut contenir des valeurs differentes selon l'installation.

### 4.3 Heap Java

La valeur par defaut du modele est ligne 41 :

```text
-Xms10g -Xmx10g
```

`Xms` est la heap initiale et `Xmx` la heap maximale. L'installateur peut
modifier ces valeurs. La baseline locale observait `4g`, pas `10g`.

Cela montre une distinction importante :

```text
*.env.example : valeur source ou valeur par defaut du depot
config/*.env  : valeur effective de l'installation courante
```

### 4.4 Pourquoi il reste mono-noeud

`config/opensearch.env.example`, ligne 97 :

```text
discovery.type=single-node
```

OpenSearch ne cherche donc aucun autre noeud. Ce mode convient au service
embarque, mais ne fournit aucune redondance.

### 4.5 Index et replicas actuels

Les motifs d'index sont lignes 43-79. La baseline a mesure :

```text
41 index visibles
43 shards primaires
0 replica
668 179 documents applicatifs
```

Avec zero replica et un seul noeud, une indisponibilite du noeud rend le
stockage entier indisponible.

### 4.6 Compte actuel trop privilegie

La baseline a trouve un seul compte interne :

```text
malcolm_internal
backend role: admin
```

Ce compte commun est utilise pour des besoins differents. Le backend role
`admin` est associe a des droits tres larges. Si un composant est compromis,
ses identifiants donnent davantage de droits que necessaire.

La étape Security du nouveau cluster remplace ce modele par des comptes separes.

### 4.7 Consommateurs reels

Les principaux contrats sont :

| Composant | Fichier et ligne | Utilisation |
|---|---|---|
| Logstash | `logstash/pipelines/output/99_opensearch_output.conf:4` | destination d'indexation |
| Logstash | meme fichier, ligne 5 | verification TLS |
| Arkime | `arkime/etc/config.ini:17` | endpoint OpenSearch |
| Dashboards | `dashboards/opensearch_dashboards.yml:13` | endpoint du backend |
| API | `api/project/config.py:39-44` | credentials, mode et URL |
| pcap-monitor | `shared/bin/pcap_watcher.py:320-337` | URL, curlrc et verification TLS |
| health scripts | `shared/bin/opensearch_status.sh:46-82` | attente et sante du stockage |
| nginx | `nginx/nginx_opensearch_upstream.conf:1-2` | upstream interne actuel |

Le nouveau cluster ne sera reellement integre que lorsque tous ces contrats
auront ete bascules et testes.

## 5. Pourquoi construire un nouveau cluster separe

Les limites du mono-noeud sont :

1. aucune copie replica ;
2. un seul processus de stockage ;
3. un seul compte de service tres privilegie ;
4. certificats generes pour le fonctionnement embarque ;
5. URL Docker locale non utilisable comme endpoint stable externe ;
6. donnees et snapshots sur le meme systeme physique.

La cible de developpement est donc :

```text
                     endpoint futur : 192.168.1.241:9200
                                      |
                                      v
                             proxy de la étape endpoint
                                      |
                     +----------------+----------------+
                     |                |                |
                     v                v                v
              opensearch-1     opensearch-2     opensearch-3
              volume data-1    volume data-2    volume data-3
              172.31.241.2      172.31.241.3      172.31.241.4
```

Le proxy n'existe pas encore. Pour cette raison, les clients Oculox ne doivent
pas encore etre pointes vers `192.168.1.241:9200`.

## 6. Étape d'inventaire : baseline de l'existant

### But

Mesurer l'existant avant toute migration. Sans baseline, il serait impossible
de prouver que tous les index, templates et documents ont ete conserves.

### Fichier produit

```text
dev/docs/Opensearch/inventaire_opensearch_existant.md
```

### Ce qui a ete releve

- version OpenSearch et UUID ;
- consommateurs de `OPENSEARCH_URL` ;
- index, aliases et templates ;
- shards et replicas ;
- comptes et roles ;
- heap et stockage ;
- repository de snapshots ;
- snapshot de preuve et restauration de preuve.

### Resultat majeur

Le mono-noeud etait `green`, mais sans redondance. Un cluster mono-noeud peut
etre vert avec zero replica : cela ne signifie pas qu'il est resilient.

## 7. Étape de préparation hôte : preparation de la VM

### But

Preparer le systeme Linux qui execute les trois JVM OpenSearch.

### Fichier produit

```text
dev/docs/Opensearch/preparation_hote_cluster.md
```

### VM observee

```text
8 vCPU
14 Gio RAM
200 Go disque
Debian 13
Docker 29.7.2
Docker Compose 5.4.0
```

### Pourquoi modifier Linux

OpenSearch utilise beaucoup de fichiers, de memoire verrouillable et de zones
de mapping virtuel. Les principaux reglages sont :

```text
swap desactive
vm.max_map_count=1048576
nofile=65536
memlock=unlimited
```

`vm.max_map_count` doit etre configure sur l'hote, meme avec Docker.

### Heap retenue

```text
2 Gio par noeud
3 noeuds
6 Gio de heap totale
```

Les 8 Gio restantes ne sont pas perdues. Elles servent notamment aux JVM hors
heap, aux conteneurs, au noyau et au cache disque.

### Limite de cette VM

Cette VM convient a l'apprentissage et aux tests fonctionnels. Elle ne permet
pas de conclure au dimensionnement de production.

## 8. Étape d'organisation : organisation du depot

### But

Separer les sources versionnees des secrets et artefacts runtime.

### Repertoires

```text
dev/compose/opensearch-cluster/    orchestration Docker
dev/config/opensearch-cluster/     configuration source sans secret
dev/scripts/opensearch-cluster/    generation et exploitation
dev/tests/opensearch-cluster/      tests statiques et runtime
dev/monitoring/opensearch-cluster/ supervision future
dev/generated/opensearch-cluster/  secrets et rendu local non versionnes
```

### Regle essentielle

`dev/generated/opensearch-cluster/` est ignore par Git, sauf son README et son
`.gitignore`. Les cles et mots de passe ne doivent jamais etre ajoutes avec
`git add -f`.

## 9. Étape de topologie Compose : Compose du cluster vide

### Fichier principal

```text
dev/compose/opensearch-cluster/compose.yml
```

### Configuration commune

Les lignes 3-20 definissent l'environnement commun :

| Ligne | Parametre | Effet |
|---:|---|---|
| 4 | `cluster.name` | les trois noeuds appartiennent a `oculox-opensearch` |
| 5 | `discovery.seed_hosts` | adresses de decouverte permanente |
| 6 | `network.host` | ecoute dans le conteneur |
| 7 | `http.port` | API REST sur 9200 |
| 8 | `transport.port` | communications inter-noeuds sur 9300 |
| 9 | `node.roles` | manager, data, ingest et client remote |
| 10 | `bootstrap.memory_lock` | evite le swap de heap |
| 11 | seuils disque actifs | protege contre le remplissage du disque |
| 12 | skip self-signed | interdit la PKI automatique mono-noeud |
| 13-20 | heap | `Xms=Xmx=2g` par defaut dans ce cluster |

Les lignes 22-67 definissent le comportement commun des conteneurs : image,
entrypoint, restart policy, ulimits, healthcheck et reseau.

### Trois services distincts

```text
opensearch-1 : lignes 70-102
opensearch-2 : lignes 104-136
opensearch-3 : lignes 138-170
```

Chaque service obtient :

- son propre hostname ;
- son propre `node.name` ;
- son adresse de transport stable ;
- son volume de donnees ;
- son certificat et sa cle.

### Volumes

Les lignes 181-187 declarent :

```text
opensearch-data-1
opensearch-data-2
opensearch-data-3
```

Deux noeuds ne partagent jamais un volume. Partager un repertoire de donnees
entre deux processus OpenSearch provoquerait une corruption ou un refus de
demarrage.

### Reseau

Les lignes 172-179 creent :

```text
oculox-opensearch-transport
172.31.241.0/28
internal: true
```

`internal: true` signifie que ce reseau est prive a Docker. Le Compose expose
9200 et 9300 dans le reseau, mais ne les publie pas sur l'interface de la VM.

### Healthcheck

Le healthcheck, lignes 56-67, appelle chaque API HTTPS avec la CA. Il accepte
200, 401 ou 403 : ces codes prouvent que le processus HTTPS repond. Un 401 ne
signifie pas que l'utilisateur est valide ; il signifie ici que le service est
vivant et exige une authentification.

## 10. Étape de découverte : decouverte et amorcage

### Deux notions differentes

```text
decouverte permanente : comment un noeud retrouve les autres
amorcage initial       : comment le tout premier manager est elu
```

### Decouverte permanente

Dans `compose.yml`, ligne 5 :

```text
discovery.seed_hosts=opensearch-1:9300,opensearch-2:9300,opensearch-3:9300
```

Cette liste reste necessaire aux redemarrages et a la reintegration d'un noeud.

### Amorcage initial

Le fichier est :

```text
dev/compose/opensearch-cluster/compose.bootstrap.yml
```

Sa ligne 2 ajoute :

```text
cluster.initial_cluster_manager_nodes=opensearch-1,opensearch-2,opensearch-3
```

Les noms doivent correspondre exactement aux `node.name`.

### Pourquoi le fichier bootstrap est temporaire

Au premier demarrage, les volumes sont vides. Les noeuds n'ont aucun UUID de
cluster et aucune configuration de vote. L'override bootstrap leur indique
quels noeuds peuvent participer a la premiere election.

Apres formation, les volumes conservent :

- le `cluster_uuid` ;
- l'identite de chaque noeud ;
- la configuration de vote ;
- les metadonnees des index.

Les redemarrages utilisent uniquement `compose.yml`. Continuer a injecter
l'amorcage initial serait inutile et dangereux lors d'operations de
reconstruction.

### Correction imposee par l'image Malcolm

L'image Malcolm contient une variable `discovery.type=single-node`. La valeur
`multi-node` n'a pas ete ajoutee : le fonctionnement multi-noeud est le mode
normal lorsque la variable mono-noeud est absente.

Le wrapper :

```text
dev/config/opensearch-cluster/entrypoint-multinode.sh
```

retire cette variable avec `env -u`, lignes 5-9, puis appelle la chaine de
demarrage originale de l'image. Il ne remplace pas OpenSearch lui-meme.

## 11. Étape PKI : PKI et TLS

### Trois problemes a resoudre

1. chiffrer les appels clients sur 9200 ;
2. authentifier et chiffrer les noeuds sur 9300 ;
3. donner une identite super administrateur distincte.

### Autorite de certification

Le script est :

```text
dev/scripts/opensearch-cluster/generate-pki.sh
```

Il cree une CA OpenSearch puis signe cinq identites feuilles distinctes :

```text
opensearch-1
opensearch-2
opensearch-3
endpoint 192.168.1.241
administrateur Security
```

Chaque identite a sa propre cle privee.

### Arborescence generee

```text
dev/generated/opensearch-cluster/pki/
|-- ca/
|-- nodes/opensearch-1/
|-- nodes/opensearch-2/
|-- nodes/opensearch-3/
|-- endpoint/
|-- admin/
`-- client-trust/
```

Cette arborescence n'est pas versionnee.

### SAN

Un SAN est une identite reseau contenue dans un certificat. Les noeuds
annoncent leur IP de transport Docker. Chaque certificat contient donc le nom
et l'IP correspondante :

```text
opensearch-1 : DNS opensearch-1, IP 172.31.241.2
opensearch-2 : DNS opensearch-2, IP 172.31.241.3
opensearch-3 : DNS opensearch-3, IP 172.31.241.4
endpoint     : IP 192.168.1.241
```

Le certificat endpoint sera utilise par le proxy de la étape endpoint. Il n'est pas
le certificat d'un noeud.

### Configuration TLS des noeuds

Le fichier est :

```text
dev/config/opensearch-cluster/opensearch.yml
```

Lecture par blocs :

| Lignes | Fonction |
|---:|---|
| 1-3 | nom du cluster, ecoute et memlock |
| 5-7 | API HTTP 9200 |
| 9-13 | transport 9300 et verification stricte des noms |
| 15-23 | certificat, cle et CA du HTTPS |
| 24-28 | certificat, cle et CA du transport |
| 29-33 | DN autorises comme noeuds |
| 34-36 | DN autorise comme super administrateur |
| 37 | mappings explicites uniquement |

`clientauth_mode: OPTIONAL`, ligne 20, signifie que l'API peut recevoir un
certificat client administrateur, sans imposer un certificat client aux
comptes applicatifs utilisant HTTP Basic. La verification du certificat
serveur par les clients reste obligatoire.

### `nodes_dn`

Les lignes 29-32 listent exactement les identites X.509 acceptees comme noeuds
du cluster. Un conteneur possedant un autre certificat ne peut pas rejoindre le
transport interne.

### `admin_dn`

Les lignes 34-36 declarent le DN du certificat super administrateur. Ce
certificat permet d'initialiser ou modifier Security. Il ne doit jamais etre
copie dans Logstash, Arkime ou Dashboards.

### Neutralisation de l'initialisation automatique

L'image Malcolm est concue pour initialiser seule son Security mono-noeud.
Deux scripts no-op evitent cette action sur chacun des trois noeuds :

```text
dev/config/opensearch-cluster/setup-post-start.sh
dev/config/opensearch-cluster/setup-internal-users.sh
```

Ils quittent avec le code 0. L'initialisation controlee est faite une seule
fois pendant la étape Security.

### Keycloak

Keycloak n'est pas une CA de noeuds OpenSearch et ne remplace pas cette PKI.
Plus tard, Keycloak pourra intervenir pour l'authentification humaine via OIDC
ou SAML, principalement devant Dashboards et les applications. Les certificats
transport des noeuds, le certificat endpoint et le certificat super admin
restent necessaires.

## 12. Premier demarrage reel du cluster

Le premier demarrage a utilise les deux fichiers Compose :

```bash
docker compose \
  --env-file dev/config/opensearch-cluster/cluster.env.example \
  -f dev/compose/opensearch-cluster/compose.yml \
  -f dev/compose/opensearch-cluster/compose.bootstrap.yml \
  up -d
```

Cette commande est une operation d'etat. Elle ne doit pas etre relancee comme
commande de demarrage ordinaire d'un cluster deja forme.

Sequence interne :

1. Docker cree le reseau et les trois volumes ;
2. Docker lance les trois conteneurs ;
3. le wrapper retire `discovery.type=single-node` ;
4. chaque JVM lit `opensearch.yml` et son certificat ;
5. les noeuds se decouvrent sur 9300 ;
6. ils verifient mutuellement CA, SAN et DN ;
7. ils executent la premiere election ;
8. un UUID unique de cluster est cree et persiste ;
9. les healthchecks HTTPS deviennent valides.

Resultat observe :

```text
cluster_uuid : Qia-ZGlDTSyRYduLFlhLLg
noeuds       : 3
etat         : green
```

Les redemarrages ordinaires utilisent seulement :

```bash
docker compose \
  --env-file dev/config/opensearch-cluster/cluster.env.example \
  -f dev/compose/opensearch-cluster/compose.yml \
  up -d
```

## 13. Étape Security : plugin Security

### 13.1 Ce que Security ajoute

TLS repond a : « est-ce bien le serveur attendu et la communication est-elle
chiffree ? »

Security repond ensuite a :

```text
authentification : qui appelle ?
autorisation     : cette identite peut-elle faire cette action ?
```

### 13.2 Backend d'authentification actuel

`dev/config/opensearch-cluster/security/config.yml`, lignes 12-22, active une
base interne et HTTP Basic :

```text
client -> HTTPS -> nom utilisateur/mot de passe -> base interne Security
```

Les lignes 8-11 desactivent l'acces anonyme et la confiance X-Forwarded-For.
Les lignes 23-28 identifient le compte serveur Dashboards et son index interne.

Ce backend interne est une premiere etape. Une federation Keycloak future
pourra ajouter OIDC/SAML pour les personnes sans supprimer les comptes de
service machine.

### 13.3 Utilisateur, backend role et Security role

Ces trois notions sont differentes :

```text
utilisateur    : oculox_logstash
backend role   : oculox_logstash_writer
Security role  : oculox_logstash_writer et role statique logstash
permissions    : ecriture dans les motifs autorises
```

`internal_users.yml` donne un backend role a l'utilisateur.
`roles_mapping.yml` associe ce backend role a un ou plusieurs Security roles.
`roles.yml` definit les permissions du Security role.

### 13.4 Generation des comptes

Le script est :

```text
dev/scripts/opensearch-cluster/generate-security-config.sh
```

Les lignes importantes sont :

| Lignes | Action |
|---:|---|
| 7-8 | sources versionnees et sortie ignoree par Git |
| 54-67 | refus d'ecraser une configuration sans `--force` |
| 69-73 | permissions strictes et copie des YAML |
| 75-83 | liste des sept comptes |
| 98-116 | mot de passe aleatoire, hash bcrypt et utilisateur |
| 118-124 | permissions 0700/0600 |

Le mot de passe clair va dans `accounts.env`, mode 0600. Le fichier
`internal_users.yml` contient le hash bcrypt, pas le mot de passe clair.

### 13.5 Comptes crees

| Compte | Backend role | Usage |
|---|---|---|
| `oculox_platform_admin` | `oculox_platform_admin` | administration fonctionnelle |
| `oculox_logstash` | `oculox_logstash_writer` | Logstash 1 et 2 |
| `oculox_arkime` | `oculox_arkime_service` | Arkime et Arkime Live |
| `oculox_dashboards` | `oculox_dashboards_server` | serveur Dashboards |
| `oculox_dashboards_helper` | `oculox_dashboards_helper` | initialisation des objets |
| `oculox_api` | `oculox_api_reader` | API et pcap-monitor |
| `oculox_snapshot` | `oculox_snapshot_operator` | snapshots et restaurations |

Le compte `malcolm_internal` n'a pas ete importe.

### 13.6 Roles Oculox

Les roles propres a Oculox commencent dans
`dev/config/opensearch-cluster/security/roles.yml`, ligne 653.

#### Logstash, lignes 654-669

```text
surveillance minimale du cluster
creation et CRUD sur arkime_sessions3-*
creation et CRUD sur malcolm_beats_*
aucun acces general aux autres index
```

Le mapping se trouve dans `roles_mapping.yml`, lignes 30-44. Le role statique
OpenSearch `logstash` est egalement associe, car les operations bulk, pipelines
et templates utilisent des actions internes supplementaires.

#### Arkime, lignes 671-685

```text
gestion des motifs arkime_*
gestion des sessions arkime_sessions3-*
templates necessaires a Arkime
```

Arkime ne recoit pas le droit d'ecrire dans `malcolm_beats_*`.

#### dashboards-helper, lignes 687-706

Ce service cree templates, pipelines, objets de plugins, repositories et
snapshots. Son perimetre est plus large que celui du serveur Dashboards, mais
reste separe de l'administration Security.

#### API et pcap-monitor, lignes 708-725

```text
lecture et surveillance des index applicatifs
aucune ecriture de document
```

#### Dashboards

Le serveur utilise le role statique `kibana_server`, associe dans
`roles_mapping.yml`, lignes 14-20. Ce compte technique n'est pas le compte d'un
utilisateur humain.

#### Snapshots

Le backend role `oculox_snapshot_operator` est associe au role statique
`manage_snapshots`, `roles_mapping.yml`, lignes 22-28.

### 13.7 Super administrateur par certificat

Le certificat `oculox-opensearch-admin` est au-dessus des comptes ordinaires
pour l'administration du plugin Security. Il sert a modifier l'index systeme
`.opendistro_security`.

Il faut distinguer :

```text
oculox_platform_admin       : compte courant avec all_access
oculox-opensearch-admin.crt : super admin Security par certificat
```

Le certificat super admin ne doit pas etre distribue aux services.

### 13.8 Initialisation unique

Le script est :

```text
dev/scripts/opensearch-cluster/initialize-security.sh
```

Lecture par blocs :

| Lignes | Action |
|---:|---|
| 67-82 | exige certificat admin et quatre fichiers Security |
| 84-89 | refuse si le marqueur existe |
| 91-101 | verifie reseau et trois noeuds actifs |
| 103-120 | refuse si l'index Security repond deja |
| 122-134 | lance `securityadmin.sh` avec CA, certificat et cle admin |
| 136-139 | verifie que Security repond apres chargement |
| 141-147 | cree un marqueur avec date et hash de configuration |

`securityadmin.sh` charge les YAML dans l'index systeme
`.opendistro_security`. Les fichiers YAML ne sont pas relus automatiquement a
chaque redemarrage.

Une deuxieme execution globale peut ecraser des changements crees ensuite par
l'API. C'est pourquoi le script Oculox protege l'operation initiale.

### 13.9 Ce qui a ete teste

Le test runtime est :

```text
dev/tests/opensearch-cluster/test_security_runtime.sh
```

Il verifie :

- lignes 102-108 : cluster vert, trois noeuds et liste exacte des comptes ;
- lignes 132-134 : Logstash ecrit dans son index et recoit 403 ailleurs ;
- lignes 136-137 : Arkime ecrit dans son index et recoit 403 ailleurs ;
- lignes 139-140 : API lit mais ne peut pas ecrire ;
- lignes 142-143 : Dashboards s'authentifie mais ne peut pas ecrire dans un
  index applicatif ;
- lignes 145-147 : helper et snapshot ont leurs operations autorisees ;
- lignes 149-162 : requete anonyme et CA inconnue refusees ;
- lignes 164-166 : suppression des objets temporaires.

Resultat final :

```text
SECURITY_CONFIG_RESULT=PASS
SECURITY_RUNTIME_RESULT=PASS
```

## 14. Etat actuel exact

### Termine

```text
[x] baseline du mono-noeud
[x] preparation de la VM
[x] organisation du depot
[x] Compose de trois noeuds
[x] decouverte permanente
[x] amorcage initial
[x] cluster UUID unique
[x] cluster green avec trois noeuds
[x] PKI transport et HTTP
[x] verification stricte des certificats de noeuds
[x] comptes et roles Security
[x] tests des permissions et refus
[x] redemarrage sans configuration bootstrap
```

### Pas encore termine

```text
[ ] endpoint proxy stable publie sur 192.168.1.241:9200
[ ] strategie definitive de replicas et templates
[ ] repository de snapshots externe au disque de la VM
[ ] migration des index du mono-noeud
[ ] configuration de chaque client Oculox avec son compte
[ ] distribution de la CA aux Core et Hedgehog
[ ] bascule de OPENSEARCH_PRIMARY vers opensearch-remote
[ ] tests de perte de noeud avec donnees et replicas
[ ] supervision et alertes
[ ] integration Keycloak pour les utilisateurs humains
```

Le nouveau cluster existe, mais Oculox Core et Hedgehog ne l'utilisent pas
encore. Le mono-noeud reste donc la source applicative actuelle.

## 15. Commandes de verification locales sans modifier le cluster

Executer depuis :

```bash
cd /home/kakashi_/ICSHUB/Oculox
```

### 15.1 Voir le Compose rendu

```bash
docker compose \
  --env-file dev/config/opensearch-cluster/cluster.env.example \
  -f dev/compose/opensearch-cluster/compose.yml \
  config
```

Cette commande ne demarre rien. Elle permet de voir les variables resolues.

### 15.2 Verifier la structure des trois noeuds

```bash
./dev/tests/opensearch-cluster/test_compose_structure.py
```

Attendu :

```text
CLUSTER_COMPOSE_RESULT=PASS
```

### 15.3 Verifier decouverte et amorcage

```bash
./dev/tests/opensearch-cluster/test_discovery_config.py
```

Attendu au minimum :

```text
identical_configuration=3/3
DISCOVERY_CONFIG_RESULT=PASS
```

Le test local peut afficher `DISCOVERY_RUNTIME_RESULT=PENDING_FIRST_START`. Cette
mention signifie seulement qu'il ne trouve pas, dans le poste local, le
marqueur runtime du deploiement VM. Elle ne contredit pas la preuve collectee
sur `192.168.1.241`, ou le cluster a deja forme un UUID unique avec trois
noeuds. Les controles runtime de la section 16 restent la source de verite pour
la VM.

### 15.4 Verifier la PKI locale

```bash
./dev/tests/opensearch-cluster/test_pki.py
```

Attendu :

```text
PKI_TEST_RESULT=PASS
```

Ce test lit les certificats locaux. Il n'affiche pas les cles privees.

### 15.5 Verifier les roles sans connexion runtime

```bash
./dev/tests/opensearch-cluster/test_security_config.py
```

Attendu :

```text
SECURITY_CONFIG_RESULT=PASS
```

### 15.6 Verifier qu'aucun secret genere n'est suivi par Git

```bash
git ls-files dev/generated/opensearch-cluster
```

La sortie autorisee doit se limiter au squelette documentaire, par exemple :

```text
dev/generated/opensearch-cluster/.gitignore
dev/generated/opensearch-cluster/README.md
```

Il ne doit jamais apparaitre :

```text
accounts.env
ca.key
node.key
admin.key
endpoint.key
```

## 16. Commandes de verification sur la VM

Se connecter :

```bash
ssh debian@192.168.1.241
cd /opt/oculox/opensearch-cluster
```

### 16.1 Etat des conteneurs

```bash
docker compose \
  -f dev/compose/opensearch-cluster/compose.yml \
  ps
```

Attendu : trois services `Up` et `healthy`.

### 16.2 Verifier les redemarrages

```bash
docker inspect \
  -f '{{.Name}} status={{.State.Status}} health={{.State.Health.Status}} restart={{.RestartCount}}' \
  oculox-opensearch-cluster-opensearch-1-1 \
  oculox-opensearch-cluster-opensearch-2-1 \
  oculox-opensearch-cluster-opensearch-3-1
```

`restart=0` est ideal apres un demarrage propre. Une valeur superieure exige
l'analyse des logs.

### 16.3 Logs des noeuds

```bash
docker compose \
  -f dev/compose/opensearch-cluster/compose.yml \
  logs --tail=100 opensearch-1 opensearch-2 opensearch-3
```

Rechercher les erreurs de formation et TLS :

```bash
docker compose \
  -f dev/compose/opensearch-cluster/compose.yml \
  logs opensearch-1 opensearch-2 opensearch-3 2>&1 |
grep -Ei 'exception|failed|cluster manager not discovered|SSLHandshake|certificate_unknown'
```

Une sortie vide est attendue pour ces motifs critiques apres stabilisation.

### 16.4 Verifier que le bootstrap initial n'est plus injecte

```bash
docker inspect \
  -f '{{range .Config.Env}}{{println .}}{{end}}' \
  oculox-opensearch-cluster-opensearch-1-1 |
grep 'cluster.initial_cluster_manager_nodes'
```

Attendu : aucune sortie sur un redemarrage ordinaire.

### 16.5 Verifier les volumes distincts

```bash
docker volume ls --format '{{.Name}}' |
grep -E '^opensearch-data-[123]$'
```

Attendu : les trois noms.

### 16.6 Verifier le reseau et les IP

```bash
docker network inspect oculox-opensearch-transport \
  --format '{{range .Containers}}{{.Name}} {{.IPv4Address}}{{println}}{{end}}'
```

Attendu :

```text
opensearch-1 ... 172.31.241.2/28
opensearch-2 ... 172.31.241.3/28
opensearch-3 ... 172.31.241.4/28
```

L'ordre des lignes peut changer.

### 16.7 Verifier le marqueur Security

```bash
stat -c '%a %U:%G %n' \
  dev/generated/opensearch-cluster/state/security-initialized
```

Attendu : mode `600`.

## 17. Interroger l'API sans exposer les secrets

L'API n'est pas encore publiee sur l'IP de la VM. Les appels de verification
doivent donc partir du reseau Docker prive ou utiliser un acces administratif
temporaire controle.

### 17.1 Methode recommandee pour un compte de service

Ne placez pas le mot de passe dans l'historique du shell ni dans les arguments
visibles d'un processus. Creez un repertoire temporaire protege :

```bash
AUTH_DIR="$(mktemp -d)"
chmod 700 "${AUTH_DIR}"
trap 'rm -rf -- "${AUTH_DIR}"; unset OS_PASSWORD' EXIT

cp \
  /opt/oculox/opensearch-cluster/dev/generated/opensearch-cluster/pki/nodes/opensearch-1/ca.crt \
  "${AUTH_DIR}/ca.crt"

read -rsp 'Mot de passe oculox_platform_admin: ' OS_PASSWORD
printf '\n'
printf 'cacert = "/auth/ca.crt"\nuser = "oculox_platform_admin:%s"\n' \
  "${OS_PASSWORD}" >"${AUTH_DIR}/request.curlrc"
chmod 600 "${AUTH_DIR}/request.curlrc" "${AUTH_DIR}/ca.crt"
```

Puis, depuis la VM :

```bash
docker run --rm \
  --network oculox-opensearch-transport \
  --entrypoint curl \
  --mount "type=bind,src=${AUTH_DIR},dst=/auth,readonly" \
  ghcr.io/idaholab/malcolm/opensearch:26.07.1 \
  --config /auth/request.curlrc \
  --silent --show-error \
  'https://opensearch-1:9200/_cluster/health?pretty'
```

Nettoyer immediatement apres les verifications :

```bash
rm -rf -- "${AUTH_DIR}"
unset AUTH_DIR OS_PASSWORD
trap - EXIT
```

### 17.2 Resultat de sante attendu

```json
{
  "cluster_name": "oculox-opensearch",
  "status": "green",
  "number_of_nodes": 3,
  "number_of_data_nodes": 3,
  "unassigned_shards": 0
}
```

### 17.3 Lister les noeuds et identifier le manager

Reprendre la meme commande Docker et remplacer l'URL par :

```text
https://opensearch-1:9200/_cat/nodes?v&h=name,ip,node.role,cluster_manager
```

Attendu : trois lignes et un seul `*` dans la colonne `cluster_manager`.

### 17.4 Verifier l'UUID

URL :

```text
https://opensearch-1:9200/
```

Attendu :

```text
cluster_name = oculox-opensearch
cluster_uuid = Qia-ZGlDTSyRYduLFlhLLg
```

### 17.5 Lister les shards

URL :

```text
https://opensearch-1:9200/_cat/shards?v
```

Verifier qu'aucune ligne n'a l'etat `UNASSIGNED`.

### 17.6 Verifier le refus anonyme

Sans `--user` mais avec la bonne CA :

```text
HTTP 401 attendu
```

### 17.7 Verifier le refus d'une CA inconnue

Sans `--cacert` et sans contournement `-k` :

```text
curl doit echouer pendant la verification TLS
```

Ne pas utiliser `-k` pour declarer un test TLS reussi. `-k` desactive
precisement la verification que l'on cherche a prouver.

## 18. Tests Security complets

Le test runtime a besoin de trois entrees temporaires :

```text
accounts.env
repertoire admin contenant admin.crt, admin.key et ca.crt
copie cliente de la CA
```

Commande :

```bash
./dev/tests/opensearch-cluster/test_security_runtime.sh \
  --accounts-env /chemin/temporaire/accounts.env \
  --admin-dir /chemin/temporaire/admin \
  --ca /chemin/temporaire/oculox-opensearch-ca.crt
```

Le test cree des index et un template de test, verifie les autorisations et
les supprime. Il modifie donc temporairement l'etat du cluster. Il ne faut pas
le lancer avec des chemins inventes ni conserver les secrets sur la VM.

Attendu :

```text
cluster_three_nodes_green=PASS
security_accounts_exact_set=PASS
logstash_write_allowed=PASS
logstash_out_of_role_denied=PASS http=403
arkime_out_of_role_denied=PASS http=403
api_write_denied=PASS http=403
anonymous_denied=PASS http=401
untrusted_ca_denied=PASS
SECURITY_RUNTIME_RESULT=PASS
```

## 19. Commandes a ne pas utiliser sans comprendre leur effet

### Ne pas supprimer les volumes

```bash
docker compose down -v
docker volume rm opensearch-data-1 opensearch-data-2 opensearch-data-3
```

Ces commandes suppriment l'etat du cluster et ses donnees.

### Ne pas reamorcer un cluster existant par habitude

Ne pas ajouter automatiquement `compose.bootstrap.yml` a tous les demarrages.

### Ne pas regenerer la PKI avec `--force`

Une rotation de CA rend les certificats actuels et les magasins de confiance
clients incompatibles tant que le redeploiement coordonne n'est pas termine.

### Ne pas relancer globalement `securityadmin.sh`

Il peut ecraser des utilisateurs ou roles ajoutes ensuite par l'API. Faire une
sauvegarde Security et charger uniquement le type necessaire lors des futures
modifications.

### Ne jamais valider TLS avec `curl -k`

`-k` est utile pour diagnostiquer une connectivite, mais ne prouve aucune
confiance cryptographique.

## 20. Comment lire les principaux resultats

| Observation | Interpretation correcte |
|---|---|
| conteneur `Up` | processus lance, pas necessairement cluster sain |
| conteneur `healthy` | healthcheck HTTPS reussi |
| cluster `green` | primaires et replicas affectes |
| trois noeuds dans `_cat/nodes` | formation multi-noeud reussie |
| un seul UUID | tous les noeuds appartiennent au meme cluster |
| un seul manager `*` | election coherente |
| HTTP 200 | requete autorisee et traitee |
| HTTP 401 | identifiants absents ou invalides |
| HTTP 403 | identite reconnue mais action interdite |
| erreur TLS curl 60 | CA non reconnue ou chaine invalide |
| `connection refused` | aucun service n'ecoute sur l'adresse/port |
| timeout | filtrage, routage ou service bloque |

## 21. Carte des fichiers crees jusqu'a la étape Security

| Fichier | Role |
|---|---|
| `dev/compose/opensearch-cluster/compose.yml` | trois noeuds et ressources permanentes |
| `dev/compose/opensearch-cluster/compose.bootstrap.yml` | premiere election uniquement |
| `dev/config/opensearch-cluster/cluster.env.example` | valeurs de deploiement non secretes |
| `dev/config/opensearch-cluster/opensearch.yml` | TLS, ports et DN Security |
| `dev/config/opensearch-cluster/entrypoint-multinode.sh` | retire le mode mono-noeud de l'image |
| `dev/config/opensearch-cluster/setup-post-start.sh` | neutralise l'initialisation automatique |
| `dev/config/opensearch-cluster/setup-internal-users.sh` | neutralise les comptes mono-noeud automatiques |
| `dev/config/opensearch-cluster/security/config.yml` | domaine d'authentification |
| `dev/config/opensearch-cluster/security/roles.yml` | permissions des roles |
| `dev/config/opensearch-cluster/security/roles_mapping.yml` | associations backend roles -> roles |
| `dev/scripts/opensearch-cluster/generate-pki.sh` | genere CA et certificats |
| `dev/scripts/opensearch-cluster/generate-security-config.sh` | genere comptes et hashes |
| `dev/scripts/opensearch-cluster/initialize-security.sh` | charge Security une seule fois |
| `dev/tests/opensearch-cluster/test_compose_structure.py` | preuve structurelle étape de topologie Compose |
| `dev/tests/opensearch-cluster/test_discovery_config.py` | preuve decouverte/amorcage étape de découverte |
| `dev/tests/opensearch-cluster/test_pki.py` | preuve PKI étape PKI |
| `dev/tests/opensearch-cluster/test_security_config.py` | preuve Security statique étape Security |
| `dev/tests/opensearch-cluster/test_security_runtime.sh` | preuve reelle des droits étape Security |

## 22. Sources officielles a connaitre

- [Installation OpenSearch avec Docker](https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker/)
- [Configuration des noeuds et de leurs roles](https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/configuration-system/)
- [Decouverte et formation du cluster](https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/)
- [Amorcage initial](https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/bootstrapping/)
- [Parametres de decouverte](https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/settings/)
- [Sante du cluster](https://docs.opensearch.org/latest/opensearch/rest-api/cluster-health/)
- [Configuration TLS](https://docs.opensearch.org/latest/security/configuration/tls/)
- [Utilisateurs et roles](https://docs.opensearch.org/latest/security/access-control/users-roles/)
- [Configuration YAML Security](https://docs.opensearch.org/latest/security/configuration/yaml/)
- [Utilisation de securityadmin.sh](https://docs.opensearch.org/latest/security/configuration/security-admin/)
- [Snapshots et restauration](https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/snapshot-restore/)

## 23. Parcours d'apprentissage recommande avant la étape endpoint

1. Lire les sections 2 a 4 et savoir expliquer document, index, shard, replica,
   noeud et cluster.
2. Ouvrir `docker-compose.yml` et retrouver le mono-noeud lignes 4-74.
3. Ouvrir `config/opensearch.env.example` et retrouver URL, heap, motifs
   d'index et `single-node`.
4. Comparer avec `dev/compose/opensearch-cluster/compose.yml`.
5. Executer les quatre tests statiques de la section 15.
6. Sur la VM, verifier conteneurs, reseau, volumes et absence de bootstrap.
7. Interroger `_cluster/health`, `_cat/nodes` et `_cat/shards` avec une
   identite autorisee.
8. Lire les quatre roles Oculox dans `roles.yml`, lignes 653-725.
9. Lire les mappings dans `roles_mapping.yml`, lignes 6-116.
10. Ne commencer la étape endpoint qu'une fois capable d'expliquer pourquoi 9200 sera
    publie par un endpoint stable et pourquoi 9300 doit rester prive.

## 24. Suite du guide

La construction realisee apres Security, depuis l'endpoint haute disponibilite
jusqu'a la validation d'ingestion, est expliquee dans :

```text
dev/docs/Opensearch/01_guide_exploitation_cluster_et_integration_oculox.md
```

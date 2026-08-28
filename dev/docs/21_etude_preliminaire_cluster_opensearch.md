# Etude preliminaire : cluster OpenSearch pour Oculox

## 1. Objet du document

Cette etude rassemble les informations necessaires avant de definir le plan de clusterisation OpenSearch d'Oculox.

Aucune architecture n'est encore implementee. Le but est de comprendre :

- ce que Malcolm fournit officiellement ;
- ce que Malcolm ne prend pas en charge ;
- le fonctionnement d'un cluster OpenSearch ;
- les ecarts entre le depot Oculox actuel et une cible a trois noeuds ;
- les decisions a prendre avant de commencer le developpement.

## 2. Position officielle de Malcolm

Malcolm utilise par defaut un unique conteneur OpenSearch local. Sa configuration contient actuellement :

```text
OPENSEARCH_PRIMARY=opensearch-local
OPENSEARCH_URL=https://opensearch:9200
discovery.type=single-node
```

La documentation officielle precise que la creation des clusters OpenSearch multi-noeuds est hors du perimetre de Malcolm, car les architectures possibles sont trop nombreuses.

En revanche, Malcolm sait utiliser un cluster OpenSearch deja construit en choisissant :

```text
OPENSEARCH_PRIMARY=opensearch-remote
OPENSEARCH_URL=https://adresse-stable-du-cluster:9200
```

Conclusion : Oculox doit construire et exploiter la couche cluster OpenSearch. Malcolm doit ensuite la consommer comme un stockage OpenSearch distant.

Source officielle :

- https://idaholab.github.io/Malcolm/docs/opensearch-instances.html

## 3. Services Oculox qui utilisent OpenSearch

La clusterisation ne concerne pas uniquement Logstash.

Les composants suivants utilisent `OPENSEARCH_URL` :

- les deux Logstash pour indexer les evenements ;
- Arkime Capture pour ecrire directement les metadonnees de sessions ;
- Arkime Viewer pour rechercher les sessions ;
- OpenSearch Dashboards pour les recherches et visualisations ;
- dashboards-helper pour les templates, alertes et objets partages ;
- pcap-monitor et plusieurs scripts de maintenance ;
- l'API Oculox et le proxy Nginx pour certaines consultations.

Il faut donc fournir une adresse stable unique qui reste disponible lorsqu'un noeud OpenSearch tombe. Changer uniquement la sortie Logstash serait incomplet.

## 4. Notions fondamentales

### 4.1 Noeud

Un noeud est une instance OpenSearch avec :

- un nom unique ;
- des roles ;
- une JVM et une heap ;
- un repertoire de donnees propre ;
- un certificat de noeud propre ;
- une connexion transport aux autres noeuds sur le port `9300`.

### 4.2 Cluster manager

Le cluster manager maintient l'etat global du cluster : noeuds, index, mappings et affectation des shards.

Les noeuds eligibles elisent un cluster manager. Une majorite doit rester disponible pour modifier l'etat du cluster.

Avec trois noeuds eligibles :

```text
majorite requise = 2
perte toleree = 1 noeud
```

Avec seulement deux noeuds eligibles, aucune panne de noeud n'est tolerable, car les deux sont necessaires pour conserver une majorite.

Source officielle :

- https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/voting-quorums/

### 4.3 Shard primaire et replica

Un index est decoupe en shards primaires. Un replica est une copie d'un shard primaire placee sur un autre noeud.

Avec `number_of_replicas: 0`, la perte du noeud qui contient un shard peut rendre les donnees indisponibles.

Avec `number_of_replicas: 1`, chaque shard possede une copie. Un cluster de trois noeuds peut alors continuer a servir les donnees apres la perte d'un noeud, sous reserve d'avoir assez de disque, de CPU et de memoire sur les noeuds restants.

La replication double approximativement le stockage necessaire pour les shards concernes.

### 4.4 Endpoint stable

Les clients Malcolm utilisent principalement une variable `OPENSEARCH_URL`. Ils ne gerent donc pas tous une liste explicite de trois adresses.

Il faut leur presenter un endpoint stable, par exemple :

```text
https://opensearch-cluster:9200
```

Cet endpoint peut etre porte par un proxy interne avec verification de sante, ou par un service d'orchestration capable de distribuer les connexions vers les noeuds sains.

OpenSearch sait coordonner une requete recue par n'importe quel noeud, mais l'adresse cliente doit elle-meme survivre a la perte d'un noeud.

## 5. Formation initiale du cluster

La configuration actuelle `discovery.type=single-node` doit disparaitre dans le mode cluster.

Un nouveau cluster a besoin au minimum de :

```yaml
cluster.name: oculox-opensearch
node.name: opensearch-1
discovery.seed_hosts:
  - opensearch-1:9300
  - opensearch-2:9300
  - opensearch-3:9300
cluster.initial_cluster_manager_nodes:
  - opensearch-1
  - opensearch-2
  - opensearch-3
```

Les noms de `cluster.initial_cluster_manager_nodes` doivent correspondre exactement aux valeurs `node.name`.

Ce parametre sert uniquement au premier demarrage d'un cluster neuf. Les noeuds conservent ensuite l'identite et l'etat du cluster dans leurs repertoires de donnees.

Chaque noeud doit utiliser un volume de donnees different. Deux noeuds ne doivent jamais partager le meme repertoire `/usr/share/opensearch/data`.

Sources officielles :

- https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/settings/
- https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/bootstrapping/
- https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/discovery/

## 6. Roles envisages pour trois noeuds

Pour un petit cluster de trois noeuds, le modele le plus simple consiste a donner aux trois noeuds les roles cluster manager et data. Chaque noeud peut egalement assurer la coordination et l'ingestion native.

Ce modele permet de perdre un noeud tout en conservant :

- deux votants sur trois ;
- les shards primaires ou replicas ;
- une capacite de lecture et d'ecriture reduite mais disponible.

Des cluster managers dedies sont utiles pour les clusters plus grands, mais trois managers dedies necessiteraient aussi plusieurs noeuds data. Ce serait une architecture d'au moins cinq ou six noeuds, pas une cible de trois noeuds.

Source officielle :

- https://docs.opensearch.org/latest/tuning-your-cluster/

## 7. TLS et identite des noeuds

OpenSearch distingue deux couches TLS :

1. TLS HTTP sur le port `9200`, entre les clients et le cluster ;
2. TLS transport sur le port `9300`, entre les noeuds OpenSearch.

Le TLS transport est obligatoire lorsque le plugin Security est actif.

Les trois noeuds doivent partager la meme autorite de certification, mais chaque noeud doit posseder une cle et un certificat propres avec un SAN correspondant a son nom DNS.

Il faut egalement un certificat administrateur distinct pour initialiser et administrer le plugin Security.

Tous les noeuds doivent reconnaitre les DN des certificats de noeuds, par `plugins.security.nodes_dn` ou par une methode SAN/OID prise en charge.

### Ecart avec l'image Malcolm actuelle

L'image Malcolm genere automatiquement, dans chaque conteneur, une CA et un certificat nomme `opensearch-node`. Ce comportement convient au mono-noeud.

Si trois conteneurs generent chacun leur propre CA, ils ne peuvent pas etablir une confiance transport commune.

Le mode cluster devra donc :

- generer la PKI du cluster avant le demarrage ;
- monter la CA commune et le certificat propre a chaque noeud ;
- activer `OPENSEARCH_SKIP_SELF_SIGNED_KEY_GEN=true` ;
- definir correctement `nodes_dn` et `admin_dn` ;
- initialiser la configuration Security une seule fois de maniere controlee.

Source officielle :

- https://docs.opensearch.org/latest/security/configuration/tls/

## 8. Replication des index Malcolm et Arkime

La configuration mono-noeud actuelle utilise par defaut zero replica :

```text
OPENSEARCH_DEFAULT_REPLICA_COUNT=0
INDEX_MANAGEMENT_OLDER_SESSION_REPLICAS=0
ARKIME_INIT_REPLICAS=
```

Cette configuration annule une grande partie du benefice d'un cluster de trois noeuds.

Pour tolerer la perte d'un noeud, les templates et index actifs devront utiliser au minimum un replica. Il faudra traiter ensemble :

- le nombre de replicas par defaut du cluster ;
- les templates `arkime_sessions3-*` ;
- les templates `malcolm_beats_*` ;
- les index Arkime historiques ;
- les index systeme et Dashboards ;
- les politiques de gestion des index.

Le nombre de shards primaires ne doit pas etre choisi arbitrairement. Trop de petits shards consomment de la heap et du CPU; trop peu de gros shards limitent le parallelisme et ralentissent les recuperations.

## 9. Stockage et protection disque

Chaque noeud doit disposer de son propre stockage persistant rapide, idealement SSD ou NVMe.

La configuration Malcolm actuelle contient :

```text
cluster.routing.allocation.disk.threshold_enabled=false
```

Cette desactivation est dangereuse pour une cible resiliente : OpenSearch ne peut plus proteger correctement le cluster lorsque les disques approchent de la saturation.

Le mode cluster devra reactiver les seuils disque et definir des watermarks adaptes. Il faudra aussi superviser :

- l'espace libre de chaque noeud ;
- l'affectation et la relocalisation des shards ;
- les shards non affectes ;
- le temps de recuperation apres panne ;
- les blocages d'index en lecture seule.

Un disque ou volume unique partage par les trois conteneurs serait un point de panne commun et ne constituerait pas une resilience de stockage.

## 10. Memoire, CPU et parametres de l'hote

OpenSearch recommande une heap proche de la moitie de la memoire disponible pour le processus, en conservant le reste pour le cache du systeme de fichiers.

Les valeurs minimales de l'hote incluent notamment :

```text
vm.max_map_count >= 262144
swap desactivee ou strictement maitrisee
memlock actif
```

Les trois JVM ne doivent pas recevoir chacune la heap de l'ancien noeud unique. La somme des heaps, des memoires hors heap, du cache disque, des deux Logstash et des autres services doit rester inferieure a la RAM physique.

Sources officielles :

- https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker
- https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/configuration-system/

## 11. Cluster local et resilience reelle

Trois conteneurs sur une seule machine permettent de tester :

- la formation du cluster ;
- l'election du cluster manager ;
- la replication des shards ;
- la perte et le retour d'un conteneur ;
- le routage des clients vers les noeuds restants ;
- les procedures de mise a jour progressive.

Ils ne protegent pas contre :

- la perte de la VM ;
- la panne physique de l'hote ;
- la perte du disque commun ;
- une saturation globale de RAM ou CPU ;
- une panne du reseau de l'hote.

Le developpement local validera donc la logique logicielle. Une resilience d'infrastructure exige ensuite trois machines ou VM reparties sur des domaines de panne differents.

## 12. Sauvegardes et migration

La presence d'un replica ne remplace pas une sauvegarde. Une suppression logique, une corruption ou une erreur d'administration peut etre repliquee sur tous les noeuds.

OpenSearch recommande les snapshots pour :

- restaurer apres incident ;
- migrer d'un cluster mono-noeud vers un nouveau cluster ;
- disposer d'un point de retour avant une mise a jour.

Le repository de snapshots doit etre externe aux volumes de donnees des noeuds. Pour un repository fichier, tous les noeuds doivent acceder au meme stockage partage. Un stockage objet est preferable lorsque l'infrastructure le permet.

Pour migrer l'OpenSearch Oculox existant :

1. verifier la sante du mono-noeud ;
2. prendre et valider un snapshot ;
3. construire un cluster neuf ;
4. restaurer et verifier les index ;
5. tester Malcolm, Arkime et Dashboards ;
6. basculer l'endpoint client ;
7. conserver temporairement la source pour permettre un retour arriere.

Sources officielles :

- https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/
- https://docs.opensearch.org/latest/migrate-or-upgrade/snapshot-restore/
- https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/snapshot-management/

## 13. Supervision minimale du futur cluster

Les tests devront verifier au minimum :

```text
GET /
GET /_cluster/health
GET /_cat/nodes?v
GET /_cat/shards?v
GET /_cluster/pending_tasks
GET /_nodes/stats
GET /_cat/allocation?v
```

Les criteres principaux seront :

- un seul `cluster_uuid` ;
- trois noeuds presents ;
- un cluster manager elu ;
- etat `green` avant les tests ;
- zero shard non affecte ;
- replicas places sur un autre noeud que leur primaire ;
- poursuite des lectures et ecritures apres la perte d'un noeud ;
- retour a `green` apres reintegration ;
- aucune duplication ou perte de documents lors des basculements.

## 14. Ecarts techniques identifies dans Oculox

Avant toute implementation, il faudra traiter explicitement :

1. `discovery.type=single-node` dans l'image et `opensearch.env` ;
2. un seul service `opensearch` dans Compose ;
3. un seul repertoire de donnees `./opensearch` ;
4. la generation automatique d'une PKI independante par conteneur ;
5. le DN unique `CN=opensearch-node` prevu pour le mono-noeud ;
6. l'initialisation Security et `setup-post-start.sh` lancees par chaque conteneur ;
7. les replicas a zero dans la configuration actuelle ;
8. les seuils de protection disque desactives ;
9. l'URL OpenSearch unique consommee par tous les composants ;
10. le healthcheck actuellement pense pour un seul service ;
11. les scripts `start`, `restart`, `status`, installation et nettoyage ;
12. la migration des donnees mono-noeud existantes ;
13. les snapshots partages et leur restauration ;
14. les tests de panne, quorum, replication et reintegration.

## 15. Decisions a prendre avant le plan

Les decisions suivantes devront etre validees avant de decouper les phases de developpement :

1. La cible initiale est-elle trois conteneurs locaux de developpement, avec une cible de production multi-VM separee ?
2. Les trois noeuds auront-ils tous les roles cluster manager et data ?
3. Quel composant fournira l'endpoint stable aux clients Malcolm ?
4. Quelle PKI emettra les certificats HTTP, transport et administrateur ?
5. Quel nombre de replicas et quelle strategie de shards appliquer aux index Malcolm et Arkime ?
6. Quelle RAM et quelle heap attribuer a chaque noeud dans l'environnement local puis serveur ?
7. Quel stockage sera utilise pour les donnees de chaque noeud et pour les snapshots ?
8. Le premier prototype partira-t-il d'un cluster vide ou devra-t-il restaurer les donnees locales existantes ?
9. Quel niveau d'interruption est acceptable pendant la migration finale ?

Ces reponses permettront ensuite de produire un plan de developpement progressif, testable et documente, comme cela a ete fait pour les deux Logstash.

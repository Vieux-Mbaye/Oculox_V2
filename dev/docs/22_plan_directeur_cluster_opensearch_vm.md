# Plan directeur : cluster OpenSearch Oculox sur une VM dediee

## 1. Objectif

Construire un cluster OpenSearch de trois noeuds Docker sur une VM dediee, puis configurer Oculox Core pour utiliser ce cluster comme stockage primaire distant.

Le projet doit aboutir a une installation :

- securisee par TLS ;
- reproductible depuis le depot Git ;
- persistante apres redemarrage ;
- tolerante a la perte d'un conteneur OpenSearch ;
- observable et testable ;
- compatible avec Logstash, Arkime, Dashboards et les autres composants Oculox ;
- preparatoire a un futur deploiement sur trois VM distinctes.

## 2. Limite de resilience

Les trois noeuds seront places sur une seule VM.

Cette architecture protege contre :

- le crash d'un processus OpenSearch ;
- l'arret d'un conteneur ;
- la perte temporaire d'un noeud du cluster ;
- le remplacement et la reintegration d'un conteneur.

Elle ne protege pas contre :

- la panne de la VM ;
- la panne de l'hyperviseur ;
- la perte du stockage physique ;
- la saturation globale de la RAM ou du CPU ;
- la perte du reseau de la VM.

La haute disponibilite d'infrastructure necessitera ensuite trois VM reparties sur des domaines de panne differents.

## 3. Architecture cible

```text
VM Collecteur
  Zeek / Suricata / Arkime
  Filebeat avec load balancing
               |
               v
VM Oculox Core
  Logstash 1 + Logstash 2
  Dashboards / Arkime Viewer / API
  aucun OpenSearch local actif
               |
               v
https://192.168.1.241:9200
               |
               v
VM OpenSearch dediee
  Endpoint stable / proxy
  OpenSearch 1 + volume data-1
  OpenSearch 2 + volume data-2
  OpenSearch 3 + volume data-3
  Repository de snapshots
```

## 4. Repartition des responsabilites

### 4.1 Docker Compose

Docker Compose :

- cree le reseau Docker ;
- cree et demarre les conteneurs ;
- monte les volumes ;
- injecte les configurations ;
- applique les healthchecks ;
- arrete et recree les services.

Docker Compose ne gere ni les shards, ni les replicas, ni l'election du cluster manager.

### 4.2 Endpoint stable

Un proxy interne expose une seule URL. Pour la VM de developpement actuelle :

```text
https://192.168.1.241:9200
```

Cette valeur doit rester un parametre de deploiement et ne doit pas etre codee
en dur dans les fichiers Compose ou les scripts. Un futur deploiement pourra la
remplacer par une autre IP ou par un nom DNS sans modifier l'architecture.

Il verifie la disponibilite des trois noeuds et dirige les connexions vers un noeud sain. Il ne connait pas la repartition des shards.

### 4.3 Noeuds OpenSearch

Les trois conteneurs sont :

```text
opensearch-1
opensearch-2
opensearch-3
```

Chaque noeud possede les roles :

```text
cluster_manager
data
ingest
```

Chaque noeud peut egalement coordonner une requete. Les trois sont eligibles au role de cluster manager, mais un seul est elu a un instant donne.

### 4.4 Quorum

Avec trois noeuds eligibles :

```text
majorite requise = 2 noeuds
perte toleree = 1 noeud
```

Si le cluster manager actif tombe, les deux noeuds restants elisent un nouveau responsable.

## 5. Principe d'installation

Le cluster OpenSearch doit etre completement construit et valide avant de modifier Oculox Core.

Ordre obligatoire :

1. preparer la VM OpenSearch ;
2. construire les trois noeuds ;
3. configurer la PKI et la securite ;
4. amorcer et tester le cluster ;
5. creer l'endpoint stable ;
6. configurer les replicas et les snapshots ;
7. configurer Oculox comme client distant ;
8. tester la chaine complete.

Le script interactif Malcolm ne construit pas le cluster. Il sera execute une seule fois sur Oculox Core pour selectionner `opensearch-remote` et renseigner l'endpoint stable.

## 6. Étape 1 - Baseline de l'existant

### But

Connaitre tous les contrats entre Oculox et son OpenSearch mono-noeud actuel.

### Travaux

- inventorier les consommateurs de `OPENSEARCH_URL` ;
- relever les index, aliases, templates et politiques ;
- relever les shards et replicas ;
- relever les utilisateurs et roles ;
- relever les certificats et autorites de certification ;
- relever la heap, le CPU, la RAM et le disque ;
- compter les documents importants ;
- verifier les snapshots actuels ;
- identifier les valeurs generees par l'installeur interactif.

### Preuves attendues

- cluster mono-noeud sain ;
- liste des index et templates exportee ;
- nombre de documents de reference ;
- snapshot testable ;
- liste complete des composants clients.

### Baseline validee

La baseline de reference est documentee dans :

```text
dev/docs/Opensearch/inventaire_opensearch_existant.md
```

Valeurs de comparaison a conserver pour la migration :

```text
version OpenSearch             : 3.7.0
image                          : ghcr.io/idaholab/malcolm/opensearch:26.07.1
documents applicatifs          : 668179
sessions Arkime                : 657306
snapshot de preuve             : baseline-opensearch-20260810
documents restaures / attendus : 33679 / 33679
```

La baseline a egalement confirme les ecarts a corriger dans la cible : aucun
replica, verification TLS desactivee, certificats sans SAN, droits excessifs du
compte de service, protections disque desactivees, aucune politique ISM active
et snapshots places sur le meme hote que les donnees.

## 7. Étape 2 - Preparation de la VM OpenSearch

### Prerequis recommandes

```text
CPU       : 16 a 24 vCPU
RAM       : 32 a 64 Go
Disque    : 500 Go a 1 To SSD/NVMe
Reseau    : 10 Gbit/s si disponible
Systeme   : Linux supporte, Docker et Compose
Temps     : NTP actif
Endpoint  : adresse IP reservee/statique, ou nom DNS si disponible
```

### Parametres systeme

```text
vm.max_map_count >= 262144
swap desactivee ou strictement maitrisee
memlock illimite
limites de fichiers adaptees
```

### Heap initiale

Pour une VM de 64 Go, commencer avec trois heaps de 8 Go. Pour une VM de 32 Go, commencer avec trois heaps de 4 Go.

Ces valeurs seront ajustees apres mesure. La somme des heaps ne doit pas consommer toute la RAM, car OpenSearch utilise aussi la memoire hors heap et le cache disque Linux.

### VM de developpement preparee

La VM `192.168.1.241` preparee pour le developpement possede 8 vCPU, 14 Gio de
RAM et 200 Go de disque. Elle utilisera initialement trois heaps de 2 Gio. Cette
exception permet les validations fonctionnelles, mais pas les benchmarks ni le
dimensionnement de production.

Les preuves de preparation sont consignees dans :

```text
dev/docs/Opensearch/preparation_hote_cluster.md
```

## 8. Étape 3 - Organisation du depot

Conserver les fichiers Malcolm d'origine et ajouter une couche Oculox dediee :

```text
dev/
├── compose/
│   └── opensearch-cluster/
├── config/
│   └── opensearch-cluster/
├── generated/
│   └── opensearch-cluster/
├── scripts/
│   └── opensearch-cluster/
├── tests/
│   └── opensearch-cluster/
└── monitoring/
    └── opensearch-cluster/
```

Les cles privees, mots de passe, donnees, snapshots et fichiers runtime ne doivent pas etre versionnes.

## 9. Étape 4 - Compose du cluster vide

Creer trois services OpenSearch avec la meme version que la plateforme Oculox.

Chaque noeud doit posseder :

- un `node.name` unique ;
- un hostname unique ;
- une heap explicite ;
- un volume de donnees distinct ;
- un healthcheck ;
- une limite de redemarrage maitrisee ;
- un acces au reseau transport prive sur `9300` ;
- un acces HTTP securise sur `9200`.

Volumes attendus :

```text
opensearch-data-1
opensearch-data-2
opensearch-data-3
```

Deux noeuds ne doivent jamais partager le meme repertoire de donnees OpenSearch.

### Implementation validee

Le Compose structurel et son test sont disponibles dans :

```text
dev/compose/opensearch-cluster/compose.yml
dev/config/opensearch-cluster/cluster.env.example
dev/tests/opensearch-cluster/test_compose_structure.py
```

Les preuves sont consignees dans
`dev/docs/Opensearch/topologie_compose_cluster.md`. Aucun noeud n'est
encore demarre, car la decouverte et la PKI appartiennent aux phases suivantes.

## 10. Étape 5 - Decouverte et amorcage

Supprimer le mode :

```text
discovery.type=single-node
```

Configurer :

```yaml
cluster.name: oculox-opensearch
discovery.seed_hosts:
  - opensearch-1:9300
  - opensearch-2:9300
  - opensearch-3:9300
cluster.initial_cluster_manager_nodes:
  - opensearch-1
  - opensearch-2
  - opensearch-3
```

La liste initiale doit etre identique sur les trois noeuds. Les noms doivent correspondre exactement aux `node.name`.

La decouverte permanente est placee dans `compose.yml`. La liste
`cluster.initial_cluster_manager_nodes` est placee dans
`compose.bootstrap.yml`, charge uniquement au premier demarrage lorsque les
trois volumes sont vides.

Implementation et test statique :

```text
dev/compose/opensearch-cluster/compose.yml
dev/compose/opensearch-cluster/compose.bootstrap.yml
dev/tests/opensearch-cluster/test_discovery_config.py
```

Les preuves statiques sont validees dans
`dev/docs/Opensearch/decouverte_et_amorcage.md`. Les preuves runtime
seront collectees apres la étape 6, car le transport OpenSearch doit etre
securise avant le premier demarrage.

### Preuves attendues

```text
un seul cluster_uuid
trois noeuds presents
un cluster manager elu
cluster green
zero shard non affecte
```

## 11. Étape 6 - PKI OpenSearch

Creer avant le premier demarrage :

```text
une CA commune au cluster
un certificat transport pour opensearch-1
un certificat transport pour opensearch-2
un certificat transport pour opensearch-3
un certificat HTTP pour l'endpoint stable
un certificat administrateur
```

Chaque noeud doit posseder une cle privee differente et des SAN correspondant a
son nom DNS interne Docker et a son IP transport privee stable. OpenSearch
annonce cette IP aux autres noeuds lors de la connexion transport.

Le certificat HTTP de l'endpoint doit contenir l'identite utilisee par les
clients dans ses SAN. Pour la VM de developpement, il doit contenir
`IP:192.168.1.241`. Si un DNS est introduit plus tard, un nouveau certificat
contenant ce nom DNS sera emis.
La CA OpenSearch doit etre distribuee explicitement aux magasins de confiance
de tous les clients Oculox Core et Hedgehog. La PKI Beats existante reste
distincte de la PKI OpenSearch.

Configurer separement :

- TLS HTTP sur `9200` ;
- TLS transport sur `9300` ;
- `plugins.security.nodes_dn` ;
- `plugins.security.authcz.admin_dn`.

Desactiver la generation mono-noeud automatique avec :

```text
OPENSEARCH_SKIP_SELF_SIGNED_KEY_GEN=true
```

La verification TLS des clients doit etre activee. Aucun client ne doit rester
avec `OPENSEARCH_SSL_CERTIFICATE_VERIFICATION=false` apres la bascule.

### Implementation validee

La PKI, la configuration Security statique, les montages distincts par noeud et
les tests sont disponibles dans :

```text
dev/scripts/opensearch-cluster/generate-pki.sh
dev/config/opensearch-cluster/opensearch.yml
dev/config/opensearch-cluster/setup-post-start.sh
dev/tests/opensearch-cluster/test_pki.py
```

Les preuves sont consignees dans
`dev/docs/Opensearch/pki_opensearch.md`. Le certificat endpoint est
reserve au proxy de la étape 8. La CA cliente est prete, mais son installation
dans Core et Hedgehog aura lieu pendant leur bascule de la étape 11.

## 12. Étape 7 - Initialisation Security

Executer l'initialisation du plugin Security une seule fois, apres la formation du cluster.

Creer et documenter :

- le compte administrateur ;
- le compte de service Oculox ;
- les roles necessaires a Logstash ;
- les droits Arkime ;
- les droits Dashboards ;
- les droits de snapshot ;
- les permissions des scripts d'administration.

Le compte actuel `malcolm_internal`, associe au backend role `admin`, ne doit
pas devenir le compte de service commun du cluster. Appliquer le moindre
privilege avec des comptes ou roles adaptes au minimum a :

```text
Logstash 1 et Logstash 2
Arkime et Arkime Live
OpenSearch Dashboards
dashboards-helper et administration des templates
API et pcap-monitor
administration des snapshots
```

Verifier qu'une requete autorisee reussit, qu'une operation hors role est
refusee et qu'une requete sans certificat de confiance ou sans identifiants est
refusee.

### Implementation validee

La configuration Security, les sept comptes separes, l'initialisation unique et
les tests statiques/runtime sont implementes. Le cluster a ete valide `green`
avec trois noeuds, un cluster manager elu et zero shard non affecte, puis teste
une seconde fois apres redemarrage sans parametre d'amorcage.

Les preuves et la matrice des roles sont consignees dans :

```text
dev/docs/Opensearch/initialisation_securite.md
```

## 13. Étape 8 - Endpoint stable

Creer un proxy interne :

```text
OPENSEARCH_CLUSTER_ENDPOINT=https://192.168.1.241:9200
```

Le proxy doit :

- connaitre les trois noeuds ;
- verifier leur sante ;
- retirer temporairement un noeud indisponible ;
- conserver TLS et les en-tetes d'authentification ;
- exposer un healthcheck exploitable ;
- produire des journaux de connexion limites et supervisables.

Aucun composant Oculox ne doit dependre directement d'un noeud particulier.

L'endpoint doit etre joignable depuis la VM Oculox Core et depuis chaque VM
Hedgehog. Arkime, Arkime Live et pcap-monitor du collecteur peuvent acceder
directement au stockage distant sans passer par Logstash. Les tests doivent
donc couvrir adressage IP, routage, pare-feu, authentification et validation de la CA
depuis les deux roles de deploiement.

### Implementation validee

Le proxy HAProxy, son rendu local de secrets, les controles actifs, le
rechiffrement TLS, le healthcheck, les journaux limites et les tests de bascule
sont implementes. La validation a ete realisee entre le poste local Oculox et
la VM `192.168.1.241`, conformement au perimetre de test retenu.

Les preuves et les commandes reproductibles sont consignees dans :

```text
dev/docs/Opensearch/endpoint_haute_disponibilite.md
```

## 14. Étape 9 - Shards, replicas et disque

Configurer au minimum un replica pour les index qui doivent survivre a la perte d'un noeud :

```text
number_of_replicas: 1
```

Verifier et adapter :

- les templates `arkime_sessions3-*` ;
- les templates `malcolm_beats_*` ;
- les index Dashboards ;
- les index systeme ;
- les politiques Arkime ;
- les index existants apres restauration.

Les objets observes dans la baseline doivent etre controles explicitement :

```text
malcolm_template
malcolm_beats_template
arkime_stats_template
arkime_sessions3_ecs_template
arkime_sessions3_template
arkime_history_v1_template
aliases malcolm_network et malcolm_other
aliases Arkime
```

Creer et tester les politiques ISM necessaires. La configuration actuelle
annonce `INDEX_MANAGEMENT_ENABLED=true`, mais la baseline n'a trouve aucune
politique ISM active.

Le nombre de shards primaires sera choisi apres mesure de leur taille et du debit d'indexation.

Reactiver les protections disque et configurer les watermarks `low`, `high` et `flood_stage`.

## 15. Étape 10 - Validation autonome du cluster

Avant de connecter Oculox, tester :

1. creation d'un index de test ;
2. ecriture de documents ;
3. lecture et recherche ;
4. presence du primaire et du replica sur des noeuds differents ;
5. arret d'un noeud data ;
6. poursuite des lectures et ecritures ;
7. arret du cluster manager elu ;
8. election d'un nouveau cluster manager ;
9. retour et reintegration du noeud ;
10. retour du cluster a `green` ;
11. redemarrage complet ;
12. conservation du `cluster_uuid` et des documents.

La perte de deux noeuds doit faire perdre le quorum. Ce blocage est attendu et doit etre documente.

## 16. Étape 11 - Configuration d'Oculox Core

Lorsque le cluster est valide, executer le configurateur officiel Malcolm sur le Core et selectionner :

```text
Primary Document Store : opensearch-remote
Primary URL            : https://192.168.1.241:9200
Verify SSL             : Yes
```

Executer ensuite `auth_setup` pour enregistrer le compte de service dans :

```text
.opensearch.primary.curlrc
```

Importer la CA OpenSearch dans les magasins de confiance utilises par les conteneurs Oculox.

Exclure le service OpenSearch local du demarrage sans casser les profils Malcolm et Hedgehog.

Pour chaque collecteur Hedgehog, configurer le meme endpoint IP,
distribuer la CA et fournir les identifiants limites necessaires a Arkime,
Arkime Live et pcap-monitor. Valider cette connexion avant d'activer la capture
de production.

## 17. Étape 12 - Validation de tous les clients

Tester independamment :

```text
Logstash 1 -> cluster
Logstash 2 -> cluster
Arkime Capture -> cluster
Arkime Viewer -> cluster
OpenSearch Dashboards -> cluster
dashboards-helper -> cluster
pcap-monitor -> cluster
API Oculox -> cluster
proxy Nginx -> cluster
Arkime Hedgehog -> cluster
Arkime Live Hedgehog -> cluster
pcap-monitor Hedgehog -> cluster
scripts d'initialisation et healthchecks -> cluster
```

Arkime doit faire l'objet d'un test specifique, car ses metadonnees de sessions sont ecrites directement dans OpenSearch sans passer par Logstash.

Filebeat doit continuer a envoyer les evenements aux deux Logstash. La presence
de `OPENSEARCH_URL` dans son environnement ne doit pas creer une sortie directe
vers OpenSearch.

## 18. Étape 13 - Test de bout en bout

Envoyer un jeu de donnees identifie depuis le collecteur et mesurer :

- paquets captures ;
- evenements Zeek et Suricata produits ;
- evenements recus par chaque Logstash ;
- documents emis par les pipelines de sortie ;
- documents indexes ;
- sessions Arkime creees ;
- evenements consultables dans Dashboards ;
- erreurs et rejets OpenSearch.

Les paquets, evenements et documents sont des objets differents. Leurs nombres ne sont pas naturellement identiques.

## 19. Étape 14 - Tests de panne pendant l'ingestion

Pendant une ingestion controlee :

1. relever les compteurs de reference ;
2. arreter `opensearch-1` ;
3. verifier les lectures et ecritures ;
4. observer les files persistantes Logstash ;
5. redemarrer `opensearch-1` ;
6. attendre le retour a `green` ;
7. recommencer avec `opensearch-2` ;
8. recommencer avec `opensearch-3` ;
9. verifier la reintegration et la redistribution ;
10. comparer les documents attendus et indexes.

Le test doit prouver l'absence de perte et de duplication inattendue.

## 20. Étape 15 - Snapshots et restauration

Configurer un repository de snapshots externe aux trois volumes de donnees.

Un stockage NFS ou objet est preferable. Un repository situe sur le meme disque que les noeuds ne protege pas contre la perte de la VM ou du disque.

La disponibilite et la restauration reelle de ce repository externe sont un
prerequis obligatoire avant la migration finale du mono-noeud. Le repository
local `logs` de la baseline ne constitue qu'une preuve fonctionnelle et non une
sauvegarde contre la perte de la VM.

Tester :

```text
creation d'un snapshot
verification de son etat SUCCESS
suppression d'un index de test
restauration de l'index
comparaison du nombre de documents
restauration sur un cluster vide
```

Un replica assure la continuite de service. Un snapshot permet une restauration apres suppression ou corruption.

## 21. Étape 16 - Migration du mono-noeud existant

La premiere validation utilisera un cluster vide.

La migration finale suivra :

1. verifier la sante du mono-noeud ;
2. creer et valider un snapshot ;
3. reduire ou arreter les ecritures ;
4. restaurer dans le cluster ;
5. verifier les index, mappings et templates ;
6. comparer les documents ;
7. basculer `OPENSEARCH_URL` ;
8. tester tous les composants ;
9. conserver l'ancien OpenSearch pour le retour arriere ;
10. supprimer l'ancien stockage uniquement apres acceptation formelle.

Les controles avant et apres restauration doivent comparer au minimum :

```text
version et compatibilite avec OpenSearch 3.7.0 / image 26.07.1
nombre total de documents applicatifs
nombre de sessions Arkime
index visibles et masques
aliases
templates composables et historiques
mappings
politiques ISM
objets Dashboards
```

Pour le jeu de reference de la étape 1, les valeurs initiales sont `668179`
documents applicatifs et `657306` sessions Arkime. Toute difference doit etre
expliquee par les ecritures intervenues apres la baseline ou declaree comme
anomalie.

## 22. Étape 17 - Supervision

Collecter et afficher :

```text
cluster health
nombre de noeuds
cluster manager elu
cluster_uuid
heap JVM par noeud
CPU et RAM
garbage collection
espace disque
shards non affectes
relocalisation des shards
latence d'indexation
requetes rejetees
pending tasks
temps de recuperation
etat des snapshots
```

Creer des alertes pour :

- cluster `yellow` prolonge ;
- cluster `red` ;
- absence de cluster manager ;
- perte d'un noeud ;
- disque proche des watermarks ;
- heap excessive ;
- shards non affectes ;
- echecs de snapshot ;
- rejets d'indexation.

## 23. Étape 18 - Benchmark

Tester progressivement :

```text
100 Mbps
500 Mbps
1 Gbps
2 Gbps
3 Gbps
```

Pour chaque debit, collecter :

- debit reel du generateur ;
- CPU, RAM et RX/TX ;
- heap et GC des trois noeuds ;
- vitesse d'indexation ;
- files et pressions Logstash ;
- taille et repartition des shards ;
- erreurs et documents rejetes ;
- temps de retour a `green` ;
- nombre final de documents.

Un debit ne sera valide que si la chaine complete absorbe et indexe les donnees, pas seulement si le reseau les transmet.

## 24. Étape 19 - Automatisation Oculox

Les commandes reproductibles retenues sont :

```bash
./oculox install cluster --endpoint-ip <IP_CLUSTER>
./oculox cluster start
./oculox cluster stop
./oculox cluster restart
./oculox cluster status
./oculox cluster validate
./oculox cluster client-bundle core <SORTIE>
./oculox cluster client-bundle hedgehog <SORTIE>
```

L'installation sur une VM neuve doit generer les configurations, la PKI, les volumes et les controles sans editions manuelles dispersees.

Toutes les operations doivent etre idempotentes : les rejouer ne doit pas detruire un cluster existant ni regenerer ses certificats sans demande explicite.

## 25. Étape 20 - Tests d'installation neuve

La recette finale utilise trois VM vides et trois clones indépendants du dépôt.

Sur la VM Cluster :

1. cloner le depot ;
2. exécuter `./oculox install cluster --endpoint-ip <IP_CLUSTER>` ;
3. verifier les trois noeuds ;
4. redemarrer la VM ;
5. verifier la persistance ;
6. produire les bundles clients Core et Hedgehog ;
7. tester la perte d'un noeud ;
8. tester un snapshot et une restauration.

Sur la VM Core :

1. cloner le dépôt ;
2. transférer uniquement le bundle OpenSearch Core ;
3. exécuter `./oculox install principal --server-name <IP_CORE> --opensearch-bundle <BUNDLE_CORE>` ;
4. vérifier qu'OpenSearch local est absent ;
5. produire le bundle Beats mTLS destiné au collecteur.

Sur la VM Hedgehog :

1. cloner le dépôt ;
2. transférer le bundle Beats et le bundle OpenSearch Hedgehog ;
3. exécuter `./oculox install hedgehog --principal-host <IP_CORE> --collector-name <NOM> --bundle <BUNDLE_BEATS> --opensearch-bundle <BUNDLE_HEDGEHOG>` ;
4. injecter du trafic de validation ;
5. vérifier le chemin complet Hedgehog, Logstash, cluster et Dashboards.

La recette collecte ensuite les preuves des trois VM et vérifie leur
redémarrage indépendant.

Verifier egalement que :

- la PKI mono-noeud n'est pas regeneree automatiquement ;
- `OPENSEARCH_URL`, la CA et les identifiants sont propages a tous les clients ;
- la verification TLS est activee sur tous les clients ;
- aucun OpenSearch local n'est demarre sur Oculox Core ;
- Core et Hedgehog atteignent le meme endpoint IP configure ;
- aucun secret ou certificat prive n'est produit dans un chemin versionne.

## 26. Étape 21 - Livraison Git

Versionner uniquement :

- les fichiers Compose ;
- les exemples de configuration ;
- les scripts ;
- les tests ;
- les fichiers de supervision ;
- la documentation ;
- les fichiers `.gitignore` necessaires.

Ne jamais versionner :

- les cles privees ;
- les mots de passe ;
- les fichiers `.curlrc` ;
- les donnees OpenSearch ;
- les snapshots ;
- les journaux runtime ;
- les fichiers de test volumineux.

## 27. Criteres de fin du projet

Le projet sera termine lorsque :

- les trois noeuds forment toujours un seul cluster ;
- le cluster conserve son UUID apres redemarrage ;
- un seul cluster manager est elu ;
- la perte d'un noeud n'interrompt pas les lectures et ecritures ;
- les replicas sont correctement repartis ;
- Oculox n'utilise plus l'OpenSearch local ;
- Logstash, Arkime, Dashboards et API fonctionnent avec l'endpoint stable ;
- TLS HTTP et transport sont verifies ;
- les comptes et roles de service sont documentes et appliquent le moindre privilege ;
- tous les clients Core et Hedgehog valident la CA OpenSearch ;
- des politiques ISM explicites sont creees et testees ;
- les snapshots sont crees et restaurables ;
- les snapshots sont stockes hors de la VM et des volumes de donnees ;
- les tests de bout en bout ne montrent pas de perte inattendue ;
- les benchmarks sont reproductibles ;
- l'installation sur une VM neuve est validee ;
- les secrets et donnees runtime sont absents de Git.

## 28. Sources officielles principales

- Malcolm, instances OpenSearch et stockage distant : https://idaholab.github.io/Malcolm/docs/opensearch-instances.html
- OpenSearch, creation d'un cluster : https://docs.opensearch.org/latest/tuning-your-cluster/
- OpenSearch, amorcage : https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/bootstrapping/
- OpenSearch, decouverte : https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/discovery/
- OpenSearch, quorum : https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/voting-quorums/
- OpenSearch, TLS : https://docs.opensearch.org/latest/security/configuration/tls/
- OpenSearch, Docker : https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker
- OpenSearch, snapshots : https://docs.opensearch.org/latest/tuning-your-cluster/availability-and-recovery/snapshots/
- OpenSearch, migration par snapshot : https://docs.opensearch.org/latest/migrate-or-upgrade/snapshot-restore/

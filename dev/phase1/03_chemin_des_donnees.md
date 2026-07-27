# Phase 1 - Étude Du Chemin Des Données

## 1. Objectif Du Document

Ce document explique comment une communication réseau observée par Oculox/Malcolm devient une donnée consultable dans OpenSearch Dashboards ou dans Arkime Viewer.

Le chemin simplifié proposé au départ était le suivant :

```text
Capture locale
→ Zeek / Suricata / Arkime
→ fichiers de logs
→ Filebeat
→ Logstash
→ OpenSearch
→ Dashboards / Arkime
```

Ce schéma donne une bonne vue générale, mais il contient un raccourci important : **les trois analyseurs ne suivent pas exactement le même chemin**.

- Zeek et Suricata produisent des fichiers que Filebeat lit et transmet à Logstash.
- Arkime conserve les paquets dans des fichiers PCAP et écrit directement ses métadonnées de sessions dans OpenSearch.
- Filebeat ne transporte donc pas les PCAP bruts d'Arkime.
- Arkime Viewer utilise à la fois les métadonnées indexées dans OpenSearch et les fichiers PCAP conservés sur disque.

Le but de cette étape est de comprendre cette différence avant d'ajouter plusieurs instances de Logstash.

## 2. Vue D'ensemble Exacte

### 2.1 Chemin Du Trafic Live

```text
Interface réseau de capture définie par PCAP_IFACE
│
├── Zeek live
│   └── fichiers *.log dans zeek-logs/live
│       └── Filebeat
│           └── Beats/TLS vers Logstash:5044
│               └── parsing Zeek
│                   └── enrichissement
│                       └── OpenSearch
│                           └── OpenSearch Dashboards
│
├── Suricata live
│   └── eve*.json dans suricata-logs/live
│       └── Filebeat
│           └── Beats/TLS vers Logstash:5044
│               └── parsing Suricata
│                   └── enrichissement
│                       └── OpenSearch
│                           └── OpenSearch Dashboards
│
├── Arkime live
│   ├── PCAP dans pcap/arkime-live
│   └── métadonnées de sessions directement dans OpenSearch
│       └── Arkime Viewer
│
└── pcap-capture, si cette option est activée
    └── PCAP tournants dans pcap/upload
        └── chaîne d'analyse offline
```

### 2.2 Idée Essentielle

Un même paquet peut être observé par Zeek, Suricata et Arkime, mais chaque outil en fait un usage différent :

| Composant | Question principale | Résultat produit |
|---|---|---|
| Zeek | Que s'est-il passé au niveau protocolaire ? | Journaux de connexions et de protocoles |
| Suricata | Ce trafic correspond-il à une règle ou à un événement de sécurité ? | Événements EVE JSON et alertes IDS |
| Arkime | À quelle session ce paquet appartient-il et où retrouver les paquets ? | Métadonnées de session et fichiers PCAP |

Il ne faut donc pas interpréter la chaîne comme :

```text
Zeek → Suricata → Arkime
```

Les trois moteurs travaillent **en parallèle** sur le trafic ou sur le même PCAP. Zeek ne transmet pas ses résultats à Suricata, et Suricata ne transmet pas ses résultats à Arkime.

## 3. Étape 1 - La Capture Locale

### 3.1 Qu'est-ce Qu'une Interface De Capture ?

Une interface réseau est le point par lequel une machine reçoit ou émet des trames Ethernet. Dans un déploiement OT, l'interface de capture reçoit normalement une copie du trafic provenant d'un port miroir, d'un SPAN ou d'un TAP.

La variable qui désigne cette interface dans le projet est :

```env
PCAP_IFACE=nom_de_l_interface
```

Le modèle fourni dans le dépôt utilise `lo` uniquement comme valeur par défaut :

```env
PCAP_IFACE=lo
```

`lo` est l'interface de boucle locale. Elle n'est pas une interface de capture OT pertinente. Lors de la configuration réelle, cette valeur doit être remplacée par l'interface effectivement raccordée au trafic miroir.

### 3.2 Pourquoi Les Conteneurs Live Utilisent Le Réseau De L'hôte ?

Les services suivants utilisent :

```yaml
network_mode: host
```

- `zeek-live` ;
- `suricata-live` ;
- `arkime-live` ;
- `pcap-capture`.

Cela leur permet de voir directement les interfaces réseau de la machine hôte. S'ils utilisaient uniquement un réseau Docker classique, ils verraient surtout les interfaces virtuelles de leur propre espace réseau.

Ils reçoivent également les capacités Linux nécessaires à la capture, notamment :

```text
NET_RAW
NET_ADMIN
```

- `NET_RAW` autorise l'utilisation de sockets réseau bruts.
- `NET_ADMIN` autorise certaines opérations d'administration réseau, notamment la mise en mode promiscuité selon la configuration.

### 3.3 Activation Des Analyseurs Live

La désignation de l'interface ne suffit pas. Chaque analyseur possède aussi un interrupteur d'activation :

```env
ZEEK_LIVE_CAPTURE=true
SURICATA_LIVE_CAPTURE=true
ARKIME_LIVE_CAPTURE=true
```

Dans les fichiers `*.env.example`, ces valeurs sont à `false`. Les vrais fichiers `config/*.env`, créés lors de la configuration de l'installation, contiennent les valeurs réellement appliquées.

### 3.4 Capture Et Analyse Sont Deux Notions Différentes

Les analyseurs live peuvent lire directement l'interface sans qu'un fichier PCAP intermédiaire soit nécessaire.

Le service `pcap-capture` est une fonction distincte. Lorsqu'il est activé, `netsniff-ng` ou `tcpdump` écrit des PCAP tournants. Les paramètres suivants contrôlent notamment leur rotation :

```env
PCAP_ROTATE_MEGABYTES=4096
PCAP_ROTATE_MINUTES=10
```

Ainsi :

- Zeek, Suricata et Arkime live peuvent analyser directement l'interface ;
- `pcap-capture` peut, en plus, conserver une copie sous forme de PCAP ;
- l'activation de `pcap-capture` n'est pas une condition obligatoire pour que Zeek ou Suricata live fonctionnent.

## 4. Étape 2 - Zeek

### 4.1 Rôle De Zeek

Zeek est un moteur d'analyse protocolaire. Il reconstruit les communications observées et produit des journaux structurés.

Selon le trafic, il peut produire notamment :

```text
conn.log
dns.log
http.log
ssl.log ou tls.log
files.log
notice.log
modbus.log
```

Un paquet n'est pas égal à une ligne Zeek. Zeek raisonne principalement en connexions, transactions et événements protocolaires.

Une même communication peut donc apparaître dans plusieurs journaux. Par exemple, une connexion HTTP peut produire une entrée dans `conn.log`, une autre dans `http.log` et éventuellement des entrées relatives aux fichiers transférés.

### 4.2 Lecture De L'interface

Le script `zeek/scripts/zeekdeploy.sh` récupère `PCAP_IFACE` et configure les workers Zeek. Lorsque le support AF_PACKET est disponible, les workers utilisent une interface de la forme :

```text
af_packet::nom_interface
```

AF_PACKET est un mécanisme Linux permettant de recevoir les trames directement depuis une interface réseau.

### 4.3 Fichiers Produits

Dans le conteneur, le chemin live est :

```text
/zeek/live
```

Le montage Docker suivant rend ces fichiers persistants sur l'hôte :

```text
Hôte       : ./zeek-logs/live
Conteneur  : /zeek/live
```

Avec l'architecture Zeek en workers et logger, Filebeat lit plus précisément :

```text
/zeek/live/spool/logger-*/*.log
```

Depuis l'hôte, cela correspond à :

```text
./zeek-logs/live/spool/logger-*/*.log
```

## 5. Étape 3 - Suricata

### 5.1 Rôle De Suricata

Suricata est un moteur IDS et d'analyse réseau. Il inspecte le trafic, applique des règles de détection et produit des événements structurés.

Pour le live, il est lancé avec :

```text
suricata ... --af-packet
```

L'interface surveillée est construite à partir de `PCAP_IFACE` dans la configuration Suricata générée au démarrage.

### 5.2 Le Fichier `eve.json`

Suricata centralise ses événements dans un format appelé EVE JSON. Selon la configuration et le trafic, ce fichier peut contenir plusieurs types d'événements :

- `alert` ;
- `flow` ;
- `dns` ;
- `http` ;
- `tls` ;
- `fileinfo` ;
- statistiques, si elles sont activées.

JSON est un format texte lisible. Il répète le nom des champs dans chaque événement. Cette facilité de lecture rend le fichier plus volumineux qu'un format binaire compact.

Une seule communication peut également produire plusieurs événements EVE. Il ne faut donc pas comparer directement le nombre de lignes d'`eve.json` au nombre de paquets du PCAP.

### 5.3 Fichiers Produits

Le montage commun aux services Suricata est :

```text
Hôte       : ./suricata-logs
Conteneur  : /var/log/suricata
```

Pour la capture live, Filebeat surveille :

```text
/suricata/live/eve*.json
```

Depuis l'hôte, cela correspond à :

```text
./suricata-logs/live/eve*.json
```

## 6. Étape 4 - Arkime

### 6.1 Rôle D'Arkime

Arkime fournit une vision orientée sessions et permet de revenir aux paquets associés à une communication.

Il produit deux catégories de données :

1. les paquets bruts conservés dans des fichiers PCAP ;
2. les métadonnées de sessions indexées dans OpenSearch.

### 6.2 Stockage Des PCAP

Le processus live est lancé avec le paramètre :

```text
pcapDir=/data/pcap/arkime-live
```

Le montage Docker est :

```text
Hôte       : ./pcap
Conteneur  : /data/pcap
```

Les PCAP live se trouvent donc sur l'hôte dans :

```text
./pcap/arkime-live
```

### 6.3 Écriture Directe Dans OpenSearch

Le fichier Arkime `arkime/etc/config.ini` contient :

```ini
elasticsearch=https://opensearch:9200
```

Le nom historique de la clé est `elasticsearch`, mais la cible configurée ici est bien le service OpenSearch.

Arkime écrit donc ses métadonnées de sessions directement dans OpenSearch. Cette branche ne passe pas par Filebeat puis Logstash.

### 6.4 Ce Que Stocke OpenSearch Pour Arkime

OpenSearch ne reçoit pas l'intégralité des octets du PCAP. Il reçoit des documents de session contenant, par exemple :

- les adresses IP ;
- les ports ;
- le protocole ;
- les horodatages ;
- le nombre de paquets et d'octets ;
- les informations nécessaires pour retrouver la capture correspondante.

Le PCAP reste sur le stockage de fichiers. L'index contient les informations de recherche et le lien logique vers les paquets.

## 7. Étape 5 - Filebeat

### 7.1 Rôle De Filebeat

Filebeat est un agent de lecture et de transport de journaux.

Il ne capture pas le trafic réseau et il ne réalise pas l'analyse protocolaire principale. Son travail est de :

1. surveiller les répertoires de logs ;
2. détecter les nouvelles lignes ;
3. transformer chaque ligne en événement ;
4. ajouter des informations techniques, notamment des tags ;
5. envoyer les événements à Logstash ;
6. mémoriser jusqu'où chaque fichier a été lu.

### 7.2 Répertoires Montés

Le service Filebeat voit les données grâce aux montages suivants :

```text
./zeek-logs       → /zeek
./suricata-logs   → /suricata
./filescan-logs   → /filescan
```

Il ne possède aucun montage vers `./pcap` dans cette configuration. Cela confirme qu'il ne transporte pas les PCAP Arkime.

### 7.3 Tags De Routage

Filebeat ajoute un tag en fonction de la source :

| Source | Tag principal |
|---|---|
| Zeek live | `_filebeat_zeek_malcolm_live` |
| Zeek upload/offline | `_filebeat_zeek_malcolm_upload` |
| Suricata live | `_filebeat_suricata_malcolm_live` |
| Suricata upload/offline | `_filebeat_suricata_malcolm_upload` |

Ces tags permettent à Logstash de choisir le bon parseur. Sans eux, Logstash ne saurait pas si une ligne doit être interprétée comme un log Zeek, un événement Suricata ou une autre source.

### 7.4 Registre Filebeat

Filebeat conserve ses registres dans des volumes Docker nommés, notamment :

```text
filebeat-logs-registry
```

Un registre mémorise principalement :

- l'identité du fichier ;
- la dernière position lue, appelée offset ;
- l'état de la lecture.

Si Logstash est momentanément indisponible, Filebeat peut réessayer et reprendre sa lecture. Cette reprise reste toutefois dépendante de la présence du fichier source et de la politique de nettoyage locale.

### 7.5 Transport Vers Logstash

La destination par défaut est :

```env
LOGSTASH_HOST=logstash:5044
```

Le port `5044` utilise le protocole Beats. Ce protocole transporte des événements structurés entre Filebeat et l'entrée Beats de Logstash.

Le modèle de configuration active le chiffrement :

```env
BEATS_SSL=true
```

Le fichier `filebeat/filebeat-logs.yml` fournit un certificat client et impose TLS 1.2. Il contient cependant aussi :

```yaml
ssl.verification_mode: "none"
```

Le flux peut donc être chiffré sans que Filebeat vérifie strictement l'identité du certificat présenté par Logstash. Pour une architecture de production, la validation stricte du certificat devra être étudiée séparément.

## 8. Étape 6 - Logstash

### 8.1 Rôle De Logstash

Logstash reçoit les événements, les interprète, les normalise, les enrichit et les transmet vers le stockage.

Il ne reçoit pas directement les paquets réseau. Il reçoit les événements textuels produits par Zeek et Suricata puis envoyés par Filebeat.

### 8.2 Entrée Beats

Le pipeline d'entrée écoute sur :

```text
0.0.0.0:5044
```

Sa configuration se trouve dans :

```text
logstash/pipelines/input/01_beats_input.conf
```

### 8.3 Routage Selon Les Tags

Le fichier :

```text
logstash/maps/parse_pipelines.yaml
```

associe les tags Filebeat aux pipelines de parsing :

```text
tags Zeek      → zeek-parse
tags Suricata  → suricata-parse
autres Beats   → beats-parse
filescan       → filescan-parse
```

Au démarrage, le script `logstash/scripts/logstash-start.sh` lit cette table et génère automatiquement le fichier interne de routage `99_route_input.conf`.

### 8.4 Pipeline Zeek

Le chemin normal d'un événement Zeek est :

```text
malcolm-input
→ zeek-parse
→ log-enrichment
→ sortie OpenSearch
```

Le pipeline `zeek-parse` :

- reconnaît le format Zeek ;
- extrait les colonnes ;
- convertit les types ;
- normalise les noms de champs ;
- prépare les données pour l'enrichissement.

Les journaux de diagnostic Zeek ne suivent pas exactement cette branche. Ils sont routés vers `beats-parse`, car ce sont des données de fonctionnement et non des métadonnées de trafic à enrichir.

### 8.5 Pipeline Suricata

Le chemin normal d'un événement Suricata est :

```text
malcolm-input
→ suricata-parse
→ log-enrichment
→ sortie OpenSearch
```

Le pipeline `suricata-parse` :

- lit le JSON EVE ;
- identifie le type d'événement ;
- normalise les champs ;
- prépare les alertes et événements réseau pour l'enrichissement.

Les statistiques internes de Suricata sont routées vers `beats-parse`, comme les diagnostics Zeek.

### 8.6 Enrichissement

Le pipeline `log-enrichment` complète les événements avec le contexte disponible. Selon la configuration, il peut notamment ajouter ou harmoniser :

- des informations réseau ;
- des informations d'actifs ;
- des champs compatibles avec le modèle de données utilisé ;
- un identifiant déterministe de document ;
- le nom de l'index OpenSearch cible.

La valeur par défaut observée dans le code pour les événements réseau est :

```text
arkime_sessions3-*
```

Le suffixe temporel par défaut est construit avec la date de l'événement :

```text
%y%m%d
```

### 8.7 Sortie OpenSearch

Le dernier pipeline écrit vers :

```text
https://opensearch:9200
```

La configuration principale est :

```text
logstash/pipelines/output/99_opensearch_output.conf
```

Le nom de l'index n'est pas écrit en dur dans ce fichier. Il est préparé dans les métadonnées de l'événement par les pipelines précédents :

```text
[@metadata][malcolm_opensearch_index]
```

### 8.8 Ce Qu'est Un Pipeline Interne

Les noms `zeek-parse`, `suricata-parse` et `log-enrichment` ne sont pas des ports réseau supplémentaires. Ce sont des chemins internes au processus Logstash.

Ils permettent de séparer les responsabilités :

- réception ;
- parsing Zeek ;
- parsing Suricata ;
- enrichissement ;
- écriture dans OpenSearch.

Cette séparation sera importante lors de l'étude de plusieurs instances Logstash, car il faudra décider quelles étapes doivent être répliquées et comment Filebeat répartira les connexions.

## 9. Étape 7 - OpenSearch

### 9.1 Rôle D'OpenSearch

OpenSearch est le moteur de stockage indexé et de recherche.

Il reçoit des documents structurés. Un document est un ensemble de champs décrivant un événement ou une session, par exemple :

```json
{
  "source.ip": "192.0.2.10",
  "destination.ip": "192.0.2.20",
  "network.transport": "tcp",
  "event.provider": "zeek"
}
```

Cet exemple est pédagogique. Les documents réels contiennent davantage de champs.

### 9.2 Qu'est-ce Qu'un Index ?

Un index est un ensemble organisé de documents permettant des recherches rapides.

On peut le comparer à un classeur dans lequel :

- chaque document est une fiche ;
- chaque champ est une colonne exploitable ;
- le moteur construit des structures internes pour retrouver rapidement les valeurs.

L'index n'est pas un simple fichier de logs. OpenSearch transforme les documents reçus pour permettre les recherches, agrégations, graphiques et corrélations.

### 9.3 Données Stockées Dans OpenSearch

OpenSearch reçoit notamment :

- les événements Zeek traités par Logstash ;
- les événements et alertes Suricata traités par Logstash ;
- les métadonnées de sessions envoyées directement par Arkime ;
- d'autres journaux et données d'enrichissement selon les fonctions activées.

Les PCAP bruts restent dans les répertoires de fichiers. Ils ne doivent pas être confondus avec les documents indexés.

### 9.4 Persistance

Le service OpenSearch monte son stockage dans :

```text
/usr/share/opensearch/data
```

Ce stockage persistant contient les index, leurs segments internes et les métadonnées du moteur. Il doit être surveillé indépendamment des répertoires PCAP et des journaux Zeek/Suricata.

## 10. Étape 8 - Consultation

### 10.1 OpenSearch Dashboards

OpenSearch Dashboards interroge OpenSearch et fournit :

- des tableaux de bord ;
- des recherches temporelles ;
- des visualisations ;
- des agrégations ;
- des filtres sur les champs indexés.

Le navigateur passe normalement par Nginx Proxy, puis Nginx transmet la requête au service Dashboards sur son port interne `5601`.

Chemin simplifié :

```text
Navigateur
→ Nginx Proxy en HTTPS
→ OpenSearch Dashboards:5601
→ OpenSearch:9200
```

### 10.2 Arkime Viewer

Arkime Viewer fournit une vue orientée sessions réseau.

Il utilise :

1. OpenSearch pour rechercher les métadonnées de sessions ;
2. le dépôt PCAP pour afficher ou extraire les paquets associés.

Le service écoute en interne sur le port `8005` et est publié par Nginx sous le chemin `/arkime/`.

Chemin simplifié :

```text
Navigateur
→ Nginx Proxy en HTTPS
→ Arkime Viewer:8005
├── recherche dans OpenSearch
└── lecture des PCAP dans pcap/arkime-live ou pcap/processed
```

### 10.3 Différence Entre Les Deux Interfaces

| Interface | Usage principal | Données utilisées |
|---|---|---|
| OpenSearch Dashboards | Statistiques, recherche, visualisation SOC | Documents indexés dans OpenSearch |
| Arkime Viewer | Investigation de sessions et retour aux paquets | Métadonnées OpenSearch et fichiers PCAP |

## 11. Chemin Offline Des PCAP Importés

### 11.1 Dépôt Initial

Un PCAP importé est placé dans :

```text
./pcap/upload
```

Le service `pcap-monitor` surveille ce répertoire. Le script `watch-pcap-uploads-folder.py` vérifie le type et la taille du fichier, puis déplace un PCAP accepté vers :

```text
./pcap/processed
```

Le déplacement de `upload` vers `processed` explique pourquoi un fichier peut disparaître rapidement du dossier d'upload sans avoir été supprimé.

### 11.2 Analyseurs Offline

Les services sans suffixe `-live` traitent les fichiers importés :

- `zeek` ;
- `suricata` ;
- `arkime`.

Ils produisent ensuite les mêmes grandes catégories de résultats :

```text
PCAP importé
├── Zeek offline → zeek-logs → Filebeat → Logstash → OpenSearch
├── Suricata offline → suricata-logs/suricata-*/eve.json
│                      → Filebeat → Logstash → OpenSearch
└── Arkime offline → métadonnées directement dans OpenSearch
                     + référence au PCAP traité
```

### 11.3 Différence Entre Live Et Offline

| Mode | Source | Rythme |
|---|---|---|
| Live | Interface réseau | Le trafic arrive au fil de l'eau |
| Offline | Fichier PCAP déjà capturé | Le fichier peut être analysé aussi vite que les ressources le permettent |

Cette différence explique pourquoi un gros PCAP offline peut créer une production très rapide de logs et une forte pression sur le disque ou sur Logstash.

## 12. Ce Qui Reste Sur Disque

| Donnée | Emplacement principal | Producteur | Consommateur |
|---|---|---|---|
| Logs Zeek live | `zeek-logs/live` | Zeek live | Filebeat |
| Logs Zeek offline | `zeek-logs/upload` et chemins de traitement associés | Zeek offline | Filebeat |
| EVE Suricata live | `suricata-logs/live/eve*.json` | Suricata live | Filebeat |
| EVE Suricata offline | `suricata-logs/suricata-*/eve*.json` | Suricata offline | Filebeat |
| PCAP Arkime live | `pcap/arkime-live` | Arkime live | Arkime Viewer |
| PCAP importés/traités | `pcap/processed` | pcap-monitor et analyseurs | Arkime et investigation |
| Registres Filebeat | volumes `filebeat-*-registry` | Filebeat | Filebeat |
| Index | données persistantes OpenSearch | OpenSearch | Dashboards et Arkime Viewer |

Ces espaces ont des cycles de vie différents. Supprimer un index OpenSearch ne supprime pas nécessairement le PCAP associé. Inversement, supprimer un PCAP peut laisser des métadonnées de session sans paquets accessibles.

## 13. Que Se Passe-t-il En Cas De Panne ?

| Panne | Effet immédiat | Mécanisme de reprise ou risque |
|---|---|---|
| Zeek arrêté | Plus de nouveaux logs Zeek | Les paquets passés pendant l'arrêt ne sont pas reconstruits, sauf présence d'un PCAP exploitable |
| Suricata arrêté | Plus de nouveaux événements EVE | Les alertes de la période peuvent manquer, sauf réanalyse d'un PCAP |
| Arkime live arrêté | Plus de nouvelles sessions Arkime et plus de PCAP Arkime | La branche Zeek/Suricata peut continuer indépendamment |
| Filebeat arrêté | Les logs locaux s'accumulent | Reprise possible grâce aux registres si les fichiers existent encore |
| Logstash indisponible | Filebeat ne peut plus livrer normalement | Filebeat réessaie ; les fichiers et files doivent disposer d'une capacité suffisante |
| OpenSearch indisponible | Indexation et recherches bloquées | Logstash et Arkime attendent ou réessaient selon leur configuration |
| Disque de logs plein | Écriture Zeek/Suricata menacée | Risque d'arrêt ou de perte de visibilité |
| Disque PCAP plein | Capture Arkime menacée | Les métadonnées seules ne suffisent plus pour revenir aux paquets |

## 14. Vérifications En Lecture Seule

Les commandes suivantes ne modifient pas les données. Elles doivent être lancées depuis la racine d'une installation configurée, c'est-à-dire depuis le dossier qui contient les vrais fichiers `config/*.env`.

### 14.1 Vérifier Les Paramètres Live

```bash
grep -HnE '^(PCAP_IFACE|ZEEK_LIVE_CAPTURE|SURICATA_LIVE_CAPTURE|ARKIME_LIVE_CAPTURE|PCAP_ENABLE_NETSNIFF|PCAP_ENABLE_TCPDUMP)=' config/*.env
```

Résultat attendu :

- le nom de l'interface de capture ;
- l'état `true` ou `false` de chaque analyseur ;
- l'état de la capture PCAP séparée.

### 14.2 Vérifier Les Conteneurs

```bash
docker compose ps zeek-live suricata-live arkime-live filebeat logstash opensearch dashboards nginx-proxy
```

Un conteneur `running` exécute son processus. Un conteneur `healthy` a également réussi son contrôle de santé.

### 14.3 Vérifier Les Processus De Capture

```bash
docker compose exec -T zeek-live ps aux
docker compose exec -T suricata-live ps aux
docker compose exec -T arkime-live ps aux
```

Selon le nom de projet Compose, Docker peut préfixer les noms des conteneurs. Pour obtenir les noms exacts :

```bash
docker compose ps --format '{{.Name}}'
```

### 14.4 Vérifier La Production De Fichiers

```bash
find zeek-logs/live -type f -name '*.log' -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' | sort | tail -20
```

```bash
find suricata-logs/live -type f -name 'eve*.json' -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' | sort | tail -20
```

```bash
find pcap/arkime-live -type f -printf '%TY-%Tm-%Td %TH:%TM:%TS %s %p\n' | sort | tail -20
```

La date et la taille doivent évoluer lorsque du trafic pertinent est observé.

### 14.5 Vérifier Les Montages Filebeat

```bash
docker compose config | sed -n '/^  filebeat:/,/^  [a-zA-Z0-9_-]*:/p'
```

Cette sortie permet de confirmer les chemins réellement montés et les fichiers d'environnement chargés.

### 14.6 Vérifier La Connexion Filebeat Vers Logstash

```bash
docker compose logs --since 10m filebeat | grep -Ei 'logstash|connect|publish|error|failed|backoff'
```

L'absence de sortie n'est pas automatiquement une erreur : le niveau de journalisation peut ne rien afficher lorsque tout fonctionne. Les erreurs répétées de connexion ou de publication sont en revanche un signal de panne.

### 14.7 Vérifier L'écoute Beats De Logstash

```bash
docker exec "$(docker compose ps -q logstash)" ss -ltnp | grep ':5044'
```

Le port `5044` doit apparaître en écoute dans le conteneur Logstash.

### 14.8 Vérifier Les Pipelines Logstash

```bash
docker compose exec -T logstash \
  curl -s 'http://localhost:9600/_node/stats/pipelines?pretty'
```

Cette commande interroge l'API de supervision à l'intérieur du conteneur Logstash. Les pipelines attendus incluent notamment les fonctions d'entrée, de parsing Zeek, de parsing Suricata, d'enrichissement et de sortie OpenSearch.

### 14.9 Vérifier La Santé D'OpenSearch

Depuis le conteneur OpenSearch, avec le fichier d'identifiants prévu par le projet :

```bash
docker exec "$(docker compose ps -q opensearch)" \
  curl -K /var/local/curlrc/.opensearch.primary.curlrc \
  -sk 'https://localhost:9200/_cluster/health?pretty'
```

Un état `green` signifie que tous les shards attendus sont affectés. Un état `yellow` ou `red` doit être expliqué avant un benchmark.

### 14.10 Vérifier Les Index Réseau

```bash
docker exec "$(docker compose ps -q opensearch)" \
  curl -K /var/local/curlrc/.opensearch.primary.curlrc \
  -sk 'https://localhost:9200/_cat/indices/arkime_sessions3-*?v&s=index'
```

Cette commande affiche les index, leur état, leur nombre de documents et leur taille.

## 15. Sources Techniques Dans Le Dépôt

Les conclusions de ce document proviennent principalement des fichiers suivants :

```text
docker-compose.yml
config/pcap-capture.env.example
config/zeek-live.env.example
config/suricata-live.env.example
config/arkime-live.env.example
config/beats-common.env.example
config/filebeat.env.example
zeek/scripts/zeekdeploy.sh
suricata/supervisord.conf
arkime/scripts/live_capture.sh
arkime/etc/config.ini
filebeat/filebeat-logs.yml
logstash/maps/parse_pipelines.yaml
logstash/scripts/logstash-start.sh
logstash/pipelines/input/01_beats_input.conf
logstash/pipelines/zeek/9900_zeek_forward.conf
logstash/pipelines/suricata/99_suricata_forward.conf
logstash/pipelines/enrichment/98_finalize.conf
logstash/pipelines/output/99_opensearch_output.conf
pcap-monitor/scripts/watch-pcap-uploads-folder.py
```

## 16. Résumé À Retenir

Le chemin réel n'est pas une seule ligne, mais trois branches parallèles :

```text
Zeek → logs Zeek → Filebeat → Logstash → OpenSearch → Dashboards

Suricata → EVE JSON → Filebeat → Logstash → OpenSearch → Dashboards

Arkime → métadonnées directement vers OpenSearch → Arkime Viewer
       └→ PCAP conservés sur disque ────────────────┘
```

Les points essentiels sont les suivants :

1. Zeek, Suricata et Arkime analysent le trafic en parallèle.
2. Filebeat lit des fichiers de logs ; il ne transporte pas les PCAP Arkime.
3. Les tags Filebeat déterminent le pipeline de parsing choisi par Logstash.
4. Logstash parse et enrichit les événements Zeek et Suricata avant leur indexation.
5. Arkime écrit directement ses métadonnées de sessions dans OpenSearch.
6. OpenSearch stocke les documents indexés, tandis que les paquets bruts restent dans les fichiers PCAP.
7. Dashboards est orienté recherche et visualisation ; Arkime Viewer est orienté sessions et paquets.
8. La résilience complète dépend de plusieurs espaces : logs locaux, registres Filebeat, capacité Logstash, index OpenSearch et stockage PCAP.

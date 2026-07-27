# Phase 1 - Identification Des Fichiers D'orchestration Et De Configuration

## 1. Objectif De Cette Étape

Cette première étape sert à comprendre comment le projet Oculox/Malcolm est organisé avant toute modification.

Le but n'est pas encore d'ajouter un deuxième Logstash. Le but est d'abord de savoir :

- quels fichiers démarrent les conteneurs Docker ;
- quels fichiers définissent les paramètres des services ;
- quels fichiers sont versionnés dans Git ;
- quels fichiers sont locaux à une installation et ne doivent pas être poussés dans le dépôt ;
- où se trouvent les premières variables importantes pour Filebeat, Logstash et OpenSearch.

Cette étape est importante parce qu'une plateforme comme Malcolm/Oculox repose sur beaucoup de services Docker. Si on modifie directement un fichier sans comprendre son rôle, on peut créer une panne difficile à diagnostiquer. Ici, on documente donc l'existant avant de toucher à l'architecture.

## 2. Notions De Base

### 2.1 Docker Compose

Docker Compose est l'outil qui permet de décrire et de démarrer plusieurs conteneurs Docker ensemble.

Un conteneur Docker est comme un petit environnement isolé qui exécute un service précis. Par exemple, dans Oculox/Malcolm, il existe un conteneur pour OpenSearch, un conteneur pour Logstash, un conteneur pour Filebeat, un conteneur pour Zeek, un conteneur pour Suricata, etc.

Au lieu de démarrer chaque conteneur manuellement, Docker Compose lit un fichier YAML et démarre toute la plateforme selon ce qui est écrit dans ce fichier.

Le fichier principal est généralement :

```text
docker-compose.yml
```

### 2.2 Fichier YAML

Un fichier YAML est un fichier texte structuré. Il est souvent utilisé pour décrire de la configuration.

Dans un `docker-compose.yml`, on y trouve notamment :

- les services Docker à démarrer ;
- les images Docker utilisées ;
- les volumes montés ;
- les réseaux Docker ;
- les fichiers d'environnement utilisés ;
- les dépendances entre services ;
- les contrôles de santé des conteneurs.

Exemple simplifié :

```yaml
services:
  logstash:
    image: ghcr.io/idaholab/malcolm/logstash-oss:26.06.0
    env_file:
      - ./config/logstash.env
    volumes:
      - logstash-persistent-queue:/logstash-persistent-queue
```

Lecture simple :

- `logstash` est le nom du service ;
- `image` indique quelle image Docker sera utilisée ;
- `env_file` indique les fichiers de configuration à charger ;
- `volumes` indique les données persistantes ou les dossiers montés.

### 2.3 Fichier `.env`

Un fichier `.env` contient des variables de configuration.

Une variable ressemble à ceci :

```env
LOGSTASH_HOST=logstash:5044
```

Cela veut dire :

- nom de la variable : `LOGSTASH_HOST` ;
- valeur : `logstash:5044`.

Dans ce cas précis, cette variable indique à Filebeat où envoyer les événements. Aujourd'hui, la valeur par défaut indique un seul Logstash, nommé `logstash`, sur le port `5044`.

### 2.4 Fichier `.env.example`

Un fichier `.env.example` est un modèle.

Il sert à montrer les variables attendues, mais il n'est pas forcément utilisé directement au démarrage.

Dans ce dépôt local, on trouve beaucoup de fichiers comme :

```text
config/logstash.env.example
config/filebeat.env.example
config/beats-common.env.example
```

Cela veut dire que le dépôt contient les modèles de configuration, mais pas forcément les vrais fichiers `.env` utilisés par une installation réelle.

### 2.5 Pourquoi Les Fichiers `.env` Réels Ne Sont Pas Toujours Versionnés

Les vrais fichiers `.env` peuvent contenir :

- des mots de passe ;
- des secrets ;
- des paramètres propres à une machine ;
- des chemins locaux ;
- des adresses de service ;
- des certificats ou des informations sensibles.

Pour cette raison, ils sont souvent ignorés par Git.

Dans ce projet, le fichier suivant existe :

```text
config/.gitignore
```

Son contenu indique :

```gitignore
*.env
kubernetes-container-resources.yml
```

Cela signifie que les fichiers `config/*.env` réels ne sont pas suivis par Git. C'est volontaire. Les modèles `*.env.example`, eux, sont suivis.

### 2.6 Fichier Override Docker Compose

Un fichier override est un fichier Docker Compose complémentaire.

Il permet de modifier ou compléter le comportement du `docker-compose.yml` principal sans toucher directement au fichier officiel.

Exemple :

```text
docker-compose.local-2logstash.yml
```

Ce type de fichier pourra servir plus tard pour ajouter un deuxième Logstash en local, sans modifier directement le `docker-compose.yml` principal.

Principe :

```bash
docker compose -f docker-compose.yml -f docker-compose.local-2logstash.yml up -d
```

Docker Compose lit d'abord le fichier principal, puis applique le fichier override par-dessus.

## 3. État Du Dépôt Local

Le projet local étudié est :

```text
/home/kakashi_/ICSHUB/Oculox
```

Le dépôt Git est connecté au dépôt distant suivant :

```text
http://gitea.tcric.hq/sdiop/Oculox.git
```

Le dernier commit local identifié est :

```text
dce521d3 ajout de fichier utile au démarrage
```

Le dépôt local était propre au moment de cette vérification : aucune modification non commitée n'a été détectée.

## 4. Fichiers D'orchestration Trouvés

Les fichiers Docker Compose présents à la racine du projet sont :

```text
docker-compose.yml
docker-compose-dev.yml
```

Aucun fichier override local n'a été trouvé à ce stade :

```text
docker-compose.override.yml
compose.override.yml
*.override.yml
```

### 4.1 `docker-compose.yml`

Ce fichier est le fichier d'orchestration principal.

Il décrit les services nécessaires au fonctionnement standard de la plateforme Oculox/Malcolm.

On y trouve notamment :

- OpenSearch ;
- Dashboards ;
- Logstash ;
- Filebeat ;
- Arkime ;
- Arkime live ;
- Zeek ;
- Zeek live ;
- Suricata ;
- Suricata live ;
- filescan ;
- Strelka ;
- pcap-capture ;
- pcap-monitor ;
- upload ;
- htadmin ;
- freq ;
- NetBox ;
- PostgreSQL ;
- Valkey ;
- API ;
- Keycloak ;
- Nginx Proxy.

Ce fichier est donc le coeur de l'orchestration de la plateforme.

### 4.2 `docker-compose-dev.yml`

Ce fichier ressemble beaucoup au `docker-compose.yml`, mais il est destiné au développement.

Un fichier de développement peut servir à :

- utiliser des images ou montages adaptés au développement ;
- faciliter le test de modifications locales ;
- exposer davantage de ports ou de volumes ;
- permettre de travailler sur le code plus rapidement.

Dans notre stratégie, ce fichier doit être lu et compris, mais il ne faut pas supposer qu'il est utilisé automatiquement. Il faut toujours vérifier la commande de démarrage utilisée.

### 4.3 Absence D'override Actuel

Il n'existe pas encore d'override local pour l'architecture à deux Logstash.

Cela veut dire que l'ajout de deux Logstash devra être fait proprement dans un nouveau fichier, par exemple :

```text
docker-compose.local-2logstash.yml
```

Ce choix est important parce qu'il permet :

- de garder le fichier officiel intact ;
- de pouvoir activer ou désactiver facilement le mode deux Logstash ;
- de documenter clairement ce qui est spécifique à notre environnement de test ;
- de revenir en arrière rapidement si besoin.

## 5. Services Principaux Identifiés Dans `docker-compose.yml`

La lecture du fichier principal montre les services suivants :

| Service | Rôle Simple |
|---|---|
| `opensearch` | Stockage central indexé. Il conserve les événements, logs, alertes et métadonnées pour permettre les recherches. |
| `dashboards` | Interface web de visualisation basée sur OpenSearch Dashboards. |
| `dashboards-helper` | Service d'aide qui prépare ou maintient certains éléments nécessaires aux dashboards. |
| `logstash` | Moteur de traitement. Il reçoit les événements, les parse, les normalise, les enrichit, puis les envoie vers OpenSearch. |
| `filebeat` | Agent de collecte. Il lit les logs produits par Zeek, Suricata, filescan et autres sources, puis les envoie vers Logstash. |
| `arkime` | Analyse offline et investigation des PCAP. |
| `arkime-live` | Capture et sessionisation réseau en mode live. |
| `zeek` | Analyse protocolaires des PCAP en mode offline. |
| `zeek-live` | Analyse protocolaires du trafic réseau en direct. |
| `suricata` | Analyse IDS des PCAP en mode offline. |
| `suricata-live` | Détection IDS sur trafic live. |
| `filescan` | Analyse des fichiers extraits. |
| `strelka-*` | Analyse avancée de fichiers et orchestration associée. |
| `pcap-capture` | Capture ou gestion de PCAP selon configuration. |
| `pcap-monitor` | Surveillance et orchestration des PCAP déposés. |
| `upload` | Interface ou service de dépôt de fichiers PCAP/logs. |
| `htadmin` | Gestion des comptes selon le mode d'authentification retenu. |
| `freq` | Analyse auxiliaire de fréquence ou d'observations. |
| `netbox` | Inventaire, contexte réseau et gestion d'actifs. |
| `postgres` | Base de données relationnelle utilisée notamment par NetBox et/ou Keycloak selon la configuration. |
| `valkey` | Cache ou file légère utilisée par certains composants. |
| `valkey-cache` | Cache additionnel séparé selon les besoins internes. |
| `api` | API Malcolm/Oculox. |
| `keycloak` | Fournisseur d'identité si ce mode d'authentification est activé. |
| `nginx-proxy` | Point d'entrée web HTTPS et reverse proxy vers les services internes. |

## 6. Lecture Des Services Filebeat Et Logstash

Cette partie est essentielle parce que notre futur objectif est d'ajouter un deuxième Logstash.

### 6.1 Service `logstash`

Dans `docker-compose.yml`, le service `logstash` utilise l'image :

```text
ghcr.io/idaholab/malcolm/logstash-oss:26.06.0
```

Il charge plusieurs fichiers de configuration :

```text
./config/process.env
./config/ssl.env
./config/opensearch.env
./config/netbox-common.env
./config/netbox.env
./config/netbox-secret.env
./config/filescan.env
./config/beats-common.env
./config/lookup-common.env
./config/logstash.env
```

Ces fichiers servent à donner à Logstash ses paramètres d'exécution.

Logstash dépend de :

```text
opensearch
```

Cela veut dire que Logstash a besoin d'OpenSearch pour fonctionner correctement, car il doit écrire les événements traités dans OpenSearch.

Logstash utilise aussi ce volume :

```text
logstash-persistent-queue:/logstash-persistent-queue
```

Ce volume est très important.

Une queue persistante est une file d'attente écrite sur disque. Elle permet à Logstash de tamponner temporairement des événements si la sortie vers OpenSearch ralentit ou si le pipeline prend du retard.

Pour une architecture à deux Logstash, il ne faudra pas partager cette queue entre les deux instances. Chaque Logstash devra avoir sa propre queue.

### 6.2 Service `filebeat`

Dans `docker-compose.yml`, le service `filebeat` utilise l'image :

```text
ghcr.io/idaholab/malcolm/filebeat-oss:26.06.0
```

Il charge plusieurs fichiers de configuration :

```text
./config/process.env
./config/ssl.env
./config/opensearch.env
./config/upload-common.env
./config/nginx.env
./config/valkey.env
./config/zeek.env
./config/beats-common.env
./config/netbox-common.env
./config/filebeat.env
```

Filebeat lit notamment ces dossiers :

```text
./zeek-logs      -> /zeek
./suricata-logs  -> /suricata
./filescan-logs  -> /filescan
```

Lecture simple :

- les analyseurs produisent des logs dans les dossiers locaux ;
- Filebeat voit ces dossiers dans son conteneur ;
- Filebeat lit les nouveaux fichiers ou nouvelles lignes ;
- Filebeat envoie les événements à Logstash.

### 6.3 Variable `LOGSTASH_HOST`

Dans le modèle suivant :

```text
config/beats-common.env.example
```

on trouve :

```env
LOGSTASH_HOST=logstash:5044
```

Cela veut dire qu'aujourd'hui, la configuration par défaut pointe vers un seul Logstash :

```text
logstash:5044
```

Pour aller vers deux Logstash, cette partie devra être étudiée précisément. La cible future sera proche de :

```yaml
output.logstash:
  hosts: ["logstash:5044", "logstash2:5044"]
  loadbalance: true
```

Mais il ne faut pas encore modifier cela sans vérifier comment Malcolm génère réellement les fichiers Filebeat au démarrage.

## 7. Fichiers `.env.example` Présents Dans `config/`

Le dossier `config/` contient des modèles de configuration.

Les fichiers trouvés sont notamment :

```text
arkime-live.env.example
arkime-offline.env.example
arkime-secret.env.example
arkime.env.example
auth-common.env.example
auth.env.example
beats-common.env.example
dashboards-helper.env.example
dashboards.env.example
filebeat.env.example
filescan-secret.env.example
filescan.env.example
keycloak.env.example
logstash.env.example
lookup-common.env.example
netbox-common.env.example
netbox-secret.env.example
netbox.env.example
nginx.env.example
opensearch.env.example
pcap-capture.env.example
pipeline.env.example
postgres.env.example
process.env.example
ssl.env.example
suricata-live.env.example
suricata-offline.env.example
suricata.env.example
upload-common.env.example
valkey.env.example
zeek-live.env.example
zeek-offline.env.example
zeek.env.example
```

Ces fichiers ne sont pas tous à modifier. Pour notre objectif deux Logstash, les plus importants au départ sont :

| Fichier | Pourquoi Il Est Important |
|---|---|
| `beats-common.env.example` | Contient `LOGSTASH_HOST`, donc le point de sortie Filebeat vers Logstash. |
| `filebeat.env.example` | Contient les paramètres de lecture et de nettoyage des logs par Filebeat. |
| `logstash.env.example` | Contient les paramètres de performance Logstash : workers, batch, heap JVM, enrichissement, etc. |
| `opensearch.env.example` | Contient les paramètres OpenSearch : mémoire, rétention, index, sécurité, etc. |
| `ssl.env.example` | Contient les paramètres liés au chiffrement/TLS. |
| `process.env.example` | Contient des paramètres généraux de fonctionnement des conteneurs. |

## 8. Variables Logstash Observées

Dans `config/logstash.env.example`, on trouve notamment :

```env
pipeline.workers=2
pipeline.batch.size=125
pipeline.batch.delay=25
pipeline.ordered=false
LS_JAVA_OPTS=-server -Xmx3g -Xms3g ...
```

Explication simple :

- `pipeline.workers` : nombre de travailleurs Logstash utilisés pour traiter les événements dans un pipeline ;
- `pipeline.batch.size` : nombre d'événements que Logstash peut traiter par lot ;
- `pipeline.batch.delay` : délai maximal d'attente avant de traiter un lot incomplet ;
- `pipeline.ordered=false` : Logstash n'oblige pas le maintien strict de l'ordre des événements, ce qui peut améliorer les performances ;
- `LS_JAVA_OPTS` : paramètres Java de Logstash, notamment la mémoire JVM.

La JVM est la machine virtuelle Java. Logstash est une application Java. La heap JVM est la mémoire principale utilisée par Logstash pour traiter les événements.

Ici, le modèle indique :

```text
-Xmx3g -Xms3g
```

Cela signifie que Logstash utilise une heap Java de 3 Go.

## 9. Variables Filebeat Observées

Dans `config/filebeat.env.example`, on trouve notamment :

```env
FILEBEAT_SCAN_FREQUENCY=10s
FILEBEAT_CLEAN_INACTIVE=180m
FILEBEAT_IGNORE_OLDER=120m
FILEBEAT_CLOSE_INACTIVE=120s
FILEBEAT_CLOSE_INACTIVE_LIVE=90m
LOG_CLEANUP_MINUTES=360
ZIP_CLEANUP_MINUTES=720
```

Explication simple :

- `FILEBEAT_SCAN_FREQUENCY=10s` : Filebeat vérifie les fichiers toutes les 10 secondes ;
- `FILEBEAT_IGNORE_OLDER=120m` : Filebeat peut ignorer certains fichiers trop anciens ;
- `FILEBEAT_CLOSE_INACTIVE` : Filebeat ferme un fichier s'il n'évolue plus pendant un certain temps ;
- `LOG_CLEANUP_MINUTES=360` : les logs déjà traités peuvent être nettoyés après 360 minutes ;
- `ZIP_CLEANUP_MINUTES=720` : les archives compressées peuvent être nettoyées après 720 minutes.

Ces variables sont importantes pour éviter que les logs Zeek ou Suricata remplissent le disque.

## 10. Point Important Pour Le Futur Deux Logstash

Le point clé découvert dans cette étape est le suivant :

```env
LOGSTASH_HOST=logstash:5044
```

Aujourd'hui, Filebeat est configuré pour envoyer vers un seul Logstash.

Pour utiliser deux Logstash, il faudra comprendre et modifier proprement la configuration Filebeat afin d'obtenir une logique équivalente à :

```yaml
output.logstash:
  hosts: ["logstash:5044", "logstash2:5044"]
  loadbalance: true
```

Mais avant cela, il faut vérifier :

- si `LOGSTASH_HOST` accepte plusieurs hôtes ;
- si Filebeat génère sa configuration depuis `filebeat/scripts/filebeat.sh` ;
- si les fichiers `filebeat-logs.yml`, `filebeat-nginx.yml`, `filebeat-tcp.yml`, etc. utilisent directement cette variable ;
- si le TLS accepte le nom `logstash2` ;
- si chaque Logstash a bien sa propre queue persistante.

## 11. Commandes Utilisées Pour Cette Étape

Lister les fichiers d'orchestration et de configuration :

```bash
find /home/kakashi_/ICSHUB/Oculox -maxdepth 2 \
  \( -name 'docker-compose*.yml' -o -name 'compose*.yml' -o -path '*/config/*.env' -o -path '*/config/*.env.example' \) \
  -print | sort
```

Vérifier l'état Git du dépôt :

```bash
git -C /home/kakashi_/ICSHUB/Oculox status --short
git -C /home/kakashi_/ICSHUB/Oculox remote -v
git -C /home/kakashi_/ICSHUB/Oculox log -1 --oneline
```

Lister les services Docker déclarés :

```bash
grep -nE '^  [a-zA-Z0-9_-]+:' /home/kakashi_/ICSHUB/Oculox/docker-compose.yml
```

Chercher où Filebeat pointe vers Logstash :

```bash
rg -n "LOGSTASH_HOST|output\.logstash|loadbalance|hosts:" \
  /home/kakashi_/ICSHUB/Oculox/filebeat \
  /home/kakashi_/ICSHUB/Oculox/config \
  /home/kakashi_/ICSHUB/Oculox/scripts \
  /home/kakashi_/ICSHUB/Oculox/docker-compose.yml
```

## 12. Conclusion De La Sous-Étape 1

L'orchestration actuelle repose principalement sur :

```text
docker-compose.yml
docker-compose-dev.yml
```

Le dépôt local ne contient pas encore d'override spécifique pour deux Logstash.

Les vrais fichiers `config/*.env` ne sont pas versionnés, ce qui est normal et sain pour la sécurité. Le dépôt contient les modèles `config/*.env.example`.

Le point technique majeur pour la suite est que Filebeat pointe aujourd'hui vers un seul Logstash avec :

```env
LOGSTASH_HOST=logstash:5044
```

La prochaine sous-étape de la Phase 1 devra donc analyser plus précisément :

- comment `filebeat/scripts/filebeat.sh` construit ou lance les configurations Filebeat ;
- comment les fichiers `filebeat-*.yml` utilisent `LOGSTASH_HOST` ;
- comment Logstash charge ses pipelines ;
- comment les certificats TLS sont utilisés entre Filebeat et Logstash.

Cette compréhension est nécessaire avant de modifier l'architecture.

# Phase 1 - Filebeat, Logstash, TLS Et Persistance

## 1. Objectif Du Document

Ce document étudie en détail la partie du pipeline située entre les fichiers de logs produits par les analyseurs réseau et leur stockage dans OpenSearch :

```text
Logs Zeek / Suricata / filescan
             |
             v
         Filebeat
             |
       Beats sur TCP/5044
             |
             v
          Logstash
             |
     parsing et enrichissement
             |
             v
         OpenSearch
```

L'objectif est de comprendre précisément :

- comment Filebeat découvre et lit les fichiers ;
- ce que signifie `LOGSTASH_HOST` ;
- comment Logstash reçoit les événements sur le port `5044` ;
- comment les pipelines Logstash se transmettent les événements ;
- à quoi sert une file persistante ;
- ce que TLS protège réellement ;
- quelles données survivent au redémarrage des conteneurs.

L'analyse porte sur les fichiers sources de la version locale Oculox/Malcolm `26.06.0`. Les fichiers `config/*.env` réels sont générés pendant la configuration et ne sont pas versionnés. Les fichiers `config/*.env.example` indiquent donc les valeurs proposées par défaut, mais une installation en fonctionnement peut avoir des valeurs différentes.

---

## 2. Les Trois Notions À Ne Pas Confondre

Avant d'étudier les fichiers, il faut séparer trois fonctions différentes.

### 2.1 Filebeat Transporte Les Événements

Filebeat surveille des fichiers de logs, lit les nouvelles lignes et les envoie à Logstash.

Filebeat n'effectue pas l'analyse réseau initiale. Il ne remplace ni Zeek, ni Suricata, ni Arkime. Il intervient après la production des logs.

### 2.2 Logstash Transforme Les Événements

Logstash reçoit les lignes envoyées par Filebeat. Il les parse, les normalise, les enrichit et les prépare pour OpenSearch.

Par exemple, une ligne Zeek brute peut contenir une adresse IP, un port, un protocole et une durée. Logstash transforme ces valeurs en champs structurés et cohérents, utilisables dans les recherches et les tableaux de bord.

### 2.3 OpenSearch Stocke Et Indexe Les Événements

OpenSearch conserve les documents structurés et construit des index permettant de les rechercher rapidement.

Ainsi :

```text
Filebeat = lecteur et transporteur
Logstash = transformateur
OpenSearch = stockage indexé et moteur de recherche
```

---

## 3. Configuration Filebeat

## 3.1 Où Le Service Est-il Déclaré ?

Le service `filebeat` est déclaré dans `docker-compose.yml`.

Les éléments importants sont :

```yaml
filebeat:
  image: ghcr.io/idaholab/malcolm/filebeat-oss:26.06.0
  profiles: ["malcolm", "hedgehog"]
  env_file:
    - ./config/beats-common.env
    - ./config/filebeat.env
```

Le même conteneur peut être utilisé dans les deux profils :

- `malcolm` : plateforme principale ;
- `hedgehog` : collecteur distant.

En revanche, le service `logstash` appartient uniquement au profil `malcolm`. Cela signifie qu'un collecteur Hedgehog lit ses logs avec Filebeat puis les expédie vers le Logstash de la plateforme principale.

## 3.2 Quels Répertoires Filebeat Lit-il ?

Le Compose monte les répertoires de l'hôte dans le conteneur :

```yaml
- source: ./zeek-logs
  target: /zeek

- source: ./suricata-logs
  target: /suricata

- source: ./filescan-logs
  target: /filescan
```

Il faut bien distinguer les deux chemins :

| Chemin sur l'hôte | Chemin vu par Filebeat |
|---|---|
| `./zeek-logs` | `/zeek` |
| `./suricata-logs` | `/suricata` |
| `./filescan-logs` | `/filescan` |

Filebeat ne connaît pas directement le chemin de l'hôte. Dans le conteneur, il ne voit que `/zeek`, `/suricata` et `/filescan`.

## 3.3 Les Entrées De Fichiers

Le fichier principal est `filebeat/filebeat-logs.yml`.

Il contient plusieurs entrées `filestream`. Une entrée indique à Filebeat :

1. quels fichiers surveiller ;
2. comment reconnaître un fichier ;
3. quand le considérer comme inactif ;
4. quel tag ajouter aux événements.

Exemple pour les logs Zeek offline :

```yaml
- type: filestream
  id: zeek-upload
  paths:
    - ${FILEBEAT_ZEEK_LOG_PATH:/zeek/current}/*.log
  tags: ["_filebeat_zeek_malcolm_upload"]
```

Exemple pour les logs Zeek live :

```yaml
- type: filestream
  id: zeek-live
  paths:
    - ${FILEBEAT_ZEEK_LOG_LIVE_PATH:/zeek/live}/spool/logger-*/*.log
  tags: ["_filebeat_zeek_malcolm_live"]
```

Le tag est très important. Il indique ensuite à Logstash quel pipeline doit traiter l'événement.

Par exemple :

```text
_filebeat_zeek_malcolm_live
             |
             v
       pipeline Zeek
```

Le même principe est appliqué aux événements Suricata :

```text
_filebeat_suricata_malcolm_live
             |
             v
     pipeline Suricata
```

## 3.4 Les Paramètres De Surveillance

Les valeurs proposées se trouvent dans `config/filebeat.env.example`.

### `FILEBEAT_SCAN_FREQUENCY=10s`

Filebeat vérifie régulièrement si de nouveaux fichiers ou de nouvelles lignes sont apparus. La valeur `10s` correspond à un intervalle de dix secondes.

Ce n'est pas une durée de transport réseau. C'est la fréquence de découverte des changements dans les fichiers.

### `FILEBEAT_CLOSE_INACTIVE=120s`

Pour un fichier non live, Filebeat peut fermer son descripteur après 120 secondes sans nouvelle donnée.

Fermer le descripteur ne supprime pas le fichier et n'efface pas sa position de lecture.

### `FILEBEAT_CLOSE_INACTIVE_LIVE=90m`

Les fichiers live restent ouverts plus longtemps, car Zeek ou Suricata peuvent continuer à y écrire.

### `FILEBEAT_IGNORE_OLDER=120m`

Un fichier trop ancien peut être ignoré selon cette règle. Cette valeur doit être étudiée avec prudence lors d'une ingestion offline contenant des fichiers ou timestamps anciens.

### `LOG_CLEANUP_MINUTES=360`

Les logs déjà traités peuvent être supprimés du système de fichiers après 360 minutes, selon le mécanisme de nettoyage activé.

Ce paramètre concerne la conservation des fichiers sources. Il ne définit pas la rétention des index OpenSearch.

### `ZIP_CLEANUP_MINUTES=720`

Les archives compressées déjà traitées peuvent être supprimées après 720 minutes.

Là encore, il s'agit du nettoyage des fichiers, pas des documents indexés dans OpenSearch.

## 3.5 Le Registre Filebeat

Filebeat doit se souvenir de sa position dans chaque fichier.

Exemple :

```text
eve.json contient 1 000 000 lignes
Filebeat a confirmé les 700 000 premières
position mémorisée = ligne ou offset correspondant à 700 000
```

Si Filebeat redémarre, il consulte son registre et reprend près de la dernière position connue au lieu de relire volontairement tout le fichier.

Dans le Compose, le registre principal est stocké dans un volume nommé :

```yaml
- filebeat-logs-registry:/usr/share/filebeat-logs/data
```

Sans ce volume persistant, la position de lecture disparaîtrait avec le conteneur. Filebeat pourrait alors relire des données ou ne plus savoir précisément où reprendre.

Le registre ne contient pas les logs eux-mêmes. Il contient principalement l'état de lecture des fichiers.

## 3.6 Ce Qui Se Passe Au Démarrage

Le script `filebeat/scripts/filebeat.sh` :

1. lit les variables d'environnement ;
2. utilise `logstash:5044` si `LOGSTASH_HOST` n'est pas défini ;
3. génère la configuration effective ;
4. démarre Filebeat avec son répertoire de données persistant.

Si `LOGSTASH_HOST` est vide ou vaut `disabled`, le script n'expédie pas les événements à Logstash. Filebeat reste alors volontairement en attente.

---

## 4. La Variable `LOGSTASH_HOST`

## 4.1 Valeur Par Défaut

Le fichier `config/beats-common.env.example` propose :

```dotenv
BEATS_SSL=true
LOGSTASH_HOST=logstash:5044
```

La variable est injectée dans `filebeat/filebeat-logs.yml` :

```yaml
output.logstash:
  hosts: ["${LOGSTASH_HOST:logstash:5044}"]
```

## 4.2 Signification De `logstash:5044`

Cette valeur contient deux informations :

```text
logstash : nom DNS du service Docker
5044     : port TCP du protocole Beats
```

Dans le réseau Docker, le nom de service `logstash` est résolu vers l'adresse IP du conteneur Logstash.

Il ne s'agit pas obligatoirement du nom de la machine physique. C'est le DNS interne fourni par Docker Compose.

## 4.3 Cas Du Malcolm Principal

Quand Filebeat et Logstash appartiennent au même projet Compose :

```dotenv
LOGSTASH_HOST=logstash:5044
```

Le trafic reste dans le réseau Docker du projet.

## 4.4 Cas Du Collecteur Hedgehog

Sur un collecteur distant, `logstash` ne désigne pas automatiquement le conteneur du serveur principal. Il faut utiliser une adresse joignable du Malcolm principal, généralement :

```dotenv
LOGSTASH_HOST=<nom-dns-ou-adresse-du-principal>:5044
```

Le port doit également être exposé par le principal. La documentation Malcolm précise que l'exposition de Logstash doit être activée pendant la configuration des ports de service.

Ainsi, deux conditions sont nécessaires :

1. Filebeat connaît l'adresse du principal ;
2. le principal accepte les connexions TCP vers son entrée Beats.

## 4.5 Ce Que `LOGSTASH_HOST` Ne Fait Pas

`LOGSTASH_HOST` :

- ne démarre pas Logstash ;
- ne configure pas les pipelines Logstash ;
- ne crée pas les certificats ;
- ne garantit pas que le port est joignable ;
- ne configure pas OpenSearch.

Cette variable indique uniquement la destination de sortie de Filebeat.

---

## 5. L'entrée Beats De Logstash Sur Le Port 5044

## 5.1 Configuration Exacte

Le fichier `logstash/pipelines/input/01_beats_input.conf` contient :

```ruby
input {
  beats {
    id => "input_beats"
    host => "0.0.0.0"
    port => 5044
    ssl_enabled => "${BEATS_SSL:false}"
    ssl_certificate_authorities => ["/certs/ca.crt"]
    ssl_certificate => "/certs/server.crt"
    ssl_key => "/certs/server.key"
    ssl_client_authentication => "optional"
  }
}
```

## 5.2 Signification De Chaque Ligne

### `input { beats { ... } }`

Logstash charge le plugin d'entrée Beats. Ce plugin comprend le protocole utilisé par Filebeat.

Le port `5044` n'est donc pas un serveur web et n'attend pas une requête HTTP. Il attend une connexion Filebeat/Beats.

### `host => "0.0.0.0"`

Logstash écoute sur toutes les interfaces réseau disponibles dans son conteneur.

`0.0.0.0` ne signifie pas « toutes les machines sont automatiquement autorisées ». Les règles Docker, l'exposition de port, le pare-feu et TLS continuent de s'appliquer.

### `port => 5044`

Le processus Logstash écoute sur le port TCP `5044` dans le conteneur.

### `ssl_enabled`

Cette option active ou désactive TLS en fonction de `BEATS_SSL`.

### Certificat Et Clé Serveur

```ruby
ssl_certificate => "/certs/server.crt"
ssl_key => "/certs/server.key"
```

Logstash présente son certificat et utilise sa clé privée pour établir la session TLS.

### `ssl_client_authentication => "optional"`

Logstash peut demander et vérifier le certificat présenté par Filebeat, mais la configuration source ne rend pas cette authentification client strictement obligatoire.

Cette nuance est importante : le transport peut être chiffré sans constituer une authentification mutuelle stricte obligatoire.

## 5.3 Port Interne Et Port Exposé

Il faut distinguer :

```text
Port interne : Logstash écoute dans son conteneur sur 5044
Port exposé  : l'hôte publie éventuellement ce port vers le réseau externe
```

Dans le Compose de base étudié, le service Logstash ne possède pas directement un bloc `ports:`. L'exposition vers un collecteur distant est ajoutée ou activée par la configuration Malcolm.

Un Logstash peut donc écouter correctement dans son conteneur sans être joignable depuis une autre machine.

---

## 6. Les Pipelines Logstash

## 6.1 Qu'est-ce Qu'un Pipeline ?

Un pipeline Logstash est une chaîne composée de trois parties :

```text
input -> filter -> output
```

- `input` reçoit les événements ;
- `filter` les transforme ;
- `output` les transmet à la destination suivante.

Une analogie simple est une chaîne de tri industrielle :

```text
Réception de la matière
        |
        v
Identification et transformation
        |
        v
Expédition vers le stockage
```

## 6.2 Pourquoi Malcolm Utilise Plusieurs Pipelines

Un seul gros pipeline serait difficile à comprendre et à maintenir. Malcolm sépare donc les responsabilités :

```text
malcolm-input
    |
    +--> malcolm-zeek
    |
    +--> malcolm-suricata
    |
    +--> malcolm-filescan
    |
    +--> malcolm-beats
              |
              v
     malcolm-enrichment
              |
              v
        malcolm-output
              |
              v
          OpenSearch
```

## 6.3 Construction Dynamique Au Démarrage

Le fichier final `pipelines.yml` n'est pas entièrement écrit à la main dans le dépôt.

Le script `logstash/scripts/logstash-start.sh` :

1. parcourt les sous-répertoires de `logstash/pipelines/` ;
2. crée un pipeline `malcolm-<nom>` pour chaque sous-répertoire utile ;
3. génère le fichier `/usr/share/logstash/config/pipelines.yml` dans le conteneur ;
4. génère le routage selon les tags Filebeat ;
5. démarre Logstash.

Cela signifie que la configuration réellement exécutée est une configuration générée à l'intérieur du conteneur.

## 6.4 Pipeline `malcolm-input`

Ce pipeline reçoit les connexions Beats sur le port `5044`.

Il possède explicitement :

```yaml
pipeline.workers: 1
```

Son rôle principal est de recevoir et router. Il n'effectue pas tout le parsing Zeek ou Suricata.

Le fichier `logstash/maps/parse_pipelines.yaml` associe les tags aux pipelines.

Exemple :

```yaml
zeek-parse:
  - _filebeat_zeek_malcolm_live
  - _filebeat_zeek_malcolm_upload
```

## 6.5 Pipeline `malcolm-zeek`

Il reçoit les événements portant un tag Zeek.

Il contient de nombreux filtres spécifiques aux protocoles, notamment BACnet, DNP3, EtherNet/IP, Modbus, MQTT, OPC UA, S7, Synchrophasor et d'autres protocoles réseau.

Il transforme les champs Zeek en documents normalisés, puis les transmet vers l'enrichissement.

## 6.6 Pipeline `malcolm-suricata`

Il reçoit les événements Suricata issus de `eve.json`.

Il :

- parse le JSON ;
- distingue les alertes, flux, DNS, HTTP, TLS et autres types ;
- normalise les champs ;
- calcule certains champs de sévérité et d'identification ;
- transmet les événements vers l'enrichissement.

## 6.7 Pipeline `malcolm-enrichment`

Ce pipeline ajoute du contexte aux événements déjà parsés.

Selon les variables actives, il peut notamment effectuer :

- des correspondances de champs ;
- une conversion de types ;
- un enrichissement NetBox ;
- une comparaison de segments réseau ;
- un scoring de sévérité ;
- la préparation des champs Arkime/ECS.

L'enrichissement peut devenir coûteux en CPU lorsque le nombre d'événements augmente fortement.

## 6.8 Pipeline `malcolm-output`

Le pipeline de sortie reçoit les événements finalisés et les écrit dans OpenSearch.

Il utilise une URL HTTPS vers le service OpenSearch et sélectionne l'index à partir des métadonnées préparées en amont.

## 6.9 Les Communications Entre Pipelines

Les lignes suivantes sont utilisées :

```ruby
pipeline {
  send_to => ["log-enrichment"]
}
```

et :

```ruby
pipeline {
  address => "log-enrichment"
}
```

Ces adresses ne sont pas des ports réseau. Ce sont des canaux internes au processus Logstash.

La distinction est donc :

```text
TCP/5044          = communication réseau Filebeat -> Logstash
log-enrichment    = communication interne entre deux pipelines Logstash
```

## 6.10 Paramètres De Performance

Le fichier `config/logstash.env.example` propose :

```dotenv
pipeline.workers=2
pipeline.batch.size=125
pipeline.batch.delay=25
pipeline.ordered=false
```

### `pipeline.workers=2`

Deux threads de travail peuvent exécuter les filtres et sorties d'un pipeline, sauf lorsqu'un pipeline possède sa propre valeur, comme `malcolm-input` avec un worker.

Un worker n'est pas un processeur entier réservé. C'est un thread de traitement que le système d'exploitation exécute sur les CPU disponibles.

### `pipeline.batch.size=125`

Chaque worker peut traiter jusqu'à 125 événements par lot.

Avec deux workers, plusieurs lots peuvent être en cours simultanément. Une valeur plus grande peut augmenter le débit, mais également la mémoire utilisée et la durée d'un traitement lourd.

### `pipeline.batch.delay=25`

Logstash peut attendre au maximum 25 millisecondes pour compléter un lot avant de le traiter.

### `pipeline.ordered=false`

Logstash ne garantit pas un ordre strict entre tous les événements lorsque le traitement parallèle est utilisé.

## 6.11 Mémoire Java

Logstash est une application Java exécutée dans une JVM, la machine virtuelle Java.

La configuration proposée contient :

```dotenv
LS_JAVA_OPTS=-server -Xmx3g -Xms3g ...
```

- `-Xms3g` : la JVM démarre avec un tas de 3 Gio ;
- `-Xmx3g` : le tas ne peut pas dépasser 3 Gio.

Le tas, ou heap, est la zone mémoire utilisée pour les objets Java : événements, structures de parsing, lots et états temporaires.

Cette mémoire n'est pas nécessairement toute la mémoire du conteneur. Java et les bibliothèques utilisent également de la mémoire hors heap.

---

## 7. La File Persistante Logstash

## 7.1 Problème Résolu Par Une File

Supposons que Filebeat envoie plus vite qu'OpenSearch ne peut écrire :

```text
Filebeat ---> Logstash ---> OpenSearch lent
```

Logstash a besoin d'une zone tampon. Cette zone absorbe temporairement la différence de vitesse.

Une file en mémoire est rapide, mais disparaît si le processus ou la machine s'arrête brutalement.

Une file persistante écrit les événements acceptés sur disque avant leur traitement complet.

## 7.2 Fonctionnement Simplifié

```text
1. Logstash reçoit un événement
2. Logstash l'ajoute à la file
3. Un worker le retire de la file
4. Les filtres le traitent
5. OpenSearch confirme l'écriture
6. Logstash acquitte définitivement l'événement dans la file
```

Si Logstash redémarre entre les étapes 2 et 5, une file persistante peut permettre de reprendre l'événement présent sur disque.

## 7.3 Configuration Trouvée Dans Le Dépôt

Le fichier `logstash/pipelines/external/00_config.conf` contient :

```yaml
queue.type: persisted
queue.max_bytes: 4gb
path.queue: "/logstash-persistent-queue"
```

Signification :

- `queue.type: persisted` : la file est stockée sur disque ;
- `queue.max_bytes: 4gb` : sa taille maximale est de 4 Go ;
- `path.queue` : chemin de stockage dans le conteneur.

## 7.4 Point Critique Sur La Configuration Actuelle

Cette configuration appartient au pipeline `external`, utilisé pour une destination OpenSearch secondaire ou distante.

Le script de démarrage exclut ce pipeline lorsqu'aucune destination secondaire n'est configurée.

Les pipelines principaux `input`, `zeek`, `suricata`, `enrichment` et `output` ne déclarent pas `queue.type: persisted` dans les fichiers sources étudiés. Ils utilisent donc la file mémoire par défaut, sauf modification dans la configuration réellement générée d'une installation.

Conclusion exacte :

> Le dépôt déclare un volume nommé pour une file persistante, mais cela ne signifie pas que tout le chemin principal Filebeat vers OpenSearch est protégé par cette file.

La présence du volume et l'activation de la file sont deux choses différentes.

## 7.5 Ce Que La File Persistante Protège

Une file persistante protège surtout contre :

- un redémarrage de Logstash ;
- une indisponibilité temporaire de la sortie ;
- un ralentissement court d'OpenSearch ;
- une différence temporaire entre débit d'entrée et débit de traitement.

## 7.6 Ce Qu'elle Ne Protège Pas

Elle ne garantit pas :

- une capacité illimitée ;
- l'absence de doublons dans tous les cas ;
- la conservation si son volume est supprimé ;
- la conservation des fichiers sources supprimés trop tôt ;
- la résilience à la perte du disque hôte ;
- la haute disponibilité de Logstash.

Quand la file atteint sa taille maximale, Logstash applique une contre-pression. Il ralentit ou cesse temporairement d'accepter de nouveaux événements. Cette pression remonte alors vers Filebeat.

## 7.7 Relation Avec Le Registre Filebeat

Les deux mécanismes sont complémentaires :

```text
Registre Filebeat
  = où Filebeat en est dans chaque fichier

File persistante Logstash
  = événements déjà acceptés par Logstash mais pas encore finalisés
```

Le registre ne remplace pas la file persistante, et la file persistante ne remplace pas le registre.

## 7.8 Conséquence Pour Deux Logstash

Dans une future architecture avec deux instances Logstash, chaque instance doit avoir sa propre file et son propre volume.

```text
Logstash 1 -> volume PQ 1
Logstash 2 -> volume PQ 2
```

Deux instances ne doivent pas écrire simultanément dans le même `path.queue`. Une file persistante n'est pas une base partagée conçue pour plusieurs Logstash.

---

## 8. Les Certificats TLS

## 8.1 Objectif De TLS

TLS protège le transport entre Filebeat et Logstash.

Il apporte principalement :

- la confidentialité : un tiers ne lit pas facilement les événements en transit ;
- l'intégrité : une modification du trafic peut être détectée ;
- une forme d'authentification par certificat, selon le mode de vérification choisi.

TLS ne chiffre pas automatiquement les fichiers sur disque ni les index OpenSearch au repos.

## 8.2 Fichiers Côté Logstash

Le Compose monte :

```text
logstash/certs/ca.crt     -> /certs/ca.crt
logstash/certs/server.crt -> /certs/server.crt
logstash/certs/server.key -> /certs/server.key
```

- `ca.crt` : certificat de l'autorité de certification ;
- `server.crt` : certificat public présenté par Logstash ;
- `server.key` : clé privée du serveur, qui doit rester secrète.

Les montages sont en lecture seule dans le conteneur.

## 8.3 Fichiers Côté Filebeat

Le Compose monte :

```text
filebeat/certs/ca.crt     -> /certs/ca.crt
filebeat/certs/client.crt -> /certs/client.crt
filebeat/certs/client.key -> /certs/client.key
```

- `client.crt` identifie le client ;
- `client.key` est sa clé privée ;
- `ca.crt` permet de connaître l'autorité de confiance.

## 8.4 Génération Et Distribution

Les dossiers `filebeat/certs/` et `logstash/certs/` ne contiennent dans Git qu'un `.gitignore` :

```gitignore
*
!.gitignore
```

Tous les vrais certificats et toutes les clés sont donc exclus du dépôt.

La documentation et le code indiquent que `./scripts/auth_setup` :

1. génère les certificats serveur pour Logstash ;
2. génère un certificat client signé par la même autorité ;
3. place les fichiers serveur dans `logstash/certs/` ;
4. place ou transfère les fichiers client vers `filebeat/certs/` du collecteur.

Ce comportement est correct : les clés privées ne doivent pas être publiées dans Git.

## 8.5 Configuration Côté Filebeat

Le fichier de sortie contient :

```yaml
ssl.enabled: ${BEATS_SSL:false}
ssl.certificate_authorities: ["/certs/ca.crt"]
ssl.certificate: "/certs/client.crt"
ssl.key: "/certs/client.key"
ssl.supported_protocols: "TLSv1.2"
ssl.verification_mode: "none"
```

Avec `BEATS_SSL=true`, les données sont chiffrées pendant le transport.

Cependant, `ssl.verification_mode: "none"` signifie que Filebeat ne vérifie pas strictement l'identité du serveur Logstash. Il ne valide notamment pas que le nom demandé correspond au certificat comme le ferait un mode de vérification complet.

## 8.6 Configuration Côté Logstash

Logstash utilise :

```ruby
ssl_client_authentication => "optional"
```

Le certificat client est donc pris en charge, mais n'est pas rendu obligatoire par ce paramètre.

## 8.7 Conclusion De Sécurité Exacte

La configuration par défaut étudiée fournit bien un transport TLS lorsque `BEATS_SSL=true`.

En revanche, elle n'impose pas la validation la plus stricte possible des deux identités :

- Filebeat utilise `verification_mode: none` ;
- Logstash utilise une authentification client `optional`.

Il est donc juste de dire :

> Le flux Filebeat vers Logstash est chiffré par TLS, mais la validation mutuelle stricte des certificats n'est pas imposée dans les fichiers sources étudiés.

## 8.8 Rotation Des Certificats

Un certificat possède une période de validité. Une exploitation professionnelle doit prévoir :

- l'inventaire des certificats ;
- le contrôle de leur date d'expiration ;
- leur renouvellement avant expiration ;
- la révocation ou le remplacement en cas de compromission ;
- une distribution sécurisée vers chaque collecteur.

Copier une fois les certificats puis les oublier n'est pas une politique de gestion des certificats.

---

## 9. Les Volumes Persistants

## 9.1 Pourquoi Un Conteneur A Besoin De Persistance

Le système de fichiers interne d'un conteneur est remplaçable. Quand Docker recrée le conteneur, les données écrites uniquement dans sa couche interne peuvent disparaître.

Les données importantes doivent donc être placées :

- dans un volume Docker nommé ;
- ou dans un répertoire de l'hôte monté dans le conteneur.

## 9.2 Volume Nommé

Exemple :

```yaml
volumes:
  filebeat-logs-registry:
```

Utilisation :

```yaml
- filebeat-logs-registry:/usr/share/filebeat-logs/data
```

Docker choisit le chemin physique de stockage sur l'hôte et gère le volume.

## 9.3 Bind Mount

Exemple :

```yaml
- type: bind
  source: ./opensearch
  target: /usr/share/opensearch/data
```

Ici, le chemin est explicite : le dossier `opensearch/` du projet est directement monté dans le conteneur.

## 9.4 Volumes Filebeat

Le Compose déclare plusieurs registres :

```text
filebeat-logs-registry
filebeat-nginx-registry
filebeat-syslog-tcp-registry
filebeat-syslog-udp-registry
filebeat-tcp-registry
filebeat-zeek-files-logs-registry
```

Chaque instance ou type d'entrée garde un état de lecture séparé. Cette séparation évite qu'un registre destiné aux logs Zeek soit confondu avec celui des logs Nginx ou Syslog.

## 9.5 Volume De File Logstash

Le Compose déclare :

```yaml
logstash-persistent-queue:
```

et le monte :

```yaml
- logstash-persistent-queue:/logstash-persistent-queue
```

Ce volume peut survivre à la recréation du conteneur Logstash. Toutefois, comme expliqué précédemment, il n'est utile qu'aux pipelines réellement configurés avec `queue.type: persisted` et ce chemin.

## 9.6 Données OpenSearch

OpenSearch utilise un bind mount :

```yaml
source: ./opensearch
target: /usr/share/opensearch/data
```

Les index restent donc dans le répertoire `opensearch/` de l'hôte lorsque le conteneur est recréé.

Un second répertoire est prévu pour les sauvegardes :

```yaml
source: ./opensearch-backup
target: /opt/opensearch/backup
```

La présence de ce dossier ne signifie pas qu'une sauvegarde est automatiquement créée. Une politique ou une commande de snapshot doit réellement alimenter le dépôt de sauvegarde.

## 9.7 Logs Et PCAP

Les données suivantes utilisent également des bind mounts :

```text
./zeek-logs
./suricata-logs
./filescan-logs
./pcap
```

Elles restent sur l'hôte même si les conteneurs sont remplacés, sauf si un script de nettoyage, une politique de rétention ou un opérateur les supprime.

## 9.8 Persistance N'est Pas Sauvegarde

Cette distinction est essentielle :

```text
Persistance
  = les données survivent à la recréation du conteneur

Sauvegarde
  = une copie indépendante permet une restauration après perte
```

Si le disque de l'hôte est perdu, un volume situé sur ce même disque peut être perdu avec lui.

## 9.9 Effet Des Commandes Docker

En règle générale :

- `docker compose restart` conserve les volumes ;
- `docker compose down` conserve les volumes nommés ;
- `docker compose down -v` supprime les volumes nommés du projet ;
- supprimer manuellement un bind mount supprime réellement les données correspondantes ;
- `docker volume rm` supprime le volume ciblé.

Les commandes comprenant `-v`, `volume rm` ou une suppression de répertoire de données doivent donc être considérées comme destructrices.

---

## 10. Comportement En Cas De Panne

## 10.1 Logstash Est Temporairement Indisponible

Filebeat tente de se reconnecter. Il conserve sa position dans son registre et reprend la lecture tant que :

- les fichiers sources existent encore ;
- leur nettoyage n'intervient pas avant la reprise ;
- le registre Filebeat est intact.

## 10.2 OpenSearch Est Lent

Les pipelines Logstash peuvent ralentir. La contre-pression remonte progressivement :

```text
OpenSearch lent
      |
      v
sortie Logstash ralentie
      |
      v
pipelines et files remplis
      |
      v
entrée Beats ralentie
      |
      v
Filebeat attend et réessaie
```

Une file persistante activée sur le bon pipeline améliore la tolérance à une interruption courte, mais elle possède une taille maximale.

## 10.3 Filebeat Redémarre

Le registre persistant lui permet de retrouver les fichiers et les offsets connus.

La reprise peut néanmoins produire quelques doublons dans certains scénarios de panne, car une livraison fiable privilégie généralement la réémission d'un lot non confirmé plutôt que sa perte silencieuse.

## 10.4 Le Conteneur Logstash Est Recréé

Le volume `logstash-persistent-queue` survit, mais seuls les pipelines ayant effectivement écrit dans cette file retrouveront leurs événements.

Avec la configuration source étudiée, il ne faut pas affirmer que toute la chaîne principale est protégée par la file persistante.

## 10.5 Le Disque Est Plein

La chaîne peut être bloquée à plusieurs endroits :

- les analyseurs ne peuvent plus écrire leurs logs ;
- Filebeat ne peut plus mettre à jour son registre ;
- une file persistante ne peut plus écrire ;
- OpenSearch place des index en protection ou refuse des écritures ;
- les conteneurs deviennent unhealthy.

La supervision du disque est donc une condition de fonctionnement du pipeline, pas un simple indicateur de confort.

---

## 11. Vérifications En Lecture Seule

Les commandes suivantes servent à observer une installation sans modifier sa configuration.

## 11.1 Voir Les Valeurs Réelles

Depuis le répertoire du projet :

```bash
grep -HnE '^(BEATS_SSL|LOGSTASH_HOST|pipeline\.workers|pipeline\.batch\.size|pipeline\.batch\.delay|LS_JAVA_OPTS)=' config/*.env
```

Cette commande lit les vrais fichiers générés, pas les exemples.

## 11.2 Voir La Configuration Compose Résolue

```bash
docker compose config > /tmp/oculox-compose-resolu.yml
```

Puis :

```bash
grep -nA20 -B5 'LOGSTASH_HOST' /tmp/oculox-compose-resolu.yml
```

`docker compose config` fusionne les fichiers Compose, les overrides et les variables applicables. Il est plus fiable que la lecture isolée d'un seul fichier lorsqu'une installation possède des surcharges.

## 11.3 Vérifier La Destination Vue Par Filebeat

```bash
docker compose exec -T filebeat env | grep -E '^(BEATS_SSL|LOGSTASH_HOST)='
```

Le nom réel du conteneur peut être préfixé, par exemple `oculox-filebeat-1`. Il faut l'obtenir avec :

```bash
docker compose ps --format 'table {{.Service}}\t{{.Name}}\t{{.Status}}'
```

## 11.4 Vérifier L'écoute 5044 Dans Logstash

```bash
docker compose exec -T logstash ss -ltnp | grep ':5044'
```

Si `ss` n'est pas présent dans l'image :

```bash
docker compose exec -T logstash bash -lc 'cat /proc/net/tcp /proc/net/tcp6 | grep -i ":13B4"'
```

`13B4` est la représentation hexadécimale du port `5044`.

## 11.5 Voir Les Pipelines Générés

```bash
docker compose exec -T logstash cat /usr/share/logstash/config/pipelines.yml
```

Cette commande permet de savoir exactement quels pipelines sont chargés et lesquels possèdent une configuration de file spécifique.

## 11.6 Vérifier La File Persistante Réelle

```bash
docker compose exec -T logstash find /logstash-persistent-queue -maxdepth 2 -type f -ls
```

Puis vérifier le volume :

```bash
docker inspect "$(docker compose ps -q logstash)" --format '{{json .Mounts}}' | python3 -m json.tool
```

Un volume monté mais vide peut simplement signifier qu'aucun pipeline actif ne l'utilise.

## 11.7 Voir Les Volumes Du Projet

```bash
docker compose config --volumes
```

Cette commande affiche les volumes déclarés par la configuration résolue. Pour voir les volumes réellement créés par Docker :

```bash
docker volume ls
```

## 11.8 Vérifier Les Certificats Sans Afficher Les Clés

Certificat serveur :

```bash
openssl x509 -in logstash/certs/server.crt -noout -subject -issuer -dates -fingerprint -sha256
```

Certificat client :

```bash
openssl x509 -in filebeat/certs/client.crt -noout -subject -issuer -dates -fingerprint -sha256
```

Il ne faut jamais afficher ni copier le contenu de `server.key` ou `client.key` dans un rapport.

## 11.9 Vérifier Une Négociation TLS

Depuis une machine autorisée à joindre Logstash :

```bash
openssl s_client \
  -connect <hote-logstash>:5044 \
  -CAfile filebeat/certs/ca.crt \
  -cert filebeat/certs/client.crt \
  -key filebeat/certs/client.key \
  -tls1_2 \
  -brief
```

Cette commande vérifie la négociation TLS. Elle ne valide pas à elle seule que les événements sont correctement parsés et indexés.

## 11.10 Vérifier Le Registre Filebeat

```bash
docker inspect "$(docker compose ps -q filebeat)" --format '{{range .Mounts}}{{println .Destination "<-" .Name .Source}}{{end}}'
```

Le montage vers `/usr/share/filebeat-logs/data` doit être présent.

---

## 12. Points D'attention Pour Le Futur Environnement De Développement

Avant de créer deux instances Logstash, il faudra décider explicitement :

1. comment Filebeat répartit les connexions entre les deux instances ;
2. comment les certificats identifient chaque instance ;
3. quel volume de file persistante appartient à chaque instance ;
4. quels pipelines doivent utiliser une file persistante ;
5. comment mesurer la saturation des workers et la contre-pression ;
6. comment éviter les doublons lors d'une reprise ;
7. comment vérifier qu'OpenSearch absorbe le débit agrégé.

La future architecture ne devra pas simplement dupliquer le service `logstash`. Elle devra dupliquer proprement son identité, sa file, ses ressources, son état de santé et son chemin de trafic.

---

## 13. Sources Techniques Dans Le Dépôt

| Sujet | Fichier principal |
|---|---|
| Service Filebeat | `docker-compose.yml` |
| Entrées et sortie Filebeat | `filebeat/filebeat-logs.yml` |
| Démarrage Filebeat | `filebeat/scripts/filebeat.sh` |
| Paramètres Filebeat | `config/filebeat.env.example` |
| Destination et TLS Beats | `config/beats-common.env.example` |
| Service Logstash | `docker-compose.yml` |
| Entrée Beats | `logstash/pipelines/input/01_beats_input.conf` |
| Routage des tags | `logstash/maps/parse_pipelines.yaml` |
| Génération des pipelines | `logstash/scripts/logstash-start.sh` |
| Parsing Zeek | `logstash/pipelines/zeek/` |
| Parsing Suricata | `logstash/pipelines/suricata/` |
| Enrichissement | `logstash/pipelines/enrichment/` |
| Sortie OpenSearch | `logstash/pipelines/output/` |
| File persistante externe | `logstash/pipelines/external/00_config.conf` |
| Paramètres Logstash/JVM | `config/logstash.env.example` |
| Génération des certificats | `scripts/control.py` et `docs/authsetup.md` |

---

## 14. Résumé À Retenir

1. Filebeat lit les fichiers Zeek, Suricata et filescan ; il ne capture pas lui-même le trafic.
2. Son registre persistant mémorise la progression de lecture.
3. `LOGSTASH_HOST` indique uniquement la destination `hôte:port` de Filebeat.
4. Logstash reçoit le protocole Beats sur TCP `5044`.
5. Les tags Filebeat orientent les événements vers les pipelines Zeek, Suricata, filescan ou beats.
6. Les pipelines parsés convergent vers l'enrichissement puis vers la sortie OpenSearch.
7. Les adresses inter-pipelines sont internes à Logstash et ne sont pas des ports réseau.
8. Le dépôt contient une file persistante de 4 Go pour la sortie externe/secondaire, pas une protection explicite de tous les pipelines principaux.
9. Avec `BEATS_SSL=true`, le transport est chiffré, mais la vérification mutuelle stricte n'est pas imposée par les paramètres étudiés.
10. Les clés et certificats réels ne sont pas versionnés ; ils sont générés par `auth_setup`.
11. Les volumes Filebeat conservent les registres, le bind mount OpenSearch conserve les index et les répertoires hôtes conservent les logs et PCAP.
12. Un volume persistant n'est pas une sauvegarde.

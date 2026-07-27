# Phase 1 - Comprendre la structure d'un service Docker Compose

## 1. Objectif du document

Ce document explique les principales clés utilisées pour décrire un service dans les fichiers Docker Compose d'Oculox/Malcolm :

- `image` ;
- `build` ;
- `profiles` ;
- `env_file` ;
- `volumes` ;
- `networks` ;
- `depends_on` ;
- `healthcheck` ;
- `ports` ;
- `ulimits`.

L'objectif n'est pas seulement de connaître leur définition. Il faut comprendre ce que Docker fait réellement avec chacune d'elles, comment Malcolm les utilise et ce qu'elles ne font pas.

Les exemples proviennent directement des fichiers suivants :

- `docker-compose.yml` ;
- `docker-compose-dev.yml`.

---

## 2. Qu'est-ce qu'un service Docker Compose ?

Un **service** est la description d'un type de conteneur que Docker Compose doit créer et gérer.

Exemple simplifié :

```yaml
services:
  logstash:
    image: ghcr.io/idaholab/malcolm/logstash-oss:26.06.0
    hostname: logstash
    networks:
      - default
    env_file:
      - ./config/logstash.env
    volumes:
      - logstash-persistent-queue:/logstash-persistent-queue
```

Dans cet exemple :

- `logstash` est le nom du service Compose ;
- Docker crée un conteneur à partir d'une image Logstash ;
- le conteneur rejoint le réseau `default` ;
- il reçoit les variables présentes dans `config/logstash.env` ;
- il utilise un volume persistant pour sa file d'attente.

Il faut distinguer trois notions :

| Notion | Signification |
|---|---|
| Service | Description écrite dans le fichier Compose |
| Image | Modèle immuable utilisé pour créer le conteneur |
| Conteneur | Instance en cours d'exécution créée à partir de l'image |

Une même image peut servir à créer plusieurs conteneurs. C'est ce principe qui nous permettra plus tard de créer deux instances Logstash.

---

## 3. `image` - L'image utilisée par le service

### 3.1 Définition

La clé `image` indique à Docker quelle image utiliser pour créer le conteneur.

Exemple réel :

```yaml
logstash:
  image: ghcr.io/idaholab/malcolm/logstash-oss:26.06.0
```

Cette valeur se décompose ainsi :

```text
ghcr.io / idaholab / malcolm / logstash-oss : 26.06.0
registre   organisation  projet   image       version
```

- `ghcr.io` est le registre qui stocke l'image ;
- `idaholab/malcolm` désigne l'organisation et le projet ;
- `logstash-oss` est le nom de l'image ;
- `26.06.0` est son étiquette de version, appelée **tag**.

### 3.2 Ce que Docker fait

Lors du démarrage, Docker cherche d'abord l'image localement. Si elle n'est pas présente, il peut la télécharger depuis le registre.

```text
Image disponible localement ?
        |
      oui --> création du conteneur
        |
      non --> téléchargement --> création du conteneur
```

### 3.3 Pourquoi fixer une version ?

Le tag `26.06.0` rend le déploiement reproductible. Deux installations utilisant cette référence doivent partir de la même version du composant.

Éviter un tag flottant comme `latest` permet de ne pas recevoir silencieusement une nouvelle version lors d'un redéploiement.

### 3.4 Ce que `image` ne fait pas

La clé `image` :

- ne démarre pas le conteneur à elle seule ;
- ne configure pas ses ressources ;
- ne garantit pas que l'application contenue dans l'image fonctionne ;
- ne conserve pas les données produites par le conteneur.

Commandes utiles :

```bash
docker compose -f docker-compose.yml --profile malcolm images
docker image inspect ghcr.io/idaholab/malcolm/logstash-oss:26.06.0
```

---

## 4. `build` - La construction locale d'une image

### 4.1 Définition

La clé `build` demande à Docker de construire une image à partir de fichiers locaux.

Elle est principalement présente dans `docker-compose-dev.yml` :

```yaml
logstash:
  build:
    context: .
    dockerfile: Dockerfiles/logstash.Dockerfile
  image: ghcr.io/idaholab/malcolm/logstash-oss:26.06.0
```

### 4.2 Signification des sous-clés

```yaml
context: .
```

Le **contexte de construction** est le répertoire dont Docker peut lire les fichiers pendant la construction. Ici, `.` représente la racine du dépôt Oculox.

```yaml
dockerfile: Dockerfiles/logstash.Dockerfile
```

Le `Dockerfile` contient les instructions permettant de construire l'image : image de base, paquets à installer, fichiers à copier et scripts à ajouter.

### 4.3 Pourquoi `build` et `image` sont présents ensemble ?

Dans le fichier de développement :

- `build` explique comment fabriquer l'image ;
- `image` donne un nom et un tag au résultat construit.

Avec :

```bash
docker compose -f docker-compose-dev.yml --profile malcolm build logstash
```

Docker construit localement l'image Logstash décrite par le `Dockerfile`.

Avec :

```bash
docker compose -f docker-compose-dev.yml --profile malcolm up -d --build logstash
```

Docker reconstruit l'image si nécessaire, puis recrée le service.

### 4.4 Différence essentielle

| `image` seulement | `build` avec `image` |
|---|---|
| Utilise une image déjà construite | Peut construire une image locale |
| Adapté à l'exploitation | Adapté au développement |
| Plus rapide à déployer | Plus long et plus coûteux à construire |
| Le contenu de l'image est déjà fixé | Le contenu peut être modifié via le Dockerfile |

Une modification d'un fichier monté par volume ne nécessite pas toujours de reconstruire l'image. Une modification du `Dockerfile` ou d'un fichier copié pendant le `build` exige généralement une reconstruction.

---

## 5. `profiles` - La sélection d'un rôle de déploiement

### 5.1 Définition

Les profils permettent d'activer seulement certains services selon le rôle de la machine.

Exemple :

```yaml
filebeat:
  profiles: ["malcolm", "hedgehog"]
```

Filebeat peut être utilisé dans les deux rôles :

- Malcolm Principal ;
- collecteur Hedgehog.

À l'inverse :

```yaml
opensearch:
  profiles: ["malcolm"]
```

OpenSearch appartient uniquement au profil principal dans cette configuration.

### 5.2 Exemples de démarrage

Pour le Malcolm Principal :

```bash
docker compose -f docker-compose.yml --profile malcolm up -d
```

Pour le collecteur Hedgehog :

```bash
docker compose -f docker-compose.yml --profile hedgehog up -d
```

### 5.3 Lecture fonctionnelle

```text
Profil malcolm
  OpenSearch, Logstash, Dashboards, API, Nginx, Filebeat,
  Zeek, Suricata, Arkime et services complémentaires

Profil hedgehog
  Filebeat, Zeek, Suricata, Arkime, capture et analyse locale
```

La présence du même service dans les deux profils ne signifie pas obligatoirement qu'il aura exactement la même fonction opérationnelle. Ses variables d'environnement déterminent aussi son comportement.

### 5.4 Erreur fréquente

Oublier le profil peut conduire Docker Compose à ne sélectionner aucun des services attendus.

Pour voir les profils et services résolus :

```bash
docker compose -f docker-compose.yml config --profiles
docker compose -f docker-compose.yml --profile malcolm config --services
```

Ces commandes nécessitent que les fichiers `config/*.env` référencés existent.

---

## 6. `env_file` - Les variables injectées dans le conteneur

### 6.1 Définition

La clé `env_file` indique les fichiers dont les variables seront transmises au processus exécuté dans le conteneur.

Exemple réel de Logstash :

```yaml
env_file:
  - ./config/process.env
  - ./config/ssl.env
  - ./config/opensearch.env
  - ./config/netbox-common.env
  - ./config/netbox.env
  - ./config/netbox-secret.env
  - ./config/filescan.env
  - ./config/beats-common.env
  - ./config/lookup-common.env
  - ./config/logstash.env
```

Logstash reçoit donc des paramètres provenant de plusieurs domaines :

- fonctionnement général des processus ;
- TLS et certificats ;
- connexion à OpenSearch ;
- intégration NetBox ;
- analyse de fichiers ;
- entrée Beats ;
- réglages propres à Logstash.

### 6.2 Ordre et priorité

Les fichiers sont lus dans l'ordre. Si une même variable est définie dans plusieurs fichiers, la valeur du fichier placé plus bas prend normalement la priorité.

Une variable déclarée directement dans une section Compose `environment:` prend la priorité sur `env_file`.

### 6.3 Différence entre `.env` et `env_file`

Ces deux mécanismes sont souvent confondus :

| Mécanisme | Utilité principale |
|---|---|
| Fichier `.env` de Compose | Remplacer des `${VARIABLE}` pendant la lecture du YAML |
| `env_file:` d'un service | Injecter des variables dans le conteneur |

Dans Malcolm, les fichiers sous `config/` sont principalement utilisés avec `env_file:`.

### 6.4 Vérification

Pour voir les variables réellement présentes dans un conteneur actif :

```bash
docker compose exec logstash env | sort
```

Cette sortie peut contenir des secrets. Elle ne doit pas être publiée ni ajoutée dans Git.

Pour rechercher une variable sans afficher tout l'environnement :

```bash
docker compose exec logstash printenv LS_JAVA_OPTS
```

### 6.5 Ce que `env_file` ne fait pas

`env_file` ne monte pas le fichier dans le conteneur. Docker lit le fichier et transmet ses variables. Le chemin `./config/logstash.env` n'existe donc pas nécessairement à l'intérieur du conteneur.

---

## 7. `volumes` - La persistance et le partage des fichiers

### 7.1 Pourquoi un volume est nécessaire

Le système de fichiers interne d'un conteneur est remplaçable. Si le conteneur est supprimé et recréé, les données écrites uniquement dans sa couche interne peuvent disparaître.

Un volume permet de placer les données importantes en dehors de cette couche éphémère.

### 7.2 Les deux types utilisés par Malcolm

#### Volume nommé

Exemple :

```yaml
volumes:
  - logstash-persistent-queue:/logstash-persistent-queue
```

Et à la fin du fichier :

```yaml
volumes:
  logstash-persistent-queue:
```

Docker gère lui-même l'emplacement physique de ce volume.

```text
Volume Docker logstash-persistent-queue
                 |
                 v
/logstash-persistent-queue dans le conteneur
```

Ce volume conserve la file persistante de Logstash lors d'une recréation normale du conteneur.

#### Montage bind

Exemple OpenSearch :

```yaml
- type: bind
  bind:
    create_host_path: false
  source: ./opensearch
  target: /usr/share/opensearch/data
```

Le répertoire `./opensearch` de l'hôte est directement présenté à OpenSearch comme son répertoire de données.

```text
Hôte                                  Conteneur
./opensearch              <------>    /usr/share/opensearch/data
```

### 7.3 `source`, `target` et `read_only`

- `source` : emplacement ou volume du côté de l'hôte ;
- `target` : emplacement visible dans le conteneur ;
- `read_only: true` : interdit au conteneur de modifier ce montage.

Exemple de certificat en lecture seule :

```yaml
source: ./logstash/certs/ca.crt
target: /certs/ca.crt
read_only: true
```

### 7.4 `create_host_path: false`

Cette option demande à Docker de ne pas créer silencieusement le chemin source s'il manque. Une erreur est préférable à la création automatique d'un répertoire vide qui masquerait un problème de configuration.

### 7.5 Attention aux suppressions

```bash
docker compose down
```

arrête et supprime les conteneurs et réseaux du projet, mais conserve normalement les volumes nommés.

```bash
docker compose down -v
```

supprime aussi les volumes nommés du projet. Cette commande peut entraîner une perte de données et ne doit pas être utilisée sans inventaire et sauvegarde.

Un montage bind n'est pas supprimé par `docker compose down -v`, car il correspond à un répertoire normal de l'hôte.

Commandes de vérification :

```bash
docker volume ls
docker compose -f docker-compose.yml --profile malcolm config --volumes
docker inspect oculox-logstash-1 --format '{{json .Mounts}}'
```

---

## 8. `networks` - La communication entre les services

### 8.1 Réseau Compose standard

Exemple :

```yaml
logstash:
  networks:
    - default
```

Et en fin de fichier :

```yaml
networks:
  default:
    external: false
```

Docker Compose crée un réseau privé propre au projet. `external: false` signifie que Compose gère ce réseau au lieu d'attendre un réseau préexistant.

### 8.2 Résolution des noms

Sur le même réseau Compose, les services peuvent se joindre avec leur nom de service :

```text
filebeat  --->  logstash:5044
logstash  --->  opensearch:9200
nginx     --->  dashboards
```

Docker fournit un DNS interne. Il n'est donc pas nécessaire de connaître l'adresse IP temporaire du conteneur Logstash.

Cette propriété sera centrale pour notre architecture :

```text
logstash-1:5044
logstash-2:5044
```

seront des noms stables sur le réseau Compose, même si les adresses IP des conteneurs changent.

### 8.3 Cas particulier : `network_mode: host`

Les services de capture live utilisent notamment :

```yaml
network_mode: host
```

Dans ce mode, le conteneur partage directement l'espace réseau de l'hôte. Cela lui permet d'observer une interface de capture comme `ens18`.

```text
Mode bridge Compose : réseau virtuel isolé de Docker
Mode host           : pile réseau directement partagée avec l'hôte
```

Un service en mode `host` ne fonctionne pas comme un service attaché au réseau bridge `default`. Il faut donc analyser séparément sa résolution de noms, ses ports et ses interfaces.

### 8.4 Ce que `networks` ne garantit pas

Être sur le même réseau permet la communication, mais ne garantit pas :

- que le processus écoute sur le port attendu ;
- que TLS est correctement configuré ;
- que le service est sain ;
- que l'application accepte la connexion.

Commandes utiles :

```bash
docker compose -f docker-compose.yml --profile malcolm config --networks
docker network ls
docker network inspect oculox_default
```

Le nom réel du réseau dépend du nom du projet Compose.

---

## 9. `depends_on` - L'ordre de création des services

### 9.1 Exemple réel

```yaml
logstash:
  depends_on:
    - opensearch
```

Cela indique que Docker Compose doit démarrer OpenSearch avant Logstash.

Autre exemple :

```yaml
nginx-proxy:
  depends_on:
    - api
    - arkime
    - dashboards
    - filescan
    - htadmin
    - keycloak
    - netbox
    - opensearch
    - upload
```

### 9.2 Limite importante

Dans cette syntaxe courte, `depends_on` attend que le conteneur dépendant soit **démarré**, pas que l'application soit réellement **prête**.

```text
Conteneur OpenSearch démarré
            !=
Cluster OpenSearch prêt à recevoir des écritures
```

OpenSearch peut avoir besoin de plusieurs minutes pour initialiser ses index. C'est pourquoi Logstash possède aussi des mécanismes de reprise et un `start_period` long dans son contrôle de santé.

### 9.3 `depends_on` n'est pas un mécanisme de résilience

Si OpenSearch tombe après le démarrage :

- `depends_on` ne redémarre pas automatiquement OpenSearch ;
- `depends_on` ne stoppe pas automatiquement Logstash ;
- `depends_on` ne garantit pas l'absence de perte ;
- les applications doivent gérer les reconnexions et files d'attente.

---

## 10. `healthcheck` - Le contrôle de santé du conteneur

### 10.1 Exemple réel de Logstash

```yaml
healthcheck:
  test: ["CMD", "/usr/local/bin/container_health.sh", "-s"]
  interval: 30s
  timeout: 15s
  retries: 3
  start_period: 600s
```

### 10.2 Signification

| Paramètre | Signification |
|---|---|
| `test` | Commande exécutée dans le conteneur |
| `interval` | Temps entre deux contrôles |
| `timeout` | Durée maximale accordée à un contrôle |
| `retries` | Nombre d'échecs consécutifs avant `unhealthy` |
| `start_period` | Période initiale accordée au service pour démarrer |

Pour Logstash, `start_period: 600s` accorde jusqu'à dix minutes de phase initiale avant que les échecs de santé soient comptabilisés normalement.

### 10.3 États possibles

```text
starting  --> le service est encore dans sa période de démarrage
healthy   --> le dernier ensemble de contrôles est satisfaisant
unhealthy --> les contrôles ont échoué plusieurs fois
```

### 10.4 Important : santé et exécution sont différentes

Un conteneur peut être :

- `running` et `healthy` ;
- `running` mais `unhealthy` ;
- arrêté.

`running` signifie que son processus principal existe. `healthy` signifie que le test fonctionnel défini par l'image réussit.

### 10.5 Le healthcheck ne répare pas le service

Un `healthcheck` observe et signale un état. À lui seul, il ne redémarre pas le conteneur et ne corrige pas la cause de l'échec.

Commandes utiles :

```bash
docker compose ps
docker inspect oculox-logstash-1 --format '{{json .State.Health}}'
docker logs --since 10m oculox-logstash-1
```

---

## 11. `ports` - La publication d'un port vers l'hôte

### 11.1 Exemple réel

Dans le service `nginx-proxy` :

```yaml
ports:
  - 0.0.0.0:443:443/tcp
```

Le format est :

```text
adresse_hôte : port_hôte : port_conteneur / protocole
0.0.0.0      : 443       : 443             / tcp
```

Cela signifie :

- Nginx écoute sur le port `443` dans son conteneur ;
- Docker publie ce port comme port `443` de l'hôte ;
- `0.0.0.0` l'expose sur toutes les interfaces IPv4 de l'hôte ;
- le protocole est TCP.

### 11.2 Pourquoi les autres services n'exposent-ils pas tous leurs ports ?

Un port n'a pas besoin d'être publié vers l'hôte pour être accessible depuis un autre conteneur du même réseau.

Par exemple :

```text
Filebeat peut joindre logstash:5044 sur le réseau Docker
sans publier 5044 sur toutes les interfaces de l'hôte.
```

Cette approche réduit la surface d'exposition. Nginx constitue le point d'entrée HTTPS principal et relaie les requêtes vers les services internes.

### 11.3 `ports` et `network_mode: host`

Avec `network_mode: host`, il n'y a pas de traduction de port Docker classique. Le processus du conteneur utilise directement les ports et interfaces de l'hôte.

### 11.4 Risque de sécurité

Publier un port sur `0.0.0.0` le rend potentiellement accessible depuis tous les réseaux pouvant atteindre l'hôte. Une publication doit donc être justifiée et protégée par le pare-feu, TLS et l'authentification appropriée.

Commandes utiles :

```bash
docker compose ps
ss -ltnp
docker port oculox-nginx-proxy-1
```

---

## 12. `ulimits` - Les limites système du processus

### 12.1 Exemple réel

OpenSearch et Logstash utilisent :

```yaml
ulimits:
  memlock:
    soft: -1
    hard: -1
```

`memlock` contrôle la quantité de mémoire qu'un processus peut verrouiller en RAM.

La valeur `-1` signifie ici une limite illimitée pour ce paramètre.

### 12.2 Pourquoi verrouiller de la mémoire ?

OpenSearch et Logstash utilisent une JVM. Une partie de leur mémoire peut être sensible aux ralentissements si elle est déplacée vers le swap.

Le verrouillage permet au processus de demander que certaines pages mémoire restent en RAM.

Le Compose ajoute également :

```yaml
cap_add:
  - IPC_LOCK
  - SYS_RESOURCE
```

- `IPC_LOCK` autorise le verrouillage de mémoire ;
- `SYS_RESOURCE` autorise certaines modifications de limites de ressources.

La présence de `ulimits.memlock` sans les permissions nécessaires pourrait être insuffisante.

### 12.3 `soft` et `hard`

- limite **soft** : limite appliquée normalement au processus ;
- limite **hard** : plafond maximal auquel la limite soft peut être élevée.

### 12.4 Ce que `ulimits` ne fait pas

`ulimits` n'attribue pas directement :

- un nombre de vCPU ;
- une quantité maximale de RAM ;
- une taille de heap JVM ;
- une priorité CPU garantie.

Dans le Compose actuel, `ulimits.memlock` ne signifie donc pas que Logstash reçoit une RAM illimitée. Cela signifie seulement que sa limite de verrouillage mémoire est levée.

Les valeurs de heap JVM sont définies séparément, notamment dans `config/logstash.env` avec `LS_JAVA_OPTS`.

Vérification dans un conteneur actif :

```bash
docker compose exec logstash sh -c 'ulimit -a'
docker inspect oculox-logstash-1 --format '{{json .HostConfig.Ulimits}}'
```

---

## 13. Lecture complète du service Logstash

Voici comment lire le service Logstash dans son ensemble :

```text
image
  Utilise l'image Malcolm Logstash OSS 26.06.0.

profiles
  Le service appartient au rôle Malcolm Principal.

networks
  Il rejoint le réseau privé Compose et peut joindre OpenSearch par son nom.

env_file
  Il reçoit ses paramètres JVM, TLS, Beats, OpenSearch et pipelines.

depends_on
  Compose lance OpenSearch avant Logstash, sans garantir qu'il soit déjà prêt.

volumes
  La queue persistante survit à la recréation du conteneur.
  Les certificats et fichiers de mapping locaux sont montés en lecture seule.

healthcheck
  Un script vérifie régulièrement le fonctionnement du service.

ulimits
  Le verrouillage de mémoire nécessaire aux composants JVM est autorisé.

ports
  Aucun port Logstash n'est publié directement vers l'hôte dans ce Compose.
  Filebeat le joint par le réseau Docker ou par la configuration de transport prévue.
```

---

## 14. Relations entre les clés

Ces clés ne sont pas indépendantes. Elles forment ensemble le comportement du service :

```text
build ou image
       |
       v
Création du conteneur
       |
       +--> env_file : configuration du processus
       +--> volumes  : données et fichiers persistants
       +--> networks : communication avec les autres services
       +--> ports    : accès depuis l'extérieur de Docker
       +--> ulimits  : limites système du processus
       |
       v
depends_on : ordre initial de démarrage
       |
       v
healthcheck : observation de l'état fonctionnel
```

---

## 15. Commandes de lecture sans modification

Les commandes suivantes n'altèrent pas la plateforme :

```bash
cd /home/kakashi_/ICSHUB/Oculox

# Afficher les services sélectionnés par le profil Malcolm
docker compose -f docker-compose.yml --profile malcolm config --services

# Afficher les profils déclarés
docker compose -f docker-compose.yml config --profiles

# Afficher la configuration Compose résolue
docker compose -f docker-compose.yml --profile malcolm config

# Afficher l'état des conteneurs
docker compose -f docker-compose.yml --profile malcolm ps

# Afficher les réseaux Docker
docker network ls

# Afficher les volumes Docker
docker volume ls
```

Dans le clone actuel, la commande `docker compose ... config` peut échouer tant que les vrais fichiers `config/*.env` n'ont pas été générés. Ce comportement est attendu : le Compose référence des fichiers de configuration active qui n'existent pas encore dans un clone non configuré.

---

## 16. Points essentiels à retenir

1. `image` désigne le modèle utilisé pour créer le conteneur.
2. `build` décrit comment construire localement cette image.
3. `profiles` choisit les services correspondant au rôle Malcolm ou Hedgehog.
4. `env_file` injecte la configuration dans le processus du conteneur.
5. `volumes` assurent la persistance ou rendent des fichiers de l'hôte accessibles.
6. `networks` permettent aux services de communiquer par leurs noms.
7. `depends_on` gère un ordre de démarrage, mais pas la disponibilité réelle.
8. `healthcheck` mesure la santé, mais ne répare pas automatiquement le service.
9. `ports` publie explicitement un service vers l'hôte ou le réseau externe.
10. `ulimits` règle des limites système ; il ne dimensionne pas directement le CPU, la RAM ou la heap JVM.

La prochaine étape de la Phase 1 consistera à suivre précisément une donnée depuis un fichier Zeek ou Suricata jusqu'à Filebeat, puis de Filebeat vers l'entrée Beats et les pipelines Logstash.

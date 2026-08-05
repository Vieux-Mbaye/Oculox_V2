# Scénario Complet Du Développement Résilient Oculox

## 1. Objet Du Document

Ce document raconte, dans l'ordre, la construction de l'environnement de
développement résilient Oculox fondé sur Malcolm. Il part de la plateforme
officielle, explique le rôle de ses composants, décrit les décisions prises au
cours des onze phases du projet, présente l'arborescence obtenue et consolide
les résultats réellement mesurés.

L'objectif est double :

1. permettre à une personne débutante de comprendre ce qui a été construit ;
2. fournir une trace technique défendable des choix, des essais et des limites.

Le projet ne consiste pas à remplacer Malcolm. La base officielle est
conservée et les fonctions de résilience sont ajoutées dans des fichiers
Oculox dédiés. Cette séparation facilite les mises à jour, les comparaisons et
le retour arrière.

---

## 2. Point De Départ : Le Système Malcolm D'origine

### 2.1 Ce Qu'est Malcolm Dans Ce Projet

Malcolm est une plateforme d'analyse de trafic réseau composée de plusieurs
conteneurs Docker. Chaque conteneur réalise une fonction spécialisée :
capture, analyse protocolaire, détection, transport, transformation,
indexation, stockage ou visualisation.

Docker Compose décrit comment ces conteneurs sont assemblés. Il précise les
images utilisées, les réseaux Docker, les volumes persistants, les variables
d'environnement, les dépendances, les ports et les contrôles de santé.

Le fichier officiel `docker-compose.yml` constitue la base de déploiement. Les
profils Compose permettent d'utiliser le même dépôt pour deux rôles :

- le profil `malcolm` correspond au Principal, qui centralise, transforme,
  indexe et présente les données ;
- le profil `hedgehog` correspond au collecteur, qui observe le trafic et
  produit les données à transmettre au Principal.

### 2.2 Les Trois Analyseurs Réseau

#### Zeek

Zeek interprète les protocoles et produit des journaux structurés. Il ne crée
pas une ligne pour chaque paquet. Il reconstruit des connexions et des
transactions, puis produit des fichiers tels que `conn.log`, `dns.log`,
`http.log`, `ssl.log` ou les journaux de protocoles industriels disponibles.

Dans la chaîne Oculox, Zeek apporte principalement la visibilité
protocolaire : qui communique, avec qui, quand, sur quel protocole et avec
quelles caractéristiques.

#### Suricata

Suricata est le moteur IDS. Il compare le trafic à des règles de détection et
produit des alertes ainsi que des événements réseau. Sa sortie principale est
`eve.json`, un fichier texte JSON qui peut contenir des événements `alert`,
`flow`, `dns`, `http`, `tls`, `fileinfo` et d'autres types selon la
configuration.

Suricata apporte donc la détection fondée sur des signatures et des règles,
mais aussi des métadonnées complémentaires. Le format JSON est riche et
verbeux ; sa croissance disque doit être surveillée.

#### Arkime

Arkime capture ou lit les paquets, construit des sessions réseau et conserve
la relation entre les métadonnées de session et les PCAP. Il fournit une vue
d'investigation orientée sessions et permet, lorsque les PCAP sont conservés,
de revenir au trafic brut.

Arkime n'est pas simplement un lecteur des journaux Zeek. Il possède son propre
moteur de capture et son propre chemin d'indexation des sessions.

### 2.3 Les Deux Chemins D'analyse

Le traitement `live` concerne le trafic reçu en temps réel sur une interface
de capture :

```text
Interface réseau
  ├── Zeek live      → journaux protocolaires
  ├── Suricata live  → eve.json et alertes
  └── Arkime live    → sessions et PCAP selon configuration
```

Le traitement `offline` concerne un PCAP déjà enregistré :

```text
PCAP déposé
→ pcap-monitor
→ Zeek / Suricata / Arkime offline
→ journaux, alertes, sessions et artefacts
```

Les deux chemins produisent ensuite des données destinées au stockage et à
l'investigation. La différence se trouve à l'entrée : une interface réseau
pour le live, un fichier existant pour l'offline.

---

## 3. Chaîne De Données De Base

### 3.1 Chemin Principal Des Journaux

```text
Zeek / Suricata / autres producteurs
                 |
                 v
             Fichiers logs
                 |
                 v
              Filebeat
                 |
             Beats/TLS
                 |
                 v
              Logstash
                 |
                 v
             OpenSearch
                 |
                 v
      Dashboards / recherche SOC
```

Arkime conserve en parallèle son chemin de sessions et de PCAP. Les données
issues des différents chemins se rejoignent dans OpenSearch pour la recherche
et sont exploitées par OpenSearch Dashboards, Arkime Viewer et les API.

### 3.2 Filebeat : Lecture, Registre Et Transport

Filebeat surveille les fichiers de journaux. Lorsqu'une nouvelle ligne est
écrite, il la lit, l'encapsule en événement et l'envoie à Logstash avec le
protocole Beats.

Son registre persistant mémorise la position de lecture de chaque fichier. Par
exemple, si Filebeat a confirmé les 10 000 premiers octets d'un journal puis
redémarre, il reprend à la position enregistrée au lieu de relire
volontairement tout le fichier.

Dans la configuration Malcolm d'origine étudiée, Filebeat utilisait une seule
destination logique :

```text
LOGSTASH_HOST=logstash:5044
```

Le port `5044/TCP` est le port interne sur lequel le plugin Beats de Logstash
écoute. Il ne faut pas confondre ce port applicatif avec le port éventuellement
publié sur l'hôte Docker.

Un même conteneur Filebeat exécute plusieurs configurations spécialisées :

| Configuration | Fonction |
|---|---|
| `filebeat-logs.yml` | journaux Zeek, Suricata et filescan |
| `filebeat-nginx.yml` | journaux Nginx |
| `filebeat-syslog-tcp.yml` | réception Syslog sur TCP |
| `filebeat-syslog-udp.yml` | réception Syslog sur UDP |
| `filebeat-tcp.yml` | entrée TCP générique |

Il ne s'agit pas de cinq conteneurs Filebeat. Ce sont cinq processus ou
configurations spécialisés dans le même service.

### 3.3 Logstash : Réception, Parsing Et Enrichissement

Logstash est le moteur de transformation des événements. Il reçoit les lots
Filebeat, reconnaît leur type, transforme les champs, applique les règles ECS,
ajoute du contexte et prépare les documents à écrire dans OpenSearch.

La configuration effective contient sept pipelines :

| Pipeline | Rôle |
|---|---|
| `malcolm-input` | reçoit les lots Beats/TLS |
| `malcolm-zeek` | parse les événements Zeek |
| `malcolm-suricata` | parse les événements Suricata |
| `malcolm-filescan` | traite les résultats d'analyse de fichiers |
| `malcolm-beats` | traite les autres événements Beats |
| `malcolm-enrichment` | normalise et enrichit les événements |
| `malcolm-output` | écrit les documents dans OpenSearch |

Un pipeline est une chaîne interne `entrée → filtres → sortie`. Les workers
sont les threads qui exécutent les filtres et les sorties. La
`worker_utilization` indique la part du temps pendant laquelle ils travaillent.
La `queue_backpressure` révèle qu'une étape amont doit attendre parce que
l'étape suivante ne consomme pas assez vite.

### 3.4 OpenSearch : Indexation Et Recherche

OpenSearch reçoit les documents structurés et les stocke dans des index. Un
index est un ensemble logique de documents optimisé pour la recherche. Il ne
correspond pas à un simple fichier texte : OpenSearch organise les documents
en shards et en segments internes.

Dans ce projet, OpenSearch permet notamment :

- la recherche temporelle ;
- l'affichage des tableaux de bord ;
- la corrélation des événements ;
- la consultation des sessions Arkime ;
- le comptage exact des événements de test.

L'état `green` signifie que tous les shards attendus sont actifs. Dans
l'environnement local, OpenSearch reste une instance unique. Deux Logstash ne
rendent donc pas OpenSearch hautement disponible.

### 3.5 Persistance De Base

Trois formes de persistance doivent être distinguées :

1. les fichiers sources Zeek et Suricata restent sur disque selon leur
   politique de nettoyage ;
2. le registre Filebeat mémorise les positions de lecture ;
3. les volumes OpenSearch conservent les index.

La file persistante Logstash est un quatrième mécanisme ajouté et vérifié
pendant le développement. Elle conserve sur disque les événements acceptés
par Logstash mais pas encore acquittés par la suite du pipeline.

---

## 4. Pourquoi Modifier L'architecture

La plateforme d'origine utilisait une seule instance Logstash. Si cette
instance s'arrêtait, Filebeat n'avait plus de destination disponible. Un
ralentissement pouvait aussi concentrer toute la pression sur une seule JVM.

Le besoin retenu a été de rendre la couche d'ingestion plus résiliente sans
réécrire Malcolm :

```text
                       ┌── logstash   ── file persistante 1 ──┐
Filebeat ── mTLS ──────┤                                      ├── OpenSearch
  loadbalance: true    └── logstash-2 ─ file persistante 2 ──┘
```

Cette architecture doit permettre :

- d'utiliser les deux Logstash en fonctionnement normal ;
- de continuer à ingérer si une instance est arrêtée ;
- de remettre automatiquement l'instance revenue dans la répartition ;
- de tamponner une indisponibilité temporaire d'OpenSearch ;
- de protéger le transport par TLS mutuel ;
- de reprendre après redémarrage grâce aux files et au registre Filebeat.

Elle ne protège pas encore contre la panne physique de l'hôte Principal, car
les deux Logstash et OpenSearch résident sur la même machine.

---

## 5. Construction Du Projet Phase Par Phase

### Phase 1 - Comprendre L'existant

#### Idée

Il était nécessaire de comprendre Malcolm avant de le modifier. Une variable
présente dans un fichier n'est pas nécessairement active ; la configuration
effective doit être vérifiée dans le Compose fusionné ou dans le processus en
cours d'exécution.

#### Travail Réalisé

La phase a étudié :

- `docker-compose.yml` et `docker-compose-dev.yml` ;
- les profils `malcolm` et `hedgehog` ;
- les fichiers réels `config/*.env` et leurs modèles ;
- les clés Compose `image`, `build`, `profiles`, `env_file`, `volumes`,
  `networks`, `depends_on`, `healthcheck`, `ports` et `ulimits` ;
- les chemins live et offline ;
- Filebeat, les pipelines Logstash, TLS et les volumes persistants.

Les quatre études détaillées sont conservées dans `dev/phase1/`.

#### Résultat

Le fonctionnement initial est documenté avant tout changement. Cette phase a
notamment établi que les vrais fichiers `config/*.env` sont générés pour une
installation et ignorés par Git parce qu'ils peuvent contenir des secrets et
des paramètres propres à la machine.

### Phase 2 - Préparer Le Dépôt De Développement

#### Idée

Les modifications locales ne devaient pas être mélangées aux fichiers
officiels. La méthode retenue consiste à garder Malcolm comme socle et à
superposer explicitement les adaptations Oculox.

#### Travail Réalisé

Le répertoire `dev/` a été créé avec des espaces séparés pour la conception,
les surcharges Compose, les scripts, les tests, la supervision, les fichiers
générés et la documentation.

Le script `dev/scripts/validate-compose.sh` vérifie la fusion des fichiers
Compose sans démarrer les conteneurs. Les secrets, PCAP, métriques et résultats
de test sont exclus de Git.

#### Résultat

Le dépôt est reproductible : les sources décrivent comment générer la
configuration, tandis que l'état propre à une installation reste local.

### Phase 3 - Définir L'architecture Cible

#### Idée

L'architecture devait être décidée avant d'écrire le code. Le choix retenu est
une répartition Filebeat côté client vers deux Logstash identiques.

#### Décisions

- conserver le service officiel `logstash` ;
- ajouter `logstash-2` dans une surcharge Compose ;
- utiliser la même image et les mêmes sept pipelines ;
- donner à chaque instance son propre volume de queue ;
- utiliser `5044` comme port interne dans chaque conteneur ;
- publier `5044` pour la première instance et `5045` pour la seconde ;
- envoyer les deux instances vers le même OpenSearch ;
- protéger Beats avec TLS mutuel ;
- ne pas introduire un proxy réseau supplémentaire à ce stade.

#### Ressources De Départ

La machine locale disposait de 12 vCPU, environ 30 Gio de RAM et environ
213 Gio libres. Ces ressources permettaient le développement, mais pas une
conclusion de capacité de production.

### Phase 4 - Établir La Baseline À Un Logstash

#### Idée

Une modification ne peut être évaluée sans point de comparaison. La plateforme
d'origine a donc été mesurée avec un seul Logstash.

#### État De Référence

- version initiale : Malcolm `26.06.0` ;
- 27 services démarrés ;
- OpenSearch `green` ;
- heap Logstash : 3 Gio ;
- sept pipelines actifs ;
- backpressure nulle au repos.

Au repos, les mesures étaient :

| Composant | CPU | Mémoire |
|---|---:|---:|
| Logstash | 5,17 % | 3,60 Gio |
| OpenSearch | 2,26 % | 9,12 Gio |
| Filebeat | 0,02 % | 106 Mio |

Le PCAP de référence contenait environ 56 000 paquets pour 4 767 428 octets.
Il a été pris en charge automatiquement en 10 secondes et a produit 4 423
documents réseau dans OpenSearch.

Pendant le traitement, Logstash a atteint 478,12 % CPU, soit environ 4,8
cœurs logiques, et OpenSearch 92,14 %. Aucun service n'est devenu unhealthy.
Soixante secondes plus tard, Logstash était revenu à 6,54 % CPU et la
backpressure des sept pipelines était revenue à zéro.

#### Résultat

La baseline a prouvé le fonctionnement de bout en bout avant duplication et a
fourni les métriques de comparaison.

### Mise À Jour Intermédiaire Vers Malcolm 26.07.1

La base officielle a ensuite été mise à jour de `26.06.0` vers `26.07.1` sur
la branche `upgrade/v26.07.1`. Cette mise à jour a notamment apporté le support
IEC 60870-5-104, des corrections de sécurité, Arkime 6.6.0, Zeek 8.2.1,
Filebeat 9.4.3 et Logstash 9.4.4.

Une sauvegarde complète et un tag de retour ont été créés avant l'intégration.
Les variables réelles ont été migrées avec `./scripts/status`. Le premier
démarrage a validé 27 services, OpenSearch `green` et les interfaces protégées
par Nginx.

La plateforme a ensuite été arrêtée volontairement : en mode complet, la RAM
disponible descendait à environ 5,3 Gio et le swap était saturé ; après arrêt,
environ 25 Gio redevenaient disponibles. Cette observation a conduit à créer
des modes de développement réduits.

### Phase 5 - Créer Deux Instances Logstash

#### Idée

La seconde instance devait réutiliser la définition officielle au lieu de
dupliquer manuellement tout le service.

#### Implémentation

`dev/compose/docker-compose.dev.yml` :

- conserve `logstash` ;
- ajoute `logstash-2` par héritage de la définition officielle ;
- publie le second accès sur le port hôte `5045` ;
- monte le volume `logstash-persistent-queue-2` ;
- applique `restart: unless-stopped` aux services concernés.

Les deux conteneurs écoutent sur `5044` à l'intérieur de leur propre espace
réseau. Il n'y a pas de conflit : seul le mappage hôte diffère.

#### Résultat

Les deux Logstash ont chargé les mêmes sept pipelines, utilisé des volumes de
queue différents et sont devenus `healthy`. OpenSearch est resté `green`, avec
33 shards primaires actifs et aucun shard non assigné.

À vide, OpenSearch utilisait environ 9,1 Gio, Logstash 1 environ 3,6 Gio et
Logstash 2 environ 3,7 Gio. La RAM hôte atteignait environ 22 Gio sur 30 Gio.
La duplication était fonctionnelle, mais la contrainte mémoire était déjà
visible.

### Phase 6 - Sécuriser Et Répartir L'ingestion

#### Idée

Créer deux serveurs ne suffit pas : Filebeat doit connaître les deux
destinations, établir deux connexions et les utiliser. Le transport doit aussi
authentifier le client et les serveurs.

#### Configuration Cible

```yaml
output.logstash:
  hosts:
    - "logstash:5044"
    - "logstash-2:5044"
  loadbalance: true
  ssl.enabled: true
  ssl.verification_mode: full
```

Filebeat vérifie la CA et les noms DNS des serveurs. Chaque Logstash exige un
certificat client valide avec `ssl_client_authentication => "required"`.

L'identifiant OpenSearch est dérivé d'un hash stable. Comme Filebeat fournit
une livraison au moins une fois, une réémission est possible ; l'identifiant
stable évite qu'elle crée automatiquement un doublon.

#### Résultats

- TLS 1.3 validé vers `logstash:5044` et `logstash-2:5044` ;
- client sans certificat refusé ;
- 10 000 événements distribués en `3 200 / 6 800` ;
- 10 000 événements présents dans OpenSearch ;
- réémission de 5 000 événements : 5 000 traitements supplémentaires dans
  Logstash, mais aucun document supplémentaire dans OpenSearch ;
- arrêt de Logstash 1 : 3 000 événements sur 3 000 traités par Logstash 2 ;
- retour automatique des deux instances à l'état `healthy`.

La répartition n'est pas un partage mathématique permanent à 50/50. Filebeat
distribue des lots ; une courte série peut donc être reçue majoritairement par
une instance.

### Phase 7 - Industrialiser Persistance Et Certificats

#### Découverte Importante

Avant correction, les sept pipelines actifs utilisaient encore
`queue.type=memory`. Une configuration de file persistante existait dans le
dépôt pour un autre pipeline, mais elle n'était pas chargée. Cela confirme
qu'un paramètre doit être vérifié dans l'API effective de Logstash.

#### Correction

Les sept pipelines des deux Logstash ont reçu une file persistante :

```yaml
queue.type: persisted
queue.max_bytes: 512mb
path.queue: /logstash-persistent-queue
queue.checkpoint.acks: 1024
queue.checkpoint.writes: 1024
```

`malcolm-output` dispose de 1 Gio, car il est directement exposé à une
indisponibilité OpenSearch. Chaque instance possède six files de 512 Mio et
une file de sortie de 1 Gio, soit 4 Gio théoriques par instance. Les deux
instances ne partagent jamais le même volume.

#### Résultats De Reprise

| Incident contrôlé | Résultat |
|---|---:|
| OpenSearch arrêté | 20 000 / 20 000 retrouvés |
| Deux Logstash redémarrés pendant la panne | 8 000 / 8 000 retrouvés |
| Filebeat redémarré pendant l'indisponibilité | 7 000 / 7 000 retrouvés |
| Événements restant en file après reprise | 0 |
| État final OpenSearch | `green` |

Pendant la panne OpenSearch, 19 250 événements occupaient 34 681 202 octets
dans les files de sortie. Les 750 événements restants étaient en vol dans les
workers, soit deux instances × trois workers × 125 événements.

La taille moyenne mesurée dans la queue était d'environ 1 802 octets par
événement. Ce chiffre sert au dimensionnement, mais doit être remesuré avec le
trafic réel d'un client.

Le certificat de développement était valide jusqu'au 29 octobre 2028. La
phase a aussi ajouté les contrôles d'expiration, de chaîne de confiance et de
noms SAN. En production, la CA locale doit être remplacée par la PKI de
l'organisation.

### Phase 8 - Mettre En Place La Supervision

#### Idée

Un état `running` ne prouve pas que les événements avancent. La supervision
doit corréler Filebeat, les pipelines Logstash, OpenSearch et les ressources de
l'hôte.

#### Éléments Créés

- collecteur d'instantané JSON ;
- boucle de surveillance horodatée ;
- outil de consolidation ;
- seuils RAM, disque, queue et workers ;
- référentiel de requêtes Prometheus ;
- spécification de tableau de bord.

#### Validation Sous Charge

Une injection de 10 000 événements a produit 10 000 documents dans
OpenSearch, resté `green`.

| Indicateur | Valeur maximale ou finale |
|---|---:|
| CPU Logstash 1 | 333,22 % |
| CPU Logstash 2 | 374,18 % |
| CPU OpenSearch | 88,80 % |
| Heap Logstash 1 | 78 % |
| Heap Logstash 2 | 56 % |
| RAM hôte, début / fin | 89,671 % / 91,652 % |
| Disque hôte, fin | 60,305 % |

Aucun conteneur n'est devenu unhealthy et aucune file n'a atteint un seuil
critique. La RAM locale a néanmoins dépassé 90 %, ce qui confirme la limite du
poste de développement.

### Phase 9 - Tester La Résilience Fonctionnelle

#### Idée

Les mécanismes ont été testés ensemble, avec des marqueurs uniques et des
comptages exacts dans OpenSearch.

#### Matrice Finale

| Essai | Attendu | Mesuré | Verdict |
|---|---:|---:|---|
| Fonctionnement normal | 6 000 | 6 000 | PASS |
| Répartition initiale | deux instances | 3 200 / 2 800 | PASS |
| Logstash 1 arrêté | 3 000 | 3 000 via Logstash 2 | PASS |
| Logstash 2 arrêté | 3 000 | 3 000 via Logstash 1 | PASS |
| Retour d'une instance | 20 000 | 20 000 | PASS |
| Réintégration multilot | deux instances | 5 600 / 14 400 | PASS |
| OpenSearch indisponible | queue non vide | 4 425 en file | PASS |
| Reprise OpenSearch | 5 000 | 5 000 | PASS |
| Redémarrage Filebeat | 4 000 | 4 000 | PASS |
| Redémarrage Compose complet | 2 000 | 2 000 | PASS |
| TLS après redémarrage | succès | succès | PASS |

Un premier essai de réintégration reposait sur un seul gros lot et n'avait
utilisé qu'une connexion. Le protocole a été amélioré avec 40 ajouts de 500
événements espacés d'une seconde. Cette correction méthodologique a permis de
prouver la réintégration des deux connexions au lieu de conclure trop vite à
un défaut d'équilibrage.

### Phase 10 - Comparer Un Et Deux Logstash

#### Idée

La résilience et le débit sont deux propriétés différentes. La phase 10 a
comparé les deux modes avec les mêmes événements et les mêmes critères.

#### Résultats De Débit Local

| Palier | Un Logstash | Deux Logstash | Écart du mode double |
|---:|---:|---:|---:|
| 10 000 | 417,28 docs/s | 131,32 docs/s | -68,53 % |
| 25 000 | 312,33 docs/s | 359,45 docs/s | +15,09 % |
| 50 000 | 594,10 docs/s | 518,94 docs/s | -12,65 % |

Les nombres exacts de documents ont été indexés à chaque palier et OpenSearch
est resté `green`. La distribution a été observée en `3 200/6 800`,
`13 800/11 200`, puis `22 800/27 200`.

En mode simple, Logstash a atteint 710,48 % CPU, une heap de 85 % et
OpenSearch 346,67 % CPU. En mode double, les deux Logstash ont atteint
491,83 % et 495,48 % CPU, leurs heaps 89 % et 87 %, et OpenSearch 423,51 %.
La RAM hôte est restée entre 92,484 % et 94,451 %.

#### Conclusion

Le deuxième Logstash apporte une résilience démontrée, mais pas un gain de
débit stable sur un hôte local partagé. Les deux JVM, OpenSearch et les autres
services se disputent les mêmes ressources. Les valeurs locales servent à
valider le code et la méthode, pas à annoncer une capacité client.

### Phase 11 - Documenter Et Livrer

#### Idée

Le projet doit pouvoir être compris, audité, installé et repris par une autre
personne. La livraison ne se limite donc pas au Compose.

#### État

Les documents, scripts, modèles, tests et procédures sont présents. L'audit du
dépôt vérifie :

- la syntaxe Bash et Python ;
- le chargement des YAML ;
- les compositions simple et double ;
- l'absence de clés privées dans les sources ;
- les règles `.gitignore` ;
- les permissions des fichiers sensibles ;
- les espaces et fins de ligne Git.

La revue technique est terminée. La création d'un commit ciblé et son envoi
vers le dépôt interne restent des opérations de livraison distinctes. Les
changements runtime étrangers au développement ne doivent pas être inclus.

---

## 6. Arborescence Finale Et Rôle Des Fichiers

### 6.1 Vue D'ensemble

```text
Oculox/
├── docker-compose.yml
├── docker-compose-dev.yml
├── config/
├── scripts/
├── oculox
└── dev/
    ├── phase1/
    ├── compose/
    │   ├── docker-compose.dev.yml
    │   └── docker-compose.single-logstash.yml
    ├── config/
    │   └── logstash/
    │       ├── input/
    │       └── pipeline-settings/
    ├── scripts/
    ├── tests/
    │   ├── fixtures/
    │   └── results/
    ├── monitoring/
    │   └── data/
    ├── generated/
    │   ├── filebeat/
    │   ├── filebeat-single/
    │   └── pki/
    └── docs/
```

### 6.2 Les Trois Fichiers Compose

#### `docker-compose.yml`

Il s'agit de la base officielle Malcolm. Elle décrit les services complets et
les profils. Elle doit rester aussi proche que possible de l'amont.

#### `dev/compose/docker-compose.dev.yml`

Cette surcharge ajoute le mode résilient : `logstash-2`, la seconde queue,
les montages mTLS, les configurations Filebeat à deux destinations et les
politiques de redémarrage.

Docker Compose fusionne ce fichier avec le fichier officiel. Il ne remplace
pas toute la plateforme.

#### `dev/compose/docker-compose.single-logstash.yml`

Cette deuxième surcharge ne représente pas une autre plateforme. Elle sert à
la comparaison scientifique : elle remonte dans Filebeat les configurations
à une seule destination et garantit qu'un benchmark simple n'utilise pas
accidentellement Logstash 2.

### 6.3 Pourquoi Deux Répertoires Filebeat Générés

`dev/generated/filebeat/` contient les cinq configurations à deux
destinations avec `loadbalance: true`.

`dev/generated/filebeat-single/` contient les mêmes cinq fonctions, mais avec
une seule destination et `loadbalance: false`.

Ces fichiers sont générés à partir de scripts et ne sont pas versionnés. Ils
contiennent l'état résolu pour la machine, notamment les chemins de
certificats et les destinations. Les modèles, scripts et règles qui les
produisent sont les sources versionnées.

### 6.4 `dev/config/`

Ce répertoire contient les ajouts déclaratifs : entrée Beats mTLS et paramètres
de files persistantes. Il ne doit pas contenir les secrets d'une installation.

### 6.5 `dev/scripts/`

Les scripts rendent les opérations reproductibles :

| Famille | Exemples |
|---|---|
| validation | `validate-compose.sh`, `audit-dev-repository.sh` |
| modes locaux | `platform-mode.sh` |
| préparation | `prepare-phase6.sh`, `render-filebeat-ha-config.py` |
| PKI | `generate-beats-pki.sh`, `check-beats-certificates.sh` |
| déploiement | `configure-deployment-role.py`, `create-collector-bundle.sh` |
| mesures | `collect-platform-metrics.py`, `monitor-platform.sh` |

### 6.6 `dev/tests/`

Ce répertoire contient les fixtures, les générateurs déterministes et les
scripts de tests des phases 9 et 10. Les résultats sont placés dans
`dev/tests/results/` et ignorés par Git afin d'éviter de versionner des données
volumineuses ou dépendantes de la machine.

### 6.7 `dev/generated/`

Il s'agit d'un répertoire d'exécution, pas d'un répertoire source. Il peut
contenir :

- configurations Filebeat rendues ;
- certificats et clés de laboratoire ;
- rôle de déploiement ;
- paramètres calculés.

Le supprimer impose de régénérer ces éléments, mais ne supprime pas le code
qui décrit comment les produire.

---

## 7. Modes De Travail Locaux

La plateforme complète est trop lourde pour rester active en permanence sur
le poste. `dev/scripts/platform-mode.sh` fournit donc plusieurs modes :

| Mode | Services principaux | Usage |
|---|---|---|
| `core` | OpenSearch + un Logstash | contrôle minimal historique |
| `single-ingest` | OpenSearch + Filebeat + un Logstash | baseline et comparaison |
| `dual-core` | OpenSearch + deux Logstash | validation des pipelines |
| `dual-ingest` | OpenSearch + Filebeat + deux Logstash | résilience d'ingestion |
| `full` | profil Malcolm complet | contrôle fonctionnel complet ponctuel |
| `stop` / `dual-stop` | aucun conteneur local | libération des ressources |

Les commandes d'arrêt ne comportent pas `-v`. Elles conservent les volumes,
les index, les queues et le registre Filebeat.

---

## 8. Installation Intégrée Sur Des Serveurs Neufs

Le lanceur `./oculox` conserve l'assistant officiel au lieu de le remplacer.

### Principal

```bash
./oculox install principal --server-name <nom-stable-du-principal>
```

La commande enchaîne :

1. l'assistant officiel `scripts/install.py --tui` ;
2. le profil `malcolm` ;
3. `scripts/auth_setup` pour les comptes et secrets ;
4. la génération de la PKI Beats locale ;
5. les configurations Filebeat à deux destinations ;
6. la validation des Compose ;
7. le téléchargement et le démarrage des services.

### Collecteur Hedgehog

Le Principal crée une identité distincte :

```bash
./oculox collector-bundle <collecteur> <principal>
```

Puis le collecteur installe son profil :

```bash
./oculox install hedgehog \
  --principal-host <principal> \
  --collector-name <collecteur> \
  --bundle <répertoire-du-bundle>
```

Le bundle contient la CA publique, le certificat client, sa clé privée et les
deux destinations. La clé privée de la CA ne quitte jamais le Principal.

Les ports 5044 et 5045 doivent être filtrés pour n'accepter que les
collecteurs autorisés. TLS ne remplace pas le pare-feu.

### Limite De Validation

Les scripts, les configurations rendues et les Compose ont été validés
localement. L'installation réellement neuve des deux rôles doit encore être
qualifiée sur deux serveurs vierges représentatifs avant d'être déclarée prête
pour un client.

---

## 9. Synthèse Consolidée Des Preuves

| Propriété | Preuve obtenue |
|---|---|
| Chaîne originale | PCAP traité, 4 423 documents, OpenSearch green |
| Deux Logstash identiques | sept pipelines chargés sur chaque instance |
| Isolation des queues | deux volumes persistants distincts |
| Répartition Filebeat | 3 200/6 800 puis autres répartitions multilot |
| TLS serveur | TLS 1.3 et noms DNS vérifiés |
| Authentification client | client sans certificat refusé |
| Idempotence | réémission de 5 000 événements, zéro document ajouté |
| Perte d'un Logstash | 3 000/3 000 traités par l'instance restante |
| Panne OpenSearch | 20 000/20 000 retrouvés après reprise |
| Redémarrage des Logstash | 8 000/8 000 retrouvés |
| Redémarrage Filebeat | 7 000/7 000 retrouvés grâce au registre |
| Redémarrage complet | données, TLS, files et registre conservés |
| Supervision | métriques par hôte, conteneur, JVM, pipeline et queue |
| Tests phase 9 | tous les essais PASS |
| Comparaison locale | tous les nombres attendus indexés, pas de gain stable de débit |
| Version logicielle | Malcolm 26.07.1 intégré et validé |
| Audit du dépôt | syntaxe, Compose, secrets et hygiène contrôlés |

---

## 10. Ce Qui Est Démontré Et Ce Qui Ne L'est Pas

### Démontré

- Filebeat peut utiliser deux Logstash simultanément ;
- une seule instance Logstash peut assurer la continuité pendant la panne de
  l'autre ;
- les files persistantes absorbent des interruptions contrôlées ;
- Filebeat reprend grâce à son registre ;
- le transport Beats est chiffré et authentifié dans les deux sens ;
- les réémissions contrôlées ne créent pas de doublons dans le cas testé ;
- les modifications sont séparées de la base officielle et auditables ;
- la plateforme peut être exploitée localement en modes réduits.

### Non Démontré

- haute disponibilité après perte du serveur Principal ;
- réplication des files Logstash entre machines ;
- haute disponibilité OpenSearch ;
- capacité contractuelle en Gbit/s ;
- endurance sur plusieurs heures ou jours dans cette architecture locale ;
- dimensionnement définitif des queues et de la rétention client ;
- installation de bout en bout sur deux serveurs vierges représentatifs.

La prochaine architecture de production devra placer les instances Logstash
sur des domaines de panne distincts et utiliser un cluster OpenSearch d'au
moins trois nœuds correctement dimensionnés. Cette évolution constitue un
nouveau chantier ; elle ne doit pas être présentée comme déjà implémentée.

---

## 11. État Final Et Prochaines Étapes

Le développement local est fonctionnel, documenté et testé. La seconde
instance Logstash apporte une continuité de service réelle au niveau de
l'ingestion. Les essais montrent également pourquoi la résilience ne doit pas
être confondue avec un doublement automatique des performances.

Les prochaines opérations sont :

1. relire et créer un commit Git ciblé sans données runtime ni secrets ;
2. pousser la branche vers le dépôt interne et ouvrir une revue ;
3. installer le Principal et Hedgehog sur deux serveurs neufs de qualification ;
4. remplacer la PKI de laboratoire par la PKI administrée ;
5. répéter les tests de résilience et de performance avec des ressources
   indépendantes ;
6. définir ensuite l'architecture du cluster OpenSearch, sa sauvegarde, sa
   rétention et ses critères de reprise.

Le résultat actuel est donc une base de développement résiliente maîtrisée,
pas encore une plateforme de production entièrement hautement disponible.

---

## 12. Documents De Référence

### Compréhension De L'existant

- `dev/phase1/01_identifier_fichiers_orchestration.md` ;
- `dev/phase1/02_structure_service_docker_compose.md` ;
- `dev/phase1/03_chemin_des_donnees.md` ;
- `dev/phase1/04_filebeat_logstash_tls_persistance.md`.

### Développement Et Validation

- `dev/docs/00_plan_directeur_developpement_resilient.md` ;
- `dev/docs/01_preparation_depot_developpement.md` ;
- `dev/docs/02_architecture_cible_deux_logstash.md` ;
- `dev/docs/03_baseline_un_logstash.md` ;
- `dev/docs/05_mise_a_jour_malcolm_v26_07_1.md` ;
- `dev/docs/06_phase5_deux_instances_logstash.md` ;
- `dev/docs/07_phase6_repartition_tls_idempotence.md` ;
- `dev/docs/08_phase7_persistance_reprise_certificats.md` ;
- `dev/docs/09_phase8_supervision.md` ;
- `dev/docs/10_phase9_tests_resilience.md` ;
- `dev/docs/11_phase10_benchmark_comparatif.md` ;
- `dev/docs/12_audit_proprete_et_perimetre_local.md` ;
- `dev/docs/13_installation_resiliente_principal_hedgehog.md` ;
- `dev/docs/14_comprendre_arborescence_dev_compose_filebeat.md`.

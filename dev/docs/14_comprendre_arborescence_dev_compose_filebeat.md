# Comprendre L'Arborescence `dev/`, Les Fichiers Compose Et Filebeat

## 1. Objectif Du Répertoire `dev/`

Le dépôt Oculox contient deux catégories de fichiers :

1. les fichiers officiels de Malcolm, conservés à la racine du dépôt ;
2. les ajouts Oculox placés dans `dev/`.

Cette séparation est volontaire. Elle permet de mettre à jour Malcolm sans
mélanger silencieusement le code officiel et les adaptations Oculox. Elle
permet aussi de voir précisément ce qui a été ajouté pour obtenir :

- deux instances Logstash ;
- une répartition des événements par Filebeat ;
- un transport TLS avec authentification mutuelle ;
- des files persistantes indépendantes ;
- des scripts de validation, de supervision et de reprise.

Le répertoire `dev/` n'est donc pas une seconde installation de Malcolm. Il
complète l'installation officielle.

---

## 2. Vue D'Ensemble De L'Arborescence

```text
Oculox/
├── docker-compose.yml                    # orchestration officielle Malcolm
├── filebeat/                             # configurations officielles Filebeat
├── logstash/                             # pipelines officiels Logstash
├── config/                               # configuration réelle de Malcolm
├── scripts/                              # scripts officiels Malcolm
├── oculox                                # commande d'exploitation Oculox
└── dev/
    ├── phase1/                           # étude détaillée de l'existant
    ├── compose/                          # surcharges Docker Compose Oculox
    ├── config/                           # configuration ajoutée par Oculox
    ├── generated/                        # fichiers produits localement
    ├── scripts/                          # automatisation Oculox
    ├── tests/                            # tests fonctionnels et de résilience
    ├── monitoring/                       # métriques et résultats de supervision
    └── docs/                             # architecture, procédures et décisions
```

### 2.1 `dev/phase1/`

Ce dossier explique l'installation officielle avant modification : fichiers
Compose, chemin des données, Filebeat, Logstash, TLS et volumes persistants.
Il sert de base de compréhension.

### 2.2 `dev/compose/`

Ce dossier contient uniquement les différences d'orchestration ajoutées par
Oculox. Il ne contient pas une copie complète du Compose officiel.

### 2.3 `dev/config/`

Ce dossier contient les configurations Oculox qui doivent être lisibles et
versionnées : entrée Beats renforcée et paramètres des files persistantes.

### 2.4 `dev/generated/`

Ce dossier contient des fichiers propres à une installation : certificats,
clés privées, état du rôle et configurations Filebeat rendues. Il est ignoré
par Git et peut être reconstruit par les scripts.

### 2.5 `dev/scripts/`

Les scripts transforment les modèles versionnés en configuration utilisable.
Ils évitent les manipulations manuelles et rendent la préparation
reproductible.

### 2.6 `dev/tests/`

Ce dossier contient les générateurs d'événements et les scénarios qui vérifient
la distribution, le basculement, la reprise et la comparaison simple/double.

### 2.7 `dev/monitoring/`

Ce dossier décrit les métriques à surveiller et contient les résultats locaux.
Les résultats sont utiles pour la validation de développement, mais ne
constituent pas un dimensionnement de production.

### 2.8 `dev/docs/`

Ce dossier conserve les choix d'architecture, les preuves, les procédures et
les limites connues. Il explique pourquoi le code existe et comment
l'exploiter.

---

## 3. Pourquoi Plusieurs Fichiers Docker Compose ?

Il existe en réalité trois niveaux possibles. Ils ne représentent pas trois
plateformes différentes.

### 3.1 Le Compose Officiel : `docker-compose.yml`

Le fichier à la racine est la base fournie par Malcolm. Il déclare notamment :

- `opensearch` ;
- `logstash` ;
- `filebeat` ;
- `zeek`, `suricata` et `arkime` ;
- les interfaces web et les services complémentaires ;
- les images, profils, réseaux, variables, volumes et healthchecks.

Ce fichier continue d'être la source principale. Il n'a pas été dupliqué dans
`dev/`.

### 3.2 La Surcharge Résiliente : `dev/compose/docker-compose.dev.yml`

Ce fichier est fusionné avec le Compose officiel. Il ajoute ou remplace
seulement les propriétés nécessaires à Oculox :

- politique `restart: unless-stopped` ;
- configurations Filebeat générées ;
- certificats TLS Oculox ;
- entrée Beats avec authentification du client ;
- files persistantes des pipelines Logstash ;
- exposition de Logstash 1 sur `5044` ;
- création de `logstash-2`, exposé sur `5045` ;
- volume de queue distinct pour `logstash-2`.

La fusion est équivalente à :

```bash
docker compose \
  --project-directory . \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  config
```

L'ordre est important : le fichier placé après `docker-compose.yml` surcharge
la base.

### 3.3 La Surcharge De Comparaison : `docker-compose.single-logstash.yml`

Ce fichier ne constitue pas le mode normal de production. Il sert à revenir à
une seule destination Logstash pour :

- établir une baseline ;
- comparer un Logstash et deux Logstash ;
- diagnostiquer un problème ;
- vérifier que la résilience apporte bien le comportement attendu.

Il est appliqué en troisième position :

```bash
docker compose \
  --project-directory . \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  -f dev/compose/docker-compose.single-logstash.yml \
  config
```

Cette troisième couche remplace uniquement les fichiers montés dans Filebeat
par leurs variantes à une destination. Le script `platform-mode.sh` arrête
également `logstash-2` pour garantir que le test est réellement effectué avec
un seul Logstash.

### 3.4 Pourquoi Ne Pas Modifier Directement Le Compose Officiel ?

Une modification directe fonctionnerait, mais elle créerait trois problèmes :

1. une mise à jour de Malcolm pourrait écraser ou entrer en conflit avec nos
   changements ;
2. il serait difficile de distinguer le code officiel du code Oculox ;
3. le retour à la configuration d'origine serait risqué.

Avec une surcharge, le Compose officiel reste identifiable et les différences
Oculox restent concentrées dans un petit fichier.

---

## 4. Lecture Détaillée De `docker-compose.dev.yml`

### 4.1 `services:`

Cette clé indique que le fichier modifie des services Docker Compose. Quand un
nom existe déjà dans le Compose officiel, Compose fusionne les deux
déclarations.

Exemple :

```yaml
services:
  opensearch:
    restart: unless-stopped
```

Cela ne recrée pas OpenSearch. L'image, les variables, les volumes, le réseau
et le healthcheck continuent de venir du fichier officiel. Seule la politique
de redémarrage est remplacée.

### 4.2 `restart: unless-stopped`

Cette politique signifie :

- redémarrer le conteneur s'il s'arrête anormalement ;
- le relancer après un redémarrage de Docker ou de la machine ;
- ne pas le relancer si un administrateur l'a explicitement arrêté.

Elle est indiquée pour les services des profils Principal et Hedgehog afin que
le comportement ne dépende pas d'une réponse différente donnée dans
l'installateur officiel.

### 4.3 Surcharge Du Service `filebeat`

Le service Filebeat existe déjà dans le Compose officiel. Oculox ajoute des
montages en lecture seule :

```yaml
- ./dev/generated/filebeat/filebeat-logs.yml:/usr/share/filebeat-logs/filebeat-logs.yml:ro
- ./dev/generated/pki/ca.crt:/certs/ca.crt:ro
- ./dev/generated/pki/client.crt:/certs/client.crt:ro
- ./dev/generated/pki/client.key:/certs/client.key:ro
```

La partie gauche est le fichier sur l'hôte. La partie droite est son
emplacement dans le conteneur. `ro` signifie *read-only* : le conteneur peut le
lire, mais pas le modifier.

Ces montages remplacent les fichiers officiels aux mêmes emplacements dans le
conteneur. Filebeat conserve toutes ses entrées officielles, mais utilise la
sortie Logstash et les règles TLS générées par Oculox.

### 4.4 Surcharge Du Premier `logstash`

Le service officiel `logstash` est conservé. La surcharge lui ajoute :

- le port hôte `5044` vers le port conteneur `5044` ;
- l'entrée Beats TLS renforcée ;
- les réglages de files persistantes ;
- le certificat serveur et sa clé.

Le port est écrit ainsi :

```yaml
"${OCULOX_LOGSTASH_BIND_IP:-0.0.0.0}:5044:5044/tcp"
```

Sa lecture est :

```text
adresse d'écoute de l'hôte : port de l'hôte : port du conteneur
```

La valeur par défaut `0.0.0.0` écoute sur toutes les interfaces de l'hôte. En
production, `OCULOX_LOGSTASH_BIND_IP` peut limiter l'écoute à l'interface
prévue pour les collecteurs.

### 4.5 Création De `logstash-2`

Le service `logstash-2` n'existe pas dans Malcolm standard. Il est ajouté par :

```yaml
logstash-2:
  extends:
    file: docker-compose.yml
    service: logstash
```

`extends` signifie : reprendre la définition officielle de `logstash`. La
seconde instance récupère donc la même image, les mêmes fichiers `.env`, les
mêmes pipelines, le même réseau, les mêmes dépendances et le même healthcheck.

Oculox modifie ensuite uniquement son identité et ses ressources propres :

```yaml
hostname: logstash-2
ports:
  - "...:5045:5044/tcp"
volumes:
  - logstash-persistent-queue-2:/logstash-persistent-queue
```

Le port externe est `5045`, mais Logstash écoute toujours sur `5044` dans son
conteneur. Les deux instances ne peuvent pas publier le même port hôte.

### 4.6 Pourquoi Deux Volumes De Queue ?

Le premier Logstash utilise le volume officiel :

```text
logstash-persistent-queue
```

Le second utilise :

```text
logstash-persistent-queue-2
```

Une file persistante contient des événements en attente sur disque. Deux
processus Logstash ne doivent jamais ouvrir la même file : cela provoquerait
un verrouillage ou une corruption. Chaque instance possède donc sa propre
queue.

### 4.7 Bloc Final `volumes:`

```yaml
volumes:
  logstash-persistent-queue-2:
```

Ce bloc demande à Docker de gérer le volume nommé de la seconde instance. Il
survit au redémarrage du conteneur et à un `docker compose down` sans option
`-v`.

---

## 5. Pourquoi Y A-T-Il Plusieurs Fichiers Filebeat ?

Il n'y a qu'un service Docker nommé `filebeat`, mais l'image Malcolm lance
plusieurs processus/configurations Filebeat spécialisés.

| Fichier | Source surveillée |
|---|---|
| `filebeat-logs.yml` | logs Zeek, Suricata et résultats filescan |
| `filebeat-nginx.yml` | journaux d'accès et d'erreur Nginx |
| `filebeat-syslog-tcp.yml` | messages Syslog reçus en TCP |
| `filebeat-syslog-udp.yml` | messages Syslog reçus en UDP |
| `filebeat-tcp.yml` | événements reçus par l'entrée TCP générique |

Ces cinq fichiers existaient déjà dans le dossier officiel `filebeat/`. Oculox
n'a pas inventé cinq nouveaux collecteurs. Il génère cinq variantes parce que
chaque processus possède sa propre section `output.logstash`.

Si un seul fichier était modifié, les autres processus continueraient à
envoyer vers l'ancienne destination ou sans la même politique TLS.

---

## 6. Pourquoi Deux Répertoires Dans `dev/generated/` ?

Les deux répertoires sont :

```text
dev/generated/filebeat/          # mode résilient, deux Logstash
dev/generated/filebeat-single/   # mode de comparaison, un Logstash
```

Ce ne sont pas deux conteneurs Filebeat. Ce sont deux jeux de configuration
pour le même service.

### 6.1 Mode Résilient

Dans `dev/generated/filebeat/`, chaque fichier contient :

```yaml
output.logstash:
  hosts:
    - logstash:5044
    - logstash-2:5044
  loadbalance: true
```

Filebeat maintient des connexions vers les deux destinations et répartit les
lots d'événements. Si une destination devient indisponible, la destination
encore saine peut continuer à recevoir les événements.

`loadbalance: true` ne transforme pas Filebeat en équipement réseau séparé.
C'est une fonction du client Filebeat pour répartir ses propres événements.

### 6.2 Mode Simple

Dans `dev/generated/filebeat-single/`, la sortie devient :

```yaml
output.logstash:
  hosts:
    - logstash:5044
  loadbalance: false
```

Ce mode sert uniquement à la comparaison et au diagnostic. L'architecture
cible normale utilise `dev/generated/filebeat/`.

### 6.3 Pourquoi Ces Fichiers N'Étaient-Ils Pas Présents À L'Origine ?

Les fichiers officiels utilisent une seule destination générique :

```yaml
hosts: ["${LOGSTASH_HOST:logstash:5044}"]
```

Ils autorisent aussi une configuration TLS moins stricte selon les variables.
Pour l'architecture Oculox, il fallait produire une configuration qui impose :

- deux destinations en mode résilient ;
- `loadbalance: true` ;
- TLS 1.2 ou TLS 1.3 ;
- vérification complète du certificat serveur ;
- certificat client Filebeat pour l'authentification mutuelle.

Les fichiers officiels restent les modèles d'entrée. Le script ne change que
la section de sortie et active l'API HTTP de métriques sur le processus
principal.

---

## 7. Comment Les Fichiers Filebeat Sont Générés

Le script responsable est :

```text
dev/scripts/render-filebeat-ha-config.py
```

Son fonctionnement est le suivant :

1. lire chaque fichier officiel dans `filebeat/` avec un parseur YAML ;
2. conserver les entrées, processeurs et tags existants ;
3. remplacer la section `output.logstash` ;
4. écrire le résultat dans `dev/generated/` ;
5. ajouter un avertissement indiquant de ne pas modifier le résultat.

Pour les essais locaux, son exécution sans argument produit les deux modes :

```bash
./dev/scripts/render-filebeat-ha-config.py
```

Pour une installation Principal, la commande `./oculox prepare principal`
génère uniquement la configuration opérationnelle avec les destinations
internes :

```text
logstash:5044
logstash-2:5044
```

Pour un Hedgehog, `./oculox prepare hedgehog` génère les destinations externes
du Principal :

```text
nom-du-principal:5044
nom-du-principal:5045
```

Il ne faut pas modifier directement un fichier de `dev/generated/`, car une
nouvelle préparation écraserait cette modification. Le changement doit être
fait dans le modèle ou dans le script de rendu.

---

## 8. Contenu De `dev/generated/`

### 8.1 `deployment.env`

Ce fichier mémorise le rôle préparé :

- `principal` ou `hedgehog` ;
- nom du serveur Principal ;
- nom du collecteur ;
- adresse du Principal pour un collecteur.

La commande `./oculox start` le lit pour sélectionner automatiquement le
profil `malcolm` ou `hedgehog`.

### 8.2 `pki/`

Ce dossier contient les éléments TLS générés localement :

- `ca.crt` : certificat public de l'autorité ;
- `ca.key` : clé privée de l'autorité, uniquement sur le Principal ;
- `server.crt` et `server.key` : identité des Logstash ;
- `client.crt` et `client.key` : identité de Filebeat.

Les clés privées ne doivent jamais être poussées dans Git. Un collecteur ne
reçoit pas la clé privée de l'autorité ni la clé privée du serveur.

### 8.3 Pourquoi `generated/` Est Ignoré Par Git

Le fichier `dev/.gitignore` contient :

```gitignore
generated/
```

Le dépôt versionne la méthode de génération, pas les secrets d'une machine.
Sur un serveur neuf, `./oculox install` ou `./oculox prepare` recrée ces
fichiers avec les identités de ce serveur.

---

## 9. Configurations Logstash Ajoutées

### 9.1 Entrée Beats TLS

Le fichier suivant remplace l'entrée Beats des deux instances :

```text
dev/config/logstash/input/01_beats_input.conf
```

Il configure :

- écoute sur `0.0.0.0:5044` dans le conteneur ;
- chiffrement TLS ;
- certificat serveur Logstash ;
- autorité utilisée pour vérifier Filebeat ;
- authentification client obligatoire.

La connexion est donc mutuellement authentifiée : Filebeat vérifie Logstash et
Logstash vérifie Filebeat.

### 9.2 Files Persistantes

Les trois modèles définissent :

- une queue de `512mb` pour les pipelines standards ;
- une queue de `512mb` et un worker pour le pipeline d'entrée ;
- une queue de `1gb` pour le pipeline de sortie vers OpenSearch.

Une queue persistante absorbe une interruption courte. Elle ne remplace pas un
dimensionnement correct et ne constitue pas un stockage illimité.

---

## 10. Quel Fichier Est Utilisé Selon La Commande ?

| Commande | Compose chargés | Filebeat utilisé | Logstash actifs |
|---|---|---|---|
| `./dev/scripts/platform-mode.sh single-ingest` | officiel + dev + single | `filebeat-single/` | `logstash` |
| `./dev/scripts/platform-mode.sh dual-ingest` | officiel + dev | `filebeat/` | `logstash`, `logstash-2` |
| `./oculox start` sur Principal | officiel + dev | `filebeat/` | `logstash`, `logstash-2` |
| `./oculox start` sur Hedgehog | officiel + dev, profil Hedgehog | `filebeat/` vers le Principal | aucun Logstash local |

Le mode `single-ingest` appartient au laboratoire de développement. Le lanceur
`./oculox` utilise toujours la surcharge résiliente.

---

## 11. Chemin Réel Des Données En Mode Résilient

```text
Zeek / Suricata / autres sources
            |
            v
     fichiers et entrées
            |
            v
   un conteneur Filebeat
   plusieurs configurations
            |
            | TLS mutuel + répartition
            +---------------------+
            |                     |
            v                     v
   logstash:5044          logstash-2:5044
   queue propre           queue propre
            |                     |
            +----------+----------+
                       |
                       v
                  OpenSearch
```

Filebeat ne duplique normalement pas chaque événement vers les deux Logstash.
Il répartit les lots. Les deux Logstash exécutent les mêmes pipelines et
écrivent dans le même OpenSearch.

---

## 12. Ce Qui Est Source Et Ce Qui Est Produit

| Élément | Nature | Versionné | Modification directe |
|---|---|---:|---:|
| `docker-compose.yml` | source officielle Malcolm | oui | à éviter |
| `dev/compose/*.yml` | différences Oculox | oui | oui, après validation |
| `filebeat/*.yml` | sources officielles Filebeat | oui | à éviter |
| `render-filebeat-ha-config.py` | générateur Oculox | oui | oui |
| `dev/generated/filebeat/*` | résultat local | non | non |
| `dev/config/logstash/*` | configuration Oculox | oui | oui |
| `dev/generated/pki/*` | certificats et secrets locaux | non | non |
| `deployment.env` | état local du rôle | non | non manuellement |
| `dev/tests/results/` | résultats d'essais | non | produit par les tests |
| `dev/monitoring/data/` | mesures locales | non | produit par la supervision |

---

## 13. Commandes De Compréhension Sans Démarrage

Afficher les services résultant de la fusion :

```bash
docker compose \
  --project-directory . \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  --profile malcolm \
  config --services
```

Valider toutes les variantes sans démarrer les conteneurs :

```bash
./dev/scripts/validate-compose.sh
```

Contrôler le dépôt complet :

```bash
./dev/scripts/audit-dev-repository.sh
```

Afficher le rôle local :

```bash
cat dev/generated/deployment.env
```

Comparer uniquement les destinations des deux modes :

```bash
grep -A8 '^output.logstash:' dev/generated/filebeat/filebeat-logs.yml
grep -A8 '^output.logstash:' dev/generated/filebeat-single/filebeat-logs.yml
```

Il faut éviter de publier la sortie complète de `docker compose config`, car
Compose peut développer des variables sensibles provenant des fichiers
`config/*.env`.

---

## 14. Résumé À Retenir

1. `docker-compose.yml` est la base officielle Malcolm.
2. `docker-compose.dev.yml` ajoute la résilience sans réécrire la base.
3. `docker-compose.single-logstash.yml` sert uniquement aux comparaisons et au
   diagnostic.
4. Il existe un conteneur Filebeat, mais plusieurs configurations spécialisées
   dans ce conteneur.
5. `filebeat/` contient les sources officielles.
6. `dev/generated/filebeat/` contient le mode à deux Logstash.
7. `dev/generated/filebeat-single/` contient le mode de référence à un
   Logstash.
8. `generated/` n'est pas versionné, car il contient des fichiers locaux et
   des secrets.
9. `./oculox` prépare les fichiers puis charge toujours le Compose officiel et
   la surcharge résiliente.
10. Les benchmarks de capacité restent à exécuter sur le serveur cible ; la
    structure locale sert à valider le code, la sécurité et la reprise.

# Phase 5 - Création De Deux Instances Logstash

## 1. Objectif

Cette phase ajoute une seconde instance Logstash à l'environnement local sans
modifier le service Logstash officiel de Malcolm.

L'objectif technique est d'obtenir :

```text
                         +--> logstash   --> queue persistante 1 --+
Filebeat (phase suivante)                                        +--> OpenSearch
                         +--> logstash-2 --> queue persistante 2 --+
```

À la fin de cette phase :

- les deux Logstash existent ;
- ils utilisent la même version et les mêmes pipelines ;
- ils peuvent fonctionner simultanément ;
- chaque instance possède sa propre file persistante ;
- les deux instances peuvent joindre le même OpenSearch ;
- Filebeat n'est pas encore configuré pour distribuer les événements.

La répartition Filebeat appartient à la phase 6. Cette séparation est
volontaire : elle permet de valider l'orchestration avant d'introduire du
trafic.

## 2. Fichiers Concernés

| Fichier | Rôle |
|---|---|
| `docker-compose.yml` | Définition officielle Malcolm, conservée intacte |
| `dev/compose/docker-compose.dev.yml` | Surcharge locale qui ajoute `logstash-2` |
| `dev/scripts/platform-mode.sh` | Démarrage et arrêt du mode réduit à deux Logstash |
| `dev/scripts/validate-compose.sh` | Validation de la configuration fusionnée |

Le fichier officiel reste la référence. Nos changements sont isolés sous
`dev/`, ce qui facilite leur lecture, leur révision et leur retour arrière.

## 3. Code Ajouté

La seconde instance est déclarée ainsi :

```yaml
services:
  logstash-2:
    extends:
      file: docker-compose.yml
      service: logstash
    hostname: logstash-2
    volumes:
      - logstash-persistent-queue-2:/logstash-persistent-queue

volumes:
  logstash-persistent-queue-2:
```

### `services`

Cette clé contient les conteneurs gérés par Docker Compose. Le nouveau service
porte le nom logique `logstash-2`. Docker Compose produit ici le conteneur
`oculox-logstash-2-1` parce que le projet Compose s'appelle `oculox`.

### `extends`

`extends` évite de recopier plusieurs dizaines de lignes du service officiel.
Il demande à Compose de prendre `logstash` comme modèle.

La seconde instance hérite notamment :

- de l'image `ghcr.io/idaholab/malcolm/logstash-oss:26.07.1` ;
- des fichiers `config/*.env` utilisés par Logstash ;
- des définitions des sept pipelines Malcolm ;
- des certificats et fichiers de confiance ;
- de la connexion au réseau Docker du projet ;
- de la dépendance envers OpenSearch ;
- du contrôle de santé ;
- des capacités et limites système du service officiel.

Cette approche réduit le risque de divergence. Une mise à jour apportée au
service officiel reste héritée par `logstash-2`, sauf pour les propriétés que
nous remplaçons explicitement.

### `file: docker-compose.yml`

La commande Compose utilise :

```bash
--project-directory /home/kakashi_/ICSHUB/Oculox
```

Le fichier référencé par `extends` est donc résolu depuis la racine du projet.
Le nom correct est `docker-compose.yml`, et non `../../docker-compose.yml`.

### `service: logstash`

Cette ligne désigne le service source dans le Compose officiel. Elle ne crée
pas un lien d'exécution entre les conteneurs : elle sert uniquement à construire
la configuration de `logstash-2`.

### `hostname: logstash-2`

Chaque conteneur possède son propre nom d'hôte. Cela permet de distinguer les
instances dans les logs, les métriques et les diagnostics.

Le nom du service devient également résolvable sur le réseau Docker : un autre
conteneur du projet pourra joindre la seconde instance avec
`logstash-2:5044`.

### `volumes`

La ligne suivante affecte une file persistante indépendante à la seconde
instance :

```yaml
- logstash-persistent-queue-2:/logstash-persistent-queue
```

Elle contient deux éléments :

```text
logstash-persistent-queue-2 : nom du volume géré par Docker
/logstash-persistent-queue  : chemin utilisé dans le conteneur
```

Lors de la fusion, Compose identifie les montages par leur chemin cible. Le
nouveau montage remplace donc uniquement le volume hérité qui ciblait
`/logstash-persistent-queue`. Les autres montages, par exemple les pipelines,
les certificats et les fichiers de configuration, restent hérités.

### Déclaration Du Volume

```yaml
volumes:
  logstash-persistent-queue-2:
```

Cette déclaration demande à Docker de gérer le cycle de vie du volume. Un
simple arrêt ou un `docker compose down` sans option `-v` ne supprime pas son
contenu.

## 4. Pourquoi Les Queues Doivent Être Séparées

Une file persistante Logstash contient des pages, des checkpoints et l'état de
lecture propre à un processus Logstash. Ce n'est pas une base partagée conçue
pour être ouverte simultanément par deux instances.

La configuration correcte est :

```text
logstash   -> oculox_logstash-persistent-queue
logstash-2 -> oculox_logstash-persistent-queue-2
```

Partager le même volume pourrait provoquer des conflits de verrouillage, une
corruption de queue ou un comportement de reprise non déterministe.

## 5. Pourquoi Les Deux Services Utilisent Le Port 5044

Chaque conteneur possède son propre espace réseau. Le port `5044` de
`logstash` et le port `5044` de `logstash-2` ne sont donc pas le même socket.

```text
logstash:5044   -> espace réseau du premier conteneur
logstash-2:5044 -> espace réseau du second conteneur
```

Aucun port supplémentaire n'est publié sur l'hôte. Filebeat communiquera avec
les noms des services sur le réseau Docker interne.

## 6. Commandes De Maîtrise

### Valider Sans Démarrer

```bash
./dev/scripts/validate-compose.sh
```

Cette commande demande à Compose de fusionner le fichier officiel et la
surcharge. Une validation réussie prouve que la syntaxe et les références sont
cohérentes ; elle ne prouve pas encore que les conteneurs peuvent démarrer.

Pour lire la configuration réellement comprise par Compose :

```bash
docker compose \
  --project-directory /home/kakashi_/ICSHUB/Oculox \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  config
```

Il faut toujours raisonner sur cette configuration fusionnée, pas uniquement
sur le petit fichier de surcharge.

### Démarrer Le Mode Réduit

```bash
./dev/scripts/platform-mode.sh dual-core
```

Ce mode ne démarre que :

- OpenSearch ;
- `logstash` ;
- `logstash-2`.

Il évite de charger toute la plateforme Malcolm sur une machine de
développement limitée en RAM.

### Vérifier L'état

```bash
docker compose \
  --project-directory /home/kakashi_/ICSHUB/Oculox \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  --profile malcolm ps
```

### Lire Les Pipelines D'une Instance

```bash
docker exec oculox-logstash-1 \
  curl -fsS http://localhost:9600/_node/pipelines | jq '.pipelines | keys'

docker exec oculox-logstash-2-1 \
  curl -fsS http://localhost:9600/_node/pipelines | jq '.pipelines | keys'
```

Le port `9600` est l'API de supervision interne de Logstash. Il ne reçoit pas
les événements Beats ; ceux-ci arrivent sur `5044`.

### Vérifier Les Volumes De Queue

```bash
docker inspect oculox-logstash-1 \
  --format '{{range .Mounts}}{{if eq .Destination "/logstash-persistent-queue"}}{{.Name}}{{end}}{{end}}'

docker inspect oculox-logstash-2-1 \
  --format '{{range .Mounts}}{{if eq .Destination "/logstash-persistent-queue"}}{{.Name}}{{end}}{{end}}'
```

Les deux résultats doivent être différents.

### Mesurer Les Ressources

```bash
docker stats --no-stream \
  oculox-opensearch-1 \
  oculox-logstash-1 \
  oculox-logstash-2-1
```

### Arrêter Sans Effacer Les Volumes

```bash
./dev/scripts/platform-mode.sh dual-stop
```

La commande ne contient pas `-v`. Les files persistantes sont donc conservées.

## 7. Résultats De Validation

### Santé Des Services

| Service | État observé |
|---|---|
| `oculox-opensearch-1` | `healthy` |
| `oculox-logstash-1` | `healthy` |
| `oculox-logstash-2-1` | `healthy` |

OpenSearch était `green`, avec 33 shards primaires actifs, aucun shard non
assigné et aucune tâche en attente.

### Pipelines Chargés

Les deux instances ont chargé exactement les sept pipelines suivants :

```text
malcolm-beats
malcolm-enrichment
malcolm-filescan
malcolm-input
malcolm-output
malcolm-suricata
malcolm-zeek
```

Cette égalité confirme que `logstash-2` hérite du même traitement fonctionnel
que l'instance officielle.

### Entrée Beats

Les deux conteneurs écoutaient sur TCP `5044` en état `LISTEN`. Ils sont donc
prêts à recevoir Filebeat, mais aucune répartition n'a encore été activée.

### Files Persistantes

| Instance | Volume observé |
|---|---|
| `oculox-logstash-1` | `oculox_logstash-persistent-queue` |
| `oculox-logstash-2-1` | `oculox_logstash-persistent-queue-2` |

La règle critique de séparation des queues est respectée.

### Ressources Observées À Vide

| Service | Mémoire approximative |
|---|---:|
| OpenSearch | 9,1 Gio |
| Logstash 1 | 3,6 Gio |
| Logstash 2 | 3,7 Gio |

La machine utilisait environ 22 Gio sur 30 Gio, avec environ 8 Gio encore
disponibles grâce au cache récupérable. Cela confirme que le mode complet ne
doit pas être démarré en parallèle sur cette machine pendant le développement.

### Erreurs

Aucune occurrence récente correspondant à `error`, `exception`, `fatal` ou
`failed` n'a été relevée dans les logs des deux instances après leur
stabilisation.

## 8. Ce Que Cette Phase Prouve

La phase 5 prouve que :

1. une seconde instance peut être ajoutée sans copier le service officiel ;
2. les deux instances exécutent le même code et les mêmes pipelines ;
3. elles utilisent deux espaces réseau indépendants ;
4. elles écoutent toutes les deux sur leur port interne `5044` ;
5. elles ne partagent pas leur file persistante ;
6. elles peuvent fonctionner avec le même OpenSearch ;
7. l'environnement reste exploitable en mode réduit.

## 9. Ce Que Cette Phase Ne Prouve Pas Encore

Cette phase ne prouve pas encore :

- que Filebeat distribue les événements entre les deux instances ;
- que la distribution est équilibrée ;
- qu'une panne d'une instance est absorbée sans perte ;
- que la validation TLS est suffisamment stricte ;
- que deux Logstash augmentent le débit global ;
- qu'OpenSearch est lui-même hautement disponible.

Ces points seront traités dans les phases suivantes.

## 10. Point De Sécurité À Conserver

La configuration actuelle réutilise les certificats Malcolm existants. La
validation TLS observée dans l'environnement n'est pas encore la cible finale
de durcissement. Avant de distribuer le trafic, il faudra vérifier les noms
présents dans les certificats et activer une validation stricte compatible avec
`logstash` et `logstash-2`.

Ce sujet appartient à la phase 7. Il ne doit pas être masqué par le succès du
démarrage de la phase 5.

## 11. Conclusion

La couche Logstash est désormais dupliquée de manière contrôlée. Le code
officiel reste intact, la seconde instance est définie dans une surcharge
lisible, les pipelines sont identiques et les queues sont indépendantes.

La prochaine étape est la phase 6 : configurer explicitement Filebeat avec les
deux destinations et `loadbalance: true`, puis prouver par les métriques que
les deux Logstash reçoivent réellement des événements.

# Mise À Jour Oculox / Malcolm Vers La Version 26.07.1

## 1. Objet Du Document

Ce document décrit la mise à jour réelle du dépôt local Oculox, depuis la base Malcolm `26.06.0` vers la version officielle `26.07.1`. Il présente les contrôles effectués, les commandes utilisées, les résultats obtenus, la procédure à suivre lorsque la plateforme est déjà active et la méthode de retour arrière.

La mise à jour a été conduite comme une opération distincte du développement de l'architecture résiliente. Cette séparation évite de mélanger deux catégories de changements :

- les modifications apportées par l'éditeur entre deux versions de Malcolm ;
- les futures modifications locales concernant le déploiement de plusieurs instances Logstash.

## 2. Résultat Exécutif

| Élément | Résultat |
|---|---|
| Version de départ | Malcolm `26.06.0` |
| Version installée | Malcolm `26.07.1` |
| Branche de travail | `upgrade/v26.07.1` |
| Commit de mise à jour | `77ac5439` |
| Images attendues | 23 images en version `26.07.1` |
| Services démarrés | 27 conteneurs |
| Santé des services majeurs | `healthy` |
| État OpenSearch | `green`, 100 % des shards actifs |
| Protection des interfaces web | HTTPS actif, réponse `401` sans authentification |
| Sauvegarde complète | 1,5 Gio, empreintes SHA-256 vérifiées |
| État final sur le poste | plateforme arrêtée volontairement pour libérer les ressources |

La mise à jour logicielle est validée. La plateforme a démarré avec ses 27 services, Logstash a chargé ses sept pipelines, OpenSearch est resté `green` et les interfaces ont répondu derrière le contrôle d'accès Nginx.

La plateforme complète n'est pas laissée en fonctionnement permanent sur ce poste. Avec tous les services actifs, la mémoire disponible descendait à environ `5,3 Gio` et le swap était entièrement occupé. Après l'arrêt propre, la mémoire disponible est remontée à environ `25 Gio`. Cette décision protège la stabilité du poste de développement et ne supprime aucune donnée.

## 3. Apports Principaux De La Version 26.07.1

Cette version apporte notamment :

- le support d'IEC 60870-5-104 dans Zeek, Logstash, les champs Arkime et les tableaux de bord ;
- des corrections de sécurité sur le contrôle d'accès et l'extraction d'archives ;
- des limites de sécurité sur le nombre, la profondeur et la taille des fichiers extraits ;
- des corrections de normalisation Zeek et Suricata ;
- Arkime `6.6.0` ;
- Zeek `8.2.1` ;
- Filebeat OSS `9.4.3` ;
- Logstash OSS `9.4.4` ;
- Keycloak `26.6.4` ;
- des corrections relatives à PostgreSQL et à ses migrations de version majeure.

Les références officielles sont :

- publication `v26.07.1` : <https://github.com/cisagov/Malcolm/releases/tag/v26.07.1> ;
- procédure officielle : <https://malcolm.fyi/docs/malcolm-upgrade.html>.

## 4. État Initial Contrôlé

Le dépôt utilisé est :

```text
/home/kakashi_/ICSHUB/Oculox
```

Avant la mise à jour :

- la branche active était `custom/local` ;
- la base commune avec le dépôt officiel correspondait exactement au tag `v26.06.0` ;
- le dépôt distant interne était conservé sous le nom `origin` ;
- les données persistantes se trouvaient dans les répertoires locaux `opensearch/`, `postgres/`, `pcap/`, `zeek-logs/`, `suricata-logs/` et `filescan-logs/` ;
- environ 201 Gio étaient disponibles sur le disque ;
- la plateforme était arrêtée avant toute copie de données.

Le point important est que le dépôt Git et les données d'exécution sont deux choses différentes. Git versionne le code et les modèles de configuration. Les index, bases PostgreSQL, PCAP et journaux sont des données persistantes qui doivent être sauvegardées séparément.

## 5. Sauvegarde Réalisée

La sauvegarde se trouve dans :

```text
/home/kakashi_/ICSHUB/backups/oculox-pre-v26.07.1-20260727T162542Z
```

Elle contient :

- une copie du dépôt et des configurations locales ;
- les éléments d'authentification nécessaires au redémarrage ;
- un bundle Git complet ;
- l'état Git et l'historique avant migration ;
- les données OpenSearch ;
- les données PostgreSQL ;
- les PCAP ;
- les journaux Zeek, Suricata et filescan ;
- des sommes de contrôle SHA-256.

La taille finale est d'environ `1,5 Gio`. Les sommes SHA-256 ont été recalculées puis vérifiées fichier par fichier.

Un tag Git de retour a également été créé :

```text
backup/local-26.06.0-before-upgrade
```

Une sauvegarde de travail Git conserve séparément les suppressions de fichiers `.gitignore` observées dans les répertoires d'exécution :

```text
stash@{0}: pre-upgrade runtime gitignore changes v26.06.0
```

Cette sauvegarde n'a pas été réappliquée automatiquement, car ces suppressions concernaient l'état des répertoires d'exécution et non la mise à jour fonctionnelle.

## 6. Intégration De La Version Officielle

### 6.1 Ajout De La Source Officielle

Le dépôt interne est resté `origin`. Le dépôt officiel a été ajouté sous le nom `upstream` :

```bash
git remote add upstream https://github.com/cisagov/Malcolm.git
git fetch upstream --tags
```

Cette organisation permet de distinguer clairement :

- `origin` : dépôt Oculox interne ;
- `upstream` : dépôt Malcolm officiel.

### 6.2 Branche De Mise À Jour

Une branche dédiée a été créée :

```bash
git switch -c upgrade/v26.07.1
git merge --no-ff v26.07.1
```

Quatre conflits ont été examinés manuellement :

- `Dockerfiles/file-upload.Dockerfile` ;
- `README.md` ;
- `arkime/etc/config.ini` ;
- `htadmin/src/includes/head.php`.

La résolution a retenu la base technique et les corrections de sécurité officielles, tout en préservant les éléments de personnalisation Oculox utiles, notamment le pied de page Arkime, le README local et les ressources visuelles du portail d'upload.

Le résultat est enregistré dans le commit :

```text
77ac5439 Mise à jour Malcolm vers v26.07.1
```

## 7. Migration Des Variables De Configuration

Les fichiers `config/*.env` réels ne sont volontairement pas versionnés. Ils représentent la configuration particulière de cette installation et peuvent contenir des secrets. Le nouveau script `status` a été exécuté après l'intégration du code afin d'appliquer les actions déclarées dans `config/env-var-actions.yml` :

```bash
./scripts/status
```

Les fichiers suivants ont été adaptés par Malcolm :

- `config/arkime-secret.env` ;
- `config/logstash.env` ;
- `config/upload-common.env` ;
- `config/zeek.env`.

Les nouvelles variables contrôlées comprennent :

```text
LOGSTASH_NETBOX_ENRICHMENT_DATASETS=default
ZEEK_DISABLE_ICS_IEC104=
SAFE_EXTRACT_MAX_ENTRIES=5000
SAFE_EXTRACT_MAX_DEPTH=20
SAFE_EXTRACT_MAX_BYTES=4294967296
```

Une valeur vide pour `ZEEK_DISABLE_ICS_IEC104` ne signifie pas que la migration a échoué. Elle laisse le comportement être déterminé par la logique de configuration Malcolm. Les autres variables limitent une archive à 5 000 entrées, 20 niveaux de profondeur et 4 Gio après extraction.

## 8. Téléchargement Et Validation Des Images

Les images ont été téléchargées avec :

```bash
docker compose --profile malcolm pull
```

La correspondance entre Compose et le cache local a ensuite été vérifiée :

```bash
docker compose --profile malcolm config --images | sort -u
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' \
  | sort \
  | grep 'ghcr.io/idaholab/malcolm/.*:26.07.1'
```

Les 23 images distinctes référencées par Compose sont présentes en version `26.07.1`. Certaines images servent à plusieurs services, par exemple l'image Arkime pour `arkime` et `arkime-live`, ce qui explique que le nombre d'images soit inférieur au nombre de conteneurs.

## 9. Premier Démarrage Et Contrôles

Le premier démarrage a été réalisé avec :

```bash
./scripts/start --quiet
```

### 9.1 Santé Des Conteneurs

Les 27 services attendus ont été créés. Les composants majeurs ont atteint l'état `healthy`, notamment :

- Nginx Proxy ;
- OpenSearch ;
- OpenSearch Dashboards ;
- Dashboards Helper ;
- Logstash ;
- Filebeat ;
- Arkime et Arkime Live ;
- Zeek et Zeek Live ;
- Suricata et Suricata Live ;
- PostgreSQL ;
- NetBox ;
- Strelka ;
- Valkey ;
- pcap-monitor et pcap-capture.

### 9.2 OpenSearch

Le contrôle suivant a été exécuté :

```bash
docker exec oculox-opensearch-1 curl \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  -sk 'https://localhost:9200/_cluster/health?pretty'
```

Résultat :

```text
status: green
active_primary_shards: 33
active_shards: 33
unassigned_shards: 0
number_of_pending_tasks: 0
active_shards_percent_as_number: 100.0
```

OpenSearch accepte donc les écritures et aucun shard n'est perdu ou en attente.

### 9.3 Logstash

Logstash a démarré ses sept pipelines :

```text
malcolm-input
malcolm-output
malcolm-filescan
malcolm-suricata
malcolm-enrichment
malcolm-beats
malcolm-zeek
```

Le fichier de pipeline IEC 104 est chargé parmi les sources du pipeline Zeek :

```text
1074_zeek_iec104.conf
```

Les tests Ruby internes affichés au démarrage sont passés sans échec. Les messages relatifs à `DatabaseManager is not in classpath` sont suivis du chargement effectif des bases GeoLite locales ; ils n'ont pas empêché le démarrage des pipelines ni le passage du conteneur à l'état `healthy`.

### 9.4 Interfaces Web Et Contrôle D'Accès

Le port HTTPS `443` écoute sur toutes les interfaces. Les chemins suivants renvoient `401` lorsqu'ils sont appelés sans identifiants :

```text
/
/dashboards/
/arkime/
/upload/
```

Dans ce contexte, `401` est un résultat positif : le proxy Nginx répond et refuse correctement un accès non authentifié. Une absence de réponse aurait donné un code `000`, et une erreur de service en aval aurait généralement produit un code `502` ou `503`.

### 9.5 Test PCAP Limité

Le PCAP de référence de `4 767 428` octets a été déposé dans `pcap/upload`. `pcap-monitor` l'a déplacé vers `pcap/processed` en environ dix secondes, ce qui valide la prise en charge automatique du dépôt.

Le test de charge post-migration n'a pas été prolongé. La plateforme complète consommait trop de mémoire pour cohabiter durablement avec le reste du laboratoire sur ce poste. Cette limite d'hôte ne constitue pas un échec de mise à jour, mais elle interdit de considérer ce poste comme une plateforme de benchmark complète.

## 10. Procédure Lorsque La Plateforme Est Déjà Active

Une mise à jour ne doit pas être effectuée pendant que Malcolm traite du trafic, des fichiers PCAP ou une file Filebeat importante. Elle doit être planifiée comme une fenêtre de maintenance.

### 10.1 Préparer La Fenêtre

1. Informer les utilisateurs de l'indisponibilité temporaire.
2. Suspendre les uploads PCAP et les rejeux de benchmark.
3. Vérifier que les collecteurs peuvent conserver temporairement leurs journaux locaux.
4. Noter la version, l'état des conteneurs, l'état OpenSearch et l'espace disque.

```bash
cd /chemin/vers/Oculox
git describe --tags --always --dirty
./scripts/status
docker compose ps
df -h
```

### 10.2 Arrêter Proprement

```bash
./scripts/stop --quiet
```

Cette commande ne supprime pas les données persistantes. Il ne faut pas utiliser `docker compose down -v`, car l'option `-v` demande la suppression des volumes Docker.

### 10.3 Sauvegarder Après L'Arrêt

Sauvegarder au minimum :

```text
config/
nginx/certs/
authentification locale
opensearch/
postgres/
pcap/
zeek-logs/
suricata-logs/
filescan-logs/
```

La sauvegarde doit être placée hors du dépôt actif, accompagnée de sommes SHA-256 et, si possible, d'un bundle Git :

```bash
git bundle create repository.bundle --all
```

### 10.4 Intégrer La Nouvelle Version

```bash
git status --short
git fetch upstream --tags
git switch -c upgrade/vNOUVELLE_VERSION
git merge --no-ff vNOUVELLE_VERSION
```

Chaque conflit doit être lu et résolu. Il ne faut pas remplacer globalement les fichiers locaux par ceux de l'éditeur, ni conserver globalement les anciennes versions : l'une ou l'autre méthode peut supprimer une correction de sécurité ou une personnalisation nécessaire.

### 10.5 Migrer La Configuration

Après l'intégration du nouveau code :

```bash
./scripts/status
```

Cette commande est importante dans les versions récentes : le script Malcolm applique les créations, renommages ou migrations de variables décrites par `config/env-var-actions.yml`.

La commande `./scripts/configure` n'est nécessaire que si les notes officielles ou une modification volontaire de configuration l'exigent. Elle doit être utilisée avec prudence pour ne pas réinitialiser des choix ou secrets existants.

### 10.6 Télécharger Et Valider Le Compose

```bash
docker compose --profile malcolm config --quiet
docker compose --profile malcolm pull
docker compose --profile malcolm config --images | sort -u
```

### 10.7 Démarrer Et Contrôler

```bash
./scripts/start --quiet
docker compose ps
```

Attendre que les services passent à `healthy`, puis contrôler :

```bash
docker exec oculox-opensearch-1 curl \
  -K /var/local/curlrc/.opensearch.primary.curlrc \
  -sk 'https://localhost:9200/_cluster/health?pretty'

docker logs --since 10m oculox-logstash-1
docker logs --since 10m oculox-nginx-proxy-1
```

La remise en production ne doit être autorisée que si :

- tous les services critiques sont `healthy` ;
- OpenSearch est `green` ;
- Logstash annonce tous ses pipelines comme actifs ;
- les interfaces répondent derrière l'authentification ;
- aucun conteneur ne redémarre en boucle ;
- la mémoire et le disque conservent une marge suffisante.

## 11. Retour Arrière

Un retour arrière est justifié si OpenSearch ne démarre plus, si PostgreSQL ne termine pas sa migration, si les interfaces restent indisponibles ou si un composant critique redémarre en boucle.

La procédure est :

1. arrêter la nouvelle version ;
2. conserver les journaux de l'échec ;
3. restaurer le code depuis le tag ou le bundle Git ;
4. restaurer `config/`, PostgreSQL, OpenSearch et les autres données depuis la même sauvegarde cohérente ;
5. remettre les images correspondant à l'ancienne version ;
6. redémarrer et contrôler l'état.

Le point de retour local est :

```text
backup/local-26.06.0-before-upgrade
```

La sauvegarde des données doit être restaurée avec le code de la même époque. Restaurer uniquement l'ancien code sur des données déjà migrées par une nouvelle version peut produire une incompatibilité, particulièrement avec PostgreSQL.

## 12. Utilisation Quotidienne Sur Ce Poste

La plateforme est actuellement arrêtée pour préserver la machine. Les commandes recommandées sont :

```bash
cd /home/kakashi_/ICSHUB/Oculox

# Vérifier la configuration sans démarrer les services
./dev/scripts/platform-mode.sh check

# Démarrer seulement OpenSearch et Logstash pour un travail ciblé
./dev/scripts/platform-mode.sh core

# Démarrer exceptionnellement la plateforme complète
./dev/scripts/platform-mode.sh full

# Libérer la RAM après le contrôle
./dev/scripts/platform-mode.sh stop
```

Le mode complet doit rester réservé à une validation courte. Les benchmarks soutenus doivent être exécutés sur une machine dédiée dont les ressources ne sont pas partagées avec le laboratoire ICSHUB.

## 13. Conclusion

La mise à jour vers Malcolm `26.07.1` est techniquement intégrée et validée au démarrage. Les configurations locales et les données ont été sauvegardées avant la première exécution des nouvelles images. Les 27 services ont démarré, OpenSearch est `green`, Logstash a chargé tous ses pipelines et les interfaces HTTPS sont protégées.

La limite constatée concerne la capacité du poste local à maintenir simultanément la plateforme complète et les autres charges du laboratoire. Pour cette raison, l'état opérationnel retenu après validation est **plateforme mise à jour mais arrêtée**, avec un mode réduit disponible pour les développements ciblés.

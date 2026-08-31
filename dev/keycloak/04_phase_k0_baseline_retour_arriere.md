# Phase K0 - Baseline Et Retour Arrière

## 1. Pourquoi Cette Phase Existe

Avant de remplacer Basic par Keycloak, il faut savoir précisément ce qui
fonctionne. Cette baseline donne un point de comparaison et les fichiers
nécessaires pour revenir en arrière si une phase OIDC casse le portail,
Dashboards ou les clients techniques.

La capture a été réalisée sans redémarrer les services et sans modifier les
serveurs externes. Les tests d'ingestion ont seulement injecté le PCAP local de
test `dev/tests/fixtures/phase4_baseline_input.pcap`.

## 2. Branche Et Révision De Départ

La branche de travail est :

```text
feature/keycloak-oidc-integration
```

La révision de départ enregistrée dans la baseline est :

```text
54049bc3 Document fresh Oculox platform installation
```

Le fichier `inventory/git-status.txt` conserve aussi la liste des changements
non validés présents au moment de la capture. Cela évite de prétendre que la
révision Git décrit à elle seule tout l'état local.

## 3. Outil De Capture

Le fichier `dev/scripts/keycloak/capture-baseline.sh` produit un répertoire sous
`dev/generated/keycloak-baseline/`. Ce chemin est ignoré par Git.

Commande exécutée :

```bash
./dev/scripts/keycloak/capture-baseline.sh dev/generated/keycloak-baseline/k0-current
```

Le répertoire contient deux catégories :

```text
inventory/ -> preuves lisibles ne contenant pas les valeurs des secrets
private/   -> configurations runtime, clés et dump PostgreSQL sensibles
```

Le répertoire privé est en permission `700` et les archives en `600`. Le script
n'affiche ni mot de passe PostgreSQL ni secret OIDC. Il utilise les variables
déjà présentes à l'intérieur du conteneur PostgreSQL.

### Fichiers D'Inventaire

| Fichier | Contenu |
| --- | --- |
| `git-branch.txt` | branche capturée |
| `git-revision.txt` | commit de référence |
| `git-status.txt` | différences locales au moment de la capture |
| `containers.txt` | images, états et ports des conteneurs Oculox |
| `component-versions.txt` | versions réellement exécutées |
| `nginx-effective.conf` | configuration Nginx assemblée dans le conteneur |
| `runtime-config-hashes.sha256` | empreintes des configurations sans afficher leur contenu |
| `private-backup-hashes.sha256` | empreintes de l'archive et du dump PostgreSQL |

### Fichiers Privés

`runtime-configs.tar.gz` contient les fichiers nécessaires au retour arrière :

```text
config/auth-common.env
config/keycloak.env
config/postgres.env
config/nginx.env
config/opensearch.env
config/dashboards.env
dashboards/opensearch_dashboards.yml
.opensearch.primary.curlrc
nginx/htpasswd
nginx/certs/
nginx/ca-trust/
```

`keycloak-postgresql.dump` est produit avec `pg_dump` au format custom. Ce
format est contrôlable avec `pg_restore --list` et permet une restauration
sélective. La base est actuellement vide, ce qui est cohérent : Basic est actif
et le realm `oculox` n'a pas encore été provisionné.

## 4. Versions Relevées

| Composant | Version observée |
| --- | --- |
| Images Malcolm/Oculox | `26.07.1` |
| Keycloak | `26.6.4` |
| OpenSearch | `3.7.0` |
| OpenSearch Dashboards | `3.7.0` |
| OpenResty/Nginx | `1.31.1.1` |
| PostgreSQL | `18.4` |
| Logstash | `9.4.4` |
| Filebeat | `9.4.3` |
| Docker Engine | `26.1.5` |
| Docker Compose | `2.29.1` |

La version `26.07.1` est la version de livraison Malcolm. Les autres numéros
sont les versions des logiciels embarqués dans ces images.

## 5. État D'Authentification Initial

Les valeurs actives importantes sont :

```text
NGINX_AUTH_MODE=basic
ROLE_BASED_ACCESS=false
NGINX_REQUIRE_GROUP=
NGINX_REQUIRE_ROLE=
```

Dans ce mode, Nginx sélectionne `nginx_auth_basic.conf`, utilise
`nginx/htpasswd` et ne publie pas la route `/keycloak`. Le conteneur Keycloak
existe dans le profil Malcolm mais son port `8080` n'est pas publié sur l'hôte.

Une requête sans identifiants sur `https://127.0.0.1/` renvoie `401`. C'est la
preuve que le portail est protégé par Basic. L'URL Dashboards renvoie une
redirection vers son mécanisme de connexion actuel.

## 6. Routes Web Et API Inventoriées

La source de vérité runtime est `inventory/nginx-effective.conf`. Les routes
principales observées sont :

| Entrée | Destination ou fonction |
| --- | --- |
| `https://<Core>/` | portail Oculox protégé par Basic |
| `/auth` et `/htadmin` | administration des comptes `htpasswd` |
| `/upload` | dépôt de PCAP et fichiers |
| `/mapi` | API Oculox |
| `/arkime` | Arkime Viewer |
| `/netbox` | NetBox |
| `/wise` | Arkime WISE |
| `/dashboards` | OpenSearch Dashboards via le proxy principal |
| `https://<Core>:5601/dashboards/` | origine Dashboards dédiée actuelle |
| `/keycloak` | absente en mode Basic; activée seulement en mode Keycloak embarqué |

Le port `9200` présent dans la configuration Nginx n'est pas publié par le
conteneur Core actuel. Le Core utilise directement l'endpoint distant
`https://192.168.1.200:9200` pour OpenSearch.

## 7. Preuves De Santé

### Core

Tous les services retournés par `./oculox status` sont `Up` et `healthy`, dont
Nginx, PostgreSQL, Keycloak, Dashboards, les deux Logstash, Filebeat, Arkime,
Zeek et Suricata.

### Cluster OpenSearch

```text
status                 : green
number_of_nodes        : 3
number_of_data_nodes   : 3
unassigned_shards      : 0
cluster_uuid           : KocULrqvTBOe6PaWAjBnog
```

### Clients Techniques

La commande suivante a terminé avec `CLIENT_CONNECTIVITY_RESULT=PASS` :

```bash
./oculox verify clients --output dev/generated/keycloak-baseline/k0-current/inventory/client-connectivity.json
```

Elle a vérifié Logstash 1, Logstash 2, Arkime, Arkime Live, Dashboards,
dashboards-helper, API et pcap-monitor. Chaque client s'est authentifié avec son
compte de service limité. Elle a aussi confirmé que Filebeat utilise les deux
Logstash avec `loadbalance=true` et n'envoie pas directement vers OpenSearch.

### Dashboards

L'API de santé Dashboards a répondu HTTP `200` :

```text
state    : green
title    : Green
nickname : Looking good
version  : 3.7.0
```

Cette preuve valide le serveur Dashboards et sa connexion à OpenSearch. Elle ne
remplace pas le futur test SSO dans un navigateur, qui appartient à K6.

### Ingestion

Le test a traité un PCAP de 56 410 paquets et s'est terminé par
`INGESTION_RESULT=PASS` :

```text
Filebeat published/acked/failed : 21 / 21 / 0
Logstash 1 a reçu des événements : oui
Logstash 2 a reçu des événements : oui
Documents pipeline ajoutés      : 4
Sessions Arkime ajoutées         : 1369
Nouveaux rejets OpenSearch       : 0
Nouveaux échecs OpenSearch       : 0
INGESTION_RESULT                 : PASS
```

Les deltas globaux Logstash et OpenSearch incluent aussi le trafic traité en
parallèle pendant la fenêtre de mesure. La preuve importante est que les deux
Logstash progressent, que le PCAP identifié est accepté et qu'aucun nouvel
échec d'indexation n'apparaît.

## 8. Vérifier Les Sauvegardes

```bash
sha256sum -c dev/generated/keycloak-baseline/k0-current/inventory/private-backup-hashes.sha256
```

```bash
docker exec -i oculox-postgres-1 pg_restore --list < dev/generated/keycloak-baseline/k0-current/private/keycloak-postgresql.dump
```

La première commande doit afficher deux `OK`. La seconde doit reconnaître une
archive PostgreSQL `CUSTOM` sans produire d'erreur.

## 9. Retour Rapide Vers Basic

Ce retour sera utilisé si le portail OIDC échoue mais que les fichiers et la
base restent intacts.

1. Exécuter le configurateur officiel :

```bash
./scripts/auth_setup
```

2. Choisir l'authentification HTTP Basic et conserver les comptes existants.

3. Vérifier la valeur écrite :

```bash
grep '^NGINX_AUTH_MODE=' config/auth-common.env
```

Résultat obligatoire :

```text
NGINX_AUTH_MODE=basic
```

4. Recréer Nginx et Dashboards avec les paramètres restaurés :

```bash
./oculox restart nginx-proxy dashboards
```

5. Vérifier le comportement :

```bash
curl -k -o /dev/null -w '%{http_code}\n' https://127.0.0.1/
```

Sans identifiants, le résultat attendu est `401`.

## 10. Restauration Complète De La Baseline

Cette procédure est réservée à une panne qui nécessite de restaurer tous les
fichiers runtime. Elle doit être exécutée depuis la même révision applicative.

1. Arrêter proprement Oculox :

```bash
./oculox stop
```

2. Sauvegarder l'état défaillant avant de l'écraser :

```bash
./dev/scripts/keycloak/capture-baseline.sh dev/generated/keycloak-baseline/before-rollback
```

3. Vérifier les empreintes de la baseline K0 :

```bash
sha256sum -c dev/generated/keycloak-baseline/k0-current/inventory/private-backup-hashes.sha256
```

4. Extraire l'archive dans un répertoire temporaire et l'inspecter :

```bash
mkdir -p /tmp/oculox-k0-restore
```

```bash
tar -xzf dev/generated/keycloak-baseline/k0-current/private/runtime-configs.tar.gz -C /tmp/oculox-k0-restore
```

5. Après validation humaine, recopier les fichiers à la racine du dépôt en
préservant leurs permissions. Ne pas effectuer cette étape sur une autre VM,
car l'archive contient les certificats et identités de ce déploiement.

6. La base Keycloak n'a pas besoin d'être restaurée pour revenir à Basic. Si une
restauration Keycloak est nécessaire, elle doit se faire dans une base vide avec
`pg_restore --clean --if-exists`; cette opération destructive exigera une
validation séparée et une sauvegarde de l'état courant.

7. Redémarrer et rejouer les preuves K0 :

```bash
./oculox start
```

```bash
./oculox verify clients
```

Le portail doit de nouveau renvoyer `401` sans identifiants et accepter les
comptes de `nginx/htpasswd`.

## 11. Fichiers Créés Ou Modifiés Par K0

| Fichier | Rôle |
| --- | --- |
| `dev/scripts/keycloak/capture-baseline.sh` | capture réexécutable et privée |
| `dev/tests/keycloak/test_k0_baseline.py` | contrat automatisé de sauvegarde et rollback |
| `dev/keycloak/04_phase_k0_baseline_retour_arriere.md` | explication, résultats et procédures |
| `dev/keycloak/02_plan_developpement_keycloak_oculox.md` | statut K0 et lien vers les preuves |
| `dev/generated/keycloak-baseline/k0-current/` | résultats runtime ignorés par Git |

Aucun fichier `config/*.env`, certificat, mot de passe, base active ou service
externe n'a été modifié par la phase K0.

# Scripts du cluster OpenSearch

Ce répertoire contient les commandes reproductibles de préparation et
d'exploitation du cluster dédié. L'opérateur les utilise normalement par le
lanceur racine :

```bash
./oculox install cluster --endpoint-ip <IP_CLUSTER>
./oculox cluster status
./oculox cluster validate
```

Responsabilités :

```text
validation des prerequis de la VM
rendu des configurations
generation et verification de la PKI
demarrage et arret controles
etat et diagnostic du cluster
initialisation Security executee une seule fois
application des politiques de stockage validees
```

Chaque script devra etre idempotent, calculer ses chemins depuis son propre
emplacement et refuser les operations ambigues. Aucun mot de passe ou endpoint
de machine ne doit etre code en dur.

Les operations destructives devront demander une option explicite et verifier
l'identite du cluster avant toute suppression. Les sorties sensibles ne devront
jamais afficher de cle privee ni de mot de passe.

## Bundles des clients Oculox

Creer un bundle Core contenant uniquement la CA et les comptes de service :

```bash
./oculox cluster client-bundle core /chemin-securise/oculox-core-opensearch
```

Pour Hedgehog, utiliser `--role hedgehog`. Le bundle contient des secrets,
reste en mode 0700 et ne doit jamais etre ajoute a Git.

## Cycle Complet VM Neuve

Sur la VM cluster :

```bash
./oculox install cluster --endpoint-ip <IP_CLUSTER>
./oculox cluster validate
./oculox cluster client-bundle core /tmp/oculox-core-opensearch
./oculox cluster client-bundle hedgehog /tmp/oculox-hedgehog-opensearch
```

Sur la VM Core, le bundle Core est importe avec :

```bash
./oculox install principal \
  --server-name <IP_CORE_OU_DNS> \
  --opensearch-bundle <repertoire-bundle-core>
```

Cette etape configure `config/opensearch.env`, installe la CA dans
`nginx/ca-trust/`, genere les fichiers `.opensearch.*.curlrc` locaux et donne a
Logstash, Arkime, Dashboards, API et dashboards-helper leurs identites
techniques separees.

## Scripts Et Responsabilites

| Script | Role |
|---|---|
| `prepare-host.py` | Verifie les prerequis systeme de la VM cluster |
| `render-cluster-config.py` | Rend la configuration cluster depuis le modele |
| `generate-pki.sh` | Genere CA, certificats noeuds, endpoint et admin |
| `generate-security-config.sh` | Genere utilisateurs internes, roles et hashes |
| `render-oidc-security-config.py` | Ajoute la configuration OIDC OpenSearch Security |
| `initialize-security.sh` | Initialise OpenSearch Security une seule fois |
| `update-security-config.sh` | Applique une configuration Security validee |
| `update-security-roles.sh` | Met a jour roles et mappings sans reinitialiser le cluster |
| `create-client-bundle.py` | Produit les bundles Core/Hedgehog limites par role |
| `apply-storage-policy.py` | Applique replicas, ISM et seuils disque |
| `manage-cluster.sh` | Demarrage, arret, logs, status et validation |

## Comptes De Service

Le cluster n'utilise pas un seul super compte partage. Les clients ont des
identites distinctes :

```text
oculox_logstash
oculox_arkime
oculox_dashboards
oculox_dashboards_helper
oculox_api
oculox_snapshot
```

Chaque role est limite dans les fichiers de configuration Security sous
`dev/config/opensearch-cluster/security/`.

## Verification Depuis Le Core

Apres import du bundle :

```bash
./oculox verify clients
curl --cacert nginx/ca-trust/oculox-opensearch-ca.crt \
  --config .opensearch.primary.curlrc \
  https://<IP_CLUSTER>:9200/_cluster/health?pretty
```

Le resultat attendu est `CLIENT_CONNECTIVITY_RESULT=PASS`, avec Logstash,
Arkime, Dashboards, dashboards-helper, API et pcap-monitor authentifies avec
leurs comptes techniques propres.

## Réplicas, ISM et protections disque

Appliquer la politique de stockage uniquement lorsque les trois nœuds sont disponibles :

```bash
./dev/scripts/opensearch-cluster/apply-storage-policy.py
```

Le script sauvegarde d'abord les reglages, templates, aliases et politiques
dans `dev/generated/opensearch-cluster/storage-policy/backups/`. Il applique ensuite un
replica minimum, les politiques ISM Arkime/Beats et les seuils disque. Lorsqu'un
template Oculox existe, seul son reglage `number_of_replicas` est ajuste ; ses
mappings et aliases sont conserves.

Par defaut, les transitions d'optimisation sont actives mais la suppression
automatique des index reste desactivee. L'operateur doit l'activer explicitement
dans `cluster.yml` apres validation d'une strategie de snapshots.

## Generation de la PKI

Depuis la racine du depot :

```bash
./dev/scripts/opensearch-cluster/generate-pki.sh --endpoint-ip <IP_CLUSTER>
```

Le script refuse d'ecraser une PKI existante. Une rotation volontaire exige
`--force`, puis le redeploiement coordonne de la CA et des certificats vers le
cluster et tous ses clients.

Les fichiers sont crees sous `dev/generated/opensearch-cluster/pki/` et sont
ignores par Git. Ne jamais versionner `ca.key`, `node.key`, `endpoint.key` ou
`admin.key`.

## Initialisation Security

Generer une seule fois les comptes et les hashes :

```bash
./dev/scripts/opensearch-cluster/generate-security-config.sh
```

Apres formation des trois noeuds, initialiser Security avec un repertoire
administrateur temporaire :

```bash
./dev/scripts/opensearch-cluster/initialize-security.sh \
  --admin-dir /chemin/temporaire/admin
```

Le script refuse une seconde initialisation. `accounts.env`, `admin.key` et la
cle de CA ne doivent jamais etre copies dans le deploiement permanent.

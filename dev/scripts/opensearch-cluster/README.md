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

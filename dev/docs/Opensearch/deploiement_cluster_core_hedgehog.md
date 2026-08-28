# Déploiement propre sur trois VM

## Contrat d'installation

Le déploiement final utilise trois clones indépendants du même dépôt Oculox.
Aucun fichier généré sur la machine de développement n'est requis, hormis les
bundles secrets produits par la VM Cluster puis transférés explicitement.

| VM | Rôle | Commande d'installation |
|---|---|---|
| Cluster | trois nœuds OpenSearch et HAProxy | `./oculox install cluster --endpoint-ip <IP_CLUSTER>` |
| Core | plateforme Oculox principale | `./oculox install principal --server-name <IP_CORE> --opensearch-bundle <BUNDLE_CORE>` |
| Hedgehog | capture et analyse distribuée | `./oculox install hedgehog --principal-host <IP_CORE> --collector-name <NOM> --bundle <BUNDLE_BEATS> --opensearch-bundle <BUNDLE_HEDGEHOG>` |

Les trois commandes sont conçues pour être lancées depuis la racine du clone
présent sur la VM concernée.

## Ordre obligatoire

### 1. Installer le cluster

```bash
git clone <URL_GITEA_OCULOX> Oculox_V2
cd Oculox_V2
./oculox install cluster --endpoint-ip <IP_CLUSTER>
./oculox cluster validate
```

L'installation crée automatiquement :

```text
dev/generated/opensearch-cluster/client-bundles/core
dev/generated/opensearch-cluster/client-bundles/hedgehog
```

Ces répertoires contiennent la CA et les comptes de service. Ils doivent être
transférés avec `scp` et supprimés des emplacements de transit après usage.

### 2. Installer le Core

```bash
git clone <URL_GITEA_OCULOX> Oculox_V2
cd Oculox_V2
./oculox install principal --server-name <IP_CORE> --opensearch-bundle <BUNDLE_CORE>
```

Dans l'assistant d'authentification, les identifiants OpenSearch distants ne
doivent pas être régénérés : ils sont fournis par le bundle et réinstallés à
la fin de la préparation. Les comptes HTTP des utilisateurs Oculox restent
configurés normalement.

Après validation du Core, produire le bundle mTLS Beats du collecteur :

```bash
./oculox collector-bundle <NOM_COLLECTEUR> <IP_CORE>
```

### 3. Installer Hedgehog

Transférer sur la VM Hedgehog le bundle Beats produit par le Core et le bundle
OpenSearch Hedgehog produit par le Cluster, puis exécuter :

```bash
git clone <URL_GITEA_OCULOX> Oculox_V2
cd Oculox_V2
./oculox install hedgehog --principal-host <IP_CORE> --collector-name <NOM_COLLECTEUR> --bundle <BUNDLE_BEATS> --opensearch-bundle <BUNDLE_HEDGEHOG>
```

## Ce qui ne doit pas être copié

Les volumes Docker, `dev/generated` complet, les fichiers `config/*.env`, les
répertoires de données et les mots de passe d'une ancienne installation ne
doivent jamais être copiés vers une VM neuve. Seuls les deux types de bundles
prévus par le lanceur traversent les machines.

## Validation finale

La recette finale sera exécutée sur trois VM remises à zéro. Elle vérifiera :

- installation depuis le dépôt Gitea uniquement ;
- démarrage après redémarrage de chaque VM ;
- cluster OpenSearch `green` à trois nœuds ;
- CA vérifiée par le Core et Hedgehog ;
- comptes de service limités ;
- Filebeat connecté aux deux Logstash en mTLS ;
- indexation et recherche d'un événement de bout en bout ;
- continuité après perte d'un nœud OpenSearch et d'un Logstash ;
- absence d'OpenSearch local sur le Core et Hedgehog.

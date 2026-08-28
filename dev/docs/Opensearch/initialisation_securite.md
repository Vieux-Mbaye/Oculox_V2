# Étape Security - Initialisation OpenSearch Security

## 1. Resultat

La Étape Security a ete executee le 11 aout 2026 sur la VM OpenSearch
`192.168.1.241`.

Resultat final :

```text
SECURITY_CONFIG_RESULT=PASS
SECURITY_RUNTIME_RESULT=PASS
cluster=green
nodes=3
data_nodes=3
unassigned_shards=0
security_initialization=ONCE
```

Le cluster utilise OpenSearch `3.7.0` avec l'UUID :

```text
Qia-ZGlDTSyRYduLFlhLLg
```

`opensearch-2` etait le cluster manager elu lors de la preuve finale.

## 2. Ajustements d'execution des phases precedentes

Le premier demarrage reel a mis en evidence deux contraintes de l'image
Malcolm qui n'etaient pas visibles dans les tests statiques.

### 2.1 Mode mono-noeud embarque

L'image declare `discovery.type=single-node` dans ses variables `ENV`.
OpenSearch ne reconnait pas la valeur `multi-node` : le mode multi-noeud est le
mode par defaut lorsque `discovery.type` est absent.

Le wrapper suivant retire la variable avant de lancer l'entrypoint original :

```text
dev/config/opensearch-cluster/entrypoint-multinode.sh
```

Les redemarrages ordinaires ne contiennent plus
`cluster.initial_cluster_manager_nodes`.

### 2.2 Verification TLS transport

OpenSearch annonce une adresse IP sur le transport, meme lorsque la decouverte
utilise les noms Docker. La verification stricte rejetait donc un certificat
contenant seulement un SAN DNS.

Le reseau transport possede maintenant un sous-reseau prive stable :

```text
172.31.241.0/28
opensearch-1 = 172.31.241.2
opensearch-2 = 172.31.241.3
opensearch-3 = 172.31.241.4
```

Chaque certificat de noeud contient son nom DNS et son IP transport. La
verification du nom reste active ; elle n'a pas ete contournee.

## 3. Initialisation unique

L'index Security a ete cree une seule fois avec :

```text
dev/scripts/opensearch-cluster/initialize-security.sh
```

Le chargement a confirme :

```text
Clusterstate: GREEN
Number of nodes: 3
Number of data nodes: 3
9 types de configuration charges sur 3/3 noeuds
```

Un marqueur local protege l'operation :

```text
dev/generated/opensearch-cluster/state/security-initialized
```

Une seconde execution a ete refusee avec un code retour non nul. Le script
verifie aussi l'existence de l'index Security avant tout chargement.

## 4. Comptes et roles

Sept comptes internes distincts ont ete generes. Aucun mot de passe n'est
versionne ou affiche.

| Compte | Usage | Roles principaux |
|---|---|---|
| `oculox_platform_admin` | administration fonctionnelle du cluster | `all_access` |
| `oculox_logstash` | Logstash 1 et Logstash 2 | role officiel `logstash` et `oculox_logstash_writer` |
| `oculox_arkime` | Arkime et Arkime Live | `oculox_arkime_service` |
| `oculox_dashboards` | serveur OpenSearch Dashboards | `kibana_server` |
| `oculox_dashboards_helper` | templates et objets des plugins | `oculox_dashboards_helper` et roles des plugins necessaires |
| `oculox_api` | API Oculox et pcap-monitor en lecture | `oculox_api_reader` |
| `oculox_snapshot` | snapshots et restaurations | `manage_snapshots` |

Le compte `malcolm_internal` est absent. Aucun compte de service n'a le backend
role generique `admin`.

Le certificat `oculox-opensearch-admin` reste l'identite de super
administration Security. Il sert uniquement aux modifications des comptes,
roles et mappings ; il n'est pas distribue aux services applicatifs.

Le role statique officiel `logstash` est conserve car OpenSearch 3.7 l'utilise
pour les actions internes `bulk`, les pipelines et les templates. Le role
Oculox complementaire limite les index specifiques a
`malcolm_beats_*` et `arkime_sessions3-*`.

## 5. Preuves de moindre privilege

Le test reproductible est :

```text
dev/tests/opensearch-cluster/test_security_runtime.sh
```

Operations autorisees validees :

```text
administrateur : lecture de la sante du cluster
Logstash        : creation et ecriture dans malcolm_beats_*
Arkime          : creation dans arkime_*
API             : lecture des index applicatifs
Dashboards      : authentification du compte serveur
helper          : creation d'un index template
snapshot        : consultation des repositories
```

Operations refusees validees :

```text
Logstash hors de ses motifs d'index              : HTTP 403
Arkime dans malcolm_beats_*                      : HTTP 403
API en ecriture                                  : HTTP 403
Dashboards en ecriture sur un index applicatif   : HTTP 403
snapshot en lecture d'un index applicatif        : HTTP 403
requete sans identifiants                        : HTTP 401
requete sans CA de confiance                     : curl 60
```

Le role officiel `manage_snapshots` autorise la creation et l'ecriture d'index,
car ces droits sont necessaires a une restauration. Son test hors role porte
donc sur la lecture d'un index applicatif.

## 6. Preuves du cluster apres redemarrage

Apres suppression de la configuration d'amorcage et recreation des conteneurs
sur les memes volumes :

```text
opensearch-1 : healthy, restart=0, bootstrap absent
opensearch-2 : healthy, restart=0, bootstrap absent
opensearch-3 : healthy, restart=0, bootstrap absent
cluster      : green
nodes        : 3
shards       : 12 actifs, 0 non affecte
```

Le test Security complet repasse apres ce redemarrage. Cela prouve la
persistance de l'index Security et du cluster UUID.

## 7. Protection des secrets et permissions

Sur la VM, les fichiers permanents ont les permissions suivantes :

```text
initialize-security.sh       0755
internal_users.yml           0600
security-initialized         0600
```

Les controles finaux ne trouvent aucun `accounts.env` ni `admin.key` dans le
deploiement permanent. Les elements temporaires de test ont ete supprimes de
`/tmp` apres validation.

Les secrets locaux restent sous :

```text
dev/generated/opensearch-cluster/security/accounts.env
dev/generated/opensearch-cluster/pki/admin/admin.key
```

Ils sont ignores par Git et doivent etre places dans un coffre de secrets avant
la production.

## 8. Fichiers de reference

```text
dev/config/opensearch-cluster/security/config.yml
dev/config/opensearch-cluster/security/roles.yml
dev/config/opensearch-cluster/security/roles_mapping.yml
dev/scripts/opensearch-cluster/generate-security-config.sh
dev/scripts/opensearch-cluster/initialize-security.sh
dev/tests/opensearch-cluster/test_security_config.py
dev/tests/opensearch-cluster/test_security_runtime.sh
```

La Étape endpoint pourra maintenant ajouter l'endpoint stable sans donner aux clients
un acces direct a un noeud particulier.

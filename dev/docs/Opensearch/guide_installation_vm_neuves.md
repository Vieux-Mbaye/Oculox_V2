# Installation Oculox sur trois VM neuves

Ce guide installe une plateforme composee de trois roles distincts :

```text
VM Cluster OpenSearch  <- stockage, recherche, replicas et endpoint HA
VM Oculox Core         <- pipelines Logstash, Arkime, Dashboards et API
VM Hedgehog            <- collecte et analyse du trafic industriel
```

Le flux principal est le suivant :

```text
interface industrielle -> Hedgehog -> Logstash 1 et Logstash 2 du Core -> cluster OpenSearch
                                      Arkime Core et Hedgehog -----------> cluster OpenSearch
```

Les trois nœuds OpenSearch sont des conteneurs dans la **VM Cluster**. Ils ne
sont pas trois VM. HAProxy expose un endpoint unique sur cette VM et repartit
les requêtes entre les trois nœuds sains.

## 1. Choisir les adresses et les rôles

Préparez des adresses stables et joignables entre les VM. Cet exemple utilise :

| Rôle | Hôte | Adresse exemple | Ports à autoriser |
| --- | --- | --- | --- |
| Cluster OpenSearch | `oculox-opensearch` | `192.168.1.200` | `9200` depuis Core et Hedgehog; `8404` uniquement pour supervision |
| Oculox Core | `oculox-core` | `192.168.1.174` | `443` pour les utilisateurs; `5044` et `5045` depuis Hedgehog; `5601` seulement pour Dashboards direct |
| Hedgehog | `oculox-collector-01` | `192.168.1.201` | accès sortant vers Core `5044`, `5045` et Cluster `9200` |

Ne publiez jamais le port OpenSearch transport `9300` hors de la VM Cluster.
Les trois nœuds l'utilisent uniquement entre eux sur le réseau Docker privé.

L'installation ne depend pas d'un nom DNS. Les IP sont donc acceptables. Si un
DNS interne est ajouté plus tard, il faut emettre un nouveau certificat
endpoint avec le nom DNS dans ses SAN, puis mettre à jour les bundles clients.

## 2. Préparer chaque VM

Les trois VM doivent avoir Debian ou Ubuntu récent, un compte administrateur
capable d'utiliser `sudo`, une route entre les trois IP et l'accès Internet
pendant le téléchargement des images. Le script d'installation installe Docker
et les dépendances nécessaires quand elles sont absentes.

Sur chaque VM, clonez le dépôt puis entrez dans le répertoire :

```bash
git clone https://gitea.tcric.hq/vmbaye/Oculox_V2.git ~/Oculox_V2
cd ~/Oculox_V2
git status --short
```

`git status --short` doit être vide juste après le clone. Ne stockez ni bundle,
ni PCAP, ni mot de passe dans le dépôt: utilisez plutôt `/tmp` pour un transfert
temporaire ou un répertoire privé hors du dépôt, par exemple
`~/oculox-bundles`.

## 3. Installer le cluster OpenSearch

Cette partie est faite uniquement sur la VM `oculox-opensearch`.

### 3.1 Choisir la configuration

Pour une installation de production, copiez le modèle hors du dépôt :

```bash
cp dev/config/opensearch-cluster/cluster.yml.example ~/oculox-cluster.yml
nano ~/oculox-cluster.yml
```

Modifiez au minimum `endpoint.ip` avec l'adresse de cette VM. Conservez le
profil `production` et `heap_per_node: 2g` au minimum. Une VM de 14 Gio de RAM
et 200 Gio de disque satisfait les garde-fous de ce profil.

Exemple de configuration cohérente :

```yaml
version: 1

cluster:
  profile: production
  name: oculox-opensearch
  image: ghcr.io/idaholab/malcolm/opensearch:26.07.1
  heap_per_node: 2g
  restart_policy: unless-stopped

endpoint:
  ip: 192.168.1.200
  port: 9200
  monitoring_port: 8404

storage:
  primary_shards: 1
  replicas: 1
  max_docvalue_fields_search: 200
  watermarks:
    low: 75
    high: 85
    flood_stage: 90

policies:
  arkime_sessions:
    enabled: true
    optimize_after_days: 30
    delete_enabled: false
    delete_after_days: 90
  arkime_history:
    enabled: true
    delete_enabled: false
    delete_after_days: 91
  beats:
    enabled: true
    optimize_after_days: 30
    delete_enabled: false
    delete_after_days: 90

snapshots:
  enabled: false
```

`primary_shards: 1` signifie qu'un nouvel index commence avec un shard de
données principal. `replicas: 1` signifie qu'une seconde copie de ce shard est
placée sur un autre nœud. Le nombre de shards n'est pas un indicateur de
qualité: il doit être augmenté plus tard seulement après mesure de la taille
des index et du débit réel.

Les politiques sont actives, mais la suppression est désactivée par défaut:
aucune donnée ne sera supprimée après 90 jours tant que
`delete_enabled: false` est conservé. Les snapshots ne sont pas encore pris en
charge par le projet; ils restent donc explicitement désactivés.

### 3.2 Vérifier avant installation

```bash
./oculox install cluster --config ~/oculox-cluster.yml --check
```

Cette commande ne démarre rien. Elle valide l'IP, la heap, les limites disque,
les watermarks, les politiques et le Compose rendu.

### 3.3 Installer et démarrer

```bash
./oculox install cluster --config ~/oculox-cluster.yml
```

Cette commande installe Docker si nécessaire, génère la PKI privée, génère les
comptes de service, forme le cluster à trois nœuds, initialise le plugin
Security une seule fois, applique les politiques d'indexation et crée les
bundles Core et Hedgehog. Elle peut être relancée après une interruption: elle
ne supprime ni les volumes de données ni la PKI existante.

Les fichiers générés et secrets restent localement dans :

```text
dev/generated/opensearch-cluster/
```

Ils ne doivent jamais être ajoutés à Git.

### 3.4 Vérifier le cluster

```bash
./oculox cluster validate
./oculox cluster status
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin https://192.168.1.200:9200/_cluster/health?pretty
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt -u oculox_platform_admin "https://192.168.1.200:9200/_cat/nodes?v&h=name,ip,node.role,master"
```

`curl` demande le mot de passe sans l'afficher dans la commande. Le résultat
attendu est `green`, trois nœuds data, zéro shard non affecté et une étoile
devant un seul cluster manager. Le cluster manager coordonne les décisions du
cluster; il ne reçoit pas toutes les requêtes applicatives à la place des
autres nœuds.

### 3.5 Produire les bundles clients

Les bundles distribuent seulement la CA, l'endpoint et les identités de service
minimales. Ils permettent aux clients de vérifier le certificat du cluster.

```bash
mkdir -p ~/oculox-bundles
./oculox cluster client-bundle core ~/oculox-bundles/core
./oculox cluster client-bundle hedgehog ~/oculox-bundles/hedgehog
cd ~/oculox-bundles/core
sha256sum -c SHA256SUMS
cd ~/oculox-bundles/hedgehog
sha256sum -c SHA256SUMS
```

Le bundle contient des mots de passe de service. Transférez-le uniquement par
un canal d'administration sûr, puis supprimez la copie temporaire après
importation.

## 4. Installer Oculox Core

Cette partie est faite uniquement sur la VM `oculox-core`.

### 4.1 Copier le bundle Core depuis la VM Cluster

Sur la VM Core :

```bash
mkdir -p ~/oculox-bundles
scp -r debian@192.168.1.200:/home/debian/oculox-bundles/core ~/oculox-bundles/
cd ~/oculox-bundles/core
sha256sum -c SHA256SUMS
cd ~/Oculox_V2
```

Remplacez `debian` par le compte réel de la VM Cluster. Le contrôle
`SHA256SUMS` est obligatoire: il confirme que le bundle n'a pas été altéré
pendant le transfert.

### 4.2 Installer le rôle Principal

```bash
./oculox install principal --server-name 192.168.1.174 --opensearch-bundle ~/oculox-bundles/core
```

L'installeur officiel Malcolm ouvre son menu. Les décisions importantes sont :

| Réglage | Valeur attendue |
| --- | --- |
| Run Profile | `malcolm` ou `principal` selon le libellé proposé |
| Primary Document Store | `opensearch-remote` |
| Primary URL | `https://192.168.1.200:9200` |
| Verify SSL | `Yes` |
| Expose Oculox Service Ports | `Yes` si des collecteurs externes doivent joindre `5044` et `5045` |
| Capture Live Network Traffic | selon le rôle réel du Core; `No` si seul le collecteur capture |

L'assistant demande aussi les secrets d'authentification Oculox. Conservez-les
dans un coffre de secrets. Ils contrôlent l'accès web Oculox et sont distincts
des comptes techniques OpenSearch contenus dans le bundle.

Après le menu, le script importe le bundle distant, lance `auth_setup`, rend la
configuration Docker et démarre les services. Le Core ne démarre pas son
OpenSearch local: il utilise l'endpoint HAProxy `https://192.168.1.200:9200`.

### 4.3 Vérifier le Core

```bash
./oculox status
./oculox verify clients
curl --cacert nginx/ca-trust/oculox-opensearch-ca.crt --config .opensearch.primary.curlrc https://192.168.1.200:9200/_cluster/health?pretty
```

Tous les contrôles `./oculox verify clients` doivent être `PASS`. Il vérifie les
connexions de Logstash 1, Logstash 2, Arkime, Dashboards, API et pcap-monitor,
ainsi que le fait que Filebeat charge les deux Logstash et ne contacte pas
directement OpenSearch.

Pour ouvrir l'interface générale Oculox :

```text
https://192.168.1.174/
```

Pour Dashboards, utilisez l'origine dédiée :

```text
https://192.168.1.174:5601/dashboards/
```

Connectez-vous au portail et à Dashboards avec les comptes humains Keycloak
provisionnés par Oculox, par exemple `oculox-admin`, `oculox-analyst`,
`oculox-incident-response` ou `oculox-viewer`. Pour l'administration humaine,
utilisez `oculox-admin` via le SSO Keycloak.

`oculox_platform_admin` est le compte d'administration technique OpenSearch. Il
sert aux scripts, aux vérifications contrôlées et aux opérations de secours; il
ne doit pas être le compte quotidien du navigateur. Le compte
`oculox_dashboards` est un compte de service du conteneur Dashboards: il ne
doit jamais être utilisé dans un navigateur et affichera des erreurs de
permission sur les panneaux.

Un cluster neuf ne contient pas encore de trafic. Avec un compte autorisé, les
écrans peuvent alors afficher zéro résultat ou une visualisation vide; ce n'est
pas une erreur. Un badge `Error` indique au contraire un problème de requête,
de champ ou de permission et doit être investigué avec :

```bash
./oculox logs dashboards
./oculox verify clients
```

Le navigateur peut aussi afficher `Not secure` tant que le certificat HTTPS de
la VM Core n'est pas signé par une autorité reconnue par le poste utilisateur.
La PKI privée OpenSearch chiffre les communications internes et les clients
Oculox; elle ne rend pas automatiquement le certificat web du Core reconnu par
tous les navigateurs. Pour une production, utilisez un certificat émis par la
PKI d'entreprise ou par une autorité publique pour le nom DNS du Core, ou
installez l'autorité interne dans les magasins de confiance des postes gérés.

## 5. Installer le collecteur Hedgehog

Cette partie est faite uniquement sur la VM `oculox-collector-01`.

Le collecteur reçoit le trafic industriel sur son interface de capture. Il
produit des journaux Zeek et Suricata, puis Filebeat les envoie simultanément
vers Logstash `5044` et Logstash `5045` du Core avec mTLS. Arkime et
pcap-monitor utilisent aussi directement OpenSearch pour leurs métadonnées.

### 5.1 Créer le bundle Beats du collecteur sur le Core

Sur la VM Core :

```bash
cd ~/Oculox_V2
mkdir -p ~/oculox-bundles
./oculox collector-bundle oculox-collector-01 192.168.1.174 ~/oculox-bundles/oculox-collector-01
cd ~/oculox-bundles/oculox-collector-01
sha256sum -c SHA256SUMS
```

Ce bundle contient une autorité Beats, un certificat client unique pour ce
collecteur, sa clé privée et les deux destinations Logstash. Chaque collecteur
doit posséder son propre bundle et donc sa propre clé.

### 5.2 Copier les deux bundles vers Hedgehog

Sur la VM Hedgehog :

```bash
mkdir -p ~/oculox-bundles
scp -r admin@192.168.1.174:/home/admin/oculox-bundles/oculox-collector-01 ~/oculox-bundles/
scp -r debian@192.168.1.200:/home/debian/oculox-bundles/hedgehog ~/oculox-bundles/
cd ~/oculox-bundles/oculox-collector-01
sha256sum -c SHA256SUMS
cd ~/oculox-bundles/hedgehog
sha256sum -c SHA256SUMS
cd ~/Oculox_V2
```

Remplacez `admin` et `debian` par les comptes SSH réellement utilisés.

### 5.3 Installer Hedgehog

```bash
./oculox install hedgehog --principal-host 192.168.1.174 --collector-name oculox-collector-01 --bundle ~/oculox-bundles/oculox-collector-01 --opensearch-bundle ~/oculox-bundles/hedgehog
```

Dans le menu Malcolm Hedgehog, réglez uniquement les paramètres pertinents à
votre capture :

| Réglage | Valeur attendue |
| --- | --- |
| Run Profile | `hedgehog` |
| Logstash Host | laissé au bundle Oculox; ne remplacez pas les deux hôtes générés |
| Primary Document Store | `opensearch-remote` |
| Primary URL | `https://192.168.1.200:9200` |
| Verify SSL | `Yes` |
| Capture Live Network Traffic | `Yes` si ce collecteur doit réellement capturer |
| Capture Interface(s) | l'interface du miroir, par exemple `br-mirror` ou `otmirror0` |
| Analyze with Zeek / Suricata / Arkime | `Yes` selon les besoins |

Avant d'activer la capture, vérifiez le nom réel des interfaces :

```bash
ip -br link
```

Le miroir doit être visible sur l'hôte. Il n'est pas nécessaire de changer le
`network_mode` Docker pour exposer une interface miroir hôte à la capture.

### 5.4 Vérifier le collecteur et le mTLS

```bash
./oculox status
./oculox logs filebeat | grep -E '5044|5045|Connection .*established'
./oculox verify clients
```

Les journaux Filebeat doivent indiquer une connexion établie vers les deux
ports du Core. Cela prouve que Filebeat répartit les publications sur les deux
Logstash. Les certificats Beats sont vérifiés pendant cette connexion mTLS:
le Core vérifie le certificat client du collecteur et le collecteur vérifie le
certificat serveur du Core.

## 6. Vérifier le parcours complet d'ingestion

Une fois le Core et Hedgehog démarrés, lancez d'abord la mesure de référence
sur le Core :

```bash
mkdir -p dev/generated/validation/demo
./oculox verify ingestion baseline --output dev/generated/validation/demo/baseline.json
```

Injectez ensuite un PCAP de test sur le collecteur :

```bash
./oculox verify ingestion inject --pcap /chemin/vers/test.pcap --run-id demonstration-01 --output dev/generated/validation/demo/collector.json
```

Revenez sur le Core pour finaliser :

```bash
./oculox verify ingestion finalize --baseline dev/generated/validation/demo/baseline.json --collector-report dev/generated/validation/demo/collector.json --output dev/generated/validation/demo/final.json
jq '{result,filebeat:.collector.filebeat,logstash_delta,opensearch_delta,checks}' dev/generated/validation/demo/final.json
```

Le résultat attendu est `INGESTION_RESULT=PASS`. Les compteurs de paquets, de
journaux Zeek, de journaux Suricata et de documents indexés ne sont pas égaux:
un paquet peut créer plusieurs événements ou aucun événement.

## 7. Exploitation courante et changements

### Cluster OpenSearch

```bash
./oculox cluster status
./oculox cluster logs opensearch-1
./oculox cluster restart
./oculox cluster validate
```

Pour changer des politiques, la heap ou les watermarks, modifiez
`~/oculox-cluster.yml`, puis appliquez la configuration :

```bash
./oculox cluster apply --config ~/oculox-cluster.yml
```

`cluster apply` refuse volontairement de changer l'adresse endpoint ou le nom
du cluster existant. Ces changements impliquent une migration, pas un simple
redémarrage.

### Core et collecteur

```bash
./oculox status
./oculox logs dashboards
./oculox restart
./oculox stop
./oculox start
```

`./oculox restart` reconcilie d'abord le Compose rendu afin de prendre en
compte les montages, ports et variables modifiés, puis redémarre les services.
Il peut donc recréer certains conteneurs. Cette opération ne supprime pas les
volumes de données.

Pour modifier les options officielles Malcolm, utilisez le configurateur :

```bash
./scripts/configure
```

Après une modification sur un Core ou un Hedgehog relié à OpenSearch distant,
réimportez le bundle correspondant avant le redémarrage, afin de préserver la
CA et les comptes de service :

```bash
./oculox configure-opensearch-remote --bundle ~/oculox-bundles/core
./oculox start
```

Sur Hedgehog, utilisez le bundle `~/oculox-bundles/hedgehog`. Si les paramètres
Filebeat ou le rôle Hedgehog ont été modifiés, relancez aussi la préparation
avec les mêmes paramètres `--principal-host`, `--collector-name` et `--bundle`.

## 8. Ce qui est validé et ce qui reste à organiser

Le projet valide la formation du cluster, le quorum à trois nœuds, TLS HTTP et
transport, la PKI, le proxy HAProxy, les replicas, les politiques de stockage,
les rôles de service, les clients Core/Hedgehog, la distribution Filebeat vers
les deux Logstash et les tests d'ingestion/résilience.

Le système de snapshots est volontairement désactivé. Avant une mise en
production, choisissez un stockage de sauvegarde externe, la fréquence, la
rétention, le chiffrement et un test de restauration. Sans snapshots, les
replicas protègent contre la perte d'un nœud, mais ne remplacent pas une
sauvegarde contre une suppression, une corruption logique ou la perte complète
de la VM Cluster.

Les utilisateurs humains Dashboards sont provisionnés côté Keycloak et reliés à
OpenSearch Security par les rôles OIDC. Les profils attendus sont
`oculox-admin`, `oculox-analyst`, `oculox-incident-response` et
`oculox-viewer`. Vérifiez-les avec :

```bash
./oculox keycloak verify-hardening
./oculox keycloak credentials
```

Ne partagez pas `oculox_platform_admin` pour l'usage quotidien et n'utilisez
jamais les comptes techniques `oculox_dashboards`, `oculox_logstash`,
`oculox_arkime` ou `oculox_api` dans un navigateur.

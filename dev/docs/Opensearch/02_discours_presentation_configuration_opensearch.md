# Discours de presentation de la configuration OpenSearch Oculox

## 1. Comment utiliser ce document

Ce document est un support oral. Les paragraphes marques **A dire** peuvent
etre presentes presque mot pour mot. Les parties **A montrer** indiquent le
fichier ou la commande a afficher pendant la demonstration.

L'objectif n'est pas de lire chaque ligne de configuration. Il faut montrer :

1. quel probleme le fichier resout ;
2. quand il est utilise ;
3. ce qu'il produit ;
4. comment on verifie son resultat.

La presentation complete dure environ quinze minutes.

## 2. Introduction

### A dire

> Oculox utilisait initialement un OpenSearch mono-noeud integre au meme
> Docker Compose que le reste de la plateforme. Cette architecture fonctionne
> pour un laboratoire, mais la perte du noeud fait perdre tout le service de
> recherche. Nous avons donc separe le stockage dans une VM dediee et construit
> trois noeuds OpenSearch. Les applications ne contactent jamais directement
> un noeud. Elles utilisent une adresse stable fournie par HAProxy.

### A montrer

```text
Clients Oculox -> HAProxy:9200 -> OpenSearch 1, 2 ou 3
                                  OpenSearch transport prive:9300
```

### Point essentiel

Un **noeud** est une instance OpenSearch. Un **cluster** est un groupe de
noeuds qui partagent le meme etat et les memes donnees.

## 3. Premier fichier : le lanceur `oculox`

### A montrer

```text
oculox
```

### A dire

> Le fichier `oculox` est la porte d'entree pour l'operateur. Il ne contient
> pas le fonctionnement interne d'OpenSearch. Il traduit une commande simple,
> par exemple `install cluster`, `cluster status` ou `verify clients`, vers le
> script specialise correspondant. Cela evite de demander a l'operateur de
> connaitre toutes les commandes Docker, Python et OpenSSL.

### Commandes principales

```bash
./oculox install cluster --endpoint-ip 192.168.1.241
./oculox cluster status
./oculox cluster validate
./oculox verify clients
```

### Terme difficile : abstraction

Une **abstraction** cache plusieurs operations techniques derriere une commande
plus simple. Ici, `./oculox cluster start` est une abstraction de la validation
de la configuration, du demarrage Compose et de l'attente du cluster sain.

## 4. Chef d'orchestre : `manage-cluster.sh`

### A montrer

```text
dev/scripts/opensearch-cluster/manage-cluster.sh
```

### A dire

> Ce script est le chef d'orchestre de l'installation. Il verifie la capacite
> de la VM, genere les fichiers runtime, appelle la PKI, demarre le cluster,
> initialise Security une seule fois, attend trois noeuds, applique les
> politiques de stockage et cree les bundles clients. Il est concu pour etre
> relance apres une interruption sans supprimer les donnees existantes.

### Terme difficile : idempotent

Une operation **idempotente** peut etre relancee sans produire une nouvelle
configuration differente ou detruire l'ancienne. Par exemple, relancer
l'installation ne doit pas regenerer automatiquement la CA ni supprimer les
volumes.

## 5. Structure des conteneurs : `compose.yml`

### A montrer

```text
dev/compose/opensearch-cluster/compose.yml
```

### A dire

> Ce fichier decrit ce que Docker doit faire fonctionner. Il declare trois
> services OpenSearch et un service HAProxy. Chaque noeud possede un nom, une
> adresse interne, un healthcheck et un volume de donnees distinct. Les trois
> volumes sont indispensables : deux noeuds ne doivent jamais ecrire dans le
> meme repertoire OpenSearch.

### Elements importants

```text
opensearch-1 -> volume opensearch-data-1
opensearch-2 -> volume opensearch-data-2
opensearch-3 -> volume opensearch-data-3
```

```text
node.roles=cluster_manager,data,ingest,remote_cluster_client
```

### Explication des roles de noeud

- `cluster_manager` : peut participer a l'election du responsable du cluster ;
- `data` : stocke les shards et execute les recherches ;
- `ingest` : peut transformer un document avant son indexation ;
- `remote_cluster_client` : permet certaines communications avec un cluster
  distant.

### Terme difficile : healthcheck

Un **healthcheck** est un test automatique de sante. Docker ne se contente pas
de voir que le processus existe ; il interroge aussi le service HTTPS. Un
conteneur `running` est demarre. Un conteneur `healthy` a reussi son test.

## 6. Premier amorcage : `compose.bootstrap.yml`

### A montrer

```text
dev/compose/opensearch-cluster/compose.bootstrap.yml
```

### A dire

> Ce petit fichier n'est utilise qu'au premier demarrage, lorsque les trois
> volumes sont vides. Il indique quels noeuds ont le droit de participer a la
> toute premiere election. Apres cette election, l'identite du cluster est
> enregistree dans les volumes. Les demarrages suivants utilisent seulement
> `compose.yml`.

### Terme difficile : bootstrap ou amorcage

Le **bootstrap** est la creation initiale de l'identite du cluster. On peut le
comparer a la premiere reunion ou les trois noeuds decident qu'ils appartiennent
au meme groupe. Le refaire sur un cluster existant peut creer une incoherence ;
c'est pourquoi le fichier est temporaire.

### Difference avec discovery

- **bootstrap** : premiere election, une seule fois ;
- **discovery** : methode permanente pour que les noeuds se retrouvent apres
  chaque redemarrage.

## 7. Variables de deploiement : `cluster.env.example`

### A montrer

```text
dev/config/opensearch-cluster/cluster.env.example
dev/generated/opensearch-cluster/cluster.env
```

### A dire

> Le fichier `cluster.env.example` est un modele sans secret. Le fichier
> `cluster.env` est genere pour la VM reelle. Il contient l'image, la heap, le
> nom du cluster, l'adresse de l'endpoint et les noms de decouverte. Cette
> separation evite de coder l'adresse d'une VM directement dans plusieurs
> fichiers sources.

### Terme difficile : heap Java

La **heap** est la memoire principale reservee a la machine virtuelle Java
d'OpenSearch. Elle sert aux calculs, caches et objets temporaires. Elle ne
contient pas toutes les donnees du cluster : les index restent sur disque et le
systeme utilise aussi la memoire disponible comme cache de fichiers.

## 8. Configuration OpenSearch : `opensearch.yml`

### A montrer

```text
dev/config/opensearch-cluster/opensearch.yml
```

### A dire

> Ce fichier configure le comportement commun aux trois noeuds. Il fixe le nom
> du cluster, les ports, TLS et les identites de certificats autorisees. Le nom
> propre a chaque noeud est injecte par Compose, ce qui permet aux trois
> conteneurs de partager le meme fichier sans partager la meme identite.

### Ports

```text
9200 = API HTTPS utilisee par les applications
9300 = communication interne entre les noeuds
```

Le port `9300` ne doit pas etre expose aux utilisateurs. Il transporte l'etat
du cluster et les echanges entre noeuds.

### `nodes_dn`

`nodes_dn` contient les identites exactes des certificats autorises comme
noeuds OpenSearch. Un conteneur avec un certificat inconnu ne peut pas rejoindre
le cluster.

### `admin_dn`

`admin_dn` contient l'identite du certificat d'administration. Ce certificat
permet les operations Security sensibles avec `securityadmin.sh`. Il n'est pas
monte en permanence dans les applications.

### Terme difficile : DN

Le **Distinguished Name**, ou DN, est le nom complet inscrit dans un certificat.
Exemple : organisation Oculox, unite OpenSearch Nodes et nom opensearch-1.

## 9. PKI : EJBCA et manifest Oculox

### A montrer

```text
dev/ejbca/pki-manifest.yml
dev/scripts/ejbca/pki-lifecycle.py
dev/scripts/opensearch-cluster/manage-cluster.sh
dev/generated/opensearch-cluster/pki/
```

### A dire

> La PKI etablit la confiance cryptographique. Dans la version durcie,
> l'autorite reelle est EJBCA. Oculox declare les certificats attendus dans un
> manifest, demande leur emission a EJBCA, les installe dans les chemins actifs,
> puis valide les noeuds OpenSearch, l'endpoint HAProxy et le certificat
> administrateur.

La CA OpenSearch est `Oculox OpenSearch CA`. Elle signe :

- un certificat pour `opensearch-1` ;
- un certificat pour `opensearch-2` ;
- un certificat pour `opensearch-3` ;
- un certificat pour l'endpoint HTTPS `opensearch-endpoint` ;
- un certificat client administrateur `oculox-opensearch-admin`.

Le script `generate-pki.sh` est conserve comme artefact historique de
developpement, mais le chemin normal d'installation du cluster passe par
`./oculox pki enroll --provider ejbca`.

### Termes difficiles

- **CA** : autorite de certification ; elle signe et permet de verifier les
  certificats ;
- **certificat** : document public prouvant une identite ;
- **cle privee** : secret utilise pour prouver que l'on possede cette identite ;
- **SAN** : liste des noms DNS ou IP pour lesquels le certificat est valide ;
- **TLS** : chiffrement et verification de l'identite du serveur ;
- **mTLS** : TLS mutuel, le serveur verifie aussi le certificat du client.

### Exemple simple

Pour joindre `https://192.168.1.241:9200`, le certificat de HAProxy doit
contenir `IP:192.168.1.241` dans ses SAN. Sinon, la CA peut etre correcte mais
le nom de destination reste invalide.

Pour eviter de figer une adresse dans Git, cette IP vient du fichier runtime
`dev/generated/opensearch-cluster/cluster.env`. Si la VM change d'adresse, il
faut re-emettre ou faire tourner le certificat endpoint.

## 10. Security : les fichiers du dossier `security`

### A montrer

```text
dev/config/opensearch-cluster/security/config.yml
dev/config/opensearch-cluster/security/roles.yml
dev/config/opensearch-cluster/security/roles_mapping.yml
```

### A dire pour `config.yml`

> `config.yml` definit comment OpenSearch authentifie une requete. Dans la
> configuration actuelle, les applications utilisent un nom d'utilisateur et
> un mot de passe transmis dans une connexion HTTPS. Keycloak pourra etre
> ajoute plus tard comme autre methode d'authentification sans remplacer la PKI
> entre les noeuds.

### A dire pour `roles.yml`

> `roles.yml` indique ce qu'une identite a le droit de faire. Logstash peut
> ecrire dans les index d'evenements, Arkime gere ses sessions, l'API lit les
> donnees et dashboards-helper gere les templates et objets techniques. Le but
> est le moindre privilege : chaque service obtient seulement les permissions
> dont il a besoin.

### A dire pour `roles_mapping.yml`

> `roles_mapping.yml` fait le lien entre l'identite de l'utilisateur et le role
> de permissions. On peut le comparer a l'attribution d'un badge de fonction a
> une personne authentifiee.

### Trois notions a ne pas confondre

1. **utilisateur** : identite et mot de passe ;
2. **backend role** : etiquette attribuee a l'utilisateur ;
3. **Security role** : liste des actions autorisees.

### Exemple

```text
utilisateur oculox_logstash
        -> backend role oculox_logstash_writer
        -> Security role oculox_logstash_writer
        -> ecriture autorisee dans malcolm_beats_* et arkime_sessions3-*
```

## 11. HAProxy : `haproxy.cfg.template`

### A montrer

```text
dev/config/opensearch-cluster/haproxy.cfg.template
```

### A dire

> HAProxy fournit l'adresse stable `192.168.1.241:9200`. Il connait les trois
> noeuds, verifie regulierement leur sante et envoie les requetes uniquement aux
> noeuds disponibles. Les applications ne changent pas de configuration si un
> noeud tombe.

### Terme difficile : frontend et backend

- **frontend** : cote visible par les clients, ici le port `9200` de la VM ;
- **backend** : liste des serveurs internes capables de traiter la requete.

### Terme difficile : roundrobin

**Roundrobin** signifie tour a tour. Si les trois noeuds sont disponibles,
HAProxy envoie les nouvelles requetes dans cet ordre : 1, 2, 3, puis recommence
par 1. Il ne coupe pas un document en trois morceaux et il ne choisit pas le
cluster manager. Il choisit seulement le noeud qui recevra la requete HTTP.

Le noeud recepteur examine ensuite l'etat du cluster et contacte les noeuds qui
possedent les shards necessaires.

### Healthcheck HAProxy

HAProxy appelle une URL de sante avec un compte limite. Si un noeud echoue
plusieurs fois, il est retire de la liste active. Il reste dans le fichier de
configuration et revient automatiquement apres plusieurs controles reussis.

### Port 8404

Le port `8404` affiche l'etat interne de HAProxy : backends UP/DOWN, connexions
et erreurs. Il sert a l'administration, pas aux applications OpenSearch.

## 12. Stockage : `cluster-settings.json` et les politiques ISM

### A montrer

```text
dev/config/opensearch-cluster/storage-policy/cluster-settings.json
dev/config/opensearch-cluster/storage-policy/arkime-sessions-policy.json
dev/config/opensearch-cluster/storage-policy/arkime-history-policy.json
dev/config/opensearch-cluster/storage-policy/malcolm-beats-policy.json
```

### A dire

> `cluster-settings.json` impose au moins un replica et active les protections
> disque. Les fichiers de politique ISM gerent automatiquement le vieillissement
> des index Arkime et Beats. Le script `apply-storage-policy.py` sauvegarde la
> configuration actuelle avant d'appliquer ces changements.

### Termes difficiles : shard primaire et replica

Un **shard primaire** est une partie originale d'un index. Un **replica** est
une copie de cette partie sur un autre noeud. Avec un replica, la perte du noeud
portant le primaire permet a la copie de prendre sa place.

Un replica ne remplace pas une sauvegarde. Si un document est supprime
volontairement, la suppression est reproduite sur le replica.

### Terme difficile : ISM

**Index State Management** automatise le cycle de vie d'un index. Par exemple :
index actif, optimisation a trente jours, puis suppression a quatre-vingt-dix
jours. La suppression n'est pas un archivage. Pour consulter les donnees six
mois plus tard, il faut un snapshot conserve ailleurs puis restaure.

### Terme difficile : watermark

Un **watermark** est un seuil d'occupation disque :

- `75 %` : eviter de placer de nouveaux shards ;
- `85 %` : essayer de deplacer des shards ;
- `90 %` : proteger le disque, eventuellement en bloquant des ecritures.

## 13. Bundles et clients distants

### A montrer

```text
dev/scripts/opensearch-cluster/create-client-bundle.py
dev/scripts/configure-remote-opensearch.py
dev/scripts/render-remote-opensearch-compose.py
```

### A dire

> Le cluster genere un bundle Core et un bundle Hedgehog. Un bundle contient
> l'adresse HTTPS, la CA et seulement les comptes necessaires au role cible.
> Le Core importe cinq identites de service. Hedgehog importe uniquement les
> identites Arkime et API. Les sommes SHA-256 permettent de detecter un fichier
> modifie pendant le transfert.

`configure-remote-opensearch.py` installe le bundle, active la verification TLS
et configure `opensearch-remote`.

`render-remote-opensearch-compose.py` desactive le conteneur OpenSearch local,
retire les dependances vers celui-ci et monte le bon compte dans chaque
conteneur.

### Terme difficile : endpoint

Un **endpoint** est l'adresse stable d'un service. Ici :

```text
https://192.168.1.241:9200
```

Les trois noeuds peuvent changer derriere cette adresse sans modifier les
applications.

## 14. Filebeat et les deux Logstash

### A dire

> Filebeat ne contacte pas directement OpenSearch. Il envoie les evenements aux
> deux Logstash. Logstash analyse, transforme puis indexe les documents dans le
> cluster distant. Arkime est une exception importante : il peut ecrire ses
> sessions directement dans OpenSearch.

### Terme difficile : load balancing Filebeat

Avec `loadbalance: true`, Filebeat maintient des connexions vers les deux
Logstash et distribue ses lots entre eux. Ce mecanisme est different du
roundrobin HAProxy :

```text
Filebeat load balancing -> repartit les evenements entre Logstash 1 et 2
HAProxy roundrobin       -> repartit les requetes HTTP entre OpenSearch 1, 2 et 3
```

### mTLS Beats

Filebeat presente un certificat client signe par la CA Beats. Logstash refuse
une connexion sans certificat avec `Empty client certificate chain`.

La PKI Beats et la PKI OpenSearch sont separees :

- PKI Beats : Filebeat vers Logstash ;
- PKI OpenSearch : clients vers HAProxy et communications entre noeuds.

## 15. Tests : comment prouver que cela fonctionne

### A montrer

```text
dev/tests/opensearch-cluster/test_cluster_resilience_runtime.sh
dev/tests/opensearch-cluster/validate-client-connectivity.py
dev/tests/opensearch-cluster/validate-ingestion-path.py
```

### A dire

> Nous ne validons pas le cluster uniquement parce que les conteneurs sont
> demarres. Nous testons la creation de documents, la perte d'un noeud, la
> promotion d'un replica, l'election d'un nouveau manager, la perte du quorum,
> les permissions de chaque client et l'ingestion d'un PCAP complet.

### Resultats a citer

```text
cluster green
3 noeuds
0 shard non affecte
clients Core PASS
mTLS 5044 et 5045 PASS
ingestion PCAP PASS
0 nouveau rejet OpenSearch
0 nouvel echec d'indexation
```

Le PCAP de validation contenait `56 410` paquets. Les deux Logstash ont recu
des evenements et OpenSearch a cree des documents Beats et des sessions Arkime.

## 16. Notion de quorum

### A dire

> Avec trois noeuds eligibles comme cluster manager, OpenSearch exige une
> majorite de deux. Si un noeud tombe, les deux autres peuvent continuer. Si
> deux noeuds tombent, le dernier refuse de prendre seul les decisions de
> cluster. Ce blocage est volontaire : il evite que deux parties isolees
> acceptent des modifications contradictoires.

### Analogie

Trois personnes doivent prendre une decision. Une personne seule ne represente
pas la majorite. Deux personnes peuvent decider. Le cluster fonctionne de la
meme maniere pour les changements importants.

## 17. Questions probables et reponses simples

### Pourquoi trois noeuds et pas deux ?

Avec deux noeuds, la perte d'un noeud ne laisse qu'une voix sur deux, donc pas
de majorite claire. Trois noeuds permettent de perdre un noeud tout en gardant
deux voix sur trois.

### HAProxy est-il le cluster manager ?

Non. HAProxy repartit les connexions HTTP. Le cluster manager est un noeud
OpenSearch elu qui gere l'etat interne du cluster.

### Le manager contient-il toutes les donnees ?

Pas specialement. Dans notre topologie, tous les noeuds sont aussi `data`, mais
le role manager concerne les decisions de cluster, pas la centralisation des
documents.

### Pourquoi un endpoint si tous les noeuds acceptent HTTP ?

Sans endpoint, chaque application devrait connaitre les trois noeuds et gerer
elle-meme les pannes. L'endpoint fournit une seule adresse et retire les noeuds
indisponibles.

### Pourquoi TLS existe-t-il deux fois autour de HAProxy ?

La premiere connexion protege le client vers HAProxy. La seconde protege
HAProxy vers le noeud OpenSearch. Aucun segment ne circule en clair.

### Pourquoi ne pas utiliser le compte administrateur partout ?

Parce qu'une compromission de Logstash ou de l'API donnerait alors le controle
total du cluster. Les comptes limites reduisent les consequences d'une fuite.

### Replica et snapshot, est-ce la meme chose ?

Non. Le replica assure la continuite apres une panne de noeud. Le snapshot
permet de revenir a un etat anterieur ou de restaurer des donnees supprimees.

### Pourquoi le cluster peut-il etre yellow ?

`yellow` signifie que tous les primaires sont disponibles mais qu'au moins un
replica n'est pas place. Les recherches restent possibles, mais la resilience
est incomplete. `green` signifie que primaires et replicas sont tous affectes.

### Que signifie `UNASSIGNED` ?

OpenSearch connait un shard ou une copie, mais ne peut actuellement le placer
sur aucun noeud. L'API `_cluster/allocation/explain` donne la raison precise.

### Que fait Keycloak dans cette architecture ?

Keycloak pourra authentifier les utilisateurs humains. Il ne remplace ni TLS,
ni les certificats entre noeuds, ni necessairement les comptes techniques des
services.

## 18. Glossaire tres simple

| Terme | Explication simple |
|---|---|
| Alias | nom stable qui pointe vers un ou plusieurs index |
| Backend | serveur interne choisi par un proxy |
| Bootstrap | toute premiere formation du cluster |
| CA | autorite qui signe et permet de verifier les certificats |
| Cluster | groupe de noeuds OpenSearch travaillant ensemble |
| Cluster manager | noeud elu pour gerer l'etat du cluster |
| Discovery | methode utilisee par les noeuds pour se retrouver |
| DN | identite complete ecrite dans un certificat |
| Endpoint | adresse stable utilisee par les clients |
| Frontend | adresse visible d'un proxy |
| Healthcheck | test automatique de disponibilite |
| Heap | memoire Java reservee au processus OpenSearch |
| Idempotent | relancable sans casser ni dupliquer l'etat |
| Index | ensemble logique de documents |
| ISM | automatisation du cycle de vie des index |
| Mapping | definition des types de champs d'un index |
| mTLS | TLS ou serveur et client presentent une identite |
| Noeud | une instance OpenSearch |
| Quorum | nombre minimum de voix pour prendre une decision |
| Replica | copie d'un shard primaire sur un autre noeud |
| Roundrobin | distribution tour a tour entre serveurs sains |
| SAN | noms DNS et IP couverts par un certificat |
| Shard | portion physique d'un index |
| Snapshot | sauvegarde restaureable du cluster ou des index |
| Template | modele applique aux nouveaux index correspondants |
| TLS | chiffrement et verification d'identite sur le reseau |
| Watermark | seuil d'occupation disque declenchant une protection |

## 19. Conclusion a dire

> La configuration est separee en couches. Docker Compose decrit les processus
> et les volumes. OpenSearch YAML configure le cluster et TLS. La PKI definit
> les identites. Security limite les permissions. HAProxy fournit l'adresse
> stable. Les politiques de stockage gerent replicas, disque et retention. Les
> bundles configurent les clients sans partager un compte administrateur.
> Enfin, les tests prouvent la continuite apres une panne et le trajet reel des
> donnees. Cette separation nous permet de comprendre, verifier et remplacer
> chaque partie sans traiter la plateforme comme une boite noire.

## 20. Commandes de demonstration

Les commandes manuelles de test du cluster sont regroupees dans :

```text
dev/docs/Opensearch/03_commandes_tests_manuels_cluster_opensearch.md
```

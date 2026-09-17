# Prompt Astra - Schema D'Architecture Oculox

Dessiner une architecture professionnelle de la plateforme **Oculox** pour un reseau ferroviaire industriel/OT.

Le schema doit etre clair, propre, lisible et structure en **3 zones principales**. Utiliser des blocs separes avec des titres visibles, des icones de services si possible, et des fleches directionnelles entre les composants. Ne pas mettre d'adresses IP. Mettre uniquement les **ports**, les **protocoles**, les **sens des flux** et les **capacites serveur**.

## Objectif Du Schema

Montrer comment Oculox collecte le trafic industriel dans les gares, traite les logs dans le Core, centralise l'authentification avec Keycloak, puis indexe les donnees dans un cluster OpenSearch dedie.

Le schema doit faire comprendre que :

- le collecteur est installe **une fois par gare** ;
- la capture reseau se fait via un **port mirroring / SPAN / TAP** ;
- Zeek et Suricata produisent des logs ;
- Filebeat envoie les logs vers deux Logstash et fait la repartition de charge ;
- Arkime ecrit ses metadonnees directement dans OpenSearch ;
- le Core heberge les services applicatifs, les interfaces et l'authentification ;
- OpenSearch est separe dans une zone dediee avec 3 noeuds ;
- les utilisateurs accedent via HTTPS au portail, Dashboards et Arkime ;
- les flux doivent afficher les ports.

## Zone 1 - Collecteur Hedgehog Par Gare

Titre du bloc :

```text
Zone 1 - Collecteur Hedgehog OT par gare
```

Capacite serveur a afficher dans le bloc :

```text
8 vCPU
16 Go RAM
1 To SSD
1 NIC management
1 NIC capture 10 GbE
Deploiement : 1 collecteur par gare
```

Services a dessiner dans cette zone :

```text
Interface capture OT
Zeek
Suricata
Arkime Capture
Filebeat
pcap-monitor
```

Flux internes dans la zone collecteur :

```text
Port mirroring / SPAN / TAP -> Interface capture OT
Interface capture OT -> Zeek
Interface capture OT -> Suricata
Interface capture OT -> Arkime Capture
Zeek -> Filebeat
Suricata -> Filebeat
Arkime Capture -> pcap-monitor
```

Explication visuelle a faire apparaitre :

```text
Le collecteur observe le trafic OT local sans interrompre le reseau.
Zeek produit les journaux protocolaire.
Suricata produit les alertes IDS.
Filebeat transporte les journaux vers le Core.
Arkime Capture cree les sessions reseau et ecrit directement ses metadonnees dans OpenSearch.
```

## Zone 2 - Oculox Core

Titre du bloc :

```text
Zone 2 - Oculox Core / Services applicatifs
```

Capacite serveur a afficher dans le bloc :

```text
12 vCPU
32 Go RAM
1 To SSD
```

Services a dessiner dans cette zone :

```text
Nginx Proxy
Portail Oculox
Keycloak
OpenSearch Dashboards
Arkime Viewer
Logstash 1
Logstash 2
API Oculox
PostgreSQL
Valkey
Dashboards Helper
Filescan / Strelka
```

Organisation interne recommandee dans le dessin :

```text
Sous-bloc Acces utilisateur :
- Nginx Proxy
- Portail Oculox
- Keycloak

Sous-bloc Visualisation :
- OpenSearch Dashboards
- Arkime Viewer

Sous-bloc Ingestion :
- Logstash 1
- Logstash 2
- Dashboards Helper
- API Oculox

Sous-bloc Services support :
- PostgreSQL
- Valkey
- Filescan / Strelka
```

Flux utilisateurs vers le Core :

```text
Utilisateurs -> Nginx Proxy : HTTPS 443/TCP
Utilisateurs -> OpenSearch Dashboards : HTTPS 5601/TCP
Utilisateurs -> Arkime Viewer : HTTPS via Nginx / port applicatif interne Arkime
Nginx Proxy -> Keycloak : OIDC / HTTPS
Nginx Proxy -> Portail Oculox : HTTPS interne
OpenSearch Dashboards -> Keycloak : OIDC / HTTPS
```

Flux collecteur vers Core :

```text
Filebeat -> Logstash 1 : Beats TLS/mTLS 5044/TCP
Filebeat -> Logstash 2 : Beats TLS/mTLS 5045/TCP
```

Important a montrer dans le dessin :

```text
Filebeat agit comme repartiteur cote client.
Il envoie les evenements vers Logstash 1 et Logstash 2.
Logstash 1 et Logstash 2 ecrivent ensuite dans le cluster OpenSearch.
```

## Zone 3 - Cluster OpenSearch Dedie

Titre du bloc :

```text
Zone 3 - Cluster OpenSearch dedie
```

Capacite serveur a afficher dans le bloc :

```text
16 vCPU
48 Go RAM
2 To SSD
Cluster logique : 3 noeuds OpenSearch Docker
```

Services a dessiner dans cette zone :

```text
HAProxy Endpoint OpenSearch
OpenSearch node 1
OpenSearch node 2
OpenSearch node 3
PKI OpenSearch
Snapshots / Backup
```

Ports a afficher :

```text
HAProxy Endpoint OpenSearch : 9200/TCP HTTPS
HAProxy Monitoring : 8404/TCP HTTP
OpenSearch HTTP securise : 9200/TCP HTTPS
OpenSearch transport cluster : 9300/TCP TLS
```

Flux internes dans la zone OpenSearch :

```text
HAProxy Endpoint -> OpenSearch node 1 : HTTPS 9200/TCP
HAProxy Endpoint -> OpenSearch node 2 : HTTPS 9200/TCP
HAProxy Endpoint -> OpenSearch node 3 : HTTPS 9200/TCP
OpenSearch node 1 <-> OpenSearch node 2 : Transport TLS 9300/TCP
OpenSearch node 1 <-> OpenSearch node 3 : Transport TLS 9300/TCP
OpenSearch node 2 <-> OpenSearch node 3 : Transport TLS 9300/TCP
OpenSearch nodes -> Snapshots / Backup : port selon solution de sauvegarde
```

Explication visuelle a faire apparaitre :

```text
HAProxy expose un endpoint stable pour les clients.
Les clients ne dependent pas directement d'un noeud OpenSearch.
Les trois noeuds forment un seul cluster.
Les shards primaires et replicas sont repartis entre les noeuds.
Le cluster supporte la perte d'un noeud logique.
```

## Flux Entre Les Zones

Dessiner les fleches suivantes avec les ports clairement affiches.

### Collecteur Vers Core

```text
Zone 1 Filebeat -> Zone 2 Logstash 1 : 5044/TCP Beats TLS/mTLS
Zone 1 Filebeat -> Zone 2 Logstash 2 : 5045/TCP Beats TLS/mTLS
```

### Collecteur Vers OpenSearch

```text
Zone 1 Arkime Capture -> Zone 3 HAProxy OpenSearch : 9200/TCP HTTPS
Zone 1 pcap-monitor -> Zone 3 HAProxy OpenSearch : 9200/TCP HTTPS
```

### Core Vers OpenSearch

```text
Zone 2 Logstash 1 -> Zone 3 HAProxy OpenSearch : 9200/TCP HTTPS
Zone 2 Logstash 2 -> Zone 3 HAProxy OpenSearch : 9200/TCP HTTPS
Zone 2 OpenSearch Dashboards -> Zone 3 HAProxy OpenSearch : 9200/TCP HTTPS
Zone 2 Arkime Viewer -> Zone 3 HAProxy OpenSearch : 9200/TCP HTTPS
Zone 2 API Oculox -> Zone 3 HAProxy OpenSearch : 9200/TCP HTTPS
Zone 2 Dashboards Helper -> Zone 3 HAProxy OpenSearch : 9200/TCP HTTPS
```

### Utilisateurs Vers Core

```text
Utilisateurs -> Zone 2 Nginx Proxy / Portail : 443/TCP HTTPS
Utilisateurs -> Zone 2 OpenSearch Dashboards : 5601/TCP HTTPS
Utilisateurs -> Zone 2 Arkime Viewer : HTTPS via Nginx
```

## Securite A Representer

Ajouter des pictogrammes ou etiquettes de securite :

```text
TLS/mTLS entre Filebeat et Logstash
HTTPS entre Core/Collecteurs et OpenSearch
OIDC/SSO avec Keycloak pour les utilisateurs
RBAC par roles : admin, analyst, viewer, incident-response
PKI privee pour certificats internes
CA OpenSearch distribuee aux clients techniques
```

Pour Keycloak, afficher :

```text
Keycloak = identite centrale
OIDC = protocole de connexion SSO
RBAC = droits selon le role utilisateur
```

## Labels Techniques A Mettre Sur Le Schema

Ajouter ces notes courtes dans le dessin :

```text
Collecteur par gare
Capture passive via SPAN/TAP
Filebeat load balancing vers deux Logstash
Arkime ecriture directe OpenSearch
Endpoint OpenSearch stable via HAProxy
Cluster OpenSearch 3 noeuds
Replica OpenSearch = 1
TLS/mTLS active
SSO Keycloak/OIDC
```

## Style Visuel Demande

Le dessin doit etre professionnel, clair et exploitable dans une presentation.

Contraintes de style :

```text
Format paysage
Trois grandes zones de gauche a droite
Zone 1 a gauche : Collecteur Hedgehog par gare
Zone 2 au centre : Oculox Core
Zone 3 a droite : Cluster OpenSearch
Fleches orientees de gauche vers droite pour l'ingestion
Fleches utilisateurs depuis le haut vers le Core
Fleches internes OpenSearch entre les trois noeuds
Ports ecrits sur chaque liaison importante
Pas d'adresses IP
Pas de texte trop long dans les boites
Couleurs sobres et professionnelles
Utiliser une legende pour TLS, mTLS, OIDC, RBAC
```

## Message Global Que Le Schema Doit Transmettre

```text
Oculox est organise en trois zones :

1. Une zone collecteur par gare, qui observe passivement le trafic ferroviaire OT avec Zeek, Suricata et Arkime.
2. Une zone Core, qui centralise l'ingestion, les interfaces, l'authentification Keycloak, les tableaux de bord et les services applicatifs.
3. Une zone OpenSearch dediee, qui stocke et indexe les donnees dans un cluster logique a trois noeuds derriere un endpoint stable.

Les logs Zeek et Suricata passent par Filebeat puis deux Logstash.
Arkime ecrit directement ses metadonnees dans OpenSearch.
Les utilisateurs passent par Keycloak pour le SSO et les roles.
Les communications critiques sont securisees par TLS ou mTLS.
```

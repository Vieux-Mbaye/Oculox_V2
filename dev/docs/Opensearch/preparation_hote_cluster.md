# Étape de préparation hôte - Preparation de la VM OpenSearch

## 1. Objet

Ce document consigne la preparation de la VM dediee au futur cluster
OpenSearch Oculox de trois noeuds Docker.

```text
Date de validation : 2026-08-10
Adresse actuelle   : 192.168.1.241
Nom d'hote         : oculox-opensearch
Systeme            : Debian GNU/Linux 13 (trixie)
Virtualisation     : VMware
```

Aucun noeud OpenSearch, proxy de cluster, certificat ou secret n'a ete deploye
pendant cette étape.

## 2. Ressources observees

| Ressource | Valeur observee |
|---|---:|
| CPU | 8 vCPU |
| RAM | 14 Gio |
| Disque virtuel | 200 Go |
| Systeme de fichiers racine | ext4, 186 Go utilisables |
| Espace libre apres preparation | 171 Go |
| Interface | `ens33` |
| Adresse IPv4 | `192.168.1.241/24` |
| Passerelle | `192.168.1.1` |

La VM est inferieure au dimensionnement recommande de 32 a 64 Gio de RAM et de
16 a 24 vCPU. Elle est acceptable pour le developpement fonctionnel, les tests
de formation du cluster et les tests de perte d'un conteneur. Elle ne doit pas
servir a valider les benchmarks ni le dimensionnement de production.

Pour cette VM, la valeur initiale a utiliser dans la étape Compose est :

```text
heap par noeud : 2 Gio
heaps totales  : 6 Gio
```

Le reste de la RAM doit rester disponible pour la memoire hors heap des trois
JVM, les conteneurs, le proxy et le cache disque Linux. Cette valeur devra etre
confirmee par les mesures de heap, de GC et de pression memoire.

## 3. Docker installe

Docker a ete installe depuis le depot APT officiel Docker pour Debian Trixie.

```text
Docker Engine  : 29.7.2
Docker Compose : 5.4.0
Storage driver : overlayfs
Cgroup driver  : systemd
Service        : active et enabled
```

L'utilisateur `debian` appartient au groupe `docker`. Un conteneur
`hello-world` a ete execute avec succes sans `sudo`, ce qui valide le daemon,
le socket, le telechargement d'image et l'execution d'un conteneur.

Source d'installation officielle :

```text
https://docs.docker.com/engine/install/debian/
```

## 4. Swap

La VM possedait une partition swap de 10,2 Go. Elle a ete desactivee en memoire
et dans `/etc/fstab`.

```text
Swap apres redemarrage : 0 octet
```

La ligne d'origine est conservee en commentaire et une sauvegarde anterieure a
la modification existe dans :

```text
/etc/fstab.pre-oculox-opensearch
```

## 5. Parametres noyau

Le fichier suivant a ete cree :

```text
/etc/sysctl.d/99-oculox-opensearch.conf
```

Valeurs actives apres redemarrage :

```text
vm.max_map_count = 1048576
vm.swappiness = 1
net.core.somaxconn = 65535
fs.file-max = 9223372036854775807
```

`vm.max_map_count` depasse le minimum OpenSearch de `262144`. La valeur
existante de `fs.file-max`, deja superieure au besoin, n'a pas ete abaissee.

## 6. Limites de processus

Le fichier suivant a ete cree :

```text
/etc/security/limits.d/99-oculox-opensearch.conf
```

Il configure pour les utilisateurs ordinaires et `root` :

```text
nofile soft/hard : 65536
memlock soft/hard: unlimited
```

Le service Docker possede egalement cette surcharge :

```text
/etc/systemd/system/docker.service.d/99-oculox-opensearch.conf
LimitMEMLOCK=infinity
```

Apres redemarrage :

```text
Docker LimitNOFILE  = 524288
Docker LimitMEMLOCK = infinity
```

Les futurs services Compose devront toujours declarer leurs propres `ulimits`
pour `memlock` et `nofile`.

## 7. Temps et identite

Le nom d'hote a ete remplace par :

```text
oculox-opensearch
```

`systemd-timesyncd` est actif et active au demarrage. Apres le redemarrage de
validation :

```text
System clock synchronized : yes
NTP service               : active
RTC                        : UTC
```

Le fuseau actuel reste `Europe/Paris`. Les journaux OpenSearch devront etre
interpretes en UTC, comme les autres composants Oculox.

## 8. Validation apres redemarrage

La VM a ete redemarree apres toutes les modifications. Les controles suivants
ont reussi :

| Controle | Resultat |
|---|---|
| SSH | PASS |
| Nom d'hote | PASS, `oculox-opensearch` |
| Swap toujours desactive | PASS |
| Parametres sysctl persistants | PASS |
| Docker actif | PASS |
| Docker active au demarrage | PASS |
| Compose disponible | PASS |
| `LimitMEMLOCK=infinity` | PASS |
| NTP synchronise | PASS |
| Resolution Internet | PASS |
| Ports OpenSearch encore libres | PASS |

Seuls SSH sur `22/tcp` et CUPS en boucle locale etaient en ecoute. Les ports
`9200/tcp` et `9300/tcp` sont libres.

## 9. Endpoint retenu pour le developpement

La configuration IPv4 de `ens33` utilise actuellement DHCP :

```text
ipv4.method = auto
adresse      = 192.168.1.241/24
route        = default via 192.168.1.1
```

Pour le developpement, l'endpoint retenu est directement l'adresse IP :

```text
https://192.168.1.241:9200
```

Le certificat HTTP du proxy devra contenir le SAN suivant :

```text
IP:192.168.1.241
```

L'adresse doit rester stable pendant les tests. Il faut donc effectuer l'une
des deux operations suivantes :

1. reserver `192.168.1.241` pour la MAC de cette VM dans le serveur DHCP ;
2. ou fournir les parametres autorisant une configuration IPv4 statique.

L'endpoint doit etre conserve dans une variable de deploiement et non inscrit
en dur dans les fichiers Compose ou les scripts. Lors du remplacement de la VM,
il faudra fournir la nouvelle IP, regenerer le certificat HTTP avec le nouveau
SAN IP, puis relancer la configuration des clients Core et Hedgehog.

Un DNS pourra etre ajoute plus tard pour eviter cette reconfiguration, mais il
n'est pas requis pour poursuivre le developpement actuel.

## 10. Decision de sortie

La preparation systeme de la VM est validee. La étape d'organisation d'organisation du
depot peut commencer.

La construction du cluster ne devra cependant pas etre ouverte aux clients
Oculox tant que la condition suivante n'est pas confirmee :

```text
adresse 192.168.1.241 reservee ou statique
```

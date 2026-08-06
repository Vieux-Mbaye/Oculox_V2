# Identité Visuelle Oculox Et Déploiement Sur Serveur Neuf

## 1. Objectif

Cette personnalisation garantit que les interfaces directement exposées aux utilisateurs présentent l’identité **Oculox** dès la première installation : portail principal, pages d’erreur, import de données, gestion des comptes, inventaire NetBox et consultation des fichiers extraits.

Les noms techniques internes requis par le moteur d’origine sont conservés. Par exemple, le profil Compose `malcolm`, certaines variables `MALCOLM_*`, les API internes et les images `ghcr.io/idaholab/malcolm/*` restent nécessaires au fonctionnement de la plateforme. Ils ne constituent pas l’identité visuelle affichée à l’utilisateur et ne doivent pas être renommés sans refonte du logiciel amont.

## 2. Pourquoi Une Installation Neuve Affichait Malcolm

Le dépôt contenait déjà une page personnalisée dans `nginx/landingpage/index.html`, mais le déploiement de production utilisait l’image Nginx officielle préconstruite :

```text
ghcr.io/idaholab/malcolm/nginx-proxy:26.07.1
```

Cette image embarque sa propre page Malcolm. Avant la correction, aucun montage Compose ne remplaçait cette page par les fichiers du dépôt. Une modification du code source local n’avait donc aucun effet sur un serveur installé avec les images officielles.

## 3. Sources Graphiques

Le logo destiné au Web est :

```text
docs/images/logo/logo_Oculox.png
```

Il s’agit d’une version PNG transparente adaptée aux fonds sombres. L’icône carrée utilisée dans les onglets du navigateur est :

```text
dev/branding/oculox-icon.png
```

Elle est dérivée de l’écusson du logo Oculox et possède un fond transparent.

## 4. Fichiers Personnalisés

| Interface | Fichier source Oculox | Destination dans le conteneur |
|---|---|---|
| Portail principal | `nginx/landingpage/index.html` | `/usr/share/nginx/html/index.html` |
| Erreur 401 | `nginx/landingpage/401.html` | `/usr/share/nginx/html/401.html` |
| Erreur 404 | `nginx/landingpage/404.html` | `/usr/share/nginx/html/404.html` |
| Erreur 502 | `nginx/landingpage/502.html` | `/usr/share/nginx/html/502.html` |
| Import de données | `file-upload/site/index.html` | `/var/www/upload/index.html` |
| Gestion des comptes | `htadmin/src/includes/head.php` | `/var/www/htadmin/includes/head.php` |
| Fichiers extraits | `filescan/scripts/extracted_files_http_server.py` | `/usr/local/bin/extracted_files_http_server.py` |
| NetBox | `nginx/nginx_netbox_location.conf` | `/etc/nginx/nginx_netbox_location.conf` |

## 5. Fonctionnement Du Wrapper Nginx

Le script `dev/branding/install-nginx-branding.sh` est exécuté avant le point d’entrée officiel de Nginx.

Son fonctionnement est le suivant :

1. les sources Oculox sont montées en lecture seule sous `/opt/oculox-branding` ;
2. le wrapper copie les pages, le logo et l’icône dans le système de fichiers inscriptible du conteneur ;
3. il lance ensuite `/usr/local/bin/docker_entrypoint.sh` avec les arguments d’origine ;
4. le point d’entrée officiel remplace normalement les marqueurs d’URL dynamiques ;
5. Nginx démarre avec les pages Oculox finales.

La copie préalable est importante. Un montage direct de `index.html` empêcherait le point d’entrée officiel de remplacer ce fichier avec `sed -i`, car Docker présente un fichier monté comme une ressource non remplaçable.

## 6. Application Par Docker Compose

Le fichier `dev/compose/docker-compose.dev.yml` applique les surcharges à chaque démarrage :

- wrapper et ressources Oculox pour `nginx-proxy` ;
- page et logo Oculox pour `upload` ;
- en-tête et logo Oculox pour `htadmin` ;
- serveur personnalisé et icône Oculox pour `filescan` ;
- substitutions Oculox pour NetBox et la gestion des comptes.

Le lanceur `./oculox` fusionne automatiquement cette surcharge avec le `docker-compose.yml` officiel. Aucune copie manuelle dans un conteneur n’est nécessaire.

## 7. Installation Sur Un Serveur Neuf

```bash
git clone ssh://git@gitea.tcric.hq/vmbaye/Oculox_V2.git
cd Oculox_V2
./oculox install principal --server-name <nom-DNS-ou-IP-du-principal>
```

L’installateur officiel génère les variables et les secrets, puis le lanceur prépare la résilience et démarre la composition fusionnée. Le branding Oculox est donc déployé pendant le premier démarrage.

Après une mise à jour du dépôt :

```bash
git pull --ff-only
./oculox validate
./oculox start
```

`./oculox start` est préférable à un simple `docker restart`, car Docker Compose doit relire les nouveaux montages, le nouvel entrypoint et recréer les conteneurs dont la définition a changé.

## 8. Validation Avant Livraison

Depuis la racine du dépôt :

```bash
./dev/tests/test-branding.sh
./dev/scripts/validate-compose.sh
```

Après démarrage, identifier le conteneur Nginx :

```bash
docker ps --format '{{.Names}}' | grep nginx-proxy
```

Vérifier la page réellement servie dans le conteneur :

```bash
docker exec <conteneur-nginx> grep -E '<title>|Oculox_logo' /usr/share/nginx/html/index.html
```

Vérifier la réponse HTTPS :

```bash
curl -sk https://<adresse-du-principal>/ | grep -E '<title>|Oculox_logo'
```

Le résultat attendu contient :

```text
<title>Oculox | Sécurité OT</title>
assets/img/Oculox_logo.png
```

Les contrôles visuels doivent ensuite couvrir le portail, l’import, la gestion des comptes, NetBox ainsi que les pages 401, 404 et 502, en thème clair et sombre.

## 9. Résistance Aux Mises À Jour

Les images officielles peuvent être mises à jour sans réintégrer manuellement les logos. Tant que les chemins internes utilisés par l’image restent compatibles, la surcharge Compose réapplique les fichiers Oculox au démarrage.

Après chaque montée de version, il faut néanmoins exécuter les validations et vérifier les interfaces. Si l’éditeur modifie les chemins internes ou le point d’entrée Nginx, le wrapper devra être adapté avant la mise en production.

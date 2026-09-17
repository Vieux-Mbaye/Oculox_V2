# Nginx Dans Oculox

Nginx est la porte d'entree Web de la plateforme.

Il assure :

- terminaison TLS ;
- reverse proxy vers les services internes ;
- authentification portail via Keycloak ;
- controle RBAC avant proxy ;
- publication de Dashboards sur le port 5601 ;
- routage vers Keycloak, Arkime, NetBox, Upload, API et assets statiques.

## Ports Publics

| Port | Usage |
|---|---|
| `443/tcp` | Portail Oculox et services proxifies |
| `5601/tcp` | OpenSearch Dashboards |

## Fichiers Importants

| Fichier | Role |
|---|---|
| `nginx.conf` | Configuration principale et routage du portail |
| `nginx_auth_keycloak.conf` | Authentification OIDC du portail via `lua-resty-openidc` |
| `nginx_auth_keycloak_basic.conf` | Compatibilite Basic Auth quand necessaire |
| `nginx_dashboards_remote_server.conf` | Origine navigateur dediee a Dashboards |
| `nginx_keycloak_location.conf` | Proxy vers Keycloak |
| `nginx_envs.conf` | Variables d'environnement exposees a Nginx |
| `lua/nginx_auth_helpers.lua` | Verification groupes, roles et RBAC |
| `scripts/docker_entrypoint.sh` | Generation des includes runtime |

## Flux Portail

```text
Navigateur -> Nginx 443 -> Keycloak -> Nginx -> Portail Oculox
```

Nginx verifie ensuite :

```text
NGINX_AUTH_MODE=keycloak
NGINX_REQUIRE_GROUP=/oculox-users
ROLE_BASED_ACCESS=true
```

Ces valeurs viennent de `config/auth-common.env`.

## Flux Dashboards

```text
Navigateur -> Nginx 5601 -> conteneur dashboards -> Keycloak -> OpenSearch
```

Le port 5601 est separe du portail pour eviter que les sessions Dashboards et
les sessions portail se perturbent.

## Assets Statiques

Les chemins `/assets/`, `/css/` et `/js/` sont servis sans declencher de login.
C'est volontaire : pendant le callback OIDC, des requetes CSS/JS paralleles ne
doivent pas ecraser l'etat de session.

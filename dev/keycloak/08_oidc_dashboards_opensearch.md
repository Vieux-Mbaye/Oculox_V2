# Phase K6 - OIDC Dashboards Et OpenSearch

> Mise a jour EJBCA du 1 octobre 2026 : le cluster doit faire confiance a la
> chaine Web EJBCA, distincte de sa CA OpenSearch. Apres demarrage du Core,
> executer sur Cluster `./oculox cluster configure-oidc --keycloak-auth-url
> https://<CORE>/keycloak`, puis `./oculox cluster verify-oidc`. Pour corriger
> seulement une ancienne confiance, utiliser `./oculox cluster oidc-trust` :
> les roles et mappings actifs ne sont pas reecrits. Le parcours a jour est
> dans [la procedure trois VM](../ejbca/docs/installation_3_vm_et_bundles.md).

## But

Cette phase connecte OpenSearch Dashboards à Keycloak pour les utilisateurs
humains, tout en gardant les comptes techniques OpenSearch utilisés par
Logstash, Arkime, l'API et les scripts.

L'objectif n'est pas de remplacer tous les mots de passe techniques par
Keycloak. L'objectif est plus précis :

- un humain ouvre Dashboards avec Keycloak et OIDC ;
- Dashboards envoie ensuite le jeton de l'utilisateur à OpenSearch ;
- OpenSearch vérifie ce jeton auprès de Keycloak ;
- OpenSearch traduit les rôles Keycloak en permissions OpenSearch ;
- les comptes techniques existants restent en Basic avec le moindre privilège.

## Ce Que Fait OIDC Ici

OIDC signifie OpenID Connect. C'est une couche d'identité au-dessus d'OAuth2.
Dans notre cas, Keycloak joue le rôle de fournisseur d'identité.

Le navigateur ne donne plus un mot de passe OpenSearch directement à
Dashboards. Il est redirigé vers Keycloak, Keycloak authentifie l'utilisateur,
puis Dashboards reçoit un jeton signé. Ce jeton contient l'identité de
l'utilisateur et ses rôles.

OpenSearch ne fait pas confiance au navigateur directement. Il vérifie la
signature, l'issuer, l'audience et l'expiration du jeton.

## Flux Cible

```text
Navigateur
  -> OpenSearch Dashboards
  -> Keycloak
  -> OpenSearch Dashboards
  -> OpenSearch Security
  -> index autorises selon les roles
```

Dashboards reste sur son port applicatif. Le portail Oculox, lui, reste géré
par Nginx et Keycloak depuis la phase K5.

## Fichiers Modifiés

### `docker-compose.yml`

Le service `dashboards` charge maintenant :

```text
config/dashboards.env
config/keycloak.env
```

Sans ces deux fichiers, le conteneur Dashboards ne voit pas
`DASHBOARDS_AUTH_TYPE`, `KEYCLOAK_AUTH_URL`,
`KEYCLOAK_DASHBOARDS_CLIENT_ID`, le secret client et l'URI de redirection.

### `dashboards/opensearch_dashboards.yml`

Le type d'authentification n'est plus codé en dur en `basicauth`.
Il est remplacé par un marqueur :

```yaml
opensearch_security:
  auth:
    type: "_MALCOLM_DASHBOARDS_AUTH_TYPE_"
```

Au démarrage, le conteneur remplace ce marqueur par :

```text
basicauth
```

ou :

```text
openid
```

selon la valeur de `DASHBOARDS_AUTH_TYPE`.

### `dashboards/scripts/docker_entrypoint.sh`

Ce script prépare le fichier final lu par Dashboards.

Si `DASHBOARDS_AUTH_TYPE=openid`, il ajoute les paramètres OIDC :

```text
opensearch_security.openid.connect_url
opensearch_security.openid.client_id
opensearch_security.openid.client_secret
opensearch_security.openid.base_redirect_url
```

`connect_url` pointe vers le document de découverte Keycloak :

```text
https://<core>/keycloak/realms/oculox/.well-known/openid-configuration
```

Ce document indique à Dashboards où trouver les endpoints OIDC et les clés
publiques utilisées pour vérifier les jetons.

### `dev/compose/docker-compose.dev.yml`

L'override local monte maintenant deux fichiers Dashboards depuis le dépôt :

```text
dashboards/opensearch_dashboards.yml
dashboards/scripts/docker_entrypoint.sh
```

Les deux doivent aller ensemble. Le template contient les marqueurs, et
l'entrypoint les remplace au démarrage. Si le template est monté sans
l'entrypoint correspondant, Dashboards voit encore le marqueur
`_MALCOLM_DASHBOARDS_AUTH_TYPE_` et refuse de démarrer.

### `config/dashboards.env.example`

La valeur par défaut reste volontairement :

```text
DASHBOARDS_AUTH_TYPE=basicauth
```

Cela conserve le retour arrière. OIDC est activé explicitement, pas par
accident.

### `dev/scripts/keycloak/configure-dashboards-oidc.py`

Ce script active, désactive ou vérifie OIDC côté Core.

Il refuse l'activation si :

- le realm Keycloak n'a pas été provisionné avec succès ;
- l'URL publique n'est pas en HTTPS ;
- l'URL Keycloak ne correspond pas à l'URL publique du Core ;
- le client n'est pas `oculox-dashboards` ;
- le secret client Dashboards est absent ;
- l'URI de redirection Dashboards n'est pas exactement celle attendue.

Il écrit uniquement la bascule :

```text
DASHBOARDS_AUTH_TYPE=openid
```

ou le retour arrière :

```text
DASHBOARDS_AUTH_TYPE=basicauth
```

### `oculox`

Trois commandes sont ajoutées :

```text
./oculox keycloak activate-dashboards
./oculox keycloak deactivate-dashboards
./oculox keycloak verify-dashboards
```

Elles évitent de modifier les fichiers à la main.

## OpenSearch Security

### `dev/scripts/opensearch-cluster/render-oidc-security-config.py`

Ce script génère une copie contrôlée de la configuration Security OpenSearch
avec un domaine OIDC en plus du domaine Basic.

Le domaine Basic reste présent pour les comptes techniques :

```text
oculox_logstash
oculox_logstash_2
oculox_arkime
oculox_dashboards_server
oculox_platform_admin
```

Le nouveau domaine OIDC sert aux utilisateurs humains :

```text
openid_auth_domain
```

Il valide :

- l'issuer Keycloak ;
- l'audience `oculox-dashboards` ;
- la signature du jeton ;
- l'expiration ;
- les rôles reçus dans `realm_access.roles`.

### `dev/scripts/opensearch-cluster/update-security-config.sh`

Ce script applique seulement :

```text
config.yml
roles_mapping.yml
```

Il ne régénère pas les utilisateurs internes ni les rôles techniques. C'est
important pour ne pas casser Logstash, Arkime ou les scripts.

### `dev/scripts/opensearch-cluster/manage-cluster.sh`

La commande ajoutée est :

```text
./oculox cluster configure-oidc --keycloak-auth-url https://<core>/keycloak --keycloak-ca <ca.crt>
```

`--keycloak-ca` installe dans le cluster la CA qui signe le certificat HTTPS du
Core. C'est nécessaire en développement, car la CA est privée et les conteneurs
OpenSearch ne la connaissent pas par défaut.

Quand cette CA est ajoutée, les trois nœuds OpenSearch sont recréés pour
prendre le nouveau montage en compte. HAProxy est recréé juste après, afin de
recharger les noms Docker des nœuds. Sans cela, il peut garder une ancienne IP
interne et considérer un nœud comme invalide parce que le certificat présenté
ne correspond pas au nom attendu.

### `dev/compose/opensearch-cluster/compose.yml`

Chaque nœud OpenSearch monte maintenant :

```text
dev/generated/opensearch-cluster/idp-trust
```

dans :

```text
/usr/share/opensearch/config/idp-trust
```

OpenSearch utilise cette CA pour vérifier l'URL HTTPS de découverte Keycloak.
On ne désactive donc pas la vérification TLS.

Chaque nœud OpenSearch est aussi attaché à un réseau Docker sortant nommé :

```text
oculox-opensearch-idp-egress
```

Ce réseau ne publie pas de port OpenSearch sur l'hôte. Il permet seulement aux
nœuds OpenSearch de joindre Keycloak pour lire le document OIDC et les clés
JWKS. Le réseau transport du cluster reste séparé et privé.

## Mappage Des Rôles

Keycloak envoie des rôles simples dans le jeton, par exemple :

```text
read_access
dashboards_read_access
dashboards_read_write_access
admin
```

OpenSearch reçoit ces rôles comme `backend_roles`. Ensuite
`roles_mapping.yml` les relie aux rôles OpenSearch.

Exemple simple :

```text
Utilisateur dans Keycloak -> role read_access
Jeton OIDC -> realm_access.roles contient read_access
OpenSearch -> dashboards_read_access accepte ce backend role
Dashboards -> lecture autorisee
```

## Commandes D'Activation

Sur le cluster OpenSearch :

```text
cd ~/Oculox_V2
./oculox cluster configure-oidc --keycloak-auth-url https://<IP_CORE>/keycloak --keycloak-ca /tmp/oculox-web-ca.crt
```

Sur le Core :

```text
cd ~/ICSHUB/Oculox
./oculox keycloak activate-dashboards
./oculox restart dashboards nginx-proxy
./oculox keycloak verify-dashboards
```

Retour arrière :

```text
cd ~/ICSHUB/Oculox
./oculox keycloak deactivate-dashboards
./oculox restart dashboards nginx-proxy
```

## Tests Réalisés

Tests logiciels :

```text
python3 -m unittest discover -s Oculox/dev/tests/keycloak -p 'test_*.py'
python3 Oculox/dev/tests/opensearch-cluster/test_oidc_security_config.py
bash -n Oculox/oculox Oculox/dashboards/scripts/docker_entrypoint.sh Oculox/dev/scripts/opensearch-cluster/manage-cluster.sh Oculox/dev/scripts/opensearch-cluster/update-security-config.sh
python3 -m py_compile Oculox/dev/scripts/keycloak/configure-dashboards-oidc.py Oculox/dev/scripts/opensearch-cluster/render-oidc-security-config.py
```

Résultat attendu :

```text
tests Keycloak OK
tests OpenSearch OIDC OK
syntaxe Bash OK
compilation Python OK
```

## Résultats Observés Le 9 Septembre 2026

Sur le Core local :

```text
./oculox keycloak verify-portal
result: PASS
```

```text
./oculox keycloak verify-dashboards
result: PASS
```

```text
./oculox verify clients
CLIENT_CONNECTIVITY_RESULT=PASS
```

Ce dernier test confirme :

- Logstash 1 authentifié sur le cluster ;
- Logstash 2 authentifié sur le cluster ;
- Arkime authentifié sur le cluster ;
- Arkime Live authentifié sur le cluster ;
- Dashboards authentifié avec son compte serveur ;
- dashboards-helper authentifié avec son compte serveur ;
- pcap-monitor et API authentifiés avec le compte API ;
- Filebeat reste en sortie Logstash avec `loadbalance: true` ;
- Filebeat n'a pas de sortie directe OpenSearch ;
- Arkime peut écrire directement dans OpenSearch.

Sur le cluster OpenSearch `192.168.1.200` :

```text
cluster status: green
number_of_nodes: 3
number_of_data_nodes: 3
unassigned_shards: 0
```

HAProxy voit les trois backends :

```text
opensearch-1: UP, L7OK/200
opensearch-2: UP, L7OK/200
opensearch-3: UP, L7OK/200
```

Depuis un conteneur OpenSearch, Keycloak est joignable avec la CA web du Core :

```text
issuer: https://192.168.1.174/keycloak/realms/oculox
jwks_uri: https://192.168.1.174/keycloak/realms/oculox/protocol/openid-connect/certs
```

Depuis Dashboards, la découverte OIDC Keycloak est joignable avec la CA web du
Core :

```text
issuer: https://192.168.1.174/keycloak/realms/oculox
authorization_endpoint: https://192.168.1.174/keycloak/realms/oculox/protocol/openid-connect/auth
```

La route Dashboards sans session utilisateur retourne une redirection OIDC :

```text
HTTP 302
location: /dashboards/auth/openid/captureUrlFragment?nextUrl=/dashboards/
```

La route login OIDC redirige vers Keycloak :

```text
HTTP 302
location: https://192.168.1.174/keycloak/realms/oculox/protocol/openid-connect/auth?client_id=oculox-dashboards...
```

Une requête OpenSearch sans identifiants est refusée :

```text
HTTP 401
```

Une requête OpenSearch avec un faux Bearer token est refusée :

```text
HTTP 401
```

## Incidents Corrigés Pendant K6

### Dashboards Voyait Encore Le Marqueur Brut

Symptôme :

```text
Unsupported authentication type: _MALCOLM_DASHBOARDS_AUTH_TYPE_
```

Cause : le template Dashboards du dépôt était monté, mais pas l'entrypoint
modifié qui remplace le marqueur.

Correction : `dev/compose/docker-compose.dev.yml` monte maintenant aussi
`dashboards/scripts/docker_entrypoint.sh`.

### OpenSearch Ne Pouvait Pas Joindre Keycloak

Symptôme :

```text
curl depuis opensearch-1 vers https://<core>/keycloak impossible
```

Cause : les nœuds OpenSearch étaient uniquement sur le réseau Docker
`cluster-transport`, déclaré `internal: true`.

Correction : ajout du réseau `oculox-opensearch-idp-egress`, sans publication
de port, pour permettre aux nœuds OpenSearch de lire la découverte OIDC et le
JWKS Keycloak.

### HAProxy Gardait Des Backends Invalides Après Recréation Des Nœuds

Symptôme :

```text
Layer6 invalid response: Server presented an SSL certificate different from the expected one
```

Cause : les nœuds OpenSearch avaient changé d'IP Docker interne après
recréation, mais HAProxy n'avait pas encore rechargé les résolutions Docker.

Correction : `manage-cluster.sh` recrée HAProxy juste après la recréation des
nœuds dans le chemin `configure-oidc`.

### Le Test Client Confondait Deux Services `api`

Symptôme :

```text
FAIL api_container: absent ou ambigu
```

Cause : la machine locale héberge d'autres stacks Docker avec un service
Compose nommé `api`.

Correction : le vérificateur filtre maintenant les conteneurs du projet
Compose `oculox`.

## Points De Maîtrise Pour Présentation

Dashboards utilise OIDC pour les personnes. OpenSearch garde Basic pour les
machines. Ce choix évite de mettre Keycloak dans le pipeline d'ingestion.

La CA Web du Core est distribuée au cluster uniquement pour que les nœuds
OpenSearch puissent vérifier Keycloak en HTTPS. Ce n'est pas un secret : c'est
un certificat public de confiance. Les clés privées restent locales.

Le fichier `roles_mapping.yml` ne crée pas les rôles. Il dit à OpenSearch :
« si le jeton contient tel rôle Keycloak, alors donne tel rôle OpenSearch ».

Le retour arrière reste simple : on remet Dashboards en `basicauth` et on
redémarre Dashboards. Les comptes techniques n'ont pas été supprimés.

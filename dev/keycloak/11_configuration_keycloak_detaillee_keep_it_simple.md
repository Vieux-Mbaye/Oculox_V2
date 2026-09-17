# Configuration Keycloak Oculox - Explication Simple Et Détaillée

## 1. Le But De Keycloak Dans Oculox

Keycloak est là pour gérer les **utilisateurs humains**.

Exemples :

```text
administrateur
analyste SOC
analyste OT
lecteur simple
intervenant incident
```

Keycloak répond à deux questions :

```text
Qui est cette personne ?
Qu'a-t-elle le droit de faire ?
```

Dans Oculox, Keycloak ne remplace pas Logstash, Filebeat, Arkime ou
OpenSearch. Il ne transporte pas les événements industriels.

La séparation importante est :

```text
Utilisateurs humains  -> Keycloak + OIDC
Services techniques   -> comptes techniques + certificats + mTLS
```

## 2. Les Deux Chemins À Ne Pas Confondre

### Chemin Utilisateur

Quand une personne ouvre le portail Oculox :

```text
navigateur
 -> Nginx Oculox
 -> Keycloak
 -> retour vers Oculox
 -> accès au portail, Arkime, NetBox, Upload ou API
```

Ce chemin concerne l'authentification humaine.

### Chemin Industriel

Quand Oculox traite du trafic réseau :

```text
PCAP ou capture réseau
 -> Zeek et Suricata
 -> Filebeat
 -> Logstash 1 et Logstash 2
 -> OpenSearch
 -> Arkime et Dashboards
```

Keycloak n'est pas dans ce chemin.

Donc si Keycloak tombe, l'ingestion doit continuer. C'est ce qui a été testé
dans la phase K8.

## 3. Les Mots Techniques En Simple

### OIDC

OIDC veut dire **OpenID Connect**.

C'est le protocole utilisé entre une application et Keycloak pour connecter un
utilisateur.

En simple :

```text
Oculox demande à Keycloak : est-ce que cet utilisateur est bien connecté ?
Keycloak répond : oui, voici son identité et ses rôles.
```

### SSO

SSO veut dire **Single Sign-On**.

En simple :

```text
L'utilisateur se connecte une fois à Keycloak.
Ensuite, plusieurs applications peuvent utiliser cette même session.
```

Exemple :

```text
connexion au portail Oculox
puis accès à Dashboards sans redemander un autre mot de passe
```

### Realm

Un realm est un espace isolé dans Keycloak.

Dans Oculox :

```text
realm master  -> administration technique de Keycloak
realm oculox  -> utilisateurs Oculox
```

On ne met pas les utilisateurs Oculox dans `master`, parce que `master` doit
rester réservé à l'administration de Keycloak.

### Client OIDC

Un client OIDC est une application déclarée dans Keycloak.

Dans Oculox, il y a deux clients importants :

```text
oculox-portal
oculox-dashboards
```

`oculox-portal` sert au portail Oculox derrière Nginx.

`oculox-dashboards` sert à OpenSearch Dashboards.

On les sépare parce que le portail et Dashboards ne sont pas la même
application. Ils ont des URLs, des secrets et des redirections différents.

### Client Secret

Le client secret est un mot de passe technique entre une application et
Keycloak.

Exemple :

```text
Dashboards prouve à Keycloak : je suis bien le client oculox-dashboards.
```

Ce secret ne doit pas être mis dans Git, dans une capture d'écran ou dans une
documentation publique.

### Redirect URI

La Redirect URI est l'adresse vers laquelle Keycloak renvoie le navigateur
après une connexion réussie.

Exemple Dashboards :

```text
https://192.168.1.174:5601/dashboards/auth/openid/login
```

Elle doit être exacte. On évite les wildcards comme `*`, car c'est dangereux.

### MFA

MFA veut dire **Multi-Factor Authentication**.

En simple :

```text
mot de passe + second facteur
```

Dans notre configuration, le second facteur TOTP est activé.

TOTP correspond au code temporaire généré par une application comme :

```text
FreeOTP
Google Authenticator
Microsoft Authenticator
```

## 4. Vue D'Ensemble Des Fichiers

Les fichiers importants sont :

```text
config/keycloak.env
config/auth-common.env
config/dashboards.env
config/postgres.env
docker-compose.yml
nginx/nginx_auth_keycloak.conf
nginx/lua/nginx_auth_helpers.lua
nginx/nginx_keycloak_location.conf
dashboards/opensearch_dashboards.yml
dashboards/scripts/docker_entrypoint.sh
keycloak/scripts/docker-entrypoint.sh
keycloak/scripts/hardening-preflight.sh
keycloak/scripts/realm-setup.sh
dev/scripts/keycloak/configure-realm.py
dev/scripts/keycloak/configure-portal-auth.py
dev/scripts/keycloak/configure-dashboards-oidc.py
dev/scripts/keycloak/verify-functional-hardening.py
oculox
```

## 5. `config/keycloak.env`

Fichier :

```text
config/keycloak.env
```

Ce fichier contient la configuration runtime de Keycloak.

Les lignes importantes sont :

```text
KEYCLOAK_AUTH_REALM=oculox
KEYCLOAK_AUTH_URL=https://192.168.1.174/keycloak
KEYCLOAK_CLIENT_ID=oculox-portal
KEYCLOAK_PORTAL_CLIENT_ID=oculox-portal
KEYCLOAK_DASHBOARDS_CLIENT_ID=oculox-dashboards
KEYCLOAK_DASHBOARDS_REDIRECT_URI=https://192.168.1.174:5601/dashboards/auth/openid/login
KEYCLOAK_SSL_VERIFY=true
KEYCLOAK_MFA_REQUIRED=true
KEYCLOAK_PROVISIONING_ENABLED=false
```

Explication :

```text
KEYCLOAK_AUTH_REALM
```

Le realm utilisé par Oculox. Ici, c'est `oculox`.

```text
KEYCLOAK_AUTH_URL
```

L'URL publique de Keycloak vue par le navigateur et par les services.

```text
KEYCLOAK_CLIENT_ID
```

Le client utilisé par le portail Oculox. Ici, `oculox-portal`.

```text
KEYCLOAK_DASHBOARDS_CLIENT_ID
```

Le client utilisé par Dashboards. Ici, `oculox-dashboards`.

```text
KEYCLOAK_DASHBOARDS_REDIRECT_URI
```

L'adresse où Keycloak renvoie le navigateur après login Dashboards.

```text
KEYCLOAK_SSL_VERIFY=true
```

Les services doivent vérifier le certificat TLS de Keycloak.

```text
KEYCLOAK_MFA_REQUIRED=true
```

Le second facteur est obligatoire.

```text
KEYCLOAK_PROVISIONING_ENABLED=false
```

Le mode création automatique est désactivé après provisionnement. C'est normal.
On ne laisse pas le mode provisionnement ouvert en permanence.

Commande pour voir ce fichier :

```text
grep -E '^(KEYCLOAK_AUTH_REALM|KEYCLOAK_AUTH_URL|KEYCLOAK_CLIENT_ID|KEYCLOAK_PORTAL_CLIENT_ID|KEYCLOAK_DASHBOARDS_CLIENT_ID|KEYCLOAK_DASHBOARDS_REDIRECT_URI|KEYCLOAK_SSL_VERIFY|KEYCLOAK_MFA_REQUIRED|KEYCLOAK_PROVISIONING_ENABLED)=' config/keycloak.env
```

## 6. `config/auth-common.env`

Fichier :

```text
config/auth-common.env
```

Ce fichier dit à Nginx quelle méthode d'authentification utiliser.

Les lignes importantes sont :

```text
NGINX_AUTH_MODE=keycloak
NGINX_REQUIRE_GROUP=/oculox-users
ROLE_BASED_ACCESS=true
NGINX_KEYCLOAK_BASIC_AUTH=false
```

Explication :

```text
NGINX_AUTH_MODE=keycloak
```

Le portail passe par Keycloak.

```text
NGINX_REQUIRE_GROUP=/oculox-users
```

Pour entrer dans Oculox, l'utilisateur doit appartenir au groupe
`/oculox-users`.

```text
ROLE_BASED_ACCESS=true
```

Les rôles sont pris en compte. Un viewer, un analyste et un admin n'ont pas les
mêmes droits.

```text
NGINX_KEYCLOAK_BASIC_AUTH=false
```

On ne traduit pas automatiquement Keycloak vers Basic pour les utilisateurs
humains.

Commande pour vérifier :

```text
grep -E '^(NGINX_AUTH_MODE|NGINX_REQUIRE_GROUP|ROLE_BASED_ACCESS|NGINX_KEYCLOAK_BASIC_AUTH)=' config/auth-common.env
```

## 7. `config/dashboards.env`

Fichier :

```text
config/dashboards.env
```

La ligne importante est :

```text
DASHBOARDS_AUTH_TYPE=openid
```

Explication :

```text
openid
```

veut dire que Dashboards utilise OIDC, donc Keycloak.

Si cette valeur était :

```text
basicauth
```

Dashboards demanderait un login/mot de passe classique.

Commande pour vérifier :

```text
grep '^DASHBOARDS_AUTH_TYPE=' config/dashboards.env
```

## 8. `config/postgres.env`

Fichier :

```text
config/postgres.env
```

Keycloak utilise PostgreSQL pour stocker :

```text
realms
clients
utilisateurs
groupes
rôles
sessions
événements
```

Les lignes Keycloak sont :

```text
POSTGRES_KEYCLOAK_DB=keycloak
POSTGRES_KEYCLOAK_USER=keycloak
POSTGRES_KEYCLOAK_PASSWORD=...
```

Explication :

```text
POSTGRES_KEYCLOAK_DB
```

Nom de la base Keycloak.

```text
POSTGRES_KEYCLOAK_USER
```

Utilisateur PostgreSQL utilisé par Keycloak.

```text
POSTGRES_KEYCLOAK_PASSWORD
```

Mot de passe PostgreSQL de Keycloak.

Ce mot de passe n'est pas un mot de passe utilisateur navigateur. C'est un
secret technique entre Keycloak et PostgreSQL.

Commande pour vérifier sans afficher le mot de passe :

```text
grep -E '^(POSTGRES_KEYCLOAK_DB|POSTGRES_KEYCLOAK_USER)=' config/postgres.env
```

## 9. `docker-compose.yml`

Fichier :

```text
docker-compose.yml
```

La section Keycloak déclare le conteneur :

```text
service: keycloak
image: ghcr.io/idaholab/malcolm/keycloak:26.07.1
hostname: keycloak
command: /opt/keycloak/bin/kc.sh start
```

Elle charge plusieurs fichiers `.env` :

```text
config/process.env
config/ssl.env
config/auth-common.env
config/postgres.env
config/keycloak.env
```

En simple :

```text
Docker démarre Keycloak avec les variables de configuration Oculox.
```

Commande pour voir l'état :

```text
./oculox status
```

Commande ciblée :

```text
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep keycloak
```

## 10. `keycloak/scripts/docker-entrypoint.sh`

Fichier :

```text
keycloak/scripts/docker-entrypoint.sh
```

Ce script est lancé au démarrage du conteneur Keycloak.

Il sert surtout à préparer la connexion PostgreSQL :

```text
KC_DB=postgres
KC_DB_USERNAME=keycloak
KC_DB_PASSWORD=<mot de passe postgres>
KC_DB_URL=jdbc:postgresql://postgres:5432/keycloak
```

En simple :

```text
Avant de lancer Keycloak, le script lui dit où est sa base de données.
```

## 11. `keycloak/scripts/hardening-preflight.sh`

Fichier :

```text
keycloak/scripts/hardening-preflight.sh
```

Ce script vérifie que la configuration est assez sûre avant de provisionner ou
d'activer Keycloak.

Il vérifie notamment :

```text
realm oculox présent
realm différent de master
URL Keycloak en HTTPS
KC_HOSTNAME cohérent avec KEYCLOAK_AUTH_URL
vérification TLS activée
MFA activé
secrets clients assez longs
pas de wildcard dans les redirect URI
RBAC activé
durées de tokens correctes
```

En simple :

```text
Il empêche de démarrer une configuration Keycloak trop faible ou incohérente.
```

Commande de contrôle :

```text
./oculox keycloak verify-hardening
```

## 12. `keycloak/scripts/realm-setup.sh`

Fichier :

```text
keycloak/scripts/realm-setup.sh
```

C'est le script qui crée réellement les objets dans Keycloak.

Il crée le realm :

```text
oculox
```

Il applique les politiques de sécurité :

```text
mot de passe minimum 14 caractères
majuscule obligatoire
minuscule obligatoire
chiffre obligatoire
caractère spécial obligatoire
historique de mots de passe
protection brute force
durée courte des access tokens
rotation des refresh tokens
événements activés
événements admin activés
MFA TOTP activé
```

Il crée les groupes :

```text
oculox-users
oculox-admins
oculox-analysts
oculox-viewers
oculox-incident-response
```

Il crée les clients :

```text
oculox-portal
oculox-dashboards
```

Il crée les utilisateurs operationnels de demonstration :

```text
oculox-admin
oculox-analyst
oculox-viewer
oculox-incident-response
oculox-denied
```

En simple :

```text
realm-setup.sh construit le modèle d'identité Oculox dans Keycloak.
```

## 13. Les Groupes Et Les Rôles

Les groupes sont des équipes ou profils d'utilisateurs.

Les rôles sont des permissions.

Dans notre modèle :

```text
oculox-users
```

est le groupe minimum pour entrer dans Oculox.

```text
oculox-admins
```

donne le rôle admin.

```text
oculox-analysts
```

donne des droits d'analyste.

```text
oculox-viewers
```

donne des droits de lecture.

```text
oculox-incident-response
```

donne des droits utiles pour l'investigation et les PCAP.

Les rôles sont configurés dans :

```text
config/auth-common.env
```

Exemples :

```text
ROLE_ADMIN=admin
ROLE_READ_ACCESS=read_access
ROLE_READ_WRITE_ACCESS=read_write_access
ROLE_DASHBOARDS_READ_ACCESS=dashboards_read_access
ROLE_DASHBOARDS_READ_WRITE_ACCESS=dashboards_read_write_access
ROLE_ARKIME_READ_ACCESS=arkime_read_access
ROLE_ARKIME_PCAP_ACCESS=arkime_pcap_access
ROLE_ARKIME_HUNT_ACCESS=arkime_hunt_access
```

Matrice actuelle :

| Compte | Groupe Keycloak | Rôles reçus | Ce que cela veut dire |
| --- | --- | --- | --- |
| `oculox-admin` | `oculox-users`, `oculox-admins` | `admin` | Accès administrateur Oculox et Dashboards. |
| `oculox-analyst` | `oculox-users`, `oculox-analysts` | `read_write_access`, `dashboards_read_write_access`, `arkime_hunt_access` | Peut analyser, chercher, créer ou modifier les objets nécessaires au travail d'analyste. |
| `oculox-viewer` | `oculox-users`, `oculox-viewers` | `read_access`, `dashboards_read_access`, `arkime_read_access` | Peut consulter sans modifier. |
| `oculox-incident-response` | `oculox-users`, `oculox-incident-response` | `read_access`, `dashboards_read_access`, `arkime_pcap_access`, `arkime_hunt_access` | Peut consulter Dashboards et travailler sur les investigations Arkime/PCAP. |
| `oculox-denied` | aucun groupe | aucun rôle | Compte de refus contrôlé : il doit être bloqué par le portail. |
| `oculox-keycloak-admin` | realm `master` | `admin` Keycloak | Administre Keycloak lui-même, pas un profil utilisateur Oculox normal. |

Le groupe `oculox-users` est volontairement séparé des rôles métier. Il sert
de ticket d'entrée global dans le portail. Ensuite les groupes métier donnent
les permissions fines.

En simple :

```text
Keycloak dit : cet utilisateur appartient à tel groupe.
Oculox traduit cela en droits concrets.
```

## 14. Le Portail Oculox Avec Nginx

Le portail passe par Nginx.

Le fichier qui active l'authentification Keycloak côté Nginx est :

```text
nginx/nginx_auth_keycloak.conf
```

Il utilise :

```text
KEYCLOAK_AUTH_URL
KEYCLOAK_AUTH_REALM
KEYCLOAK_CLIENT_ID
KEYCLOAK_CLIENT_SECRET
KEYCLOAK_AUTH_REDIRECT_URI
KEYCLOAK_SSL_VERIFY
```

Le chemin est :

```text
navigateur
 -> Nginx
 -> Keycloak
 -> Nginx
 -> service Oculox demandé
```

Si l'utilisateur n'est pas connecté, Nginx le redirige vers Keycloak.

Après connexion, Nginx reçoit les informations utilisateur et vérifie :

```text
groupe /oculox-users présent
rôles autorisés
session valide
```

## 15. Les Headers Nginx

Fichier :

```text
nginx/lua/nginx_auth_helpers.lua
```

Après authentification, Nginx peut transmettre aux services :

```text
X-Forwarded-User
X-Forwarded-Groups
X-Forwarded-Roles
```

Exemple :

```text
X-Forwarded-User: oculox-admin
X-Forwarded-Groups: /oculox-users,/oculox-admins
X-Forwarded-Roles: admin
```

Mais avant de les mettre, Nginx supprime les anciens headers fournis par le
navigateur.

Pourquoi ?

Parce qu'un attaquant pourrait essayer d'envoyer lui-même :

```text
X-Forwarded-Roles: admin
```

La configuration actuelle nettoie ces headers avant de reconstruire l'identité
à partir du token Keycloak.

En simple :

```text
On ne croit pas ce que le navigateur prétend.
On croit uniquement ce que Keycloak a signé.
```

## 16. La Route `/keycloak`

Fichier :

```text
nginx/nginx_keycloak_location.conf
```

Cette configuration expose Keycloak derrière Nginx :

```text
https://192.168.1.174/keycloak
```

Il y a aussi une protection sur :

```text
/keycloak/admin
```

Cette partie est limitée aux réseaux privés :

```text
127.0.0.1
10.0.0.0/8
172.16.0.0/12
192.168.0.0/16
```

En simple :

```text
L'interface admin Keycloak ne doit pas être exposée à n'importe qui.
```

## 17. OpenSearch Dashboards

Dashboards est une application à part.

Adresse :

```text
https://192.168.1.174:5601/dashboards/
```

Dashboards a deux relations différentes :

```text
utilisateur humain -> Dashboards
Dashboards -> OpenSearch
```

Pour :

```text
utilisateur humain -> Dashboards
```

on utilise Keycloak.

Pour :

```text
Dashboards -> OpenSearch
```

Dashboards utilise un compte technique OpenSearch.

Il ne faut pas confondre les deux.

## 18. `dashboards/opensearch_dashboards.yml`

Fichier :

```text
dashboards/opensearch_dashboards.yml
```

Il contient :

```text
server.basePath=/dashboards
opensearch.hosts=${OPENSEARCH_URL}
opensearch_security.auth.type=<type auth>
```

Quand Dashboards est en mode Keycloak, le type auth devient :

```text
openid
```

Les placeholders sont remplacés au démarrage :

```text
_MALCOLM_DASHBOARDS_AUTH_TYPE_
_MALCOLM_DASHBOARDS_OPENSEARCH_USER_
_MALCOLM_DASHBOARDS_OPENSEARCH_PASSWORD_
```

En simple :

```text
Le fichier source est un modèle.
Le conteneur génère la vraie configuration au démarrage.
```

## 19. `dashboards/scripts/docker_entrypoint.sh`

Fichier :

```text
dashboards/scripts/docker_entrypoint.sh
```

Ce script prépare la configuration finale de Dashboards.

Il lit :

```text
DASHBOARDS_AUTH_TYPE
KEYCLOAK_AUTH_URL
KEYCLOAK_AUTH_REALM
KEYCLOAK_DASHBOARDS_CLIENT_ID
KEYCLOAK_DASHBOARDS_CLIENT_SECRET
KEYCLOAK_DASHBOARDS_REDIRECT_URI
```

Si :

```text
DASHBOARDS_AUTH_TYPE=openid
```

alors il ajoute :

```text
opensearch_security.openid.connect_url
opensearch_security.openid.client_id
opensearch_security.openid.client_secret
opensearch_security.openid.base_redirect_url
opensearch_security.openid.verify_hostnames
```

En simple :

```text
Ce script dit à Dashboards comment parler à Keycloak.
```

## 20. Le Scénario De Connexion Dashboards

Quand tu ouvres :

```text
https://192.168.1.174:5601/dashboards/
```

le scénario est :

```text
1. Dashboards voit que tu n'as pas de session.
2. Dashboards te redirige vers Keycloak.
3. Tu entres ton login, ton mot de passe et ton MFA.
4. Keycloak renvoie un code temporaire à Dashboards.
5. Dashboards échange ce code contre des tokens.
6. Dashboards vérifie les tokens.
7. OpenSearch vérifie aussi les informations OIDC.
8. Dashboards utilise son compte technique pour fonctionner avec OpenSearch.
9. Tu vois les données selon tes droits.
```

## 21. Pourquoi Le Portail Et Dashboards Ont Deux Clients

Le portail utilise :

```text
oculox-portal
```

Dashboards utilise :

```text
oculox-dashboards
```

Pourquoi ?

Parce que ce sont deux applications différentes.

Elles n'ont pas :

```text
la même URL
la même Redirect URI
le même fonctionnement interne
le même secret
```

Mais elles partagent le même realm :

```text
oculox
```

Donc le SSO reste possible.

En simple :

```text
Même Keycloak, même utilisateur, mais clients séparés.
```

## 22. Les Scripts `dev/scripts/keycloak`

### `configure-realm.py`

Fichier :

```text
dev/scripts/keycloak/configure-realm.py
```

Il prépare `config/keycloak.env` avant le provisionnement.

Il génère ou conserve :

```text
secrets clients
mots de passe de test
URL Keycloak
Redirect URI
mode provisioning
```

Il écrit aussi les identifiants initiaux dans :

```text
dev/generated/keycloak-initial-credentials.env
```

### `configure-portal-auth.py`

Fichier :

```text
dev/scripts/keycloak/configure-portal-auth.py
```

Il active ou désactive Keycloak pour le portail.

Activation :

```text
./oculox keycloak activate-portal
```

Désactivation :

```text
./oculox keycloak deactivate-portal
```

Vérification :

```text
./oculox keycloak verify-portal
```

### `configure-dashboards-oidc.py`

Fichier :

```text
dev/scripts/keycloak/configure-dashboards-oidc.py
```

Il active ou désactive OIDC pour Dashboards.

Activation :

```text
./oculox keycloak activate-dashboards
```

Désactivation :

```text
./oculox keycloak deactivate-dashboards
```

Vérification :

```text
./oculox keycloak verify-dashboards
```

### `verify-functional-hardening.py`

Fichier :

```text
dev/scripts/keycloak/verify-functional-hardening.py
```

Il vérifie le durcissement fonctionnel.

Commande :

```text
./oculox keycloak verify-hardening
```

Il vérifie :

```text
portail en mode Keycloak
RBAC activé
groupe /oculox-users requis
Dashboards en openid
realm oculox
HTTPS
MFA
brute force protection
tokens courts
audit
pas de wildcard
secrets sensibles non suivis par Git
```

## 23. La Commande `./oculox`

Fichier :

```text
oculox
```

Les commandes Keycloak disponibles sont :

```text
./oculox keycloak provision
./oculox keycloak activate-portal
./oculox keycloak activate-dashboards
./oculox keycloak deactivate-portal
./oculox keycloak deactivate-dashboards
./oculox keycloak verify-portal
./oculox keycloak verify-dashboards
./oculox keycloak verify-hardening
./oculox keycloak credentials
./oculox keycloak report
```

En simple :

```text
./oculox est la porte d'entrée propre.
On évite de lancer les scripts internes à la main sauf pour investigation.
```

## 24. Les Identifiants Operationnels De Demonstration

Les utilisateurs créés pour valider les profils sont :

```text
oculox-keycloak-admin
oculox-admin
oculox-analyst
oculox-viewer
oculox-incident-response
oculox-denied
```

Pour afficher leurs mots de passe :

```text
./oculox keycloak credentials
```

Ne copie pas ces mots de passe dans Git ou dans une documentation partagée.

Interprétation :

```text
oculox-keycloak-admin
```

sert à administrer Keycloak lui-même. Il se connecte à l'admin console
Keycloak dans le realm `master`.

Adresse :

```text
https://192.168.1.174/keycloak/admin
```

Ce compte n'est pas un simple utilisateur applicatif Oculox. Il sert à gérer
les realms, clients, groupes, rôles et utilisateurs dans Keycloak.

```text
oculox-admin
```

administre Oculox côté application. Il est dans le realm `oculox`, groupe
`oculox-admins`. Il sert à tester le portail et Dashboards, pas à administrer
Keycloak lui-même.

```text
oculox-analyst
```

doit avoir des droits d'analyse.

```text
oculox-viewer
```

doit avoir des droits lecture.

```text
oculox-incident-response
```

doit avoir des droits utiles pour les investigations.

```text
oculox-denied
```

sert à vérifier le refus. Il ne doit pas entrer normalement dans Oculox, car il
n'a pas le groupe obligatoire.

Point important :

```text
oculox-keycloak-admin  -> admin Keycloak, realm master
oculox-admin           -> admin Oculox, realm oculox
```

Ce sont deux rôles différents.

## 25. Les Comptes Techniques À Ne Pas Utiliser Dans Le Navigateur

Les comptes techniques OpenSearch sont différents des utilisateurs Keycloak.

Exemples :

```text
oculox_logstash
oculox_arkime
oculox_dashboards
oculox_dashboards_helper
oculox_api
```

Ils servent à :

```text
Logstash -> OpenSearch
Arkime -> OpenSearch
Dashboards -> OpenSearch
API -> OpenSearch
```

Ces comptes ne sont pas faits pour ouvrir le portail.

## 26. Comment Vérifier Dans Le Navigateur

Portail Oculox :

```text
https://192.168.1.174/
```

Dashboards :

```text
https://192.168.1.174:5601/dashboards/
```

Admin Keycloak :

```text
https://192.168.1.174/keycloak/admin
```

Dans Keycloak Admin, vérifier :

```text
Realm: oculox
Clients: oculox-portal, oculox-dashboards
Groups: oculox-users, oculox-admins, oculox-analysts, oculox-viewers, oculox-incident-response
Users: oculox-admin, oculox-analyst, oculox-viewer, oculox-incident-response, oculox-denied
Authentication: CONFIGURE_TOTP activé
Realm settings: brute force protection activée
Events: événements activés
```

## 27. Commandes De Vérification Simples

Voir l'état des conteneurs :

```text
./oculox status
```

Voir les identifiants de test :

```text
./oculox keycloak credentials
```

Voir le rapport de provisionnement :

```text
./oculox keycloak report
```

Vérifier le portail :

```text
./oculox keycloak verify-portal
```

Vérifier Dashboards :

```text
./oculox keycloak verify-dashboards
```

Vérifier le durcissement :

```text
./oculox keycloak verify-hardening
```

Vérifier les clients techniques Oculox vers OpenSearch :

```text
./oculox verify clients
```

Vérifier que le portail est en mode Keycloak :

```text
grep '^NGINX_AUTH_MODE=' config/auth-common.env
```

Vérifier que le RBAC est actif :

```text
grep '^ROLE_BASED_ACCESS=' config/auth-common.env
```

Vérifier que Dashboards utilise OIDC :

```text
grep '^DASHBOARDS_AUTH_TYPE=' config/dashboards.env
```

Vérifier l'URL Keycloak :

```text
grep '^KEYCLOAK_AUTH_URL=' config/keycloak.env
```

Vérifier le client Dashboards :

```text
grep '^KEYCLOAK_DASHBOARDS_CLIENT_ID=' config/keycloak.env
```

## 28. Commandes Pour Voir La Configuration Dans Les Conteneurs

Voir les variables Keycloak dans le conteneur Nginx :

```text
docker exec oculox-nginx-proxy-1 env | grep KEYCLOAK
```

Voir le mode d'authentification dans Nginx :

```text
docker exec oculox-nginx-proxy-1 env | grep NGINX_AUTH_MODE
```

Voir les variables Dashboards :

```text
docker exec oculox-dashboards-1 env | grep DASHBOARDS_AUTH_TYPE
```

Voir la configuration finale Dashboards générée dans le conteneur :

```text
docker exec oculox-dashboards-1 grep -n 'openid' /usr/share/opensearch-dashboards/config/opensearch_dashboards.yml
```

Voir si Keycloak répond :

```text
curl -k https://192.168.1.174/keycloak/realms/oculox/.well-known/openid-configuration
```

## 29. Test Simple De Non-Régression Pipeline

Le principe à retenir :

```text
Keycloak peut tomber sans arrêter l'ingestion.
```

Commande de vérification complète déjà utilisée :

```text
./oculox verify ingestion baseline --output dev/generated/keycloak-validation/pipeline-non-regression/baseline-keycloak-up.json
```

Arrêt Keycloak :

```text
docker compose -f dev/generated/docker-compose.runtime.yml --profile malcolm stop keycloak
```

Injection PCAP :

```text
./oculox verify ingestion inject --pcap pcap/processed/mnetsniff-wlo1_1786618984.pcap --run-id k8-keycloak-down-20260909 --output dev/generated/keycloak-validation/pipeline-non-regression/collector-keycloak-down.json --wait 300 --allow-core
```

Finalisation :

```text
./oculox verify ingestion finalize --baseline dev/generated/keycloak-validation/pipeline-non-regression/baseline-keycloak-up.json --collector-report dev/generated/keycloak-validation/pipeline-non-regression/collector-keycloak-down.json --output dev/generated/keycloak-validation/pipeline-non-regression/final-keycloak-down.json
```

Redémarrage Keycloak :

```text
docker compose -f dev/generated/docker-compose.runtime.yml --profile malcolm start keycloak
```

Résultat attendu :

```text
INGESTION_RESULT=PASS
```

## 30. Ce Qui A Été Fait Jusqu'Ici

Les éléments suivants sont en place :

```text
Keycloak embarqué activé sur le Core
realm oculox créé
client oculox-portal créé
client oculox-dashboards créé
groupes Oculox créés
rôles Oculox créés
utilisateurs opérationnels de validation créés
MFA TOTP activé
protection brute force activée
tokens courts configurés
audit Keycloak activé
portail Oculox en mode Keycloak
Dashboards en mode openid
OpenSearch garde les comptes techniques
pipeline industriel indépendant de Keycloak
tests K8 validés
```

## 31. Ce Qui Reste À Faire Plus Tard

Les points encore prévus après K8 sont :

```text
sauvegarde et restauration Keycloak
rotation des secrets clients
rotation des certificats
test complet sur VM neuves
migration future IP vers DNS
documentation d'exploitation finale
```

## 32. Résumé Pour Présentation

Phrase simple :

```text
Keycloak devient l'autorité d'identité des utilisateurs Oculox.
```

Phrase plus complète :

```text
Le portail et Dashboards utilisent OIDC avec Keycloak pour authentifier les
humains. Les groupes Keycloak donnent les rôles Oculox. Les services techniques
gardent leurs comptes limités et leurs certificats. Keycloak n'est pas dans le
pipeline industriel, donc une panne Keycloak ne bloque pas l'ingestion.
```

Phrase technique mais claire :

```text
Oculox sépare l'IAM humain du machine-to-machine : OIDC pour les utilisateurs,
comptes techniques et mTLS pour les services.
```

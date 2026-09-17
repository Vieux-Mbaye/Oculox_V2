# Phase K5 - OIDC Nginx Et Portail

## 1. But

Cette phase prépare le portail Oculox pour utiliser Keycloak comme
authentification principale sur le port HTTPS `443`.

Avant K5, le portail utilise surtout l'authentification Basic : le navigateur
présente un couple utilisateur/mot de passe directement à Nginx. Avec K5,
Nginx redirige l'utilisateur vers Keycloak, Keycloak authentifie l'utilisateur,
puis Nginx reçoit un jeton OIDC et transmet aux services Oculox une identité
propre : utilisateur, groupes et rôles.

OIDC veut dire OpenID Connect. C'est une couche d'identité au-dessus d'OAuth2.
Dans notre cas, cela permet à Oculox de ne plus gérer directement les sessions
humaines : Keycloak devient le fournisseur d'identité.

## 2. Ce Qui A Été Ajouté

### Commandes Oculox

Le fichier `oculox` expose maintenant trois commandes de contrôle :

```text
./oculox keycloak activate-portal
./oculox keycloak deactivate-portal
./oculox keycloak verify-portal
```

`activate-portal` applique le contrat K5 :

```text
NGINX_AUTH_MODE=keycloak
ROLE_BASED_ACCESS=true
NGINX_REQUIRE_GROUP=/oculox-users
KEYCLOAK_CLIENT_ID=oculox-portal
KEYCLOAK_SSL_VERIFY=true
```

`deactivate-portal` remet le portail en Basic sans supprimer le realm
Keycloak, les secrets client ou les utilisateurs.

`verify-portal` vérifie que la configuration locale correspond bien au contrat
K5.

## 3. Fichiers Touchés

| Fichier | Rôle |
| --- | --- |
| `dev/scripts/keycloak/configure-portal-auth.py` | applique, annule ou vérifie la bascule du portail vers Keycloak |
| `oculox` | ajoute les commandes `keycloak activate-portal`, `deactivate-portal` et `verify-portal` |
| `config/auth-common.env.example` | documente `NGINX_KEYCLOAK_BASIC_AUTH=false` comme valeur par défaut |
| `nginx/nginx_auth_keycloak.conf` | durcit le cookie de session OIDC |
| `nginx/lua/nginx_auth_helpers.lua` | nettoie les en-têtes d'identité entrants avant de poser l'identité validée |
| `dev/tests/keycloak/test_portal_oidc_activation.py` | teste le contrat K5 |
| `dev/keycloak/02_plan_developpement_keycloak_oculox.md` | marque K5 comme implémenté côté logiciel |

## 4. Sécurité Des En-Têtes

Un navigateur ou un client HTTP peut essayer d'envoyer lui-même :

```text
X-Forwarded-User
X-Forwarded-Groups
X-Forwarded-Roles
```

Ces en-têtes ne doivent jamais être crus tels quels. Ils doivent venir de Nginx
après authentification. C'est pour cela que `nginx_auth_helpers.lua` les efface
d'abord, puis les reconstruit à partir du jeton Keycloak.

En termes simples : même si quelqu'un envoie `X-Forwarded-Roles: admin` depuis
son navigateur, Nginx supprime cette valeur et remet les vrais rôles lus dans
Keycloak.

## 5. Cookie De Session

`nginx_auth_keycloak.conf` configure maintenant le cookie OIDC avec :

```text
Secure
HttpOnly
SameSite=Lax
```

`Secure` force l'utilisation HTTPS.

`HttpOnly` empêche le JavaScript de lire le cookie.

`SameSite=Lax` limite l'envoi du cookie depuis des navigations externes, tout
en gardant un comportement compatible avec les redirections normales de login.

## 6. Procédure D'Activation

Sur un Core déjà préparé :

```bash
cd ~/ICSHUB/Oculox
./oculox prepare principal --server-name <IP-ou-DNS-du-Core>
./oculox keycloak provision
./oculox keycloak activate-portal
./oculox restart nginx-proxy keycloak
./oculox keycloak verify-portal
```

Ensuite, ouvrir :

```text
https://<IP-ou-DNS-du-Core>/
```

Le navigateur doit arriver sur Keycloak pour la connexion, puis revenir vers le
portail Oculox.

## 7. Retour Arrière

Si la bascule Keycloak pose problème :

```bash
cd ~/ICSHUB/Oculox
./oculox keycloak deactivate-portal
./oculox restart nginx-proxy
```

Cela remet :

```text
NGINX_AUTH_MODE=basic
ROLE_BASED_ACCESS=false
NGINX_REQUIRE_GROUP=
```

Le realm Keycloak reste présent. On peut donc corriger puis réactiver plus
tard.

## 8. Tests Exécutés

Commande :

```bash
python3 -m unittest discover -s Oculox/dev/tests/keycloak -p 'test_*.py'
```

Résultat :

```text
Ran 32 tests
OK
```

Les tests couvrent K0 à K5 :

- durcissement avant activation ;
- identité publique portable ;
- PKI web de développement ;
- provisionnement Keycloak ;
- modèle IAM et RBAC ;
- activation du portail ;
- refus d'activation si le realm n'est pas validé ;
- retour arrière vers Basic ;
- présence des protections cookie et en-têtes.

## 9. Ce Que K5 Ne Fait Pas Encore

K5 active le portail Oculox via Keycloak.

K5 ne configure pas encore OpenSearch Dashboards en OIDC natif. Pour
Dashboards, il reste encore une étape dédiée : K6. K6 devra connecter
Dashboards et OpenSearch Security à Keycloak, tout en conservant les comptes
techniques pour Logstash, Arkime, API et les scripts.

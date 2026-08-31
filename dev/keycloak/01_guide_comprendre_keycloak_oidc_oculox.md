# Comprendre Et Intégrer Keycloak Dans Oculox

## 1. Objectif Du Guide

Ce document explique Keycloak depuis les bases, puis décrit comment il doit
devenir la méthode principale d'authentification des utilisateurs Oculox.

L'objectif n'est pas de faire intervenir Keycloak partout. La séparation cible
est la suivante :

```text
Personnes utilisant les interfaces Oculox  -> Keycloak et OIDC
Machines transportant les événements       -> certificats et comptes de service
```

Cette séparation est importante. Une panne Keycloak doit empêcher une nouvelle
connexion humaine, mais elle ne doit pas arrêter la collecte, Logstash, Arkime
ou l'indexation OpenSearch.

## 2. Les Notions De Base

### 2.1 Identité

Une identité représente une personne ou une machine connue du système.

Exemples d'identités humaines :

```text
aminata.diallo
moussa.ndiaye
admin.oculox
```

Exemples d'identités techniques :

```text
oculox_logstash
oculox_arkime
oculox_dashboards
oculox_api
```

Une identité humaine ne doit pas être partagée. Une identité technique ne doit
pas être utilisée dans un navigateur.

### 2.2 Authentification Et Autorisation

L'authentification répond à la question :

```text
Qui êtes-vous ?
```

Exemple : Keycloak vérifie le mot de passe et le second facteur d'Aminata.

L'autorisation répond à une autre question :

```text
Qu'avez-vous le droit de faire ?
```

Exemple : Aminata peut consulter Dashboards, mais ne peut pas supprimer un
index OpenSearch.

Une connexion réussie ne doit donc pas automatiquement donner tous les droits.

### 2.3 Keycloak

Keycloak est un gestionnaire central d'identités et d'accès. Il conserve ou
fédère les comptes humains, vérifie leur authentification et fournit aux
applications une preuve signée de leur identité.

Dans Oculox, Keycloak doit gérer :

- les utilisateurs humains ;
- les groupes ;
- les rôles ;
- les sessions ;
- les politiques de mot de passe ;
- le MFA ;
- les événements de connexion et d'administration.

Keycloak ne stocke pas le trafic industriel et ne remplace ni OpenSearch, ni
Logstash, ni la PKI.

### 2.4 SSO

SSO signifie **Single Sign-On**, ou authentification unique.

Sans SSO, un utilisateur peut devoir saisir un mot de passe pour le portail,
un autre pour Dashboards et encore un autre pour Arkime.

Avec le SSO, l'utilisateur s'authentifie une fois auprès de Keycloak. Lorsqu'il
ouvre ensuite une autre application Oculox, celle-ci demande à Keycloak si une
session existe déjà. Si la session est valide, Keycloak renvoie immédiatement
l'utilisateur vers l'application sans redemander son mot de passe.

SSO ne veut pas dire que toutes les applications partagent un même mot de
passe. Elles font confiance à une même autorité d'identité : Keycloak.

### 2.5 OIDC

OIDC signifie **OpenID Connect**. C'est le protocole utilisé entre une
application et Keycloak pour authentifier une personne.

OIDC est construit au-dessus d'OAuth 2.0 :

- OAuth 2.0 traite principalement de l'autorisation d'accès ;
- OIDC ajoute une identité vérifiable de l'utilisateur.

Dans Oculox, le scénario navigateur recommandé est le flux OIDC
**Authorization Code** :

```text
1. L'utilisateur ouvre Oculox.
2. Oculox ne trouve pas de session locale.
3. Le navigateur est redirigé vers Keycloak.
4. Keycloak vérifie l'utilisateur et son MFA.
5. Keycloak renvoie un code temporaire à Oculox.
6. Oculox échange ce code contre des jetons signés.
7. Oculox crée une session et autorise les fonctions permises.
```

Le code temporaire ne peut être utilisé qu'une fois. Le mot de passe est saisi
sur la page Keycloak et n'est pas transmis aux applications Oculox.

### 2.6 Jetons OIDC

Après une authentification réussie, Keycloak produit généralement trois types
de jetons :

| Jeton | Rôle |
| --- | --- |
| ID Token | décrit l'utilisateur authentifié |
| Access Token | permet d'appeler les ressources autorisées |
| Refresh Token | permet d'obtenir un nouvel Access Token sans redemander immédiatement le mot de passe |

Les jetons sont signés par Keycloak. Une application peut vérifier la signature
avec la clé publique de Keycloak et détecter toute modification.

Un jeton peut contenir des **claims**, c'est-à-dire des informations déclarées
par Keycloak :

```json
{
  "preferred_username": "aminata.diallo",
  "groups": ["/oculox-users", "/oculox-analysts"],
  "realm_access": {
    "roles": [
      "read_write_access",
      "dashboards_read_write_access",
      "arkime_hunt_access"
    ]
  }
}
```

Ce JSON est un exemple pédagogique, pas un jeton utilisable.

### 2.7 JWT

Les jetons OIDC sont souvent au format JWT, **JSON Web Token**. Un JWT contient
trois parties :

```text
en-tête.contenu.signature
```

Le contenu n'est généralement pas secret : il est encodé, pas chiffré. La
signature garantit son origine et son intégrité. Il ne faut donc jamais placer
de mot de passe dans un jeton.

### 2.8 Realm

Un realm est un espace d'identités isolé dans Keycloak. Il contient ses propres
utilisateurs, groupes, rôles, clients, sessions et politiques.

La cible Oculox est :

```text
realm master  -> administration technique de Keycloak
realm oculox  -> utilisateurs et applications Oculox
```

Les utilisateurs opérationnels ne doivent pas être gérés durablement dans
`master`.

### 2.9 Client OIDC

Dans Keycloak, un client représente une application qui demande une
authentification.

La cible comprend au moins deux clients :

```text
oculox-portal      -> portail, Arkime, NetBox, Upload et API derrière Nginx
oculox-dashboards  -> OpenSearch Dashboards
```

Deux clients permettent de séparer leurs secrets, leurs sessions techniques et
leurs URI de redirection tout en conservant le SSO utilisateur.

### 2.10 Client ID Et Client Secret

Le Client ID est le nom public d'un client, par exemple `oculox-portal`.

Le Client Secret est un secret partagé entre Keycloak et l'application. Il
permet à une application serveur de prouver son identité lorsqu'elle échange
un code temporaire contre des jetons.

Le secret ne doit jamais être placé dans Git, dans une capture d'écran ou dans
un rapport. Les deux clients OIDC ne doivent pas utiliser le même secret.

### 2.11 URI De Redirection

Après l'authentification, Keycloak doit savoir vers quelle adresse renvoyer le
navigateur. Cette adresse est l'URI de redirection.

Elle doit être déclarée précisément, par exemple :

```text
https://oculox.tcric.hq/index.html
https://oculox.tcric.hq/dashboards/auth/openid/login
```

Une valeur générale comme `https://oculox.tcric.hq/*` augmente les possibilités
de détournement. En production, seules les URI réellement nécessaires doivent
être autorisées.

### 2.12 Issuer, Audience Et JWKS

L'**issuer** identifie le realm qui a émis le jeton :

```text
https://oculox.tcric.hq/keycloak/realms/oculox
```

L'**audience** indique à quelle application le jeton est destiné. Une
application ne doit pas accepter un jeton émis pour un autre client.

JWKS est l'endpoint qui publie les clés publiques utilisées pour vérifier les
signatures des jetons. OpenSearch peut récupérer ces clés et les mettre en
cache.

Le document de découverte OIDC fournit automatiquement les endpoints utiles :

```text
https://oculox.tcric.hq/keycloak/realms/oculox/.well-known/openid-configuration
```

### 2.13 Groupes, Rôles Et RBAC

Un groupe rassemble des utilisateurs ayant une fonction commune. Un rôle
représente une permission ou un niveau d'accès.

RBAC signifie **Role-Based Access Control**, contrôle d'accès basé sur les
rôles.

La bonne méthode consiste à attribuer les rôles aux groupes, puis les
utilisateurs aux groupes :

```text
aminata.diallo
      |
      v
/oculox-analysts
      |
      +-- read_write_access
      +-- dashboards_read_write_access
      `-- arkime_hunt_access
```

Cela évite d'administrer une longue liste de permissions pour chaque personne.

### 2.14 MFA

MFA signifie **Multi-Factor Authentication**. L'utilisateur doit fournir au
moins deux preuves différentes, par exemple :

```text
un mot de passe + un code TOTP
```

Le MFA doit être obligatoire pour les administrateurs. Son extension aux
analystes doit être prévue après validation de la procédure de récupération.

## 3. Authentification Actuelle D'Oculox

La configuration actuelle utilise :

```text
NGINX_AUTH_MODE=basic
ROLE_BASED_ACCESS=false
```

Ces valeurs se trouvent dans `config/auth-common.env`.

Le fonctionnement actuel est :

```text
Navigateur
    |
    | HTTPS + identifiant/mot de passe Basic
    v
Nginx
    |
    | vérification dans nginx/htpasswd
    v
Services Oculox
```

En mode Basic, Nginx transmet pratiquement le rôle administrateur à chaque
utilisateur authentifié. Les rôles détaillés existent dans la configuration,
mais `ROLE_BASED_ACCESS=false` empêche leur utilisation normale.

Dashboards constitue actuellement un chemin particulier :

```text
Navigateur -> Nginx :5601 -> Dashboards -> OpenSearch distant
```

Dashboards demande actuellement une authentification OpenSearch Basic. Le
compte humain utilisé pour Dashboards n'est donc pas encore une identité
Keycloak.

## 4. Ce Qui Est Déjà Embarqué

Oculox contient déjà les composants nécessaires à une première intégration :

| Composant | Fonction |
| --- | --- |
| service Docker `keycloak` | serveur d'identité |
| PostgreSQL | persistance du realm, des utilisateurs et des sessions |
| Nginx `/keycloak` | point d'entrée HTTPS vers Keycloak |
| `lua-resty-openidc` | client OIDC utilisé par Nginx |
| `realm-setup.sh` | création initiale des rôles et du client |
| `auth_setup` | sélection de la méthode d'authentification |
| `nginx_auth_helpers.lua` | extraction et contrôle des groupes et rôles |

Les principaux fichiers sont :

| Fichier | Rôle |
| --- | --- |
| `docker-compose.yml` | définit Keycloak, PostgreSQL et Nginx |
| `config/auth-common.env` | choisit Basic ou Keycloak et déclare les rôles |
| `config/keycloak.env` | configure realm, URL, client et paramètres serveur |
| `keycloak/scripts/docker-entrypoint.sh` | relie Keycloak à PostgreSQL |
| `keycloak/scripts/realm-setup.sh` | initialise realm, rôles, client et claims |
| `nginx/nginx_auth_keycloak.conf` | exécute le flux OIDC navigateur |
| `nginx/lua/nginx_auth_helpers.lua` | applique le RBAC aux chemins Oculox |
| `dashboards/opensearch_dashboards.yml` | configure l'authentification Dashboards |
| `dev/config/opensearch-cluster/security/config.yml` | configure les domaines d'authentification OpenSearch |
| `dev/config/opensearch-cluster/security/roles_mapping.yml` | associe les rôles externes aux permissions OpenSearch |

Keycloak est donc présent dans le produit, mais il n'est pas encore l'autorité
active des utilisateurs Oculox.

## 5. Problème À Résoudre

L'authentification humaine est actuellement fragmentée :

```text
Portail Oculox       -> compte Basic Oculox
Dashboards           -> compte OpenSearch
OpenSearch technique -> comptes de service
```

Cette situation entraîne :

- plusieurs écrans de connexion ;
- plusieurs emplacements pour gérer les comptes ;
- une désactivation utilisateur difficile à garantir partout ;
- l'absence de MFA centralisé ;
- peu de séparation entre administrateur et lecteur ;
- le risque qu'un compte technique soit utilisé dans un navigateur ;
- des événements d'authentification dispersés.

## 6. Architecture Cible

### 6.1 Plan Des Identités Humaines

```text
Utilisateur SOC
      |
      | HTTPS
      v
Nginx Oculox
      |
      | OIDC Authorization Code
      v
Keycloak embarqué
      |
      +-- comptes humains
      +-- groupes
      +-- rôles
      +-- MFA
      +-- sessions
      `-- événements
      |
      v
Arkime, NetBox, Upload, API et portail
```

Nginx reçoit les claims du jeton et fournit aux applications des en-têtes
contrôlés :

```text
X-Forwarded-User
X-Forwarded-Groups
X-Forwarded-Roles
```

Les applications ne doivent accepter ces en-têtes que depuis Nginx. Un client
extérieur ne doit jamais pouvoir les imposer directement.

### 6.2 Chemin Dashboards Et OpenSearch

Dashboards doit utiliser son propre client OIDC :

```text
Navigateur
    |
    v
Dashboards
    |
    | redirection OIDC
    v
Keycloak
    |
    | jeton signé contenant les rôles
    v
Dashboards
    |
    | Authorization: Bearer <jeton>
    v
Cluster OpenSearch
    |
    | validation signature, issuer, audience et rôles
    v
Index autorisés
```

Même avec deux clients OIDC, l'utilisateur conserve une seule session SSO
Keycloak et ne doit normalement pas ressaisir son mot de passe.

### 6.3 Plan Des Données Et Des Machines

```text
Trafic industriel
      |
      v
Hedgehog
      |
      | mTLS
      v
Logstash 1 et Logstash 2
      |
      | HTTPS + compte oculox_logstash
      v
OpenSearch
```

Keycloak n'intervient pas dans ce chemin.

Les identités techniques restent séparées :

| Communication | Authentification conservée |
| --- | --- |
| Filebeat vers Logstash | mTLS Beats |
| Logstash vers OpenSearch | compte de service limité |
| Arkime vers OpenSearch | compte de service limité |
| Dashboards serveur vers OpenSearch | compte interne Dashboards |
| API vers OpenSearch | compte de lecture limité |
| administration cluster | compte ou certificat administrateur |

Ainsi, une panne Keycloak ne doit pas interrompre l'ingestion.

## 7. Coexistence Basic Et OIDC Dans OpenSearch

OpenSearch devra accepter deux domaines d'authentification HTTP :

```text
Basic -> comptes techniques Oculox
OIDC  -> utilisateurs humains Keycloak
```

Le domaine Basic ne doit pas être supprimé. Logstash et les autres services ne
sont pas des personnes et n'ont pas besoin d'une session SSO.

Le domaine OIDC devra vérifier au minimum :

- la signature du jeton ;
- l'issuer du realm `oculox` ;
- l'audience du client Dashboards ;
- la date d'expiration ;
- le nom d'utilisateur ;
- les rôles présents dans le jeton.

OpenSearch récupérera les clés publiques via l'endpoint JWKS de Keycloak. Le
cache JWKS doit être activé afin d'éviter une requête Keycloak pour chaque
validation et de mieux supporter une interruption courte de l'IdP.

## 8. Modèle D'Accès Proposé

### 8.1 Groupes

| Groupe | Fonction |
| --- | --- |
| `/oculox-users` | autorisation minimale d'entrer dans Oculox |
| `/oculox-admins` | administration de la plateforme |
| `/oculox-analysts` | investigation et traitement des alertes |
| `/oculox-viewers` | consultation uniquement |
| `/oculox-incident-response` | accès PCAP et recherches Hunt |

### 8.2 Rôles

| Groupe | Rôles initiaux proposés |
| --- | --- |
| `/oculox-admins` | `admin` |
| `/oculox-analysts` | `read_write_access`, `dashboards_read_write_access`, `arkime_hunt_access` |
| `/oculox-viewers` | `read_access`, `dashboards_read_access`, `arkime_read_access` |
| `/oculox-incident-response` | `arkime_pcap_access`, `arkime_hunt_access` |

Le droit de consulter ou d'exporter des PCAP doit être séparé du simple droit
de lecture. Les PCAP peuvent contenir des données sensibles ou des charges
utiles applicatives.

La matrice définitive doit être validée avec les responsables SOC, OT et
protection des données avant son application.

## 9. Ce Que Keycloak Apportera

Une intégration complète fournira :

- un compte nominatif par utilisateur ;
- le SSO entre les interfaces compatibles ;
- une désactivation centralisée ;
- des groupes et rôles cohérents ;
- le MFA ;
- des politiques de mot de passe ;
- des sessions limitées et révocables ;
- une déconnexion globale ;
- des événements de connexion et d'administration ;
- une future fédération LDAP ou Active Directory ;
- une séparation nette entre personnes et machines.

Keycloak ne fournira pas :

- les certificats HTTPS du Core ;
- la PKI OpenSearch ;
- le mTLS Filebeat-Logstash ;
- la réplication OpenSearch ;
- la collecte du trafic ;
- le load balancing ;
- la sauvegarde des événements industriels.

## 10. Points À Corriger Avant Activation

### 10.1 Realm De Bootstrap

Le script actuel tente de se connecter au realm demandé avant de le créer. Pour
un nouveau realm `oculox`, l'ordre correct est :

```text
connexion bootstrap dans master
création du realm oculox
configuration du realm oculox
```

Le script doit être rendu idempotent : une deuxième exécution ne doit ni
dupliquer les objets ni changer les secrets sans demande explicite.

### 10.2 URI De Redirection Trop Large

Le script actuel autorise un motif général `/*`. La configuration de production
doit utiliser les URI HTTPS exactes du portail et de Dashboards.

### 10.3 Direct Access Grant

Le client actuel active `directAccessGrantsEnabled`. Ce mécanisme demande à une
application de recevoir directement le mot de passe utilisateur pour demander
un jeton.

La documentation Keycloak actuelle déconseille ce flux. La cible navigateur
utilisera Authorization Code. Les appels machine conserveront leurs comptes de
service, ou utiliseront Client Credentials uniquement lorsqu'un service le
supporte réellement.

### 10.4 Adresse Et Certificat Stables

L'URL Keycloak devient l'issuer écrit dans les jetons. Une adresse qui change
après l'installation invalide la configuration des clients.

La production doit donc utiliser une URL stable, par exemple :

```text
https://oculox.tcric.hq/keycloak
```

Le certificat HTTPS doit être reconnu par les navigateurs, Dashboards et les
nœuds OpenSearch. Une IP et un certificat de laboratoire permettent les tests,
mais ne constituent pas une identité de production durable.

### 10.5 Paramètres De Proxy

Keycloak est placé derrière Nginx. Nginx termine HTTPS et communique avec
Keycloak sur le réseau Docker privé.

Keycloak doit :

- connaître son URL publique exacte ;
- accepter uniquement les en-têtes proxy provenant du proxy de confiance ;
- interpréter correctement `X-Forwarded-Proto`, `Host` et le chemin
  `/keycloak` ;
- ne pas exposer directement son port `8080` sur l'hôte.

### 10.6 Configuration OpenSearch Incomplète Pour Les Humains

Le cluster distant possède actuellement un domaine Basic et des mappings pour
les comptes techniques. Il faut ajouter :

- le domaine OIDC ;
- la CA utilisée par l'URL Keycloak ;
- la validation issuer et audience ;
- les mappings des rôles humains Keycloak vers les rôles OpenSearch ;
- des tests positifs et négatifs pour chaque profil.

## 11. Plan De Mise En Œuvre

### Étape 1 - Baseline Et Retour Arrière

Objectif : pouvoir revenir au mode Basic en cas de problème.

Travaux :

- exporter la configuration actuelle ;
- sauvegarder PostgreSQL ;
- sauvegarder `auth-common.env`, `keycloak.env` et `htpasswd` ;
- inventorier tous les chemins web et API ;
- enregistrer les tests fonctionnels actuels ;
- définir un compte d'urgence limité au réseau d'administration.

Preuve attendue : le retour temporaire à `NGINX_AUTH_MODE=basic` est documenté
et testé.

### Étape 2 - URL, HTTPS, Réseau Et Temps

Objectif : fournir une identité stable à Keycloak.

Travaux :

- créer un nom DNS stable ;
- installer un certificat HTTPS reconnu ;
- configurer l'URL publique Keycloak ;
- limiter l'accès aux interfaces d'administration ;
- autoriser le cluster OpenSearch à joindre les endpoints OIDC et JWKS ;
- synchroniser toutes les machines avec NTP.

Preuve attendue : navigateur, Nginx, Dashboards et OpenSearch valident le même
issuer HTTPS sans désactiver TLS.

### Étape 3 - Initialisation Reproductible

Objectif : créer le realm et les clients sans opération manuelle fragile.

Travaux :

1. démarrer PostgreSQL ;
2. démarrer Keycloak ;
3. créer l'administrateur bootstrap dans `master` ;
4. créer le realm `oculox` ;
5. créer les rôles et groupes ;
6. créer `oculox-portal` ;
7. créer `oculox-dashboards` ;
8. créer un administrateur permanent nominatif ;
9. tester ce compte ;
10. retirer les identifiants bootstrap de la configuration runtime.

Preuve attendue : une deuxième exécution ne crée aucun doublon et ne remplace
aucun secret existant.

### Étape 4 - Durcissement Du Realm

Objectif : rendre l'authentification exploitable en production.

Travaux :

- définir la politique de mot de passe ;
- activer la protection contre les tentatives répétées ;
- définir les durées de jeton et de session ;
- activer le MFA administrateur ;
- configurer la récupération contrôlée ;
- activer les événements de connexion et d'administration ;
- préparer la rotation des clés de signature.

Preuve attendue : un mot de passe faible est refusé, le MFA administrateur est
obligatoire et les échecs sont journalisés.

### Étape 5 - Activation OIDC Du Portail

Objectif : faire de Keycloak l'entrée principale des utilisateurs.

Configuration cible :

```text
NGINX_AUTH_MODE=keycloak
ROLE_BASED_ACCESS=true
NGINX_REQUIRE_GROUP=/oculox-users
KEYCLOAK_AUTH_REALM=oculox
KEYCLOAK_CLIENT_ID=oculox-portal
```

Nginx doit vérifier le jeton, contrôler le groupe commun, appliquer les règles
RBAC par chemin et transmettre une identité nettoyée aux applications.

Preuve attendue : un utilisateur sans `/oculox-users` reçoit `403`, un lecteur
ne peut pas appeler une fonction d'écriture et un administrateur possède les
droits prévus.

### Étape 6 - OIDC Pour Dashboards Et OpenSearch

Objectif : supprimer la deuxième authentification humaine Dashboards.

Travaux :

- configurer le client `oculox-dashboards` ;
- configurer Dashboards en mode `openid` ;
- ajouter le domaine OIDC au plugin Security OpenSearch ;
- conserver le domaine Basic des comptes techniques ;
- installer la CA Keycloak dans Dashboards et OpenSearch ;
- mapper les rôles Keycloak vers les rôles OpenSearch ;
- tester le SSO depuis le portail.

Preuve attendue : l'utilisateur déjà connecté au portail ouvre Dashboards sans
ressaisir son mot de passe et ne voit que les fonctions autorisées.

### Étape 7 - Validation De Chaque Application

Objectif : prouver l'autorisation, pas seulement l'authentification.

Créer quatre comptes de test :

```text
administrateur
analyste
lecteur
utilisateur sans rôle
```

Tester pour chacun :

- le portail ;
- Dashboards ;
- Arkime ;
- la consultation et l'export PCAP ;
- NetBox ;
- Upload ;
- les API ;
- les opérations interdites ;
- la déconnexion globale.

Une opération interdite doit retourner `403 Forbidden`, pas seulement masquer
un bouton dans l'interface.

### Étape 8 - Non-Régression Du Pipeline Industriel

Objectif : garantir que Keycloak reste hors du chemin des événements.

Pendant un arrêt Keycloak volontaire, vérifier que :

- Filebeat publie toujours ;
- les deux Logstash reçoivent toujours ;
- Arkime Capture écrit toujours ;
- OpenSearch indexe toujours ;
- les files persistantes restent opérationnelles ;
- les nouvelles connexions humaines échouent proprement.

Preuve attendue : l'ingestion continue pendant la panne Keycloak.

### Étape 9 - Sauvegarde Et Exploitation

Objectif : rendre la solution administrable dans la durée.

Documenter et tester :

- la sauvegarde PostgreSQL Keycloak ;
- la restauration sur VM neuve ;
- l'export du realm comme complément de sauvegarde ;
- la rotation des secrets clients ;
- la rotation des clés de signature ;
- le renouvellement du certificat HTTPS ;
- l'ajout et la suppression d'utilisateurs ;
- la révocation des sessions ;
- le retour temporaire au mode Basic ;
- la procédure de panne Keycloak.

## 12. Comportement Attendu En Cas De Panne

| Panne | Effet attendu |
| --- | --- |
| Keycloak indisponible | nouvelles connexions humaines impossibles |
| Keycloak indisponible | ingestion Filebeat/Logstash inchangée |
| PostgreSQL Keycloak indisponible | Keycloak ne peut plus garantir les nouvelles sessions |
| Nginx indisponible | interfaces web indisponibles, OpenSearch distant toujours actif |
| OpenSearch indisponible | authentification Keycloak possible, données Oculox indisponibles |
| expiration d'un jeton | renouvellement via Refresh Token ou nouvelle connexion |
| suppression d'un utilisateur | ses futures authentifications sont refusées et ses sessions doivent être révoquées |

Le cache JWKS OpenSearch permet de conserver temporairement les clés publiques
déjà récupérées, mais il ne transforme pas une instance Keycloak unique en
service hautement disponible.

## 13. Limites De Keycloak Embarqué

Une instance Keycloak et un PostgreSQL sur la VM Core conviennent au
laboratoire et à une première intégration.

Ce déploiement ne résiste pas à la perte complète du Core. Pour une production
exigeant de nouvelles authentifications en permanence, une évolution devra
prévoir :

- plusieurs instances Keycloak ;
- une base PostgreSQL protégée ;
- ou un Keycloak central déjà exploité par l'organisation.

Cette évolution ne change pas le modèle OIDC des applications. Elle change
uniquement la disponibilité de l'autorité d'identité.

## 14. Résumé À Présenter

> Keycloak sera l'autorité centrale des utilisateurs Oculox. Le navigateur sera
> redirigé vers Keycloak avec le protocole OpenID Connect. Après vérification du
> mot de passe et du MFA, Keycloak émettra des jetons signés contenant le nom,
> les groupes et les rôles de l'utilisateur. Nginx, Dashboards et OpenSearch
> vérifieront ces informations pour autoriser chaque fonction. Les collecteurs,
> Logstash, Arkime et les autres services conserveront leurs certificats et
> comptes techniques afin que l'ingestion continue même si Keycloak est en
> panne.

## 15. Documentation Officielle De Référence

- [Keycloak - OpenID Connect](https://www.keycloak.org/securing-apps/oidc-layers)
- [Keycloak - Administration du serveur](https://www.keycloak.org/docs/latest/server_admin/)
- [Keycloak - Configuration derrière un reverse proxy](https://www.keycloak.org/server/reverseproxy)
- [Keycloak - Configuration du hostname](https://www.keycloak.org/server/hostname)
- [Keycloak - Configuration de production](https://www.keycloak.org/server/configuration-production)
- [OpenSearch - Authentification OpenID Connect](https://docs.opensearch.org/latest/security/authentication-backends/openid-connect/)

# Durcissement Keycloak Avant Activation

## 1. Objectif Et État Réel

Ce travail sécurise le chemin qui servira plus tard à activer Keycloak. Il ne
change pas encore l'authentification du Core : `NGINX_AUTH_MODE=basic` reste la
valeur par défaut et la configuration locale active n'a pas été basculée.

Le principe est « refuser de démarrer plutôt que démarrer faiblement ». Quand
le mode `keycloak` sera demandé, un contrôle vérifie les paramètres critiques
avant que Keycloak puisse démarrer. Une erreur explicite est écrite dans les
journaux sans afficher les secrets.

## 2. Défaut Corrigé Dans Le Bootstrap

L'ancien script attendait l'URL du realm configuré puis essayait de connecter
l'administrateur temporaire à ce même realm. Avec un realm neuf nommé
`oculox`, cela formait un cercle impossible : le script attendait `oculox`
avant de pouvoir le créer.

Le nouveau déroulement est :

```text
1. Keycloak démarre avec l'administrateur temporaire.
2. Le script attend le realm système master, qui existe déjà.
3. kcadm.sh s'authentifie dans master.
4. Le script crée le realm oculox s'il est absent.
5. Il applique la politique de sécurité du realm.
6. Il crée ou met à jour le client OIDC et ses mappers.
```

`master` sert uniquement à administrer Keycloak. Les utilisateurs Oculox,
leurs groupes, leurs rôles et leurs sessions appartiendront au realm `oculox`.

## 3. Fichiers Touchés

### `keycloak/scripts/hardening-preflight.sh`

Ce nouveau script est la barrière avant activation. Il ne fait rien en mode
`basic`. En mode `keycloak`, il refuse notamment :

- le realm applicatif `master` ;
- une URL Keycloak en HTTP ;
- un hostname vide ou non strict ;
- la désactivation de la vérification TLS ;
- un secret client de moins de 32 caractères ;
- une URI de redirection contenant `*` ou pointant vers une autre origine ;
- le RBAC désactivé ou l'absence de groupe d'entrée ;
- un mot de passe bootstrap trop court ou partiellement renseigné ;
- un Access Token supérieur à 15 minutes ;
- une politique de mot de passe inférieure à 14 caractères.

Une URI de redirection est l'adresse vers laquelle Keycloak renvoie le
navigateur après connexion. Autoriser `/*` permettrait trop de destinations.
Le contrôle accepte uniquement un chemin local exact, par exemple
`/index.html`, ou une URL HTTPS appartenant à l'origine publique Oculox.

### `keycloak/scripts/docker-entrypoint.sh`

Ce script est le point d'entrée du conteneur Keycloak. Il exécute maintenant le
précontrôle avant de préparer PostgreSQL. Si le contrôle échoue, le conteneur
s'arrête avec une erreur au lieu de continuer avec une configuration faible.

La sortie de `realm-setup.sh` n'est plus envoyée vers `/dev/null`. Les étapes et
les erreurs de provisionnement sont donc visibles avec :

```bash
docker logs <nom-du-conteneur-keycloak>
```

Les valeurs des mots de passe et secrets ne sont pas écrites par les scripts.

### `keycloak/scripts/realm-setup.sh`

Ce script configure Keycloak avec son outil officiel `kcadm.sh`. Il est
idempotent : une nouvelle exécution met à jour le realm, le client et les
mappers au lieu de créer des doublons.

Le realm reçoit les réglages suivants :

| Réglage | Valeur par défaut | Effet |
| --- | ---: | --- |
| Longueur minimale | 14 | renforce les mots de passe |
| Historique | 5 | empêche de réutiliser immédiatement un ancien mot de passe |
| Échecs avant protection | 5 | limite les essais répétés |
| Attente progressive | 60 s | ralentit les attaques par mot de passe |
| Access Token | 300 s | réduit la durée d'utilisation d'un jeton volé |
| Session inactive | 1 800 s | ferme une session inactive après 30 minutes |
| Session maximale | 28 800 s | impose une reconnexion après 8 heures |
| Refresh Token | rotation, réutilisation 0 | refuse la réutilisation d'un ancien jeton |
| Événements | 604 800 s | garde 7 jours d'événements Keycloak |
| TOTP | action par défaut | demande l'enrôlement MFA aux nouveaux comptes |

Le client OIDC est confidentiel : il possède un secret. Il utilise
Authorization Code, le flux navigateur standard. Direct Access Grant et
Implicit Flow sont désactivés. Les redirections et Web Origins sont exactes.

Les trois mappers ajoutent aux jetons les informations nécessaires :

- `user_realm_role` place les rôles du realm dans `realm_access.roles` ;
- `group_membership` place les groupes dans `groups` ;
- `oculox_portal_audience` indique que le jeton est destiné au client portail.

L'audience est le destinataire prévu du jeton. Sa validation empêche un service
d'accepter un jeton émis pour une autre application.

### `config/keycloak.env.example`

Ce fichier contient des valeurs de référence, jamais les secrets réels. Les
nouveaux défauts importants sont :

```text
KEYCLOAK_AUTH_REALM=oculox
KEYCLOAK_BOOTSTRAP_REALM=master
KEYCLOAK_SSL_VERIFY=true
KC_HOSTNAME_STRICT=true
KEYCLOAK_PASSWORD_MIN_LENGTH=14
KEYCLOAK_ACCESS_TOKEN_LIFESPAN_SECONDS=300
KEYCLOAK_SSO_SESSION_IDLE_SECONDS=1800
KEYCLOAK_SSO_SESSION_MAX_SECONDS=28800
KEYCLOAK_MFA_REQUIRED=true
```

`KEYCLOAK_AUTH_URL`, `KC_HOSTNAME`, le client et les secrets restent vides. Ils
dépendent de l'IP ou du DNS choisi lors de l'installation et ne doivent pas être
figés dans Git.

### `dev/compose/docker-compose.dev.yml`

L'image Malcolm téléchargée contient ses propres scripts. L'override Compose
monte les trois scripts audités depuis le dépôt vers le conteneur en lecture
seule (`:ro`). Ainsi, le code exécuté est bien celui relu et testé dans Oculox,
sans reconstruire une image contenant des secrets.

Le port `8080` de Keycloak n'est toujours pas publié sur l'hôte. Keycloak reste
derrière Nginx et communique en HTTP uniquement à l'intérieur du réseau Docker.

### `scripts/control.py`

La valeur de secours proposée par le configurateur passe de `master` à
`oculox`. Cela évite qu'une installation neuve utilise accidentellement le
realm d'administration comme realm des utilisateurs.

### `dev/tests/keycloak/test_pre_activation_hardening.py`

Ce test exécute réellement le précontrôle avec une configuration sûre, puis
vérifie qu'il refuse les configurations faibles. Il contrôle aussi les valeurs
d'exemple, le mode `basic`, le contenu du provisionnement et les montages
Compose en lecture seule.

## 4. Paramètres Qui Restent À Fournir Au Runtime

Avant l'activation, l'installation devra produire au minimum :

```text
NGINX_AUTH_MODE=keycloak
ROLE_BASED_ACCESS=true
NGINX_REQUIRE_GROUP=/oculox-users
KEYCLOAK_AUTH_URL=https://<IP-ou-DNS-Core>/keycloak
KC_HOSTNAME=https://<IP-ou-DNS-Core>/keycloak
KEYCLOAK_CLIENT_ID=oculox-portal
KEYCLOAK_CLIENT_SECRET=<secret aléatoire d'au moins 32 caractères>
```

Le secret peut être produit sans l'afficher dans un fichier versionné avec :

```bash
openssl rand -base64 48
```

Le résultat appartient à `config/keycloak.env`, qui est un fichier runtime
ignoré par Git et protégé en `600`. Il ne doit pas être copié dans ce document,
un ticket ou un rapport de test.

## 5. Ce Qui N'Est Pas Encore Activé

Le durcissement préalable ne remplace pas les phases d'intégration. Les points
suivants doivent encore être réalisés et testés avant la bascule :

- générer le certificat web avec le SAN de l'IP ou du DNS du nouveau Core ;
- écraser et limiter les en-têtes proxy à la topologie Docker réelle ;
- limiter la console d'administration au réseau d'administration ;
- créer et tester un administrateur permanent nominatif ;
- retirer les identifiants bootstrap après ce test ;
- créer les groupes et les comptes de démonstration ;
- tester l'enrôlement, la connexion et la récupération TOTP ;
- créer un client distinct pour OpenSearch Dashboards ;
- configurer et tester OIDC dans Dashboards et OpenSearch ;
- tester la sauvegarde et la restauration de PostgreSQL Keycloak ;
- valider le parcours complet sur trois VM neuves.

Ces éléments sont volontairement signalés comme restants. Les déclarer terminés
sans parcours utilisateur ni adresse runtime donnerait une fausse preuve de
sécurité.

## 6. Commandes De Vérification

Depuis la racine du dépôt :

```bash
bash -n keycloak/scripts/hardening-preflight.sh keycloak/scripts/realm-setup.sh keycloak/scripts/docker-entrypoint.sh
python3 dev/tests/keycloak/test_pre_activation_hardening.py
./oculox validate
```

Le test Python doit terminer par :

```text
Ran 6 tests
OK
```

Pour confirmer que Keycloak n'a pas été activé involontairement :

```bash
grep '^NGINX_AUTH_MODE=' config/auth-common.env
```

Le résultat attendu avant les phases d'activation est :

```text
NGINX_AUTH_MODE=basic
```

## 7. Résumé À Présenter

« Nous n'avons pas encore activé Keycloak. Nous avons d'abord sécurisé son
chemin d'activation. Un précontrôle bloque les configurations faibles, le
bootstrap se fait correctement dans le realm système `master`, puis crée un
realm applicatif `oculox`. Le client utilise Authorization Code avec une
redirection exacte, TLS vérifié, RBAC, rotation des jetons et journalisation.
Les tests prouvent aussi que les anciennes valeurs permissives sont refusées.
Les certificats runtime, l'administrateur nominatif et les parcours OIDC réels
seront validés dans les phases suivantes avant toute bascule. »

## 8. Références Officielles Utilisées

- [Keycloak derrière un reverse proxy](https://www.keycloak.org/server/reverseproxy) : hostname public, écrasement des en-têtes transférés et adresses de proxy de confiance ;
- [Configuration du hostname Keycloak](https://www.keycloak.org/server/hostname) : URL HTTPS complète et chemin public `/keycloak` ;
- [Guide d'administration Keycloak](https://www.keycloak.org/docs/latest/server_admin/) : politiques de mot de passe, détection des attaques, TOTP et flux OIDC ;
- [Configuration de production Keycloak](https://www.keycloak.org/server/configuration-production) : exigences de déploiement avant mise en production.

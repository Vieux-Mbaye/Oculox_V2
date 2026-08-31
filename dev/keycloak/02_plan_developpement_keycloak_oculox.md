# Plan Complet De Développement Keycloak Pour Oculox

## 1. Objet

Ce document définit le plan de développement, de sécurisation, de test et de
livraison permettant de faire de Keycloak la méthode principale
d'authentification des utilisateurs Oculox.

La cible doit rester installable depuis Gitea sur des VM neuves possédant des
adresses IP différentes de l'environnement de développement.

Le développement sera considéré comme terminé uniquement lorsque les trois
rôles suivants pourront être installés depuis zéro :

```text
VM 1 : cluster OpenSearch
VM 2 : Oculox Core avec Keycloak
VM 3 : collecteur Hedgehog
```

## 2. Résultat Attendu

À la fin du projet :

- Keycloak authentifie les utilisateurs humains ;
- OIDC fournit le SSO au portail et à Dashboards ;
- les groupes Keycloak attribuent les rôles Oculox ;
- Nginx applique le RBAC aux chemins du portail ;
- OpenSearch valide les jetons OIDC des utilisateurs Dashboards ;
- les comptes techniques OpenSearch restent séparés ;
- Filebeat et Logstash conservent leur mTLS ;
- une panne Keycloak n'arrête pas l'ingestion ;
- l'installation accepte une IP ou un DNS fourni au runtime ;
- aucun certificat, mot de passe ou secret généré n'est poussé dans Git ;
- le passage futur d'une IP de développement à un DNS est documenté et testé.

## 3. Principes Non Négociables

### 3.1 Séparer Les Personnes Et Les Machines

```text
Utilisateurs humains -> Keycloak + OIDC
Services techniques  -> mTLS ou comptes de service limités
```

Keycloak ne doit pas être ajouté au chemin Filebeat, Logstash ou Arkime
Capture. Les machines ne doivent pas simuler des utilisateurs humains.

### 3.2 Aucun Paramètre De VM Dans Git

Le dépôt contient uniquement les modèles, scripts, politiques, tests et
documents. Les valeurs suivantes sont fournies à l'installation ou générées
localement :

- IP et noms DNS ;
- URL publiques ;
- certificats et clés privées ;
- secrets OIDC ;
- mots de passe PostgreSQL ;
- comptes bootstrap ;
- bundles clients.

### 3.3 Conserver Un Retour Arrière

Le mode Basic actuel doit rester disponible comme procédure d'urgence pendant
la validation. Son usage devra être limité au réseau d'administration.

### 3.4 Utiliser Les Fonctions Natives

Le développement doit réutiliser en priorité :

- Keycloak embarqué par Malcolm ;
- `scripts/auth_setup` ;
- `lua-resty-openidc` dans Nginx ;
- le RBAC natif Malcolm ;
- le plugin Security OpenSearch ;
- l'authentification OIDC native de Dashboards.

## 4. Périmètre

### 4.1 Inclus

- Keycloak embarqué sur le Core ;
- realm Oculox dédié ;
- clients OIDC séparés pour le portail et Dashboards ;
- groupes, rôles et MFA ;
- Nginx OIDC et RBAC ;
- OpenSearch OIDC en parallèle de Basic ;
- Dashboards SSO ;
- Arkime, NetBox, Upload et API derrière Nginx ;
- génération dynamique des URL et certificats ;
- sauvegarde et restauration Keycloak ;
- tests d'installation sur VM neuves ;
- tests de panne et de retour arrière.

### 4.2 Hors Périmètre Initial

- cluster Keycloak multi-nœud ;
- PostgreSQL Keycloak hautement disponible ;
- remplacement du mTLS Beats ;
- authentification Filebeat par jeton ;
- fédération Active Directory ou LDAP ;
- thème Keycloak avancé ;
- exposition de Keycloak sur Internet.

## 5. Architecture Cible

### 5.1 Utilisateur Du Portail

```text
Navigateur
    |
    | HTTPS
    v
Nginx Oculox
    |
    | OIDC Authorization Code
    v
Keycloak
    |
    | ID Token + Access Token + rôles
    v
Nginx
    |
    | X-Forwarded-User / Groups / Roles
    v
Arkime, NetBox, Upload, API et portail
```

### 5.2 Utilisateur Dashboards

```text
Navigateur
    |
    v
OpenSearch Dashboards
    |
    | OIDC
    v
Keycloak
    |
    | Access Token signé
    v
Dashboards
    |
    | Bearer Token
    v
OpenSearch Security
    |
    | mapping des rôles
    v
Index et fonctions autorisés
```

### 5.3 Pipeline Industriel

```text
Interface miroir
    |
    v
Hedgehog
    |
    | mTLS
    v
Logstash 1 et Logstash 2
    |
    | comptes techniques limités
    v
Cluster OpenSearch
```

Keycloak est absent de ce troisième chemin.

## 6. Contrat De Configuration Portable

### 6.1 Entrées Obligatoires

L'installation Core doit demander au minimum :

```text
identité réseau publique du Core : IP ou DNS
bundle OpenSearch Core
activation ou non de Keycloak
realm Oculox
politique MFA initiale
```

L'identité réseau doit être fournie explicitement, car une VM peut posséder
plusieurs interfaces et le script ne peut pas toujours choisir la bonne IP.

### 6.2 Valeurs Dérivées

Pour un Core installé avec une IP fournie au runtime :

```text
OCULOX_PUBLIC_URL=https://<IP_CORE>
KEYCLOAK_AUTH_URL=https://<IP_CORE>/keycloak
KEYCLOAK_ISSUER=https://<IP_CORE>/keycloak/realms/oculox
certificat web SAN=IP:<IP_CORE>
```

Pour un Core installé avec un DNS :

```text
OCULOX_PUBLIC_URL=https://<DNS_CORE>
KEYCLOAK_AUTH_URL=https://<DNS_CORE>/keycloak
KEYCLOAK_ISSUER=https://<DNS_CORE>/keycloak/realms/oculox
certificat web SAN=DNS:<DNS_CORE>
```

### 6.3 Fichiers Générés

Les fichiers runtime seront placés dans des emplacements ignorés par Git :

```text
config/keycloak.env
config/auth-common.env
config/postgres.env
nginx/certs/
dev/generated/keycloak/
```

Les secrets et clés privées doivent avoir la permission `600` ou être montés
en lecture seule dans les conteneurs.

### 6.4 Changement D'Adresse

Une installation neuve génère une nouvelle identité pour sa nouvelle adresse.

Une migration d'un déploiement existant doit :

1. émettre un nouveau certificat ;
2. modifier l'URL publique et l'issuer ;
3. modifier les URI de redirection ;
4. modifier Dashboards et OpenSearch ;
5. invalider les anciennes sessions ;
6. valider la nouvelle URL ;
7. retirer l'ancienne URL après transition.

## 7. Modèle D'Identité Initial

### 7.1 Realms

```text
master -> administration Keycloak uniquement
oculox  -> utilisateurs, groupes, rôles et clients Oculox
```

### 7.2 Clients OIDC

| Client | Type | Fonction |
| --- | --- | --- |
| `oculox-portal` | confidentiel | Nginx et portail Oculox |
| `oculox-dashboards` | confidentiel | OpenSearch Dashboards |

Chaque client possède son propre secret et des URI de redirection exactes.

### 7.3 Groupes Et Rôles

| Groupe | Rôles proposés |
| --- | --- |
| `/oculox-users` | autorisation d'entrer dans Oculox |
| `/oculox-admins` | `admin` |
| `/oculox-analysts` | `read_write_access`, `dashboards_read_write_access`, `arkime_hunt_access` |
| `/oculox-viewers` | `read_access`, `dashboards_read_access`, `arkime_read_access` |
| `/oculox-incident-response` | `arkime_pcap_access`, `arkime_hunt_access` |

L'accès PCAP doit rester indépendant du rôle générique de lecture.

## 8. Durcissement Minimal Avant Activation

Les mesures de cette section doivent être terminées avant que Keycloak remplace
Basic comme méthode principale.

### 8.0 État Du Socle Au 31 Août 2026

Les garde-fous qui peuvent être appliqués sans activer Keycloak sont maintenant
implémentés. Le détail vérifiable se trouve dans
`dev/keycloak/03_durcissement_pre_activation.md`.

```text
Mode actif du Core                    : basic, inchangé
Contrôle bloquant avant activation    : implémenté
Realm Oculox séparé de master         : imposé
Client Authorization Code durci       : implémenté dans le provisionnement
Redirections exactes sans joker       : imposées
TLS et hostname strict                : imposés à l'activation
RBAC et groupe d'entrée               : imposés à l'activation
Politique realm, anti-bruteforce      : provisionnées
Rotation des refresh tokens           : provisionnée
Événements de sécurité                : activés dans le realm
Enrôlement TOTP des nouveaux comptes  : préparé
Activation et test utilisateur réel   : non exécutés, prévus par K3 à K8
```

Le mot « implémenté » signifie ici que le dépôt sait générer ou refuser la
configuration. Il ne signifie pas que le Core utilise déjà Keycloak. La
bascule reste volontairement interdite tant que l'administrateur permanent,
le certificat correspondant à l'adresse de la VM, les groupes, les comptes de
test et les parcours OIDC complets n'ont pas été validés.

### 8.1 Bootstrap

- utiliser un administrateur temporaire uniquement dans `master` ;
- créer un administrateur permanent nominatif ;
- tester le compte permanent ;
- retirer les identifiants bootstrap du runtime ;
- ne jamais réutiliser le mot de passe bootstrap comme secret client.

### 8.2 Clients OIDC

- interdire les URI de redirection `/*` ;
- enregistrer uniquement les URI HTTPS nécessaires ;
- utiliser un secret différent par client ;
- désactiver Direct Access Grant ;
- utiliser Authorization Code pour les navigateurs ;
- valider l'audience des jetons ;
- limiter les web origins aux origines Oculox.

### 8.3 Réseau Et Reverse Proxy

- ne pas publier le port Keycloak `8080` sur l'hôte ;
- publier Keycloak uniquement derrière Nginx ;
- écraser les en-têtes `X-Forwarded-*` reçus du client ;
- n'accepter les en-têtes proxy que depuis Nginx ;
- fixer le hostname public Keycloak ;
- conserver HTTP uniquement sur le réseau Docker privé ;
- limiter la console d'administration au réseau d'administration.

### 8.4 TLS

- utiliser HTTPS côté navigateur ;
- générer un SAN correspondant à l'IP ou au DNS fourni ;
- distribuer la CA de développement aux clients de test ;
- activer la vérification TLS dans Dashboards et OpenSearch ;
- interdire `-k` dans les tests d'acceptation ;
- prévoir une PKI d'entreprise en production.

### 8.5 Comptes, Sessions Et MFA

- définir une politique de mot de passe ;
- activer la protection contre les tentatives répétées ;
- limiter la durée des Access Tokens ;
- définir l'inactivité et la durée maximale des sessions ;
- activer la rotation des Refresh Tokens si compatible ;
- imposer le MFA aux administrateurs ;
- fournir une procédure de récupération ;
- interdire les comptes partagés.

### 8.6 Secrets, Audit Et Sauvegarde

- générer les secrets avec un générateur cryptographique ;
- ne jamais les afficher dans les journaux ou rapports ;
- ne jamais les ajouter à Git ;
- vérifier les permissions et documenter la rotation ;
- activer les événements de connexion et d'administration ;
- journaliser les refus RBAC sans journaliser les jetons ;
- sauvegarder et restaurer PostgreSQL Keycloak ;
- conserver l'export du realm comme complément de sauvegarde.

## 9. Phases De Développement

### Phase K0 - Baseline Et Retour Arrière

Objectif : établir l'état de référence avant toute modification.

État au 31 août 2026 : **terminée sur le Core local et le cluster distant de
développement**. Le rapport détaillé et la procédure de retour arrière se
trouvent dans `dev/keycloak/04_phase_k0_baseline_retour_arriere.md`. Les preuves
contenant des secrets sont conservées uniquement sous
`dev/generated/keycloak-baseline/`, hors Git.

Travaux :

- créer une branche dédiée ;
- relever les versions des composants ;
- inventorier les routes web et API ;
- sauvegarder les configurations et PostgreSQL ;
- exécuter les tests clients, Dashboards et ingestion ;
- documenter le retour à `NGINX_AUTH_MODE=basic`.

Preuves attendues :

```text
Core sain
cluster OpenSearch green
ingestion PASS
Dashboards fonctionnel
retour Basic possible
```

Résultat observé : les cinq preuves sont satisfaites. Le test de retour Basic
est structurel à ce stade, car Basic est encore le mode actif; la transition
Keycloak vers Basic sera rejouée après la première activation en phase K5.

### Phase K1 - Configuration Portable

Objectif : supprimer toute dépendance à une IP particulière.

État au 31 août 2026 : **terminée et appliquée sur le Core local**. Le rapport
d'implémentation et les commandes de reproduction se trouvent dans
`dev/keycloak/05_phases_k1_k2_configuration_portable_pki_web.md`.

Travaux :

- centraliser l'identité publique du Core ;
- dériver les URL Oculox et Keycloak ;
- accepter une IP ou un DNS ;
- générer le SAN adapté ;
- rejeter une URL HTTP publique ;
- rendre les commandes réexécutables ;
- préserver les secrets existants sauf rotation explicite.

Tests : rendu IPv4, rendu DNS, rejet URL invalide, absence d'IP de laboratoire
dans Git et seconde exécution sans changement de secret.

Résultat : `./oculox prepare principal --server-name <IP-ou-DNS>` centralise
désormais l'identité publique, dérive les URL HTTPS et Keycloak, puis conserve
les secrets déjà présents. Les tests couvrent IPv4, IPv6 et DNS. Aucune des
adresses de laboratoire n'est codée dans les scripts génériques.

Critère de sortie atteint au niveau logiciel : la même révision accepte des
identités différentes sans modification du dépôt. La preuve d'installation
complète sur deux VM reste intégrée au jalon K10.

### Phase K2 - PKI Web De Développement

Objectif : valider TLS sans désactiver la sécurité.

État au 31 août 2026 : **terminée et appliquée sur le Core local**. Keycloak
reste volontairement en attente d'activation : le mode d'authentification
actif demeure `basic` jusqu'à K5.

Travaux :

- créer une CA web de développement par déploiement ;
- générer le certificat Nginx avec le SAN runtime ;
- monter la clé privée en lecture seule ;
- créer un bundle de confiance sans clé privée ;
- distribuer la CA à Dashboards et OpenSearch ;
- préparer le mode certificat fourni pour la production.

Preuves : `openssl verify` réussi, `curl --cacert` réussi, appel sans CA refusé,
SAN correct et clé privée absente des bundles publics.

Résultat : une CA Web propre au déploiement signe le certificat Nginx. Le SAN
est calculé à partir de l'identité runtime. Dashboards reçoit la CA au moyen de
`NODE_EXTRA_CA_CERTS`. Un mode `provided` accepte aussi un certificat fourni
par une PKI d'entreprise après contrôle de son SAN, de sa chaîne et de sa clé.
Sur le Core local, Nginx présente `IP:192.168.1.174`, la vérification OpenSSL
retourne `0 (ok)`, l'appel sans CA est refusé et Dashboards reste `green`.

La CA est préparée pour OpenSearch dans un bundle public sans clé privée. Son
installation sur le cluster pour la validation OIDC/JWKS sera effectuée avec
la configuration OpenSearch de K6, pas par une modification implicite distante.

### Phase K3 - Provisionnement Keycloak Idempotent

Objectif : créer le realm et ses objets sans duplication.

Travaux :

- corriger le bootstrap dans `master` ;
- créer ou mettre à jour le realm `oculox` ;
- créer rôles, groupes et associations ;
- créer les deux clients OIDC ;
- créer les protocol mappers ;
- utiliser des URI exactes ;
- désactiver Direct Access Grant ;
- générer les secrets hors Git ;
- retirer le bootstrap après validation.

Tests : première exécution, deuxième exécution sans doublon, préservation des
secrets, absence de wildcard et compte bootstrap retiré.

### Phase K4 - Modèle IAM Et RBAC

Objectif : appliquer le moindre privilège.

Travaux :

- valider la matrice groupes-rôles ;
- séparer lecture, écriture, administration, PCAP et Hunt ;
- vérifier les expansions de rôles Nginx ;
- supprimer toute attribution implicite trop large ;
- créer des utilisateurs de test ;
- documenter arrivée, changement de fonction et départ.

Tests : accès lecteur, refus écriture, refus PCAP sans rôle, accès Hunt analyste,
refus utilisateur sans groupe et accès administrateur.

### Phase K5 - OIDC Nginx Et Portail

Objectif : faire de Keycloak la méthode principale sur le port `443`.

Configuration cible :

```text
NGINX_AUTH_MODE=keycloak
ROLE_BASED_ACCESS=true
NGINX_REQUIRE_GROUP=/oculox-users
KEYCLOAK_AUTH_REALM=oculox
KEYCLOAK_CLIENT_ID=oculox-portal
```

Travaux : configurer le client, vérifier discovery/issuer/audience, sécuriser
les cookies, nettoyer les en-têtes entrants et gérer logout et expiration.

Tests : login valide/invalide, groupe absent, SSO, expiration, logout et rejet
d'un faux `X-Forwarded-Roles`.

### Phase K6 - OIDC Dashboards Et OpenSearch

Objectif : obtenir le SSO Dashboards sans supprimer les comptes techniques.

Travaux :

- configurer `oculox-dashboards` ;
- passer l'authentification humaine Dashboards à `openid` ;
- ajouter le domaine OIDC OpenSearch ;
- conserver le domaine Basic interne ;
- activer le cache JWKS ;
- mapper les rôles humains vers OpenSearch ;
- conserver `oculox_dashboards` comme compte serveur uniquement ;
- retirer la seconde connexion Basic humaine.

Tests : SSO portail-Dashboards, profils lecture/écriture/admin, refus sans rôle,
mauvaise audience, mauvais issuer, jeton expiré, signature inconnue et maintien
des connexions Logstash/Arkime.

### Phase K7 - Durcissement Fonctionnel

Objectif : appliquer toute la section 8 avant utilisation réelle.

Travaux : politique de mot de passe, protection brute force, MFA, sessions,
audit, restriction console admin, revue des secrets, permissions et recherche
de secrets dans Git.

Critère de sortie : chaque mesure possède une preuve et un test négatif.

### Phase K8 - Non-Régression Du Pipeline

Objectif : démontrer que Keycloak ne casse pas la plateforme industrielle.

Travaux : vérifier les deux Logstash, mTLS, injecter un PCAP, mesurer Zeek,
Suricata, OpenSearch et Arkime, puis arrêter Keycloak pendant l'ingestion.

Preuves :

```text
Filebeat published = acked
Filebeat failed = 0
Logstash 1 reçoit
Logstash 2 reçoit
documents OpenSearch augmentent
sessions Arkime augmentent
ingestion continue pendant la panne Keycloak
```

### Phase K9 - Sauvegarde, Restauration Et Rotation

Objectif : rendre Keycloak exploitable dans la durée.

Travaux : sauvegarde et restauration PostgreSQL, export du realm, rotation des
deux secrets clients, rotation des clés de signature, renouvellement du
certificat HTTPS et révocation des sessions.

Critère de sortie : une restauration sur VM temporaire retrouve un realm
fonctionnel et les clients se reconnectent.

### Phase K10 - Installation Sur Trois VM Neuves

Objectif : prouver la portabilité du dépôt Gitea.

Préconditions : trois VM sans Oculox, Docker potentiellement absent, nouvelles
IP, accès au dépôt et au registre, aucun `dev/generated` copié.

Scénario :

1. cloner et installer le cluster avec sa nouvelle IP ;
2. générer les bundles Core et Hedgehog ;
3. cloner le dépôt sur le Core ;
4. transférer le bundle Core ;
5. installer le Core avec sa nouvelle identité ;
6. activer et provisionner Keycloak ;
7. créer le bundle Beats ;
8. cloner le dépôt sur Hedgehog ;
9. transférer les bundles ;
10. installer Hedgehog ;
11. exécuter les validations IAM, clients et ingestion.

Preuves : aucune modification manuelle d'IP dans le code, nouveaux SAN,
OpenSearch green, SSO fonctionnel, mTLS fonctionnel, ingestion PASS et panne
Keycloak sans perte d'ingestion.

### Phase K11 - Migration Future Vers DNS

Objectif : prouver que le développement par IP n'empêche pas la production.

Travaux : créer un DNS de test, émettre un SAN DNS, ajouter les URI de
redirection, modifier l'issuer, mettre à jour Dashboards/OpenSearch, forcer une
nouvelle authentification et retirer les anciennes URI IP.

Critère de sortie : aucune modification de code et aucune perte de données.

### Phase K12 - Livraison Et Exploitation

Livrables :

- guide conceptuel Keycloak/OIDC ;
- guide d'installation ;
- matrice des rôles ;
- guide utilisateurs et MFA ;
- procédures sauvegarde, restauration et rotation ;
- procédure de panne et retour Basic ;
- rapport de validation sur VM neuves ;
- tests automatisés intégrés au dépôt.

Critère de sortie : un autre administrateur peut installer et exploiter la
solution uniquement avec la documentation du dépôt.

## 10. Stratégie De Tests

### 10.1 Tests Statiques

- aucune IP de laboratoire dans les modèles ;
- aucun secret suivi par Git ;
- aucune clé privée dans un bundle public ;
- aucune URI `/*` ;
- Direct Access Grant désactivé ;
- Basic technique conservé ;
- OIDC humain présent ;
- vérification TLS activée.

### 10.2 Tests Unitaires

- rendu URL avec IP et DNS ;
- choix du SAN ;
- validation des URI ;
- préservation des secrets ;
- mapping groupes-rôles ;
- idempotence du provisionnement.

### 10.3 Tests D'Intégration

- Nginx vers Keycloak ;
- Dashboards vers Keycloak ;
- OpenSearch vers JWKS ;
- rôle Keycloak vers Nginx et OpenSearch ;
- logout, révocation et renouvellement.

### 10.4 Tests Négatifs

- mauvais mot de passe ou second facteur ;
- utilisateur désactivé ;
- groupe ou rôle absent ;
- jeton expiré ;
- mauvaise audience ou issuer ;
- signature inconnue ;
- faux en-tête d'identité ;
- CA inconnue ;
- URI de redirection non déclarée.

### 10.5 Tests De Résilience

- arrêt Keycloak ;
- arrêt PostgreSQL Keycloak ;
- redémarrage Nginx et Core ;
- rotation de clé ;
- restauration PostgreSQL ;
- retour temporaire à Basic.

## 11. Critères D'Acceptation Finaux

```text
[ ] installation sur trois VM neuves réussie
[ ] aucune IP statique dans le code générique
[ ] aucun secret ou certificat privé dans Git
[ ] realm oculox séparé de master
[ ] deux clients OIDC distincts
[ ] URI de redirection exactes
[ ] Direct Access Grant désactivé
[ ] MFA administrateur actif
[ ] RBAC actif
[ ] SSO portail vers Dashboards validé
[ ] domaine OIDC OpenSearch validé
[ ] domaine Basic technique conservé
[ ] comptes de service limités conservés
[ ] Filebeat mTLS validé
[ ] ingestion maintenue pendant une panne Keycloak
[ ] sauvegarde et restauration testées
[ ] rotation des secrets testée
[ ] migration IP vers DNS documentée
[ ] retour arrière Basic testé
[ ] documentation exploitable par un autre administrateur
```

## 12. Risques Et Réponses

| Risque | Réponse prévue |
| --- | --- |
| changement d'IP | génération runtime et procédure de migration |
| certificat non reconnu | CA dev distribuée, PKI reconnue en production |
| perte de Keycloak | ingestion indépendante, restauration PostgreSQL |
| rôle trop large | matrice explicite et tests négatifs |
| secret dans Git | `.gitignore`, tests et revue du diff |
| double authentification Dashboards | client OIDC Dashboards et SSO |
| panne IdP bloquant OpenSearch | Basic technique conservé et cache JWKS |
| faux en-tête proxy | nettoyage Nginx et proxy de confiance |
| wildcard de redirection | URI exactes testées automatiquement |
| perte du MFA | récupération contrôlée et auditée |
| dépendance à une VM Core | limite documentée, évolution HA ultérieure |

## 13. Ordre Recommandé

```text
K0  Baseline
 -> K1  Configuration portable
 -> K2  PKI web de développement
 -> K3  Provisionnement Keycloak
 -> K4  Modèle IAM et RBAC
 -> K5  OIDC portail
 -> K6  OIDC Dashboards/OpenSearch
 -> K7  Durcissement complet
 -> K8  Non-régression ingestion
 -> K9  Sauvegarde et rotation
 -> K10 Installation VM neuves
 -> K11 Migration future DNS
 -> K12 Livraison
```

Une phase ne doit pas être déclarée terminée sans ses preuves. Voir une page de
connexion Keycloak ne prouve ni le RBAC, ni le SSO, ni la résilience.

## 14. Documentation Officielle

- [Keycloak - OpenID Connect](https://www.keycloak.org/securing-apps/oidc-layers)
- [Keycloak - Administration](https://www.keycloak.org/docs/latest/server_admin/)
- [Keycloak - Reverse proxy](https://www.keycloak.org/server/reverseproxy)
- [Keycloak - Hostname](https://www.keycloak.org/server/hostname)
- [Keycloak - Production](https://www.keycloak.org/server/configuration-production)
- [OpenSearch - OpenID Connect](https://docs.opensearch.org/latest/security/authentication-backends/openid-connect/)

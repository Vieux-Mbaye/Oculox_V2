# Configuration De L'Authentification Du Principal Oculox

## 1. Pourquoi Cet Ecran Apparait

La commande suivante exécute une installation complète du rôle Principal :

```bash
./oculox install principal --server-name 10.5.6.6
```

Le lanceur Oculox enchaîne plusieurs étapes :

1. l'installateur officiel Malcolm prépare le système et crée les fichiers
   `config/*.env` ;
2. le rôle `malcolm` est appliqué au serveur ;
3. le script officiel `scripts/auth_setup` ouvre l'écran **Configure
   Authentication** ;
4. après cette configuration, Oculox génère sa configuration résiliente, sa
   PKI de transport, les deux instances Logstash et les fichiers Filebeat ;
5. les fichiers Compose sont validés, les images sont récupérées et les
   services sont démarrés.

L'écran affiché ne signale donc pas une erreur. Il correspond à l'étape
obligatoire de création des comptes, certificats et secrets nécessaires avant
le premier démarrage du Principal.

## 2. Comment Lire Et Utiliser L'Ecran

- `(*)` signifie que l'élément est sélectionné.
- `( )` signifie que l'élément n'est pas sélectionné.
- Les flèches déplacent le curseur.
- La barre d'espace sélectionne ou désélectionne un élément.
- La touche `Tab` permet d'aller sur **OK** ou **Cancel**.
- La touche `Entrée` valide le bouton actif.

Sur une installation réellement neuve, la documentation officielle Malcolm
recommande de laisser **all** sélectionné et de valider **OK**. L'assistant
parcourt alors chaque configuration utile dans l'ordre.

`all` ne crée pas un mot de passe unique pour toute la plateforme. Il lance
successivement plusieurs opérations indépendantes : compte administrateur,
certificats, secrets OpenSearch, NetBox, PostgreSQL, Valkey et Arkime.

## 3. Explication De Chaque Option

### 3.1 `all` - Configurer Tous Les Eléments

Cette option exécute l'ensemble des opérations affichées dans le menu. Elle est
adaptée au premier déploiement, car aucun compte, certificat ni secret interne
n'existe encore.

**Réponse recommandée pour ce serveur neuf :** laisser `all` sélectionné et
valider **OK**.

Sur une plateforme déjà utilisée, il ne faut pas relancer aveuglément `all` :
la régénération de certains secrets peut couper l'accès aux bases de données ou
rompre la communication avec les collecteurs existants.

### 3.2 `method` - Choisir La Méthode D'Authentification

Cette option définit comment les utilisateurs s'authentifient sur les
interfaces web Oculox/Malcolm. Le choix est enregistré dans :

```text
config/auth-common.env
NGINX_AUTH_MODE=<méthode>
```

Les méthodes proposées sont :

| Méthode | Fonction | Usage conseillé |
|---|---|---|
| `basic` | Comptes locaux protégés par HTTPS | Installation initiale, laboratoire ou petite équipe |
| `ldap` | Authentification par un annuaire LDAP ou Active Directory | Organisation disposant déjà d'un annuaire |
| `keycloak` | Authentification par le Keycloak embarqué dans Malcolm | SSO, rôles et gestion centralisée des identités |
| `keycloak_remote` | Authentification par un Keycloak externe | Keycloak déjà exploité par l'organisation |
| `no_authentication` | Désactive l'authentification | Non recommandé |

Le mode `basic` ne signifie pas que le trafic web est en clair : le navigateur
utilise HTTPS. `basic` décrit la méthode d'identification, tandis que HTTPS
décrit le chiffrement du transport.

**Réponse recommandée pour valider d'abord le nouveau Principal :** conserver
`basic`. L'intégration de Keycloak pourra ensuite être réalisée comme une
évolution contrôlée, avec ses rôles, son domaine et ses critères de validation.

### 3.3 `admin` - Créer Le Compte Administrateur Local

Cette option demande un nom d'utilisateur et un mot de passe administrateur.
Ce compte permet de se connecter aux interfaces web lorsque la méthode
`basic` est active.

Les informations générées sont notamment utilisées dans :

```text
config/auth.env
nginx/htpasswd
```

Le mot de passe n'est pas enregistré en clair dans `nginx/htpasswd`. Une
empreinte de mot de passe est utilisée pour la vérification. Le fichier
`config/auth.env` est également créé avec des permissions restrictives.

Après le démarrage, des comptes locaux supplémentaires peuvent être gérés via :

```text
https://<adresse-du-principal>/auth/
```

**Réponse recommandée :** créer un compte nominatif avec un mot de passe long
et unique. Ne pas mettre le mot de passe dans Git, dans un rapport ou dans une
capture d'écran.

Si `ldap` ou `keycloak` est choisi, ce compte local n'est pas le mécanisme
normal de connexion des utilisateurs. Il reste néanmoins créé pour les besoins
locaux prévus par Malcolm.

### 3.4 `webcerts` - Certificats HTTPS Des Interfaces Web

Cette option génère le certificat et la clé utilisés par Nginx pour chiffrer les
connexions entre le navigateur et le Principal :

```text
nginx/certs/cert.pem
nginx/certs/key.pem
nginx/certs/dhparam.pem
```

Il s'agit par défaut d'un certificat auto-signé. Le contenu des échanges est
chiffré, mais le navigateur affiche généralement un avertissement parce qu'il
ne connaît pas l'autorité ayant signé ce certificat.

**Réponse recommandée sur un serveur neuf :** oui.

Pour une mise en production, ce certificat devra idéalement être remplacé par
un certificat signé par l'autorité de certification de l'organisation, avec le
nom DNS réel du service.

Régénérer ce certificat plus tard change son empreinte et peut obliger les
utilisateurs ou les outils à accepter le nouveau certificat.

### 3.5 `fwcerts` - Certificats Du Transport Des Journaux Distants

`fwcerts` signifie **forwarder certificates**. Cette option crée les
certificats TLS utilisés pour protéger le transport entre un collecteur distant
et l'entrée Logstash du Principal.

Les éléments officiels Malcolm sont créés dans :

```text
logstash/certs/   # autorité, certificat et clé côté réception
filebeat/certs/   # autorité, certificat et clé à fournir au collecteur
```

Ces certificats servent à l'authentification des machines et au chiffrement du
canal Filebeat/Logstash. Ils ne remplacent pas le compte administrateur web.

**Réponse recommandée sur une installation neuve :** oui.

#### Particularité De L'Architecture Résiliente Oculox

Après `auth_setup`, le lanceur Oculox génère aussi une PKI dédiée à
l'architecture résiliente :

```text
dev/generated/pki/
```

Cette seconde étape prépare le mTLS vers les deux entrées Logstash, sur les
ports `5044` et `5045`, ainsi que les bundles propres à chaque collecteur. Les
certificats produits par `fwcerts` appartiennent au mécanisme officiel Malcolm ;
ceux de `dev/generated/pki/` appartiennent à l'extension résiliente Oculox. Il
ne faut pas mélanger leurs clés ni copier la clé privée de l'autorité sur un
collecteur.

### 3.6 `localos` - Identifiants Internes OpenSearch Local

`localos` signifie **local OpenSearch**. Cette option crée un compte technique
interne permettant aux services Malcolm de communiquer avec l'instance locale
OpenSearch.

Le compte généré est `malcolm_internal` avec un mot de passe aléatoire. Les
informations sont enregistrées avec des permissions restrictives dans :

```text
.opensearch.primary.curlrc
```

Ce compte n'est pas le compte utilisé par un analyste dans son navigateur. Il
sert aux communications techniques entre composants.

**Réponse recommandée pour un Principal utilisant OpenSearch local :** oui.

### 3.7 `email` - Identifiants D'Envoi Des Alertes Par Courriel

Cette option enregistre le nom d'utilisateur et le mot de passe d'un compte de
messagerie utilisé par le module d'alerting OpenSearch.

Les secrets sont placés dans le keystore sécurisé d'OpenSearch :

```text
opensearch/opensearch.keystore
```

Cette option ne configure pas à elle seule le serveur SMTP, les destinataires
ou les règles d'alerte. Elle ne fait que stocker les identifiants du compte
d'envoi.

**Réponse recommandée :** ne renseigner cette partie que si un compte SMTP
réel est déjà disponible et que l'envoi d'alertes par courriel doit être activé
immédiatement. Sinon, laisser cette configuration vide ou la traiter plus tard.

### 3.8 `netbox` - Secrets Internes NetBox

NetBox conserve l'inventaire, les actifs et le contexte réseau utilisés pour
l'enrichissement. Cette option génère plusieurs secrets techniques :

- mot de passe de la base NetBox ;
- clé secrète de l'application ;
- mot de passe du superutilisateur NetBox ;
- jeton d'API NetBox.

Ils sont enregistrés principalement dans :

```text
config/postgres.env
config/netbox-secret.env
```

**Réponse recommandée sur une installation neuve avec NetBox local :** oui.

Attention : régénérer ces valeurs après que NetBox a été alimenté peut rompre
l'accès aux données existantes. Il faut sauvegarder NetBox avant toute rotation
future de ces secrets.

### 3.9 `postgres` - Mot De Passe Superutilisateur PostgreSQL

PostgreSQL stocke l'état et les données applicatives de plusieurs composants,
notamment NetBox et, selon la configuration, Keycloak.

Cette option génère le mot de passe du superutilisateur PostgreSQL dans :

```text
config/postgres.env
```

Ce mot de passe est un secret interne entre conteneurs. Ce n'est pas un compte
d'accès aux dashboards.

**Réponse recommandée sur une installation neuve :** oui.

Comme pour NetBox, une rotation non préparée sur une base déjà peuplée peut
mettre les applications et la base en désaccord. Une sauvegarde est nécessaire
avant toute régénération future.

### 3.10 `valkey` - Mot De Passe Interne Valkey

Valkey est un magasin clé-valeur en mémoire compatible avec Redis. Malcolm
l'utilise notamment pour des sessions, des caches et la coordination de
certains services.

Cette option génère un mot de passe aléatoire dans :

```text
config/valkey.env
VALKEY_PASSWORD=<secret>
```

Ce mot de passe protège les échanges internes avec Valkey. Il ne sert pas à la
connexion d'un utilisateur aux interfaces web.

**Réponse recommandée sur une installation neuve :** oui.

### 3.11 `arkime` - Secret Commun Du Cluster Arkime

Cette option demande le `passwordSecret` utilisé par Arkime. Ce secret protège
notamment les communications entre viewers Arkime lorsqu'un viewer récupère un
contenu PCAP auprès d'une autre instance.

Il est enregistré dans :

```text
config/arkime-secret.env
ARKIME_PASSWORD_SECRET=<secret>
```

Ce n'est ni le mot de passe administrateur web, ni une clé TLS. Il s'agit d'un
secret partagé propre au fonctionnement d'Arkime.

Dans une architecture distribuée, la même valeur doit être configurée sur le
Principal et sur les collecteurs Hedgehog qui transmettent des sessions Arkime
à ce Principal.

**Réponse recommandée :** définir une valeur longue, aléatoire et unique, puis
la conserver dans un coffre de secrets afin de pouvoir utiliser exactement la
même valeur lors de l'installation des collecteurs concernés.

## 4. Choix Recommandés Pour Cette Installation

Pour le Principal neuf `10.5.6.6`, la séquence recommandée est la suivante :

| Elément | Choix recommandé | Motif |
|---|---|---|
| `all` | Sélectionné | Première installation |
| `method` | `basic` | Valider d'abord le socle résilient avec une authentification simple |
| `admin` | Compte nominatif fort | Accès administrateur aux interfaces |
| `webcerts` | Oui | Activer le chiffrement HTTPS |
| `fwcerts` | Oui | Préparer le transport chiffré officiel Malcolm |
| `localos` | Oui | OpenSearch est local au Principal |
| `email` | Non, sauf SMTP déjà prêt | Fonction optionnelle |
| `netbox` | Oui | Générer les secrets du NetBox neuf |
| `postgres` | Oui | Générer le secret de la base neuve |
| `valkey` | Oui | Générer le secret du magasin interne |
| `arkime` | Oui | Créer le secret Arkime commun à conserver |

Si `method=keycloak` est choisi à la place de `basic`, l'assistant ouvre des
questions supplémentaires pour configurer Keycloak et éventuellement le RBAC.
Ce choix doit être intentionnel : il modifie le parcours d'authentification et
nécessite une validation spécifique des rôles, des groupes et des comptes.

## 5. Ce Qui Se Passe Après La Validation

Une fois `auth_setup` terminé, la commande `./oculox install principal` reprend
automatiquement :

1. le rôle Principal est consolidé ;
2. la PKI mTLS Oculox est générée ;
3. les configurations des deux Logstash sont produites ;
4. Filebeat est configuré avec la répartition de charge ;
5. Docker Compose est validé ;
6. les images manquantes sont récupérées ;
7. les services sont démarrés ;
8. leur état est affiché par `./oculox status`.

Il ne faut pas ouvrir un second terminal pour relancer l'installation pendant
que cet assistant est actif.

## 6. Règles De Sécurité A Respecter

- Ne jamais versionner les fichiers contenant les secrets générés.
- Ne jamais placer les mots de passe dans une commande, une capture ou un
  rapport.
- Sauvegarder les secrets Arkime nécessaires aux futurs collecteurs.
- Sauvegarder NetBox et PostgreSQL avant toute rotation de leurs mots de passe.
- Remplacer les certificats web auto-signés par des certificats approuvés pour
  une mise en production.
- Restreindre les ports Logstash aux adresses des collecteurs, même lorsque le
  mTLS est actif.
- Conserver la clé privée de l'autorité Oculox uniquement sur le Principal.

## 7. Résumé Simple

Le compte `admin` protège l'accès humain, `webcerts` chiffre les accès web,
`fwcerts` protège le transport des journaux, `localos` sécurise les échanges
internes avec OpenSearch, `netbox`, `postgres` et `valkey` créent les secrets
des services internes, et `arkime` établit le secret partagé entre les viewers
Arkime. Sur ce serveur neuf, `all` est donc le bon choix, à condition de
conserver soigneusement les secrets demandés et de ne pas les publier.

## 8. Verification Apres L'Assistant

Une fois l'assistant terminé, les commandes d'exploitation sont :

```bash
./oculox start
./oculox status
```

Le résultat de `./oculox status` doit afficher les services du profil
`malcolm`, et non seulement les services de supervision déjà présents sur le
serveur. L'absence de conteneur Oculox signifie que le démarrage doit être
investigué avant de poursuivre avec la création d'un bundle Hedgehog.

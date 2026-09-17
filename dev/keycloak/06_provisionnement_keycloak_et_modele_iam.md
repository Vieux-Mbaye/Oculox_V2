# Provisionnement Keycloak Et Modele IAM

Ce document couvre K3 et K4. A ce stade, le portail reste en
`NGINX_AUTH_MODE=basic`. Keycloak est prepare mais ne remplace pas encore la
connexion Basic : cette bascule est la phase K5.

## But

Keycloak gere les identites humaines Oculox. Il ne remplace ni les comptes
techniques OpenSearch, ni le mTLS Filebeat vers Logstash. Il authentifie une
personne et remet un jeton OIDC contenant ses groupes et roles.

K3 rend la creation des objets **idempotente** : relancer la commande ne cree
pas de doublon. K4 fixe les droits avant de les appliquer dans Nginx et
OpenSearch.

## Fichiers Et Responsabilites

| Fichier | Role |
| --- | --- |
| `oculox` | Commandes operateur `keycloak provision`, `report` et `credentials`. |
| `dev/scripts/keycloak/configure-realm.py` | Prepare les variables runtime, genere les secrets hors Git, puis retire les secrets temporaires. |
| `keycloak/scripts/realm-setup.sh` | Reconcile le realm, groupes, roles, clients OIDC, mappers et comptes operationnels avec `kcadm.sh`. |
| `keycloak/scripts/docker-entrypoint.sh` | Force PostgreSQL pendant le provisionnement. |
| `keycloak/scripts/hardening-preflight.sh` | Refuse une configuration insuffisamment durcie avant ecriture. |
| `config/keycloak.env.example` | Contrat sans secret. Les vraies valeurs sont dans `config/keycloak.env`, ignore par Git. |
| `dev/generated/keycloak-initial-credentials.env` | Identifiants bootstrap et operationnels, permissions `0600`, ignore par Git. |
| `dev/generated/keycloak-provisioning/realm-report.json` | Preuve JSON non secrete du resultat. |

Les scripts sont montes en lecture seule dans
`dev/compose/docker-compose.dev.yml`. Les donnees Keycloak restent dans
PostgreSQL, pas dans l'image ni dans le depot.

## Deroulement

Commande operateur :

```bash
cd ~/ICSHUB/Oculox
./oculox keycloak provision
```

1. `configure-realm.py prepare` derive les URL depuis
   `dev/generated/public-endpoint.env`, genere les secrets manquants et
   active temporairement `KEYCLOAK_PROVISIONING_ENABLED=true`. Il conserve
   `NGINX_AUTH_MODE=basic`.
2. Keycloak demarre avec `KC_DB=postgres`, donc le realm est persistant dans
   la base PostgreSQL `keycloak`.
3. Le script essaie le compte durable `oculox-realm-provisioner` du realm
   `master`.
4. Lors d'une premiere installation, ce compte n'existe pas. Oculox lance la
   commande officielle `kc.sh bootstrap-admin service`, qui cree
   `oculox-bootstrap-recovery`, uniquement pour l'amorcage.
5. Ce bootstrap attribue le role d'administration `admin` au provisionneur
   durable. Les prochains reruns fonctionnent sans compte humain.
6. `realm-setup.sh` cree ou met a jour les objets du realm `oculox`.
7. Le script ecrit `realm-report.json` et exige `"result": "PASS"`.
8. Le client de recuperation et les mots de passe temporaires de
   `config/keycloak.env` sont retires. Les secrets permanents des clients
   OIDC et du provisionneur restent uniquement dans le fichier runtime ignore
   par Git.

Un second lancement met a jour les roles, redirections et mappers, mais ne
reinitialise jamais les mots de passe d'utilisateurs existants. Cela respecte
l'historique des mots de passe Keycloak et ne casse pas un compte en production.

## Realm Et Clients OIDC

Le realm est `oculox`; `master` reste reserve a l'administration Keycloak.
Cette separation empeche un utilisateur Oculox de devenir administrateur
Keycloak par erreur.

Le realm impose : mot de passe de 14 caracteres avec complexite et historique,
anti-bruteforce apres cinq echecs, jeton d'acces de cinq minutes, session
inactive de 30 minutes, session maximale de huit heures, rotation des refresh
tokens et evenements d'authentification et d'administration. TOTP est prepare
comme action obligatoire pour les nouveaux comptes.

| Client | Usage futur | Redirection exacte |
| --- | --- | --- |
| `oculox-portal` | Portail Nginx sur 443 | `https://<core>/index.html` |
| `oculox-dashboards` | Dashboards sur 5601 | `https://<core>:5601/dashboards/auth/openid/login` |

Les deux sont des clients confidentiels : leur secret reste cote serveur.
Seul le flux Authorization Code est autorise. Direct Access Grant et Implicit
sont desactives. Les redirections n'acceptent aucun joker. Les mappers ajoutent
roles, groupes et audience au jeton, afin que les applications puissent
appliquer les droits.

## Matrice IAM

Un groupe represente une fonction. Les utilisateurs rejoignent des groupes et
les groupes recoivent les roles. Cette approche evite les droits attribues
manuellement a chaque personne.

| Groupe | Roles | But |
| --- | --- | --- |
| `/oculox-users` | aucun role metier | Groupe d'entree obligatoire du futur portail. |
| `/oculox-admins` | `admin` | Administration Oculox. |
| `/oculox-analysts` | `read_write_access`, `dashboards_read_write_access`, `arkime_hunt_access` | Analyse et investigation. |
| `/oculox-viewers` | `read_access`, `dashboards_read_access`, `arkime_read_access` | Consultation seulement. |
| `/oculox-incident-response` | `read_access`, `dashboards_read_access`, `arkime_pcap_access`, `arkime_hunt_access` | Lecture Dashboards et investigation PCAP/Hunt sans ecriture generale. |

Les comptes operationnels de demonstration prouvent la matrice : administrateur,
analyste, lecteur, intervenant incident et `oculox-denied` sans groupe. Leurs
mots de passe sont dans le fichier runtime a droits `0600`, jamais dans Git ni
dans un rapport.

K4 definit le contrat dans Keycloak. K5 l'appliquera dans Nginx et K6 dans
Dashboards/OpenSearch. Avant ces deux phases, un groupe Keycloak ne bloque pas
encore une route car le portail est toujours en Basic.

## Commandes De Controle

Rapport non sensible :

```bash
./oculox keycloak report
```

Attendu : `"result": "PASS"`, cinq groupes, sept roles et deux clients.
Le rapport montre aussi les groupes des comptes operationnels, les flux OIDC et les
protections de realm.

Verifier le mode sans afficher de secret :

```bash
grep -E '^(NGINX_AUTH_MODE|KEYCLOAK_PROVISIONING_ENABLED|KEYCLOAK_AUTH_REALM|KEYCLOAK_PORTAL_CLIENT_ID|KEYCLOAK_DASHBOARDS_CLIENT_ID)=' config/auth-common.env config/keycloak.env
```

Attendu apres succes : `NGINX_AUTH_MODE=basic` et
`KEYCLOAK_PROVISIONING_ENABLED=false`.

Afficher les identifiants initiaux seulement dans un terminal prive :

```bash
./oculox keycloak credentials
```

Cette commande lit `dev/generated/keycloak-initial-credentials.env`. Les mots
de passe doivent etre modifies a la premiere connexion avant K5.

Tester l'idempotence :

```bash
./oculox keycloak provision
./oculox keycloak report
```

Le second passage doit finir avec `PASS`, garder un seul realm et un seul
client de chaque type, sans reinitialiser de mot de passe.

## Gestion Des Utilisateurs

Arrivee : creer la personne dans `oculox`, l'ajouter a `/oculox-users`,
puis a son groupe metier.

Changement de fonction : retirer l'ancien groupe metier avant d'ajouter le
nouveau. Ne pas cumuler les groupes par defaut.

Depart : desactiver l'utilisateur, retirer les groupes et revoquer ses
sessions. Conserver les evenements d'audit pour une enquete eventuelle.

Les comptes techniques restent hors de cette matrice : Logstash, Arkime,
OpenSearch et Filebeat n'utilisent pas de compte humain Keycloak. Ainsi, une
panne SSO ne bloque pas l'ingestion industrielle.

## Limites Actuelles

- K3/K4 ne basculent pas Nginx vers OIDC : Basic reste actif jusqu'a K5.
- K3/K4 ne configurent pas le domaine OIDC d'OpenSearch : cela appartient a K6.
- La demonstration TOTP et la politique MFA des comptes existants sont prevues
  en K7.

## Sources Officielles

- [Keycloak - Bootstrap admin and recovery](https://www.keycloak.org/server/bootstrap-admin-recovery)
- [Keycloak - Server Administration Guide](https://www.keycloak.org/docs/latest/server_admin/)
- [Keycloak - OIDC layers](https://www.keycloak.org/securing-apps/oidc-layers)
- [Keycloak - Securing applications](https://www.keycloak.org/guides/securing-apps/)

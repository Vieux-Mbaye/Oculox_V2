# Phase K7 - Durcissement Fonctionnel

## Objectif

Cette phase transforme la configuration Keycloak active en configuration
contrôlable. Le but n'est pas seulement de dire que Keycloak marche, mais de
prouver que les protections importantes sont réellement présentes.

## Commande Principale

```bash
./oculox keycloak verify-hardening
```

Cette commande ne montre pas les secrets. Elle lit les fichiers runtime locaux
et le rapport de provisionnement du realm, puis retourne `PASS` uniquement si
les contrôles de sécurité sont vrais.

## Ce Qui Est Vérifié

- le portail utilise Keycloak ;
- le RBAC est actif ;
- l'entrée dans Oculox exige le groupe `/oculox-users` ;
- Dashboards utilise OIDC ;
- le realm est `oculox`, pas `master` ;
- l'URL publique et l'URL Keycloak sont en HTTPS ;
- `KC_HOSTNAME_STRICT=true` ;
- la vérification TLS Keycloak est active ;
- le MFA TOTP est demandé aux utilisateurs ;
- la protection contre les essais répétés est active ;
- les refresh tokens sont renouvelés ;
- les access tokens restent courts ;
- les événements et événements d'administration sont activés ;
- la console d'administration Keycloak est limitée à localhost et aux réseaux privés ;
- les URI de redirection sont exactes ;
- les clients navigateur n'ont pas le Direct Access Grant ;
- le mode provisionnement est désactivé après application ;
- les secrets temporaires bootstrap et test ne restent pas dans le runtime ;
- les fichiers sensibles ne sont pas lisibles par les autres utilisateurs ;
- les fichiers sensibles générés ne sont pas suivis par Git.

## Fichiers Touchés

| Fichier | Rôle |
| --- | --- |
| `keycloak/scripts/hardening-preflight.sh` | bloque une activation dangereuse avant provisionnement |
| `keycloak/scripts/realm-setup.sh` | ajoute les preuves MFA, sessions et audit dans le rapport du realm |
| `nginx/nginx_keycloak_location.conf` | limite `/keycloak/admin` à localhost et aux réseaux privés |
| `dev/scripts/keycloak/verify-functional-hardening.py` | vérifie le durcissement après activation |
| `dev/tests/keycloak/test_functional_hardening.py` | teste les cas positifs et négatifs du vérificateur |
| `oculox` | expose `./oculox keycloak verify-hardening` |
| `dev/keycloak/02_plan_developpement_keycloak_oculox.md` | met à jour l'état de K7 |

## Comment Lire Le Résultat

Un résultat normal contient :

```json
{
  "kind": "keycloak-functional-hardening",
  "result": "PASS"
}
```

Si une ligne vaut `false`, la mesure correspondante n'est pas respectée. Par
exemple, `mfa_required: false` veut dire que Keycloak ne demandera pas
l'enrôlement TOTP. `temporary_runtime_secrets_cleared: false` veut dire qu'un
secret temporaire de bootstrap ou de test est encore présent dans
`config/keycloak.env`.

## Commandes De Contrôle

```bash
./oculox keycloak report
./oculox keycloak verify-portal
./oculox keycloak verify-dashboards
./oculox keycloak verify-hardening
```

Pour vérifier les fichiers sensibles :

```bash
stat -c '%a %n' config/keycloak.env config/auth-common.env config/dashboards.env dev/generated/keycloak-initial-credentials.env
```

La permission attendue est `600`.

Pour vérifier qu'ils ne sont pas suivis par Git :

```bash
git ls-files -- config/keycloak.env config/auth-common.env config/dashboards.env dev/generated/keycloak-initial-credentials.env nginx/certs
```

La sortie attendue est vide.

# Keycloak Dans Oculox

Keycloak fournit l'identite centrale de la plateforme.

Il gere :

- les utilisateurs humains ;
- le SSO ;
- le MFA/OTP ;
- les groupes ;
- les roles ;
- les clients OIDC du portail et de Dashboards.

## Realm Principal

Le realm applicatif est :

```text
oculox
```

Le realm `master` reste reserve a l'administration Keycloak.

## Clients OIDC

| Client | Application | Redirect URI |
|---|---|---|
| `oculox-portal` | Portail Oculox protege par Nginx | `https://<IP_CORE>/index.html` |
| `oculox-dashboards` | OpenSearch Dashboards | `https://<IP_CORE>:5601/dashboards/auth/openid/login` |

Chaque client a son propre secret. Cela evite qu'un secret compromis pour une
application donne automatiquement acces a toutes les integrations.

## Groupes Et Roles

Les groupes principaux sont :

```text
oculox-users
oculox-admins
oculox-analysts
oculox-viewers
oculox-incident-response
```

Tous les utilisateurs autorises doivent etre dans `/oculox-users`. Les groupes
specialises portent ensuite les roles metier.

## Scripts

| Script | Role |
|---|---|
| `scripts/docker-entrypoint.sh` | Prepare Keycloak au demarrage du conteneur |
| `scripts/hardening-preflight.sh` | Refuse une configuration trop faible avant activation |
| `scripts/realm-setup.sh` | Cree/verifie realm, clients, groupes, roles et comptes |

L'exploitation ordinaire passe par :

```bash
./oculox keycloak provision
./oculox keycloak verify-hardening
./oculox keycloak credentials
./oculox keycloak report
```

## Principe De Securite

- pas de direct grant pour les clients navigateur ;
- pas d'implicit flow ;
- MFA obligatoire ;
- tokens courts ;
- roles separes par profil ;
- secrets dans `config/keycloak.env`, ignore par Git ;
- provisionnement desactive apres application reussie.

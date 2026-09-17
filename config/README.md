# Configuration Oculox

Ce repertoire contient les contrats de configuration charges par Docker Compose.

## Regle De Securite

```text
*.env.example = modele versionne, sans secret
*.env         = valeur reelle locale, ignoree par Git
```

Ne jamais ajouter a Git un fichier `*.env` reel. Ces fichiers peuvent contenir
des mots de passe, secrets OIDC, URLs internes ou informations propres a une VM.

## Fichiers Principaux

| Fichier | Role |
|---|---|
| `auth-common.env.example` | Mode d'authentification, groupes requis et noms des roles RBAC |
| `keycloak.env.example` | Contrat Keycloak : realm, clients OIDC, hostname, MFA, durees de session |
| `dashboards.env.example` | URL interne Dashboards et mode d'authentification Dashboards |
| `opensearch.env.example` | Choix OpenSearch local/distant et endpoint backend |
| `ssl.env.example` | Parametres TLS generaux |
| `process.env.example` | Parametres runtime communs |

## Chaines De Configuration

### Portail Oculox

```text
auth-common.env
  -> NGINX_AUTH_MODE=keycloak
  -> NGINX_REQUIRE_GROUP=/oculox-users
  -> ROLE_BASED_ACCESS=true

keycloak.env
  -> KEYCLOAK_AUTH_URL
  -> KEYCLOAK_NGINX_CONNECT_URL
  -> KEYCLOAK_CLIENT_ID
  -> KEYCLOAK_CLIENT_SECRET
```

Nginx lit ces valeurs pour rediriger vers Keycloak et controler les droits du
portail.

### OpenSearch Dashboards

```text
dashboards.env
  -> DASHBOARDS_AUTH_TYPE=openid

keycloak.env
  -> KEYCLOAK_DASHBOARDS_CLIENT_ID
  -> KEYCLOAK_DASHBOARDS_CLIENT_SECRET
  -> KEYCLOAK_DASHBOARDS_REDIRECT_URI
  -> KEYCLOAK_DASHBOARDS_CONNECT_URL

opensearch.env
  -> OPENSEARCH_URL
  -> OPENSEARCH_PRIMARY
```

Dashboards utilise ces valeurs pour faire son propre login OIDC et parler au
cluster OpenSearch.

## VM Neuves Et IP Differentes

Ne copiez pas manuellement un ancien `config/keycloak.env` vers une nouvelle VM
si l'adresse du Core change. Il faut relancer :

```bash
./oculox prepare principal --server-name <IP_CORE_OU_DNS>
```

ou l'installation complete :

```bash
./oculox install principal --server-name <IP_CORE_OU_DNS> --opensearch-bundle <bundle>
```

Ces commandes recalculent les URLs publiques, les redirect URIs OIDC et les
certificats Web.

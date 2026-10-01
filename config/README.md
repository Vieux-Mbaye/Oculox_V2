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
| `filebeat.env.example` | Ingestion Zeek/Suricata, logs tiers, syslog et port Filebeat hote |
| `nginx.env.example` | Reverse proxy et publication des logs d'acces/erreur vers OpenSearch |
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

### Logs Hote Et Dashboards Tiers

```text
nginx.env
  -> NGINX_LOG_ACCESS_AND_ERRORS=true

filebeat.env
  -> FILEBEAT_TCP_LISTEN=true
  -> FILEBEAT_TCP_PORT=5055
  -> FILEBEAT_SYSLOG_TCP_LISTEN=true
  -> FILEBEAT_SYSLOG_TCP_PORT=5514
  -> FILEBEAT_SYSLOG_UDP_LISTEN=true
  -> FILEBEAT_SYSLOG_UDP_PORT=5514
```

Ces valeurs activent les entrees necessaires aux dashboards systeme : logs
Nginx, messages syslog externes et evenements Fluent Bit hote. Le port `5055`
est volontairement separe du port `5045`, qui reste le point d'entree du
deuxieme Logstash Oculox.

## VM Neuves Et IP Differentes

Pour EJBCA, consulter la [reference trois VM et bundles](../dev/ejbca/docs/installation_3_vm_et_bundles.md).
Le parcours `prepare principal` appelle encore des generateurs PKI locaux :
sur une plateforme deja equipee de certificats EJBCA, ne pas l'utiliser comme
une rotation automatique. Le changement des SAN doit etre coordonne avec
l'enrolement et la confiance des clients.

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

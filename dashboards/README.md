# OpenSearch Dashboards Dans Oculox

Ce repertoire contient l'adaptation Oculox d'OpenSearch Dashboards.

## Fichiers Importants

| Fichier | Role |
|---|---|
| `opensearch_dashboards.yml` | Template de configuration Dashboards |
| `scripts/docker_entrypoint.sh` | Injecte les credentials OpenSearch, le mode auth et les parametres OIDC |
| `scripts/shared-object-creation.sh` | Creation des objets Dashboards necessaires |
| `scripts/index-refresh.py` | Rafraichissement des index patterns/data views |
| `templates/` | Templates OpenSearch utilises par Dashboards helper |
| `dashboards/` | Objets et definitions de dashboards importes |

## Generation Runtime

Le fichier source `opensearch_dashboards.yml` est un template. Au demarrage,
`scripts/docker_entrypoint.sh` le copie vers :

```text
/usr/share/opensearch-dashboards/config/opensearch_dashboards.yml
```

Puis il remplace :

```text
_MALCOLM_DASHBOARDS_OPENSEARCH_USER_
_MALCOLM_DASHBOARDS_OPENSEARCH_PASSWORD_
_MALCOLM_DASHBOARDS_COOKIE_PASSWORD_
_MALCOLM_DASHBOARDS_OPENSEARCH_SSL_VERIFICATION_MODE_
_MALCOLM_DASHBOARDS_AUTH_TYPE_
```

Les identifiants OpenSearch viennent de `.opensearch.primary.curlrc`, monte en
lecture seule dans le conteneur. Ce fichier est ignore par Git.

## Authentification OIDC

`config/dashboards.env` definit :

```text
DASHBOARDS_AUTH_TYPE=openid
```

Lorsque cette valeur est active, l'entrypoint ajoute :

```yaml
opensearch_security.openid.connect_url
opensearch_security.openid.client_id
opensearch_security.openid.client_secret
opensearch_security.openid.base_redirect_url
opensearch_security.openid.verify_hostnames
```

Ces valeurs viennent de `config/keycloak.env`.

## Dependances

Dashboards doit joindre :

- Keycloak pour l'OIDC ;
- OpenSearch pour les donnees et les objets sauvegardes ;
- la CA OpenSearch montee dans `/var/local/ca-trust/`.

Si OpenSearch est inaccessible, l'authentification Dashboards peut boucler ou
retourner `No Living connections` meme si Keycloak fonctionne.

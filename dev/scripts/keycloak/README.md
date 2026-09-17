# Scripts Keycloak

Ces scripts automatisent la configuration portable Keycloak/OIDC d'Oculox.

Ils sont normalement appeles par `./oculox keycloak ...`. Un operateur ne doit
les lancer directement que pour diagnostic ou developpement.

## Scripts

| Script | Role |
|---|---|
| `configure-portal-auth.py` | Active/desactive l'authentification Keycloak du portail |
| `configure-dashboards-oidc.py` | Active/desactive OIDC dans OpenSearch Dashboards |
| `configure-realm.py` | Prepare `config/keycloak.env` et les valeurs attendues du realm |
| `verify-functional-hardening.py` | Verifie le durcissement fonctionnel Keycloak/OIDC |
| `capture-baseline.sh` | Capture l'etat des fichiers critiques avant modification |

## Flux Normal

```bash
./oculox keycloak provision
./oculox keycloak activate-portal
./oculox keycloak activate-dashboards
./oculox keycloak verify-hardening
```

## Fichiers Manipules

```text
config/auth-common.env
config/keycloak.env
config/dashboards.env
keycloak/scripts/realm-setup.sh
dashboards/opensearch_dashboards.yml
nginx/nginx_auth_keycloak.conf
```

Les scripts ne doivent jamais ecrire de secret dans Git. Les valeurs reelles
restent dans `config/*.env`, ignores par le depot.

## VM Neuves

Lorsqu'une VM Core change d'adresse ou de nom DNS, il faut regenerer les URLs :

```bash
./dev/scripts/configure-public-endpoint.py --public-host <IP_CORE_OU_DNS>
```

ou relancer la preparation :

```bash
./oculox prepare principal --server-name <IP_CORE_OU_DNS>
```

Cela remet en coherence :

- `KEYCLOAK_AUTH_URL` ;
- `KC_HOSTNAME` ;
- `KEYCLOAK_DASHBOARDS_REDIRECT_URI` ;
- les redirect URIs du portail.

## Validation

```bash
python3 -m unittest discover -s dev/tests/keycloak -p 'test_*.py'
./oculox keycloak verify-hardening
```

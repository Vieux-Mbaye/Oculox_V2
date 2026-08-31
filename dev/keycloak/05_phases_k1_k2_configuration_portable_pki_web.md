# K1 Et K2 - Configuration Portable Et PKI Web

## 1. Ce Qui A Été Résolu

Avant ce développement, l'installation recevait un nom de serveur, mais cette
valeur ne formait pas un contrat unique pour l'URL publique, l'URL Keycloak et
le certificat HTTPS. Le certificat Nginx pouvait donc rester un certificat
local sans SAN correspondant à l'adresse réellement utilisée dans le
navigateur.

K1 crée une seule identité publique à partir d'une valeur fournie au runtime :
une IPv4, une IPv6 ou un nom DNS. K2 utilise ensuite exactement cette identité
pour produire ou valider le certificat web. Une même révision Git peut ainsi
être installée sur une autre VM sans remplacer d'adresse dans les sources.

Ces phases ne basculent pas encore l'authentification vers Keycloak. Le mode
actif reste `basic` jusqu'à K5.

## 2. Chaîne De Configuration

Pour un Core utilisant l'adresse `192.168.1.174`, la commande principale est :

```bash
./oculox prepare principal --server-name 192.168.1.174
```

Le lanceur exécute, dans cet ordre :

1. `configure-deployment-role.py` écrit le rôle `principal` ;
2. `configure-public-endpoint.py` valide et centralise l'identité publique ;
3. `generate-web-pki.sh` crée et publie la PKI Web ;
4. `generate-beats-pki.sh` gère séparément la PKI mTLS Filebeat/Logstash ;
5. la configuration Filebeat haute disponibilité est rendue.

Cette séparation est importante : la PKI Web protège les connexions des
navigateurs et le futur OIDC, alors que la PKI Beats authentifie les machines
Filebeat et Logstash. La PKI OpenSearch constitue encore une troisième chaîne.

## 3. Phase K1 - Identité Publique Portable

### 3.1 Script Principal

Le fichier `dev/scripts/configure-public-endpoint.py` reçoit uniquement un
hôte, pas une URL complète. Il accepte par exemple :

```text
192.168.1.174
core.oculox.example
2001:db8::25
```

Il refuse `http://...`, `https://...`, un chemin et un nom DNS invalide. Le
script peut ainsi construire lui-même des URL HTTPS cohérentes et empêcher
qu'une partie de la plateforme utilise une autre adresse.

Pour une IPv4, il produit :

```text
OCULOX_PUBLIC_HOST=192.168.1.174
OCULOX_PUBLIC_IDENTITY_TYPE=ipv4
OCULOX_PUBLIC_SAN=IP:192.168.1.174
OCULOX_PUBLIC_URL=https://192.168.1.174
OCULOX_KEYCLOAK_URL=https://192.168.1.174/keycloak
```

Pour un DNS, le SAN devient `DNS:core.oculox.example`. Pour une IPv6, l'URL
utilise les crochets requis, par exemple `https://[2001:db8::25]`.

### 3.2 Fichiers Runtime Modifiés

`dev/generated/public-endpoint.env` est la source runtime de l'identité Web.
Il est ignoré par Git et possède le mode `600`.

`dev/generated/deployment.env` conserve le rôle de la machine et reçoit aussi
l'URL publique et l'URL Keycloak dérivées.

`config/keycloak.env` reçoit les paramètres publics suivants :

```text
KEYCLOAK_AUTH_REALM=oculox
KEYCLOAK_BOOTSTRAP_REALM=master
KEYCLOAK_AUTH_REDIRECT_URI=/index.html
KEYCLOAK_AUTH_URL=https://<hôte>/keycloak
KEYCLOAK_SSL_VERIFY=true
KC_HOSTNAME=https://<hôte>/keycloak
KC_HOSTNAME_STRICT=true
```

Le script ne reconstruit pas tout `config/keycloak.env`. Il remplace seulement
les clés qu'il possède. Les secrets OIDC et les autres réglages existants sont
conservés. Si le contenu est déjà correct, il ne réécrit pas le fichier.

`KC_HOSTNAME` indique à Keycloak son adresse publique canonique. Cela lui
permettra de produire des liens, redirections et jetons contenant le bon
issuer. `KC_HOSTNAME_STRICT=true` empêchera un en-tête HTTP arbitraire de faire
changer cette identité.

## 4. Phase K2 - PKI Web De Développement

### 4.1 Notions Simples

Une CA, ou autorité de certification, possède une clé privée qui signe les
certificats. Nginx présente son certificat serveur au navigateur. Le navigateur
vérifie la signature avec le certificat public de la CA, puis vérifie que le
SAN correspond exactement à l'IP ou au DNS demandé.

Le SAN, `Subject Alternative Name`, est la liste officielle des identités
acceptées par le certificat. Un simple `CN=localhost` ne suffit pas pour
`https://192.168.1.174`.

La clé privée de la CA peut signer de nouveaux certificats. Elle reste donc
dans le répertoire privé du déploiement. Le bundle distribué aux clients ne
contient que le certificat public de cette CA.

### 4.2 Génération OpenSSL

Le fichier `dev/scripts/generate-web-pki.sh` automatise les opérations OpenSSL.
En mode de développement, il effectue l'équivalent des étapes suivantes :

```bash
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out ca.key
openssl req -x509 -new -sha256 -days 3650 -key ca.key -subj "/O=Oculox/OU=Development Web PKI/CN=Oculox Development Web CA" -out ca.crt
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out server.key
openssl req -new -sha256 -key server.key -subj "/O=Oculox/OU=Web/CN=<hôte>" -out server.csr
openssl x509 -req -sha256 -days 397 -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -extfile server.ext -out server.crt
```

Le script ajoute aussi les contraintes de CA, l'usage `serverAuth` et le SAN
runtime dans les extensions OpenSSL. Les commandes ci-dessus expliquent la
chaîne ; en exploitation, il faut exécuter le script afin de conserver toutes
les validations et permissions.

### 4.3 Emplacement Des Fichiers

| Emplacement | Contenu | Sensibilité |
| --- | --- | --- |
| `dev/generated/web-pki/ca.key` | clé privée de la CA Web | privée, `600` |
| `dev/generated/web-pki/ca.crt` | certificat public de la CA | public |
| `dev/generated/web-pki/server.key` | clé privée de Nginx | privée, `600` |
| `dev/generated/web-pki/server.crt` | certificat signé de Nginx | public |
| `nginx/certs/key.pem` | copie runtime de la clé Nginx | privée, `600` |
| `nginx/certs/cert.pem` | copie runtime du certificat Nginx | public |
| `nginx/ca-trust/oculox-web-ca.crt` | CA montée dans les conteneurs | public |
| `dev/generated/web-trust/` | bundle à distribuer aux clients | public, sans clé |

Tous ces chemins runtime sont ignorés par Git. Le bundle public contient
`oculox-web-ca.crt`, `endpoint.env` et `SHA256SUMS`, jamais une clé privée.

### 4.4 Ce Que Nginx Et Dashboards Utilisent

Nginx lit `nginx/certs/cert.pem` et `nginx/certs/key.pem`. Lors de la connexion
HTTPS, c'est donc Nginx qui présente le certificat signé par la CA Web.

Dashboards est une application Node.js. Le fichier
`dev/compose/docker-compose.dev.yml` lui fournit :

```text
NODE_EXTRA_CA_CERTS=/var/local/ca-trust/oculox-web-ca.crt
```

Le répertoire `nginx/ca-trust` est déjà monté en lecture seule dans les
conteneurs. Cette variable permet à Dashboards de reconnaître la CA Web quand
il communiquera avec Keycloak en HTTPS durant K6.

OpenSearch devra également reconnaître cette CA pour joindre les métadonnées
OIDC ou les clés JWKS de Keycloak. K2 prépare le bundle de confiance, mais ne
modifie pas silencieusement un cluster distant. L'installation explicite côté
OpenSearch sera réalisée et testée en K6.

## 5. Réexécution Et Changement D'Adresse

Si l'identité ne change pas, `generate-web-pki.sh` conserve la CA et le
certificat valides. La commande est donc idempotente.

Si l'IP ou le DNS change, le script conserve la CA du déploiement mais émet une
nouvelle clé et un nouveau certificat serveur avec le nouveau SAN. Les clients
qui font déjà confiance à cette CA n'ont pas besoin d'importer une nouvelle CA.

`--force` supprime et régénère volontairement toute la PKI Web de
développement. Cela constitue une rotation de CA : tous les clients doivent
alors recevoir le nouveau certificat de CA.

Pour appliquer une nouvelle adresse :

```bash
./oculox prepare principal --server-name <nouvelle-IP-ou-nouveau-DNS>
./oculox restart nginx-proxy dashboards
```

## 6. Certificat Fourni En Production

En production, une PKI d'entreprise ou une CA publique peut fournir le
certificat. Le mode `provided` vérifie le SAN, la chaîne de confiance et la
correspondance entre certificat et clé avant toute installation :

```bash
./dev/scripts/configure-public-endpoint.py --public-host core.oculox.example
./dev/scripts/generate-web-pki.sh --mode provided --certificate /chemin/core.crt --private-key /chemin/core.key --ca-certificate /chemin/ca.crt
```

Un certificat incorrect est refusé. La clé privée fournie n'entre jamais dans
le bundle public.

## 7. Vérifications Manuelles

Afficher l'identité calculée :

```bash
cat dev/generated/public-endpoint.env
```

Vérifier la chaîne et le SAN du certificat local :

```bash
openssl verify -CAfile dev/generated/web-pki/ca.crt dev/generated/web-pki/server.crt
openssl x509 -in dev/generated/web-pki/server.crt -noout -subject -issuer -dates -ext subjectAltName
```

Vérifier le contenu du bundle public :

```bash
cd dev/generated/web-trust && sha256sum -c SHA256SUMS
find . -maxdepth 1 -type f -printf '%f\n'
```

Après retour à la racine du dépôt, vérifier le certificat réellement présenté
par Nginx :

```bash
cd ../../..
openssl s_client -connect 192.168.1.174:443 -CAfile dev/generated/web-trust/oculox-web-ca.crt -verify_return_error </dev/null 2>&1 | grep -E 'subject=|issuer=|Verify return code'
```

Un appel sans CA doit échouer avec une erreur de certificat :

```bash
curl --silent --show-error https://192.168.1.174/ -o /dev/null
```

Le même appel avec la CA doit réussir au niveau TLS. Le code `401` est normal
tant que l'authentification Basic est active :

```bash
curl --silent --show-error --cacert dev/generated/web-trust/oculox-web-ca.crt -o /dev/null -w 'HTTP %{http_code}\n' https://192.168.1.174/
```

Vérifier Dashboards :

```bash
curl --silent --show-error --config .opensearch.primary.curlrc --cacert dev/generated/web-trust/oculox-web-ca.crt https://192.168.1.174:5601/dashboards/api/status | jq '.status.overall, (.status.statuses[] | select(.id | startswith("core:opensearch")))'
```

Pour une autre VM, remplacer uniquement l'adresse utilisée dans les commandes
de connexion. Les scripts et le dépôt ne doivent pas être modifiés.

## 8. Résultats Observés Le 31 Août 2026

Sur le Core local :

```text
identité publique     : https://192.168.1.174
SAN Nginx             : IP:192.168.1.174
issuer                : Oculox Development Web CA
OpenSSL verify        : 0 (ok)
appel sans CA         : refusé, curl code 60
appel avec CA         : TLS accepté, HTTP 401 attendu en mode Basic
Dashboards API        : HTTP 200, état green
connexion OpenSearch  : green
secret OIDC existant  : conservé
clé dans bundle public: aucune
```

## 9. Tests Automatisés

Le fichier `dev/tests/keycloak/test_portable_web_identity.py` vérifie :

- IPv4, IPv6 et DNS ;
- rejet des URL et identités invalides ;
- conservation des secrets et idempotence ;
- chaîne, SAN et permissions de la PKI ;
- renouvellement du certificat après changement d'adresse ;
- rotation contrôlée de la CA sans effacer de fichier étranger à la PKI ;
- refus TLS sans CA et succès avec CA ;
- validation d'un certificat fourni ;
- ordre d'exécution du lanceur ;
- absence des IP de laboratoire dans les sources génériques.

Le script `dev/scripts/keycloak/capture-baseline.sh` inclut désormais
l'identité publique, la PKI Web et le bundle de confiance dans ses sauvegardes
privées. La clé de CA reste ainsi récupérable lors d'un retour arrière, mais
elle n'est jamais ajoutée au dépôt.

## 10. Fichiers Touchés

| Fichier | Rôle |
| --- | --- |
| `oculox` | enchaîne identité, PKI Web et PKI Beats pendant `prepare principal` |
| `dev/scripts/configure-public-endpoint.py` | valide l'IP/DNS et dérive les URL et le SAN |
| `dev/scripts/generate-web-pki.sh` | génère ou installe le certificat Web et son bundle de confiance |
| `dev/compose/docker-compose.dev.yml` | ajoute la CA Web au magasin de confiance Node.js de Dashboards |
| `dev/scripts/keycloak/capture-baseline.sh` | sauvegarde aussi les nouveaux fichiers runtime |
| `dev/tests/keycloak/test_portable_web_identity.py` | tests automatiques K1/K2 |
| `dev/keycloak/02_plan_developpement_keycloak_oculox.md` | état du plan et résultats obtenus |

## 11. Références Officielles

- [Keycloak - Configuring the hostname](https://www.keycloak.org/server/hostname)
- [Keycloak - Configuring a reverse proxy](https://www.keycloak.org/server/reverseproxy)
- [OpenSSL x509](https://docs.openssl.org/3.6/man1/openssl-x509/)
- [OpenSSL verify](https://docs.openssl.org/3.6/man1/openssl-verify/)

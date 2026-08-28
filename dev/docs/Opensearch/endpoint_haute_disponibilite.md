# Étape endpoint - Endpoint OpenSearch stable

## 1. Resultat

La Étape endpoint a ete implementee et validee le 12 aout 2026 entre le poste local
Oculox et la VM OpenSearch `192.168.1.241`.

```text
OPENSEARCH_CLUSTER_ENDPOINT=https://192.168.1.241:9200
proxy=HAProxy 3.2.21
endpoint_health=PASS
anonymous_authentication=REJECTED
untrusted_ca=REJECTED
cluster=green
nodes=3
unassigned_shards=0
roundrobin_nodes=3/3
node_failure_survival=PASS
node_automatic_reintegration=PASS
```

La validation ne depend pas des serveurs `10.5.6.3` et `10.5.6.4`. Aucun
changement Oculox, Docker, reseau ou pare-feu n'a ete conserve sur ces serveurs.

## 2. Architecture retenue

Le service `opensearch-endpoint` est le seul point d'entree publie :

```text
poste local
    |
    | HTTPS + CA Oculox + authentification
    v
192.168.1.241:9200
    |
    | HAProxy : controle actif et round-robin
    +--> HTTPS verifie --> opensearch-1:9200
    +--> HTTPS verifie --> opensearch-2:9200
    +--> HTTPS verifie --> opensearch-3:9200
```

Les trois noeuds restent uniquement sur le reseau Docker interne
`oculox-opensearch-transport`. Ils ne publient aucun port hote. HAProxy est
rattache a ce reseau prive pour joindre les noeuds et a un second reseau
`oculox-opensearch-endpoint-ingress` pour permettre la publication hote.

## 3. TLS et authentification

HAProxy termine TLS avec le certificat d'endpoint contenant le SAN
`IP:192.168.1.241`, puis ouvre une nouvelle session TLS vers le noeud choisi.
Il verifie la CA et le SAN propre a chaque noeud avec un SNI distinct :

```text
opensearch-1
opensearch-2
opensearch-3
```

L'en-tete `Authorization` du client n'est ni remplace ni supprime. Il est
transmis au noeud OpenSearch choisi. Les controles actifs utilisent le compte
de lecture `oculox_api`; sa valeur Basic Auth est rendue dans un fichier local
ignore par Git et protege en `0600`.

Les fichiers TLS et la configuration contenant ce secret sont montes en
lecture seule. Le conteneur utilise l'UID/GID proprietaire des fichiers, un
systeme de fichiers racine en lecture seule, aucune capability Linux et
`no-new-privileges`.

## 4. Sante et bascule

Chaque noeud est interroge toutes les cinq secondes sur :

```text
GET /_cluster/health?local=true
```

Apres trois echecs consecutifs, il est retire de la rotation. Apres deux succes
consecutifs, il est reintegre. L'endpoint suivant retourne `200` tant qu'au
moins un backend est disponible, sinon `503` :

```text
GET https://192.168.1.241:9200/healthz
```

Lors du test, `opensearch-3` a ete arrete. HAProxy a journalise :

```text
Server opensearch_nodes/opensearch-3 is DOWN
2 active and 0 backup servers left
```

L'endpoint est reste disponible avec les deux autres noeuds. Apres le retour du
conteneur, HAProxy a journalise :

```text
Server opensearch_nodes/opensearch-3 is UP
3 active and 0 backup servers online
```

Le cluster est ensuite revenu `green`, avec trois noeuds et zero shard non
affecte.

## 5. Journaux et supervision

Les journaux HAProxy contiennent uniquement l'adresse client, le frontend, le
backend, le serveur choisi, le statut HTTP, le volume, les temps et la cause de
fin de session. Le chemin HTTP et l'en-tete `Authorization` ne sont pas
journalises.

Le pilote Docker `local` applique une rotation de trois fichiers de 50 Mo avec
compression. Le port interne `8404` expose `/healthz` et `/stats` uniquement
sur les reseaux Docker ; il n'est pas publie sur l'hote.

## 6. Verification depuis le poste local

Depuis la racine du depot :

```bash
set -a
source dev/generated/opensearch-cluster/security/accounts.env
set +a

CA=dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt
ENDPOINT=https://192.168.1.241:9200

curl --cacert "$CA" "$ENDPOINT/healthz"
curl --cacert "$CA" \
  -u "oculox_api:$OCULOX_API_PASSWORD" \
  "$ENDPOINT/_cluster/health?pretty"
```

Test automatise :

```bash
OPENSEARCH_CLUSTER_ENV_FILE="$PWD/dev/config/opensearch-cluster/cluster.env.example" \
  ./dev/tests/opensearch-cluster/test_endpoint_runtime.sh
```

Resultat attendu :

```text
endpoint_health=PASS
anonymous_authentication=REJECTED PASS
untrusted_ca=REJECTED PASS
cluster_green_nodes=3/3 PASS
roundrobin_nodes=3/3 PASS
ENDPOINT_PROXY_RUNTIME_RESULT=PASS
```

## 7. Generation et demarrage

Apres les phases PKI et Security, generer les fichiers locaux du proxy :

```bash
./dev/scripts/opensearch-cluster/render-endpoint-proxy-config.sh
```

Valider et demarrer uniquement l'endpoint :

```bash
docker compose \
  --env-file dev/config/opensearch-cluster/cluster.env.example \
  -f dev/compose/opensearch-cluster/compose.yml \
  config --quiet

docker compose \
  --env-file dev/config/opensearch-cluster/cluster.env.example \
  -f dev/compose/opensearch-cluster/compose.yml \
  up -d --no-deps opensearch-endpoint
```

Pour une VM neuve, adapter d'abord `OPENSEARCH_ENDPOINT_BIND_IP` et regenerer
le certificat d'endpoint avec cette meme IP. Une cle ou un certificat existant
ne doit pas etre remplace sans une rotation volontaire.

## 8. Fichiers de reference

```text
dev/compose/opensearch-cluster/compose.yml
dev/config/opensearch-cluster/cluster.env.example
dev/config/opensearch-cluster/haproxy.cfg.template
dev/scripts/opensearch-cluster/render-endpoint-proxy-config.sh
dev/tests/opensearch-cluster/test_endpoint_proxy.py
dev/tests/opensearch-cluster/test_endpoint_runtime.sh
dev/generated/opensearch-cluster/endpoint-proxy/haproxy.cfg
dev/generated/opensearch-cluster/endpoint-proxy/endpoint.pem
dev/generated/opensearch-cluster/endpoint-proxy/backend-ca.crt
```

Les trois derniers fichiers sont secrets ou derives de secrets et restent
ignores par Git.

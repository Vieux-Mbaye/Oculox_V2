# Phase K8 - Non-Régression Du Pipeline

## But

Le but de cette phase est de prouver que l'ajout de Keycloak ne casse pas le
pipeline industriel Oculox.

Keycloak doit servir aux utilisateurs humains : portail, Dashboards, SSO,
groupes et rôles. Il ne doit pas devenir un composant nécessaire pour traiter
le trafic industriel.

Le pipeline qui doit continuer à fonctionner est :

```text
PCAP ou capture réseau
 -> pcap-monitor
 -> Zeek et Suricata
 -> Filebeat
 -> Logstash 1 et Logstash 2
 -> cluster OpenSearch distant
 -> Dashboards et Arkime
```

## Principe Important

Keycloak n'est pas dans ce chemin d'ingestion.

Cela veut dire que si Keycloak tombe, les utilisateurs ne peuvent plus se
connecter normalement au portail ou à Dashboards, mais les machines doivent
continuer à traiter les événements.

Les services techniques continuent avec leurs mécanismes dédiés :

- Filebeat envoie vers Logstash ;
- Filebeat conserve son load balancing vers `logstash:5044` et
  `logstash-2:5044` ;
- Filebeat ne doit pas écrire directement dans OpenSearch ;
- Logstash écrit dans OpenSearch avec son compte technique limité ;
- Arkime écrit ses sessions directement dans OpenSearch avec son compte
  technique limité ;
- OpenSearch reste accessible via TLS avec la CA du cluster.

## Fichiers Et Commandes Utilisés

Les preuves de cette phase sont stockées localement ici :

```text
dev/generated/keycloak-validation/pipeline-non-regression/
```

Ce dossier contient des rapports runtime. Il ne contient pas de configuration
source à pousser dans Git.

Les trois fichiers de preuve produits sont :

```text
baseline-keycloak-up.json
collector-keycloak-down.json
final-keycloak-down.json
```

`baseline-keycloak-up.json` contient l'état avant injection : compteurs
Logstash, nombre de documents OpenSearch, nombre de sessions Arkime et état du
cluster.

`collector-keycloak-down.json` contient ce qui a été observé pendant l'injection
du PCAP alors que Keycloak était arrêté.

`final-keycloak-down.json` compare l'état final avec la baseline et décide si le
test passe ou échoue.

## Test Réalisé

État initial des services :

```text
./oculox status
```

Résultat observé :

```text
Core healthy
Keycloak healthy avant le test
Dashboards healthy
Logstash 1 healthy
Logstash 2 healthy
Filebeat healthy
Arkime healthy
pcap-monitor healthy
nginx-proxy healthy
```

Validation des clients techniques :

```text
./oculox verify clients
```

Résultat observé :

```text
CLIENT_CONNECTIVITY_RESULT=PASS
remote_endpoint=https://192.168.1.200:9200
logstash_authentication=HTTP 200, user=oculox_logstash
logstash-2_authentication=HTTP 200, user=oculox_logstash
arkime_authentication=HTTP 200, user=oculox_arkime
arkime-live_authentication=HTTP 200, user=oculox_arkime
dashboards_authentication=HTTP 200, user=oculox_dashboards
dashboards-helper_authentication=HTTP 200, user=oculox_dashboards_helper
pcap-monitor_authentication=HTTP 200, user=oculox_api
api_authentication=HTTP 200, user=oculox_api
filebeat loadbalance=True
filebeat direct_opensearch=False
arkime_direct_write=create 200, write 201, read 200, delete 200
```

Création de la baseline :

```text
./oculox verify ingestion baseline --output dev/generated/keycloak-validation/pipeline-non-regression/baseline-keycloak-up.json
```

Résultat important :

```text
OpenSearch health=green
documents=1002247
pipeline_documents=7285
arkime_sessions=994962
indexing_rejections=0
```

Arrêt volontaire de Keycloak :

```text
docker compose -f dev/generated/docker-compose.runtime.yml --profile malcolm stop keycloak
```

Injection d'un PCAP pendant que Keycloak est arrêté :

```text
./oculox verify ingestion inject --pcap pcap/processed/mnetsniff-wlo1_1786618984.pcap --run-id k8-keycloak-down-20260909 --output dev/generated/keycloak-validation/pipeline-non-regression/collector-keycloak-down.json --wait 300 --allow-core
```

Résultat important :

```text
packets=48087
accepted_by_monitor=true
suricata files_delta=1
suricata bytes_delta=8164
filebeat published=35
filebeat acked=35
filebeat failed=0
```

Le `files_delta` Zeek observé était négatif, mais ce n'est pas un échec dans ce
test : les fichiers de logs peuvent tourner pendant la mesure. Le contrôle
utilisé pour décider le résultat final est `zeek_events_produced=true`, et les
octets Zeek ont bien augmenté.

Finalisation du test :

```text
./oculox verify ingestion finalize --baseline dev/generated/keycloak-validation/pipeline-non-regression/baseline-keycloak-up.json --collector-report dev/generated/keycloak-validation/pipeline-non-regression/collector-keycloak-down.json --output dev/generated/keycloak-validation/pipeline-non-regression/final-keycloak-down.json
```

Résultat final :

```text
INGESTION_RESULT=PASS
```

Résumé du rapport final :

```json
{
  "result": "PASS",
  "filebeat": {
    "published": 35,
    "acked": 35,
    "failed": 0
  },
  "logstash_delta": {
    "logstash": {
      "in": 276,
      "out": 276,
      "filtered": 276
    },
    "logstash-2": {
      "in": 244,
      "out": 244,
      "filtered": 244
    }
  },
  "opensearch_delta": {
    "documents": 864,
    "pipeline_documents": 1,
    "arkime_sessions": 862,
    "indexing_rejections": 0,
    "indexing_failures": 0
  }
}
```

## Lecture Des Résultats

`filebeat published=35` veut dire que Filebeat a envoyé 35 lots ou événements
mesurés par le test.

`filebeat acked=35` veut dire que tout ce que Filebeat a envoyé a été accepté.

`filebeat failed=0` veut dire qu'aucune publication Filebeat n'a échoué pendant
le test.

Les compteurs Logstash montrent que les deux instances ont travaillé :

```text
logstash   in=276 out=276
logstash-2 in=244 out=244
```

Cela prouve que le load balancing Filebeat vers les deux Logstash n'a pas été
cassé par Keycloak.

Les compteurs OpenSearch montrent que le cluster distant a reçu de nouvelles
données :

```text
documents +864
pipeline_documents +1
arkime_sessions +862
```

Cela prouve que les événements de pipeline et les sessions Arkime continuent à
être indexés alors que Keycloak est indisponible.

Les erreurs OpenSearch restent à zéro :

```text
indexing_rejections=0
indexing_failures=0
```

Cela prouve que le cluster n'a pas rejeté les écritures pendant le test.

## Remise En Service De Keycloak

Après le test, Keycloak a été redémarré :

```text
docker compose -f dev/generated/docker-compose.runtime.yml --profile malcolm start keycloak
```

Les contrôles suivants ont ensuite été rejoués :

```text
./oculox keycloak verify-hardening
./oculox keycloak verify-portal
./oculox keycloak verify-dashboards
./oculox verify clients
./oculox status
```

Résultats :

```text
KEYCLOAK_HARDENING_RESULT=PASS
KEYCLOAK_PORTAL_RESULT=PASS
KEYCLOAK_DASHBOARDS_RESULT=PASS
CLIENT_CONNECTIVITY_RESULT=PASS
tous les conteneurs principaux sont healthy
```

## Conclusion

La phase K8 est validée.

Keycloak contrôle l'accès humain, mais il ne bloque pas l'ingestion technique.
Le pipeline PCAP, Zeek, Suricata, Filebeat, Logstash, Arkime et OpenSearch a
continué à fonctionner pendant une panne volontaire de Keycloak.

Cette phase confirme que l'intégration Keycloak respecte le principe de
séparation entre :

```text
authentification humaine
```

et :

```text
pipeline industriel machine à machine
```

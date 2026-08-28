# Validation des clients et du chemin d'ingestion

Ces contrôles sont destinés aux trois machines neuves du déploiement final :
la VM cluster, la VM Oculox Core et la VM collecteur Hedgehog. Chaque dépôt est
cloné et installé localement avec `./oculox`. Les tests ne contiennent aucune
adresse de serveur existant et ne contactent que les endpoints fournis par les
bundles de l'installation neuve.

## Validation indépendante des clients

Après le démarrage de Core, exécuter :

```bash
./oculox verify clients
```

Exécuter la même commande sur Hedgehog. Le contrôle vérifie les conteneurs, les
healthchecks, les fichiers d'identité montés, l'authentification de chaque
compte de service, les deux API Logstash, la route Nginx et une écriture Arkime
directe. Nginx est validé comme proxy HTTP ; il n'est pas un client OpenSearch.

Le contrôle Filebeat exige deux destinations Logstash, `loadbalance: true` et
l'absence de `output.elasticsearch` ou `output.opensearch`. Une variable
`OPENSEARCH_URL` présente dans l'environnement ne constitue donc pas une sortie
Filebeat.

## Test d'ingestion réparti entre les deux VM

Sur Core, prendre les compteurs avant l'injection :

```bash
./oculox verify ingestion baseline --output /tmp/oculox-ingestion-before.json
```

Sur Hedgehog, injecter un PCAP de test identifié. L'identifiant doit être unique
et le fichier doit contenir assez de trafic pour alimenter les deux connexions
Filebeat :

```bash
./oculox verify ingestion inject --pcap /chemin/test-industriel.pcap --run-id validation-20260813-01 --output /tmp/oculox-ingestion-collector.json
```

Transférer uniquement le rapport du collecteur vers Core :

```bash
scp /tmp/oculox-ingestion-collector.json utilisateur@IP_CORE:/tmp/
```

Puis finaliser sur Core :

```bash
./oculox verify ingestion finalize --baseline /tmp/oculox-ingestion-before.json --collector-report /tmp/oculox-ingestion-collector.json --output /tmp/oculox-ingestion-final.json
```

Le résultat attendu est `INGESTION_RESULT=PASS`. Le rapport conserve séparément
le nombre de paquets du PCAP, les sorties Zeek et Suricata, les événements
Filebeat acquittés, les compteurs des deux Logstash, les documents de pipelines,
les sessions Arkime et les rejets OpenSearch. Ces compteurs ne sont pas comparés
entre eux comme s'ils représentaient le même objet.

## Limites d'interprétation

Le test doit être exécuté sur une plateforme de validation sans autre ingestion
concurrente. Les deltas représentent alors le PCAP identifié par son nom, son
identifiant d'exécution et son SHA-256. En production active, les mêmes mesures
incluraient le trafic concurrent et ne permettraient plus une attribution
rigoureuse au seul fichier injecté.

## Banc local sans Hedgehog

Pour diagnostiquer le chemin d'ingestion sur une seule machine avant le test
final à trois VM, le Core peut injecter le PCAP avec `--allow-core`. Cette
exception est enregistrée dans le rapport avec `source_role=principal` et
`core_lab_override=true`. Elle valide le traitement local, Filebeat, les deux
Logstash et le cluster distant, mais ne valide ni le réseau ni le runtime d'une
VM Hedgehog séparée.

# Sources de configuration OpenSearch

Ce repertoire contient uniquement les modeles et configurations non secretes
du cluster :

```text
configuration commune OpenSearch
configuration propre a chaque noeud
modeles du plugin Security
configuration du proxy
exemples de variables d'environnement
```

Les fichiers versionnes doivent utiliser des variables ou des marqueurs pour
les valeurs de deploiement. L'operateur fournit l'endpoint dans son fichier
`cluster.yml`, sous la forme :

```text
https://<IP_CLUSTER>:9200
```

L'adresse ne doit pas etre dupliquee dans plusieurs fichiers sources. Les
certificats, cles, mots de passe, fichiers `.curlrc`, keystores et configurations
contenant des secrets sont interdits dans ce repertoire.

Les fichiers effectifs rendus a partir de ces sources seront places dans
`dev/generated/opensearch-cluster/`.

Copier `cluster.yml.example` hors du depot ou dans un emplacement operateur,
modifier uniquement les valeurs utiles, puis lancer :

```bash
./oculox install cluster --config /chemin/cluster.yml
```

Une installation rapide avec les valeurs par defaut utilise :

```bash
./oculox install cluster --endpoint-ip <IP_CLUSTER>
```

`opensearch.yml` active TLS sur les couches HTTP et transport, declare les
trois DN de noeud et le DN du certificat administrateur. Les chemins des
certificats sont relatifs au repertoire `config`, comme l'exige le plugin
Security.

`setup-post-start.sh` neutralise provisoirement l'initialisation
automatique du Security index effectuee par l'image Malcolm. Cette operation
doit etre executee une seule fois pendant la Security initialization, pas en parallele par les
trois conteneurs.

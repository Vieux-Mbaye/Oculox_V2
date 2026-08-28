# Compose du cluster OpenSearch

Ce repertoire recevra l'orchestration Docker Compose autonome du cluster
OpenSearch deploye sur la VM dediee.

Le Compose devra definir uniquement les composants propres au stockage :

```text
opensearch-1
opensearch-2
opensearch-3
proxy d'endpoint
volumes de donnees distincts
reseau transport prive
```

Il ne doit pas recopier le Compose principal Malcolm/Oculox. Oculox Core et
Hedgehog resteront des clients distants du seul endpoint publie.

Les valeurs propres a une machine, les mots de passe, les cles privees et les
configurations generees ne doivent pas apparaitre ici. Elles seront injectees
depuis `dev/generated/opensearch-cluster/`.

Le fichier `compose.yml` constitue le Compose structurel du cluster. Il ne
publie encore aucun port sur l'hote et ne doit pas etre demarre avant les phases
de decouverte et de PKI.

Validation sans demarrage :

```bash
docker compose \
  --env-file dev/config/opensearch-cluster/cluster.env.example \
  -f dev/compose/opensearch-cluster/compose.yml \
  config
```

Le reseau `oculox-opensearch-transport` est interne a Docker. Les ports `9200`
et `9300` sont exposes uniquement sur ce reseau. Le futur proxy publiera le seul
port client de la VM lors de l'activation de l'endpoint stable.

## Decouverte Et Amorcage

`compose.yml` contient la configuration de decouverte permanente :

```text
discovery.type absent (mode multi-noeud OpenSearch par defaut)
discovery.seed_hosts=opensearch-1:9300,opensearch-2:9300,opensearch-3:9300
```

`compose.bootstrap.yml` ajoute la liste d'amorcage initiale aux trois services :

```text
cluster.initial_cluster_manager_nodes=opensearch-1,opensearch-2,opensearch-3
```

Ce second fichier sera charge uniquement au premier demarrage d'un cluster dont
les trois volumes sont vides :

```bash
docker compose \
  --env-file dev/config/opensearch-cluster/cluster.env.example \
  -f dev/compose/opensearch-cluster/compose.yml \
  -f dev/compose/opensearch-cluster/compose.bootstrap.yml \
  config
```

Les redemarrages ordinaires utiliseront seulement `compose.yml`, car l'election
initiale est deja conservee dans les volumes de donnees. Aucun demarrage ne doit
encore etre effectue avant le montage de la PKI de la PKI.

## PKI OpenSearch

Chaque service monte en lecture seule le meme modele `opensearch.yml`, la CA
OpenSearch commune et son propre repertoire contenant `node.crt`, `node.key` et
`ca.crt`.

Le certificat et la cle de l'endpoint ne sont pas montes dans les noeuds. Ils
sont reserves au proxy de l.endpoint stable. La cle administrateur reste egalement
hors des conteneurs et sera utilisee ponctuellement par `securityadmin.sh`
pendant l.initialisation Security.

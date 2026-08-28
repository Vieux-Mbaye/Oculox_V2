# Étape de topologie Compose - Compose du cluster OpenSearch vide

## 1. Objet

Cette étape cree l'orchestration structurelle des trois noeuds OpenSearch sans
former le cluster et sans demarrer de conteneur.

Le fichier principal est :

```text
dev/compose/opensearch-cluster/compose.yml
```

Les valeurs non secretes de developpement sont dans :

```text
dev/config/opensearch-cluster/cluster.env.example
```

## 2. Version

Les trois services utilisent exactement l'image du mono-noeud Oculox :

```text
ghcr.io/idaholab/malcolm/opensearch:26.07.1
```

Le Dockerfile de cette image repose sur OpenSearch `3.7.0`. Aucun tag `latest`
n'est utilise.

## 3. Services

| Service | Hostname | `node.name` | Heap |
|---|---|---|---:|
| `opensearch-1` | `opensearch-1` | `opensearch-1` | 2 Gio |
| `opensearch-2` | `opensearch-2` | `opensearch-2` | 2 Gio |
| `opensearch-3` | `opensearch-3` | `opensearch-3` | 2 Gio |

Les trois noeuds declarent les roles suivants :

```text
cluster_manager,data,ingest,remote_cluster_client
```

La somme des heaps vaut 6 Gio sur la VM de developpement de 14 Gio. La taille
est parametree par `OPENSEARCH_HEAP_SIZE`, avec `2g` comme valeur actuelle.

## 4. Volumes de donnees

Chaque service possede exactement un volume monte sur
`/usr/share/opensearch/data` :

```text
opensearch-1 -> opensearch-data-1
opensearch-2 -> opensearch-data-2
opensearch-3 -> opensearch-data-3
```

Les volumes possedent des noms Docker explicites :

```text
opensearch-data-1
opensearch-data-2
opensearch-data-3
```

Aucun volume de donnees n'est partage. Aucun bind mount vers le mono-noeud
Oculox existant n'est reutilise.

## 5. Reseau et ports

Les trois noeuds utilisent le reseau bridge interne :

```text
oculox-opensearch-transport
internal: true
```

Chaque noeud expose dans ce reseau :

```text
9200/tcp : API HTTP protegee par le plugin Security
9300/tcp : transport inter-noeuds
```

Aucun `ports:` ne publie directement un noeud sur l'hote. Cette absence est
volontaire : le futur proxy sera le seul composant autorise a publier
`192.168.1.241:9200`. Le transport `9300` restera prive au reseau Docker.

Le plugin Security n'est pas desactive. La PKI mono-noeud automatique est
desactivee avec :

```text
OPENSEARCH_SKIP_SELF_SIGNED_KEY_GEN=true
```

La étape PKI montera les certificats propres aux trois noeuds avant tout premier
demarrage.

## 6. Limites et redemarrage

Chaque noeud applique :

```text
memlock soft/hard : unlimited
nofile soft/hard  : 65536
stop_grace_period : 3 minutes
restart           : unless-stopped
```

La politique `unless-stopped` permet le retour apres redemarrage de Docker ou
de la VM, tout en respectant un arret volontaire de l'operateur.

Les logs utilisent le driver `local`, deux fichiers de 200 Mio au maximum par
noeud.

## 7. Healthcheck

Chaque noeud possede un healthcheck de l'endpoint HTTPS local sur `9200`. Les
codes suivants prouvent que la pile TLS et le serveur HTTP repondent :

```text
200 : requete autorisee
401 : authentification requise
403 : identite reconnue mais operation refusee
```

Ce controle ne remplace pas la verification de sante du cluster. Les phases
suivantes ajouteront les preuves authentifiees de nombre de noeuds, election du
cluster manager et absence de shards non affectes.

## 8. Protection contre un demarrage premature

L'image Malcolm mono-noeud utilise `discovery.type=single-node`. Le Compose du
cluster ne definit pas `discovery.type` : son absence active le mode de
decouverte multi-noeud standard d'OpenSearch. La valeur `multi-node` n'existe
pas et ferait echouer le demarrage.

Les `discovery.seed_hosts` et
`cluster.initial_cluster_manager_nodes` ne sont pas encore definis : ils
appartiennent a la étape de découverte. Les certificats ne sont pas encore montes : ils
appartiennent a la étape PKI.

Le Compose de étape de topologie Compose est donc valide structurellement, mais ne doit pas etre
demarre dans son etat actuel.

## 9. Test automatise

Le test suivant n'utilise aucune dependance Python externe :

```bash
./dev/tests/opensearch-cluster/test_compose_structure.py
```

Il verifie :

- la liste exacte des trois services ;
- l'image `26.07.1` ;
- les hostnames et `node.name` uniques ;
- la heap explicite de 2 Gio ;
- la presence du healthcheck ;
- les ports internes `9200` et `9300` ;
- l'absence de port publie sur l'hote ;
- le reseau transport interne ;
- l'unicite des trois volumes ;
- la desactivation de la PKI mono-noeud automatique.

Resultat obtenu :

```text
services=opensearch-1,opensearch-2,opensearch-3
data_volumes=opensearch-data-1,opensearch-data-2,opensearch-data-3
host_ports=none
CLUSTER_COMPOSE_RESULT=PASS
```

## 10. Validation sur la VM cible

Les fichiers Compose et environnement ont ete copies temporairement dans
`/tmp` sur `192.168.1.241`. Docker Compose `5.4.0` a valide la configuration :

```text
services : opensearch-1, opensearch-2, opensearch-3
volumes  : opensearch-data-1, opensearch-data-2, opensearch-data-3
erreur   : aucune
```

Le repertoire temporaire a ensuite ete supprime. Aucun pull d'image, volume,
reseau ou conteneur n'a ete cree sur la VM : son compteur de conteneurs est
reste a zero.

## 11. Sources techniques

- OpenSearch, installation Docker :
  `https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker`
- OpenSearch, parametres de decouverte :
  `https://docs.opensearch.org/latest/tuning-your-cluster/discovery-cluster-formation/settings/`
- OpenSearch, configuration TLS :
  `https://docs.opensearch.org/latest/security/configuration/tls/`

## 12. Decision de sortie

La étape de topologie Compose est validee. Le Compose respecte les contrats structurels demandes
et n'a modifie aucun service Oculox existant.

La étape de découverte peut maintenant ajouter la decouverte et l'amorcage communs aux
trois noeuds. Aucun `docker compose up` ne doit etre execute avant que la PKI de
la étape PKI soit egalement disponible.

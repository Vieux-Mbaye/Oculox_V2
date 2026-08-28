# Tests du cluster OpenSearch

Ce répertoire contient les validations statiques et fonctionnelles du cluster
dédié.

Les campagnes seront separees par objectif :

```text
syntaxe Compose et configuration
formation des trois noeuds et election
TLS HTTP et transport
roles et moindre privilege
shards, replicas et watermarks
perte et reintegration d'un noeud
connexion de tous les clients Core et Hedgehog
snapshot et restauration
installation sur VM neuve
```

Les tests doivent produire des resultats explicites `PASS` ou `FAIL` et ne
jamais considerer un simple demarrage de conteneur comme une validation du
cluster. Les journaux et preuves volumineuses iront dans `dev/tests/results/`,
deja ignore par Git.

Aucun test de cette arborescence ne doit cibler le mono-noeud local par defaut.
La cible devra toujours etre fournie explicitement.

PKI setup :

```bash
./dev/tests/opensearch-cluster/test_pki.py
```

Ce test verifie les chaines X.509, les SAN, les usages serveur/client, le format
PKCS#8, l'unicite des cles privees, leurs permissions, les DN Security et les
montages Compose en lecture seule. Il confirme aussi qu'aucun secret PKI n'est
suivi par Git.

Security initialization statique :

```bash
./dev/tests/opensearch-cluster/test_security_config.py
```

Security initialization runtime, depuis l'hote du cluster avec des secrets temporaires :

```bash
./dev/tests/opensearch-cluster/test_security_runtime.sh \
  --accounts-env /chemin/temporaire/accounts.env \
  --admin-dir /chemin/temporaire/admin \
  --ca /chemin/temporaire/oculox-opensearch-ca.crt
```

Le test est idempotent, nettoie ses index et templates, et verifie les succes,
les refus `403`, l'anonyme `401` et le rejet d'une CA non fiable.
## Storage policy

Validation statique locale :

```bash
python3 dev/tests/opensearch-cluster/test_storage_policy_static.py
```

Validation runtime sur la VM du cluster :

```bash
./dev/tests/opensearch-cluster/test_storage_policy_runtime.sh
```

Le test runtime applique deux fois la configuration pour verifier son
idempotence, cree un index temporaire, arrete le noeud qui porte son shard
primaire, verifie la lecture depuis le replica, redemarre le noeud et exige un
retour du cluster a l'etat `green`. L'index de test est ensuite supprime.

## Cluster resilience

Validation autonome complete du cluster dedie :

```bash
python3 dev/tests/opensearch-cluster/test_cluster_resilience_static.py
./dev/tests/opensearch-cluster/test_cluster_resilience_runtime.sh
```

Le test valide l'indexation, la recherche, la separation primaire/replica, la
perte d'un noeud data, la reelection du cluster manager, la perte attendue du
quorum avec deux noeuds arretes et la persistance apres un redemarrage Compose
complet. Un mecanisme de recuperation relance tous les services et supprime
l'index temporaire en cas d'echec.
## Intégration des clients Oculox

```bash
python3 dev/tests/opensearch-cluster/test_remote_client_integration.py
```

Ce test ne contacte aucun serveur. Il verifie l'exclusion conditionnelle du
service OpenSearch local, la suppression des dependances et l'affectation des
identites de moindre privilege aux clients Core et Hedgehog.

Validation fonctionnelle après installation sur les VM neuves :

```bash
./oculox verify clients
```

Le test d'ingestion distribué entre Core et Hedgehog est documenté dans
`dev/docs/Opensearch/validation_clients_et_ingestion.md`.

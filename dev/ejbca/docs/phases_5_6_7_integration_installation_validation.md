# Phases 5, 6 et 7 - Integration Oculox vers EJBCA

> Rapport de l'integration initiale. Les commandes distantes et l'exploitation
> actuelles sont dans [installation trois VM](installation_3_vm_et_bundles.md).

## Objectif

Ces phases ajoutent la couche qui permet a Oculox de consommer une PKI professionnelle sans devenir lui-meme une autorite de certification.

Le partage des responsabilites est le suivant :

```text
EJBCA signe les certificats
Oculox les recupere ou les importe
Oculox les verifie en staging
Oculox les installe seulement sur demande explicite
Oculox redemarre uniquement les services concernes
Oculox valide le resultat et restaure les anciens fichiers si besoin
```

Aucun certificat actif n'est remplace par defaut.

## Fichiers crees ou modifies

### `dev/scripts/ejbca/pki-lifecycle.py`

Script principal des phases 5 et 6.

Il ajoute les commandes suivantes derriere `./oculox pki` :

```bash
./oculox pki enroll --provider ejbca
./oculox pki renew --provider ejbca --service <entree-manifest>
./oculox pki import --provider customer --bundle <repertoire>
```

Son role :

- lire `dev/ejbca/pki-manifest.yml` ;
- lire `dev/ejbca/profiles/ca-plan.yml` ;
- trouver la CA EJBCA qui doit signer chaque certificat ;
- creer une entite finale EJBCA ;
- generer une cle privee et une CSR sur la machine demandeuse ;
- transmettre uniquement la CSR publique a EJBCA via son CLI local ;
- recevoir `cert.crt`, conserver `key.key` localement (pas de P12 service) ;
- exporter le bundle de CA `intermediate + root` ;
- verifier le certificat en staging ;
- installer seulement avec `--install` ;
- sauvegarder les anciens certificats avant remplacement ;
- restaurer automatiquement les anciens fichiers si la validation post-installation echoue.

### `dev/scripts/pki-validate-services.py`

Script principal de la phase 7.

Il ajoute :

```bash
./oculox validate web
./oculox validate keycloak
./oculox validate dashboards
./oculox validate opensearch
./oculox validate ingestion
./oculox validate all
```

Son role :

- verifier le manifest PKI avec `./oculox pki status` ;
- tester le portail HTTPS local ;
- tester l'endpoint OIDC Keycloak ;
- tester l'acces OpenSearch Dashboards ;
- verifier la presence des conteneurs Filebeat et Logstash ;
- produire des statuts `OK`, `WARN` ou `FAIL`.

Un `WARN` n'est pas bloquant. Exemple : un cluster OpenSearch distant peut etre valide par les commandes cluster dediees et ne pas exposer `https://127.0.0.1:9200`.

### `oculox`

Le lanceur principal expose maintenant :

```bash
./oculox pki enroll|renew|import
./oculox validate web|keycloak|dashboards|opensearch|ingestion|all
```

Cela evite de demander a l'operateur d'appeler les scripts Python directement.

## Phase 5 - Integration Oculox vers EJBCA

### Enrolement EJBCA

Commande type :

```bash
./oculox pki enroll --provider ejbca --service logstash_server
```

Ce que fait la commande :

1. Elle verifie qu'EJBCA repond dans le conteneur `oculox-ejbca`.
2. Elle lit l'entree `logstash_server` dans `dev/ejbca/pki-manifest.yml`.
3. Elle trouve le profil `oculox-logstash-server`.
4. Elle lit `dev/ejbca/profiles/ca-plan.yml`.
5. Elle determine que la CA emettrice est `Oculox Internal Services CA`.
6. Elle cree une entite finale EJBCA avec un Subject DN unique.
7. Elle garde les SAN fonctionnels du manifest, par exemple `logstash` et `logstash-2`.
8. Elle genere localement `key.key` (RSA 3072, permissions 0600) et `request.csr`.
9. Elle transmet la CSR publique, puis EJBCA emet le certificat avec `createcert`.
10. Elle exporte le bundle de confiance avec l'intermediate CA et la Root CA.
11. Elle verifie la correspondance cle/certificat, la chaine, les EKU et les SAN.
12. Elle place le resultat dans `dev/ejbca/generated/enrollments/<timestamp>/<nom>/`.

Exemple de sortie valide :

Ce parcours reste local au Core : il utilise `docker exec`, pas une API
d'enrolement distant. Les profils generiques `SERVER`/`ENDUSER` et `EMPTY`
restent utilises. Le fichier de plan ne suffit donc pas a imposer les droits
specifiques Cluster et Collecteur. Voir le suivi de preparation trois VM.

```text
OK    logstash_server: certificat present: cert.crt
OK    logstash_server: cle privee present: key.key
OK    logstash_server: CA present: ca.crt
OK    logstash_server: la cle privee correspond au certificat
OK    logstash_server: chaine validee avec la CA declaree
OK    logstash_server: EKU serverAuth present
OK    logstash_server: SAN present: logstash
OK    logstash_server: SAN present: logstash-2
STAGE logstash_server: dev/ejbca/generated/enrollments/...
```

### Renouvellement

Commande type :

```bash
./oculox pki renew --provider ejbca --service logstash_server
```

Dans cette version, `renew` force une nouvelle emission en staging. Il ne remplace pas le certificat actif sans `--install`.

### Import d'une PKI client

Commande type :

```bash
./oculox pki import --provider customer --bundle ./customer-pki --service logstash_server
```

Format attendu pour un service :

```text
customer-pki/
  logstash_server/
    cert.crt
    key.key
    ca.crt
```

Oculox verifie le bundle fourni par le client avant toute installation :

- le certificat existe ;
- la cle existe ;
- la CA existe ;
- la cle correspond au certificat ;
- la chaine est valide ;
- les EKU attendus sont presents ;
- les SAN attendus sont presents.

## Phase 6 - Installation sans interruption brutale

Par defaut, les commandes `enroll`, `renew` et `import` ne touchent pas les certificats actifs.

Pour installer un certificat valide :

```bash
./oculox pki renew --provider ejbca --service logstash_server --install
```

Pour installer puis redemarrer uniquement les services declares dans le manifest :

```bash
./oculox pki renew --provider ejbca --service logstash_server --install --restart
```

Le script applique l'ordre suivant :

1. generation ou import dans une zone de staging ;
2. validation hors ligne ;
3. sauvegarde des certificats actifs dans `dev/ejbca/generated/backups/<timestamp>/` ;
4. remplacement atomique fichier par fichier ;
5. permissions correctes :
   - certificats et CA : `0644` ;
   - cles privees : `0600` ;
6. redemarrage seulement si `--restart` est fourni ;
7. validation `./oculox validate pki` ;
8. rollback automatique si la validation echoue.

Le rollback restaure les fichiers sauvegardes et redemarre les services concernes si `--restart` avait ete utilise.

## Phase 7 - Validation automatique

Commandes disponibles :

```bash
./oculox validate pki
./oculox validate web
./oculox validate keycloak
./oculox validate dashboards
./oculox validate opensearch
./oculox validate ingestion
./oculox validate all
```

Interpretation :

- `OK` : le controle est valide ;
- `WARN` : point a verifier, mais pas bloquant pour le contexte courant ;
- `FAIL` : probleme bloquant, la commande retourne un code d'erreur.

Exemple de validation complete observee :

```text
OK    pki          manifest PKI actif valide ou avec avertissements non bloquants
OK    web          https://127.0.0.1/ repond HTTP 302
OK    keycloak     https://127.0.0.1/keycloak/realms/oculox/.well-known/openid-configuration repond HTTP 200
OK    dashboards   https://127.0.0.1/dashboards/ repond HTTP 302
WARN  opensearch   endpoint local 9200 non detecte; verifiez le cluster distant avec les commandes cluster dediees
OK    ingestion    conteneur filebeat: actif
OK    ingestion    conteneur logstash: actif
OK    ingestion    conteneur logstash-2: actif
```

Le `WARN` OpenSearch est acceptable dans une architecture ou OpenSearch n'est pas expose directement sur `127.0.0.1:9200`.

## Tests realises

Les commandes suivantes ont ete executees :

```bash
python3 -m py_compile dev/scripts/ejbca/pki-lifecycle.py dev/scripts/pki-validate-services.py dev/scripts/pki-audit.py dev/scripts/ejbca/validate-ca-plan.py
bash -n oculox dev/scripts/ejbca/manage-ejbca.sh
./oculox pki-ca verify-hardening
./oculox pki enroll --provider ejbca --service logstash_server
./oculox pki enroll --provider ejbca --service filebeat_client
./oculox pki enroll --provider ejbca --service web_server
./oculox pki enroll --provider ejbca --service web_ca
./oculox pki enroll --provider ejbca --service ingestion_ca
./oculox pki enroll --provider ejbca
./oculox pki renew --provider ejbca --service logstash_server
./oculox pki import --provider customer --bundle dev/ejbca/generated/enrollments/<staging> --service logstash_server
./oculox validate pki
./oculox validate web
./oculox validate keycloak
./oculox validate dashboards
./oculox validate all
```

Resultat :

- EJBCA durci : OK ;
- emission Logstash serveur : OK ;
- emission Filebeat client : OK ;
- emission Web/Nginx : OK ;
- export CA Web et CA Ingestion : OK ;
- enrolement global des entrees requises : OK ;
- renouvellement Logstash en staging : OK ;
- import type PKI client : OK ;
- validation PKI active : OK ;
- validation Web : OK ;
- validation Keycloak : OK ;
- validation Dashboards : OK ;
- validation Ingestion : OK ;
- OpenSearch local 9200 : WARN documente.

## Points importants pour une VM neuve

Sur une VM neuve, l'ordre propre est :

```bash
./oculox prepare principal --server-name <dns-ou-ip>
./oculox start
./oculox keycloak provision
./oculox pki-ca init
./oculox pki-ca start
./oculox pki-ca create-ca-plan
./oculox pki-ca harden
./oculox pki enroll --provider ejbca --service web_server
./oculox pki enroll --provider ejbca --service logstash_server
./oculox pki enroll --provider ejbca --service filebeat_client
./oculox validate all
```

Ensuite seulement, l'operateur peut choisir de basculer un certificat :

```bash
./oculox pki renew --provider ejbca --service web_server --install --restart
```

Cette approche permet de tester EJBCA et les certificats avant de remplacer ce qui fait deja fonctionner la plateforme.

## Bascule complete validee

La bascule des certificats requis vers EJBCA a ete executee et validee avec le flux suivant :

```bash
./oculox pki enroll --provider ejbca --install
./oculox restart nginx-proxy filebeat logstash logstash-2
./oculox validate all
```

Le premier ordre emet les certificats depuis EJBCA, les valide, puis installe les certificats dans les chemins actifs declares par le manifest. Le second redemarre uniquement les services qui consomment ces fichiers. Le dernier verifie le resultat de bout en bout.

Les certificats actifs verifies apres la bascule sont :

| Usage | Certificat actif | Autorite EJBCA | Etat |
|---|---|---|---|
| Portail Nginx | `nginx/certs/cert.pem` | `Oculox Web CA` | OK |
| Confiance Web | `nginx/ca-trust/oculox-web-ca.crt` | `Oculox Web CA` + Root | OK |
| Serveur Logstash | `dev/generated/pki/server.crt` | `Oculox Internal Services CA` | OK |
| Client Filebeat | `dev/generated/pki/client.crt` | `Oculox Internal Services CA` | OK |
| Confiance ingestion | `dev/generated/pki/ca.crt` | `Oculox Internal Services CA` + Root | OK |
| CA OpenSearch | `dev/generated/opensearch-cluster/pki/ca/ca.crt` | `Oculox OpenSearch CA` | OK |
| Noeud OpenSearch 1 | `dev/generated/opensearch-cluster/pki/nodes/opensearch-1/node.crt` | `Oculox OpenSearch CA` | OK |
| Noeud OpenSearch 2 | `dev/generated/opensearch-cluster/pki/nodes/opensearch-2/node.crt` | `Oculox OpenSearch CA` | OK |
| Noeud OpenSearch 3 | `dev/generated/opensearch-cluster/pki/nodes/opensearch-3/node.crt` | `Oculox OpenSearch CA` | OK |
| Endpoint OpenSearch | `dev/generated/opensearch-cluster/pki/endpoint/endpoint.crt` | `Oculox OpenSearch CA` | OK |
| Admin OpenSearch | `dev/generated/opensearch-cluster/pki/admin/admin.crt` | `Oculox OpenSearch CA` | OK |
| Confiance Dashboards vers OpenSearch | `nginx/ca-trust/oculox-opensearch-ca.crt` | `Oculox OpenSearch CA` + Root | OK |

Le certificat Web contient le SAN IP `192.168.1.174`. Le certificat Logstash contient les SAN Docker `logstash` et `logstash-2`. Le certificat Filebeat contient l'usage `TLS Web Client Authentication`.

Le certificat endpoint OpenSearch contient le SAN DNS `opensearch-endpoint` et,
lorsque `dev/generated/opensearch-cluster/cluster.env` existe, l'IP declaree
par `OPENSEARCH_ENDPOINT_BIND_IP`. Cela evite de coder une IP dans le depot :
l'IP reelle est une donnee runtime de la VM.

La validation finale a produit :

```text
OK    pki
OK    web
OK    keycloak
OK    dashboards
OK    ingestion
WARN  opensearch endpoint local 9200 non detecte
```

Le `WARN` OpenSearch est informatif : le cluster n'est pas publie sur
`127.0.0.1:9200` dans cette architecture. La validation dediee du cluster est
`./oculox cluster validate`.

Les anciennes versions restent conservees dans `dev/ejbca/generated/backups/` afin de permettre un rollback. Ce repertoire est genere et ignore par Git ; il ne doit pas etre pousse dans Gitea. Les entrees OpenSearch marquees `optional` ne sont pas forcees pendant cette bascule, car leur cluster et ses certificats sont geres selon son propre plan de deploiement.

## Bascule OpenSearch vers EJBCA

Le chemin d'installation du cluster OpenSearch appelle maintenant EJBCA.

Fichier modifie :

```text
dev/scripts/opensearch-cluster/manage-cluster.sh
```

La fonction `install_cluster` appelle `ensure_ejbca_opensearch_pki` avant le
demarrage des noeuds. Cette fonction :

1. verifie qu'EJBCA est disponible avec `./oculox pki-ca validate` ;
2. enrole `opensearch_cluster_ca` ;
3. enrole `opensearch_node_1`, `opensearch_node_2` et `opensearch_node_3` ;
4. enrole `opensearch_admin_client` ;
5. enrole `opensearch_endpoint` ;
6. enrole `opensearch_remote_trust` ;
7. installe chaque fichier dans les chemins declares par le manifest ;
8. ecrit `dev/generated/opensearch-cluster/pki/manifest.txt` pour tracer que la
   PKI vient d'EJBCA.

L'ancien script OpenSSL `dev/scripts/opensearch-cluster/generate-pki.sh` reste
un artefact de developpement historique, mais il n'est plus le chemin normal de
l'installation cluster.

Le manifest PKI fixe les DN OpenSearch attendus :

```text
CN=opensearch-1,OU=OpenSearch Nodes,O=Oculox,C=SN
CN=opensearch-2,OU=OpenSearch Nodes,O=Oculox,C=SN
CN=opensearch-3,OU=OpenSearch Nodes,O=Oculox,C=SN
CN=opensearch-endpoint,OU=OpenSearch HTTP,O=Oculox,C=SN
CN=oculox-opensearch-admin,OU=OpenSearch Administration,O=Oculox,C=SN
```

OpenSearch Security utilise ces DN dans `nodes_dn` et `admin_dn`. Un noeud ou
un administrateur avec un certificat signe par une autre CA ou avec un DN non
attendu est refuse.

## Ordre Trois VM Avec EJBCA

Cette section decrit une cible, pas une installation distante validee.
Consulter la [reference revisee](installation_3_vm_et_bundles.md) pour le statut
reel, le contenu des bundles et les prerequis encore manquants.

Pour trois VM distinctes, l'ordre logique est :

```text
1. VM Core : installer EJBCA et creer les CA.
2. VM Cluster : obtenir les certificats OpenSearch depuis EJBCA, puis installer le cluster.
3. VM Core : importer le bundle cluster et finaliser le Core.
4. VM Collecteur : installer le collecteur avec son bundle.
```

Detail operationnel :

```bash
# VM Core
./oculox prepare principal --server-name <DNS_OU_IP_CORE>
./oculox pki-ca init
./oculox pki-ca start
./oculox pki-ca create-ca-plan
./oculox pki-ca harden
./oculox pki-ca verify-hardening
./oculox pki enroll --provider ejbca --service web_server --install
./oculox pki enroll --provider ejbca --service logstash_server --install
./oculox pki enroll --provider ejbca --service filebeat_client --install

# VM Cluster
./oculox install cluster --config ~/oculox-cluster.yml --check
./oculox install cluster --config ~/oculox-cluster.yml
./oculox cluster validate
./oculox cluster client-bundle core ~/oculox-bundles/core

# VM Core
./oculox install principal --server-name <DNS_OU_IP_CORE> --opensearch-bundle ~/oculox-bundles/core
./oculox validate all

# VM Collecteur
./oculox install hedgehog --principal-host <DNS_OU_IP_CORE> --collector-name <nom> --bundle <bundle>
```

Point d'attention important : dans l'implementation actuelle, la commande
`./oculox install cluster` enrole les certificats via le conteneur EJBCA
accessible par les scripts Oculox. En deploiement multi-VM avec EJBCA uniquement
sur Core, il faut implementer un enrolement distant authentifie et limite.
Le transport manuel de cles dans un bundle PKI cluster n'est pas le parcours
normal retenu. Le bundle de configuration client OpenSearch reste distinct :
il transporte la CA publique, l'URL et les comptes techniques.

## Tests supplementaires OpenSearch EJBCA

Les controles suivants ont ete executes apres la bascule OpenSearch :

```bash
./oculox pki-ca verify-hardening
./oculox pki enroll --provider ejbca --service opensearch_cluster_ca --install --force
./oculox pki enroll --provider ejbca --service opensearch_node_1 --install --force
./oculox pki enroll --provider ejbca --service opensearch_node_2 --install --force
./oculox pki enroll --provider ejbca --service opensearch_node_3 --install --force
./oculox pki enroll --provider ejbca --service opensearch_admin_client --install --force
./oculox pki enroll --provider ejbca --service opensearch_endpoint --install --force
./oculox pki enroll --provider ejbca --service opensearch_remote_trust --install --force
OPENSEARCH_CLUSTER_ENV_FILE=dev/config/opensearch-cluster/cluster.env.example \
  python3 dev/tests/opensearch-cluster/test_pki.py
./oculox pki status
./oculox pki expiry
./oculox validate all
```

Resultat observe :

```text
PKI_TEST_RESULT=PASS
web_server OK
logstash_server OK
filebeat_client OK
opensearch_cluster_ca OK
opensearch_node_1 OK
opensearch_node_2 OK
opensearch_node_3 OK
opensearch_admin_client OK
opensearch_endpoint OK
opensearch_remote_trust OK
```

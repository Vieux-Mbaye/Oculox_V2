# Remote client integration - Configuration d'Oculox Core

## 1. Portee de cette étape

Cette procédure prépare Oculox Core et les collecteurs Hedgehog pour utiliser le
cluster OpenSearch distant a travers l'endpoint stable :

```text
https://192.168.1.241:9200
```

Les modifications de cette procédure sont réalisées dans le dépôt Oculox. Aucun
serveur `10.5.6.x` n'est utilise. L'installation sur une machine Core ou
Hedgehog reste une operation explicite de l'operateur.

## 2. Configuration officielle Malcolm

Sur le futur Core, le configurateur officiel doit enregistrer dans
`config/opensearch.env` :

```text
OPENSEARCH_PRIMARY=opensearch-remote
OPENSEARCH_URL=https://192.168.1.241:9200
OPENSEARCH_SSL_CERTIFICATE_VERIFICATION=true
```

Dans l'interface interactive, cela correspond a :

```text
Primary Document Store : opensearch-remote
Primary URL            : https://192.168.1.241:9200
Verify SSL             : Yes
```

`./scripts/auth_setup` conserve son role officiel pour saisir un compte distant
dans `.opensearch.primary.curlrc`. Cependant, le cluster de la Security initialization possede
des comptes séparés. Le bundle client remplace donc, dans chaque
conteneur, le fichier generique par l'identite de service appropriee.

## 3. Comptes utilises

| Client | Compte OpenSearch | Raison |
|---|---|---|
| Logstash 1 et 2 | `oculox_logstash` | ecriture des evenements |
| Arkime et Arkime Live | `oculox_arkime` | sessions et statistiques Arkime |
| OpenSearch Dashboards | `oculox_dashboards` | compte serveur Dashboards |
| dashboards-helper | `oculox_dashboards_helper` | templates et objets des plugins |
| API et pcap-monitor | `oculox_api` | lecture et suivi des traitements |

Un Hedgehog ne recoit que les identites `oculox_arkime` et `oculox_api`.
Filebeat continue d'envoyer ses evenements aux deux Logstash en mTLS et ne se
connecte pas directement a OpenSearch.

## 4. Generation du bundle sur l'hote du cluster

La commande suivante lit la CA publique et les mots de passe generes pendant
la Security initialization. Aucun secret n'est affiche :

```bash
./dev/scripts/opensearch-cluster/create-client-bundle.py --role core --endpoint https://192.168.1.241:9200 --output /chemin-securise/oculox-core-opensearch
```

Pour un collecteur :

```bash
./dev/scripts/opensearch-cluster/create-client-bundle.py --role hedgehog --endpoint https://192.168.1.241:9200 --output /chemin-securise/oculox-hedgehog-opensearch
```

Le repertoire contient la CA, un fichier `curlrc` par fonction, `bundle.env`
et `SHA256SUMS`. Il contient des mots de passe et doit etre transfere par un
canal securise, puis supprime apres import.

## 5. Import sur Oculox Core

Apres le configurateur et `auth_setup`, importer le bundle :

```bash
./oculox configure-opensearch-remote --bundle /chemin-securise/oculox-core-opensearch
```

L'importeur effectue les operations suivantes :

1. controle toutes les sommes SHA-256 ;
2. refuse un bundle du mauvais role ;
3. refuse un fichier `curlrc` contenant `insecure` ;
4. copie la CA vers `nginx/ca-trust/oculox-opensearch-ca.crt` ;
5. installe les identites sous `dev/generated/opensearch-clients/` en mode 600 ;
6. configure le mode distant, l'URL HTTPS et la verification TLS ;
7. conserve un compte de lecture limite dans `.opensearch.primary.curlrc` pour
   les outils generiques compatibles Malcolm.

La CA montee dans `/var/local/ca-trust` est importee au demarrage dans le
magasin systeme des conteneurs. Le demarrage Logstash importe aussi cette CA
dans le magasin Java avec `jdk-cacerts-auto-import.sh`.

## 6. Exclusion de l'OpenSearch local

`./oculox start` fusionne d'abord le Compose officiel et la surcharge Oculox.
`render-remote-opensearch-compose.py` examine ensuite `config/opensearch.env`.

En mode `opensearch-remote`, il :

- place le service local dans le profil inactif
  `oculox-opensearch-local-disabled` ;
- retire les dependances `depends_on: opensearch` ;
- monte le fichier `curlrc` limite correspondant dans chaque client.

Le service reste defini dans le Compose rendu pour préserver la compatibilite
des outils Malcolm, mais il n'est pas demarre avec le profil `malcolm`. En mode
`opensearch-local`, le rendu reste inchange.

## 7. Verification locale sans contacter le cluster

```bash
python3 dev/tests/opensearch-cluster/test_remote_client_integration.py
```

Resultat attendu :

```text
REMOTE_CLIENT_INTEGRATION_RESULT=PASS
```

Verifier les trois valeurs de connexion :

```bash
grep -E '^OPENSEARCH_PRIMARY=|^OPENSEARCH_URL=|^OPENSEARCH_SSL_CERTIFICATE_VERIFICATION=' config/opensearch.env
```

Verifier que le Compose d'execution n'active pas l'OpenSearch local :

```bash
grep -A3 '^  opensearch:$' dev/generated/docker-compose.runtime.yml
```

Le profil attendu est `oculox-opensearch-local-disabled`.

## 8. Verification reseau avant la capture

Ces tests seront executes depuis le Core puis chaque Hedgehog uniquement au
moment du deploiement :

```bash
curl --cacert nginx/ca-trust/oculox-opensearch-ca.crt --config dev/generated/opensearch-clients/api.curlrc https://192.168.1.241:9200/_cluster/health?pretty
```

```bash
curl --cacert nginx/ca-trust/oculox-opensearch-ca.crt --config dev/generated/opensearch-clients/arkime.curlrc https://192.168.1.241:9200/_plugins/_security/authinfo?pretty
```

La capture de production ne doit etre activee qu'apres validation de l'IP, du
routage, du pare-feu, de la CA et des permissions du compte depuis la machine
concernee.

## 9. Limite actuelle

Cette procédure prépare et valide le code local. Elle ne prouve pas encore que tous
les clients fonctionnent contre le cluster reel. Les connexions de Logstash,
Arkime, Dashboards, API et Hedgehog seront testees independamment lors de la validation des clients.

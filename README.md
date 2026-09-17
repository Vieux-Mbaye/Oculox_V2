# Oculox

Oculox est une plateforme de supervision reseau IT/OT basee sur Malcolm. Elle
collecte le trafic reseau, extrait des journaux de securite, les envoie vers
OpenSearch, puis les presente dans OpenSearch Dashboards, Arkime et les outils
du portail Oculox.

Ce depot contient l'integration Oculox actuelle :

- un Core Oculox avec portail, Nginx, Keycloak, Dashboards, Arkime, Logstash,
  Filebeat local et services auxiliaires ;
- un cluster OpenSearch dedie a trois noeuds ;
- un role collector/Hedgehog pour les sites distants ;
- une authentification SSO Keycloak avec RBAC ;
- des comptes de service OpenSearch separes selon le principe du moindre
  privilege ;
- des scripts d'installation et de validation regroupes dans `./oculox`.

Les secrets, certificats generes, bundles, journaux runtime, bases de donnees,
captures et fichiers `*.env` reels ne doivent pas etre ajoutes a Git.

## Vue D'Ensemble

```text
                       Utilisateurs
                            |
                            | HTTPS 443 / 5601
                            v
              +-------------------------------+
              | Zone 2 - Core Oculox          |
              |                               |
              | Nginx reverse proxy           |
              | Keycloak SSO / RBAC           |
              | Portail Oculox                |
              | OpenSearch Dashboards         |
              | Arkime Viewer                 |
              | Logstash 1 + Logstash 2       |
              | Filebeat local                |
              | API, NetBox, Filescan, etc.   |
              +-------------------------------+
                    ^                    |
                    | Beats TLS 5044/5045|
                    |                    | HTTPS 9200
                    |                    v
 +------------------------------+  +------------------------------+
 | Zone 1 - Collecteur Par Gare |  | Zone 3 - Cluster OpenSearch |
 |                              |  |                              |
 | Port mirroring / SPAN        |  | HAProxy endpoint 9200       |
 | Zeek                         |  | OpenSearch node 1           |
 | Suricata                     |  | OpenSearch node 2           |
 | Arkime capture/live          |  | OpenSearch node 3           |
 | Filebeat load balancing      |  | OpenSearch Security         |
 +------------------------------+  +------------------------------+
```

### Role Des Services Principaux

| Service | Role |
|---|---|
| Nginx | Porte d'entree HTTPS, reverse proxy, controle d'acces portail et routage vers les outils |
| Keycloak | Identite centrale, SSO, MFA, groupes et roles humains |
| Portail Oculox | Page d'accueil et point d'acces aux outils |
| OpenSearch Dashboards | Interface de recherche, visualisation et dashboards |
| OpenSearch Security | Autorisation fine dans OpenSearch et Dashboards |
| OpenSearch | Stockage des logs, index, objets Dashboards et donnees Arkime |
| Logstash / Logstash-2 | Ingestion resiliente, normalisation et sortie vers OpenSearch |
| Filebeat | Acheminement des logs vers les deux Logstash avec repartition de charge |
| Zeek | Analyse protocolaire reseau |
| Suricata | Detection IDS/alertes |
| Arkime | Sessions reseau, recherche paquets et PCAP |

## SSO Et RBAC En Simple

Le SSO signifie qu'un utilisateur se connecte une seule fois a Keycloak et que
les applications Oculox reutilisent cette session.

```text
1. L'utilisateur ouvre https://<IP_CORE>/
2. Nginx redirige vers Keycloak si aucune session n'existe.
3. Keycloak authentifie l'utilisateur et impose le MFA.
4. Nginx verifie que l'utilisateur appartient a /oculox-users.
5. Le portail s'affiche.
6. L'utilisateur ouvre Dashboards.
7. Dashboards utilise son propre client OIDC Keycloak.
8. Keycloak confirme l'identite sans redemander le mot de passe.
9. OpenSearch Security applique les droits reels.
```

Les profils humains principaux sont :

| Profil | Usage |
|---|---|
| `oculox-admin` | Administration plateforme |
| `oculox-analyst` | Analyse, recherche, dashboards et investigation courante |
| `oculox-incident-response` | Investigation incident, Arkime Hunt et PCAP |
| `oculox-viewer` | Consultation lecture seule |
| `oculox-denied` | Compte de controle qui doit etre refuse |

Les comptes techniques OpenSearch sont separes des utilisateurs humains :
`oculox_logstash`, `oculox_arkime`, `oculox_dashboards`,
`oculox_dashboards_helper`, `oculox_api`, etc. Chaque service a seulement les
droits necessaires a son role.

## Ordre D'Installation Sur VM Neuves

L'ordre recommande est :

```text
1. Installer le cluster OpenSearch sur sa VM dediee.
2. Creer le bundle OpenSearch reserve au Core.
3. Installer le Core avec ce bundle.
4. Valider Keycloak, Dashboards, Logstash et les clients OpenSearch.
5. Creer un bundle collecteur par gare.
6. Installer un collector/Hedgehog par gare.
7. Valider l'ingestion de bout en bout.
```

Cette separation est importante : le Core doit connaitre l'endpoint et la CA du
cluster OpenSearch avant de demarrer Dashboards, Logstash, Arkime et l'API.

## Installation Du Cluster OpenSearch

Sur la VM cluster :

```bash
cd ~/Oculox
./oculox install cluster --endpoint-ip <IP_CLUSTER>
```

Arguments :

- `install cluster` prepare une VM dediee au stockage OpenSearch ;
- `--endpoint-ip <IP_CLUSTER>` indique l'adresse qui sera mise dans les
  certificats et exposee aux clients Core/Hedgehog ;
- le script genere la PKI, rend les fichiers Compose, demarre les trois noeuds,
  initialise OpenSearch Security et publie l'endpoint HTTPS.

Verifier :

```bash
./oculox cluster status
./oculox cluster validate
curl -k https://<IP_CLUSTER>:9200/_cluster/health?pretty
```

La sante attendue pour une plateforme propre est :

```text
status: green
number_of_nodes: 3
unassigned_shards: 0
```

Creer ensuite le bundle Core :

```bash
./oculox cluster client-bundle core /tmp/oculox-core-opensearch
cd /tmp/oculox-core-opensearch
sha256sum -c SHA256SUMS
```

Ce bundle contient la CA OpenSearch et les identites techniques necessaires au
Core. Il contient des secrets et ne doit jamais etre ajoute a Git.

## Installation Du Core Oculox

Sur la VM Core :

```bash
cd ~/Oculox
mkdir -p dev/generated/opensearch-bundles
scp -r <user>@<IP_CLUSTER>:/tmp/oculox-core-opensearch \
  dev/generated/opensearch-bundles/

cd dev/generated/opensearch-bundles/oculox-core-opensearch
sha256sum -c SHA256SUMS

cd ~/Oculox
./oculox install principal \
  --server-name <IP_CORE_OU_DNS> \
  --opensearch-bundle dev/generated/opensearch-bundles/oculox-core-opensearch
```

Arguments :

- `install principal` installe le Core Oculox ;
- `--server-name` declare le nom ou l'IP publique du Core. Cette valeur sert aux
  certificats Web, aux URLs Keycloak et aux redirect URIs OIDC ;
- `--opensearch-bundle` importe la CA et les comptes de service du cluster
  OpenSearch distant.

Valider :

```bash
./oculox status
./oculox keycloak verify-hardening
./oculox verify clients
curl --cacert nginx/ca-trust/oculox-opensearch-ca.crt \
  --config .opensearch.primary.curlrc \
  https://<IP_CLUSTER>:9200/_cluster/health?pretty
```

## Installation D'Un Collecteur Par Gare

Sur le Core, creer un bundle pour chaque collecteur :

```bash
./oculox collector-bundle <nom-collecteur> <IP_CORE_OU_DNS> \
  /tmp/oculox-collector-<nom-collecteur>
```

Si le collecteur doit aussi parler directement au cluster OpenSearch pour
Arkime, creer le bundle Hedgehog cote cluster :

```bash
./oculox cluster client-bundle hedgehog /tmp/oculox-hedgehog-opensearch
```

Sur la VM collecteur :

```bash
cd ~/Oculox
./oculox install hedgehog \
  --principal-host <IP_CORE_OU_DNS> \
  --collector-name <nom-collecteur> \
  --bundle <repertoire-bundle-collecteur> \
  --opensearch-bundle <repertoire-bundle-opensearch-hedgehog>
```

Arguments :

- `install hedgehog` installe le role collecteur ;
- `--principal-host` indique le Core qui recevra les flux Beats ;
- `--collector-name` identifie la gare ou le capteur ;
- `--bundle` contient la CA et le certificat Beats du collecteur ;
- `--opensearch-bundle` contient les secrets OpenSearch limites au role
  Hedgehog lorsque necessaire.

Un collecteur est attendu par gare. Il recoit le trafic via port mirroring/SPAN,
Zeek et Suricata produisent des logs, Filebeat les envoie vers les deux
Logstash du Core, et Arkime peut ecrire directement dans OpenSearch selon la
configuration retenue.

## Le Role De `./oculox`

`./oculox` est l'interface unique d'installation et d'exploitation. Il evite
d'appeler directement de nombreux scripts internes.

Commandes principales :

```bash
./oculox install principal --server-name <IP_CORE_OU_DNS> --opensearch-bundle <bundle>
./oculox install hedgehog --principal-host <IP_CORE_OU_DNS> --collector-name <nom> --bundle <bundle>
./oculox install cluster --endpoint-ip <IP_CLUSTER>

./oculox start
./oculox stop
./oculox restart [service...]
./oculox status
./oculox logs [service...]
./oculox pull
./oculox validate

./oculox keycloak provision
./oculox keycloak verify-hardening
./oculox keycloak credentials

./oculox configure-opensearch-remote --bundle <bundle-core>
./oculox verify clients
```

Il charge toujours le Compose officiel et la surcharge Oculox
`dev/compose/docker-compose.dev.yml`, rend la configuration runtime et conserve
les fichiers generes dans `dev/generated/`.

## Fichiers Et Repertoires Importants

| Chemin | Role |
|---|---|
| `oculox` | Lanceur d'installation, exploitation et validation |
| `docker-compose.yml` | Compose principal herite de Malcolm |
| `dev/compose/docker-compose.dev.yml` | Surcharges Oculox : restart policy, Logstash-2, mounts locaux, SSO |
| `config/*.env.example` | Contrats de configuration versionnes sans secret |
| `config/*.env` | Configuration locale ignoree par Git |
| `keycloak/scripts/realm-setup.sh` | Provisionnement realm, clients, groupes, roles et comptes |
| `nginx/` | Reverse proxy, SSO portail, routage, headers et pages statiques |
| `dashboards/` | Template OpenSearch Dashboards et entree OIDC |
| `dev/scripts/keycloak/` | Activation, verification et durcissement Keycloak |
| `dev/scripts/opensearch-cluster/` | Installation, PKI, security config et bundles cluster |
| `dev/config/opensearch-cluster/` | Roles, mappings, HAProxy et templates du cluster |
| `dev/tests/` | Tests de non-regression Keycloak, OpenSearch et Compose |
| `dev/docs/` | Guides de conception, installation, dimensionnement et exploitation |
| `dev/generated/` | Resultats generes localement, ignores par Git |

## Validation Avant Livraison

Avant commit ou push :

```bash
git diff --check
./dev/scripts/validate-compose.sh
python3 -m unittest discover -s dev/tests/keycloak -p 'test_*.py'
python3 -m unittest discover -s dev/tests/opensearch-cluster -p 'test_*.py'
./dev/tests/test-branding.sh
./oculox status
./oculox keycloak verify-hardening
./oculox verify clients
```

Resultat attendu :

```text
Compose valide
tests OK
tous les conteneurs healthy
KEYCLOAK hardening PASS
CLIENT_CONNECTIVITY_RESULT=PASS
```

## Securite Et Git

Ne jamais versionner :

```text
config/*.env
.opensearch*.curlrc
dev/generated/
*.key
bundles client
captures PCAP
logs runtime
bases de donnees
archives temporaires
```

Les fichiers versionnes doivent rester generiques et portables. Pour une VM
neuve avec une nouvelle IP, relancer les commandes `install`, `prepare` ou
`configure-public-endpoint` afin de recalculer les certificats, URLs Keycloak et
redirect URIs.

## Documentation De Detail

- Keycloak/OIDC : `dev/keycloak/11_configuration_keycloak_detaillee_keep_it_simple.md`
- Plan de developpement Keycloak : `dev/keycloak/02_plan_developpement_keycloak_oculox.md`
- Installation Principal/Hedgehog : `dev/docs/13_installation_resiliente_principal_hedgehog.md`
- Cluster OpenSearch : `dev/docs/22_plan_directeur_cluster_opensearch_vm.md`
- Dimensionnement ferroviaire : `dev/docs/dimensionnement/`
- Scripts OpenSearch : `dev/scripts/opensearch-cluster/README.md`
- Compose cluster : `dev/compose/opensearch-cluster/README.md`

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

**Etat au 30 septembre 2026 : le parcours EJBCA multi-VM est implemente,
mais il n'a pas encore ete valide depuis trois VM vierges.** La reference
operative est [installation trois VM et bundles](dev/ejbca/docs/installation_3_vm_et_bundles.md).
Les corrections et preuves de test sont dans le
[rapport de livraison EJBCA](dev/ejbca/docs/livraison_ejbca_2026-09-30.md).
Les exemples ci-dessous ne remplacent pas ses controles ni ses etapes de
confiance initiale. Ne pas publier ce deploiement comme qualifie en production
avant l'essai complet sur les trois VM.

L'ordre cible recommande avec EJBCA est :

```text
1. Installer le Core minimal et EJBCA sur la VM Core.
2. Creer les CA et profils EJBCA Oculox.
3. Configurer l'API HTTPS EJBCA et emettre les certificats Core.
4. Enroler un agent Cluster par CSR locale et bundle public authentifie.
5. Installer le cluster OpenSearch avec des certificats emis par EJBCA.
6. Creer le bundle OpenSearch reserve au Core.
7. Finaliser le Core avec ce bundle ; valider Keycloak, Dashboards et ingestion.
8. Enroler un agent Collecteur puis son certificat Filebeat sur sa VM.
9. Installer le Collecteur et valider l'ingestion de bout en bout.
```

Cette separation est importante : EJBCA est la source de certificats, puis le
Core doit connaitre l'endpoint et la CA du cluster OpenSearch avant de demarrer
Dashboards, Logstash, Arkime et l'API.

Dans le deploiement actuel, EJBCA est installe sur la VM Core. Les certificats
emis localement ne prouvent pas la migration du cluster distant : verifier
l'issuer du certificat presente par l'endpoint reel. Une connexion par IP
necessite une reemission si l'IP change; un DNS stable dans les SAN permet de
changer l'IP via DNS sans reemettre pour ce seul changement.

### Premiere Etape Obligatoire : Core Et EJBCA

Sur la VM Core :

```bash
cd ~/Oculox_V2
./oculox bootstrap principal --server-name <DNS_OU_IP_CORE>
./oculox pki-ca init
./oculox pki-ca start
./oculox pki-ca create-ca-plan
./oculox pki-ca provision-profiles
./oculox pki-ca harden
./oculox pki-ca verify-hardening
./oculox pki-ca configure-api --public-host <DNS_OU_IP_CORE> --bind-address <IP_LOCALE_CORE>
./oculox pki-ca provision-profiles --verify-only
./oculox pki enroll --provider ejbca --service web_ca --install
./oculox pki enroll --provider ejbca --service ingestion_ca --install
./oculox pki enroll --provider ejbca --service web_server --install
./oculox pki enroll --provider ejbca --service logstash_server --install
./oculox pki enroll --provider ejbca --service filebeat_client --install
./oculox pki status
```

`bootstrap` ne demarre pas le Core : il cree la configuration necessaire pour
que les SAN des certificats reprennent l'IP ou le DNS choisi. Les commandes
suivantes installent EJBCA et les certificats actifs du Core. Keycloak n'a pas d'HTTPS direct
separe dans l'architecture actuelle : son acces public HTTPS passe par Nginx,
donc il est couvert par le certificat Web Nginx emis par EJBCA.

## Installation Du Cluster OpenSearch

Sur la VM cluster :

```bash
cd ~/Oculox_V2
./oculox pki agent-init --role cluster --identity cluster-01
# Sur Core, autoriser la CSR publique avec ./oculox pki-ca authorize-agent.
# Revenir ici avec le bundle public et l'empreinte Root CA verifiee.
./oculox pki agent-install --bundle ~/cluster-01-enrollment --root-sha256 <EMPREINTE>
cp dev/config/opensearch-cluster/cluster.yml.example ~/oculox-cluster.yml
nano ~/oculox-cluster.yml
./oculox install cluster --config ~/oculox-cluster.yml --check
./oculox install cluster --config ~/oculox-cluster.yml
```

Arguments :

- `install cluster` prepare une VM dediee au stockage OpenSearch ;
- `--config ~/oculox-cluster.yml` declare l'endpoint, le profil, la heap, les
  watermarks, les politiques de stockage et les ports exposes ;
- `--check` valide la configuration et le Compose rendu sans demarrer le
  cluster ;
- le script enrole la PKI OpenSearch via EJBCA, rend les fichiers Compose,
  demarre les trois noeuds, initialise OpenSearch Security et publie l'endpoint
  HTTPS.

La PKI OpenSearch comprend :

- la CA `Oculox OpenSearch CA`, geree par EJBCA ;
- un certificat par noeud OpenSearch ;
- un certificat endpoint HAProxy/OpenSearch ;
- un certificat administrateur OpenSearch ;
- les bundles de confiance utilises par Dashboards, Logstash, Arkime et les
  clients internes.

Le script d'installation du cluster n'utilise plus le generateur OpenSSL local.
Il appelle `./oculox pki request` via l'agent mTLS pour les entrees
`opensearch_*` du manifeste. Les cles sont generees sur la VM Cluster.

Pour un laboratoire rapide, `./oculox install cluster --endpoint-ip
<IP_CLUSTER>` reste accepte. Pour une installation partagee ou reproductible,
le fichier `~/oculox-cluster.yml` est preferable.

Verifier :

```bash
./oculox cluster status
./oculox cluster validate
curl --cacert dev/generated/opensearch-cluster/pki/client-trust/oculox-opensearch-ca.crt \
  -u oculox_platform_admin \
  https://<IP_CLUSTER>:9200/_cluster/health?pretty
```

La sante attendue pour une plateforme propre est :

```text
status: green
number_of_nodes: 3
unassigned_shards: 0
```

Creer ensuite le bundle Core :

```bash
mkdir -p ~/oculox-bundles
./oculox cluster client-bundle core ~/oculox-bundles/core
cd ~/oculox-bundles/core
sha256sum -c SHA256SUMS
```

Ce bundle contient des mots de passe dans les fichiers `.curlrc`, la CA publique,
l'URL et les parametres de stockage dans `bundle.env`, ainsi que `SHA256SUMS`.
Il ne contient ni cle de CA ni certificat administrateur OpenSearch. Il transporte
la configuration cliente, meme lorsque les certificats sont emis par EJBCA.

Ce bundle contient la CA OpenSearch et les identites techniques necessaires au
Core. Il contient des secrets et ne doit jamais etre ajoute a Git.

## Installation Du Core Oculox

Sur la VM Core :

```bash
cd ~/Oculox_V2
mkdir -p ~/oculox-bundles
scp -r <user>@<IP_CLUSTER>:/home/<user>/oculox-bundles/core \
  ~/oculox-bundles/

cd ~/oculox-bundles/core
sha256sum -c SHA256SUMS

cd ~/Oculox_V2
./oculox resume-install principal \
  --server-name <IP_CORE_OU_DNS> \
  --opensearch-bundle ~/oculox-bundles/core
./oculox keycloak provision --admin-username <ADMIN_KEYCLOAK>
./oculox keycloak activate-portal
./oculox keycloak activate-dashboards
./oculox restart keycloak nginx-proxy dashboards
```

Apres demarrage et provisionnement Keycloak, **sur la VM Cluster** :

```bash
./oculox cluster configure-oidc --keycloak-auth-url https://<IP_CORE_OU_DNS>/keycloak
./oculox cluster verify-oidc
```

La confiance Keycloak utilise la chaine **Web EJBCA** du bundle public de
l'agent, pas la CA OpenSearch. Pour une ancienne confiance deja configuree,
`./oculox cluster oidc-trust` recharge les noeuds un par un sans reecrire les
roles. Sur Core, `python3 dev/tests/keycloak/test_live_opensearch_oidc.py
--run-live` teste les jetons signes et les mappings lecture/admin avec un
client temporaire supprime en fin de test. Terminer par une connexion humaine
Dashboards; une redirection HTTP seule ne valide pas OIDC.

Arguments :

- `resume-install principal` termine l'installation du Core Oculox apres `bootstrap` ;
- `--server-name` declare le nom ou l'IP publique du Core. Cette valeur sert aux
  certificats Web, aux URLs Keycloak et aux redirect URIs OIDC ;
- `--opensearch-bundle` importe la CA et les comptes de service du cluster
  OpenSearch distant.

Valider :

```bash
./oculox status
./oculox keycloak verify-hardening
./oculox verify clients
./oculox host-telemetry verify
./oculox host-telemetry status
curl --cacert nginx/ca-trust/oculox-opensearch-ca.crt \
  --config .opensearch.primary.curlrc \
  https://<IP_CLUSTER>:9200/_cluster/health?pretty
```

La commande `install principal` active aussi la telemetrie hote par defaut :
logs Nginx, syslog TCP/UDP local sur `5514`, et services Fluent Bit utilisateur
pour `cpu`, `mem`, `df`, `disk`, `network`, `systemd`, `kmsg`, `auditlog`,
`aide` et `thermal`. Ces flux alimentent les dashboards "Malcolm and
Third-Party Logs". Le port Filebeat dedie est `5055`, reserve aux logs hote, ce
qui evite le conflit avec `5045` deja utilise par le second Logstash.
Sur Debian/Ubuntu, `./oculox install` installe automatiquement les dependances
OS necessaires : `fluent-bit`, `auditd`, `aide` et `jq`.

## Installation D'Un Collecteur Par Gare

Sur le Core, creer un bundle pour chaque collecteur :

```bash
./oculox collector-bundle <nom-collecteur> <IP_CORE_OU_DNS> \
  /tmp/oculox-collector-<nom-collecteur>
```

Ce bundle contient uniquement la CA publique et les endpoints : le collecteur
genere sa cle et sa CSR sur sa VM, puis demande son certificat Filebeat a
EJBCA via un agent autorise. Voir la procedure d'enrolement dans la reference.

Si le collecteur doit aussi parler directement au cluster OpenSearch pour
Arkime, creer le bundle Hedgehog cote cluster :

```bash
./oculox cluster client-bundle hedgehog /tmp/oculox-hedgehog-opensearch
```

Sur la VM collecteur :

```bash
cd ~/Oculox_V2
./oculox pki agent-init --role collector --identity <nom-collecteur>
# Faire autoriser la CSR publique sur Core, puis transferer le bundle public.
./oculox pki agent-install --bundle ~/collector-enrollment --root-sha256 <EMPREINTE>
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
- `--bundle` contient la CA publique et les endpoints du collecteur ;
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
./oculox pki-ca init|start|create-ca-plan|harden|verify-hardening
./oculox pki audit|status|expiry
./oculox pki enroll --provider ejbca --service <entree> --install

./oculox bootstrap principal --server-name <IP_CORE_OU_DNS>
# Provisionner EJBCA et installer Cluster avant de finaliser Core (procedure ci-dessus).
./oculox resume-install principal --server-name <IP_CORE_OU_DNS> --opensearch-bundle <bundle>
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
./oculox host-telemetry install-deps
./oculox host-telemetry configure
./oculox host-telemetry start
./oculox host-telemetry status

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
| `dev/ejbca/` | Plan CA, manifest PKI, Compose EJBCA et documentation PKI |
| `dev/scripts/ejbca/` | Initialisation, durcissement et enrolement EJBCA |
| `dev/scripts/keycloak/` | Activation, verification et durcissement Keycloak |
| `dev/scripts/opensearch-cluster/` | Installation cluster, enrolement PKI EJBCA, security config et bundles cluster |
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
./oculox pki-ca verify-hardening
./oculox pki status
./oculox pki expiry
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

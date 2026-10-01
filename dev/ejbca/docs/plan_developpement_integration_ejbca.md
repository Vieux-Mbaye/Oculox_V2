# Plan de developpement - Integration EJBCA pour la PKI Oculox

## Objectif

Mettre en place une gestion PKI professionnelle pour Oculox en utilisant EJBCA comme autorite de certification centrale.

Le principe d'architecture est le suivant :

```text
EJBCA emet et gere les certificats
        |
        v
Oculox installe, verifie, renouvelle et supervise les certificats
        |
        v
Nginx, Keycloak, OpenSearch, Dashboards, Logstash, Filebeat et services internes les utilisent
```

Oculox ne doit pas reinventer une PKI complete. Oculox doit devenir compatible PKI :

- inventorier les certificats necessaires ;
- demander ou importer les certificats ;
- installer les certificats aux bons emplacements ;
- verifier les chaines de confiance ;
- redemarrer uniquement les services concernes ;
- tester le fonctionnement ;
- surveiller l'expiration ;
- permettre le renouvellement et le rollback.

## Perimetre

L'integration PKI doit couvrir :

- HTTPS public du portail via Nginx ;
- acces Keycloak via l'URL publique Oculox ;
- OpenSearch et OpenSearch Dashboards ;
- Logstash et Filebeat ;
- API Oculox et services internes ;
- bundles de confiance CA ;
- futurs composants distants prevus par l'architecture, meme s'ils ne sont pas encore deployes ;
- procedures d'import de certificats fournis par un client.

Les certificats extraits du trafic reseau par Zeek ou Arkime ne font pas partie de la PKI Oculox. Ce sont des artefacts d'investigation.

## Principe fondamental

EJBCA est la PKI.

EJBCA doit gerer :

- Root CA ;
- Intermediate CA ;
- profils de certificats ;
- emission des certificats ;
- expiration ;
- revocation ;
- CRL / OCSP ;
- journalisation des emissions ;
- politiques de certificats.

Oculox doit gerer :

- la matrice des besoins certificats ;
- les chemins de destination ;
- les permissions fichier ;
- le deploiement des certificats ;
- la verification technique ;
- les tests applicatifs ;
- le renouvellement orchestre ;
- le rollback.

## Architecture PKI cible

La hierarchie recommandee dans EJBCA est :

```text
Oculox Root CA
  |
  +-- Oculox Web CA
  |     +-- nginx / portail
  |     +-- keycloak public endpoint
  |
  +-- Oculox Internal Services CA
  |     +-- logstash server
  |     +-- filebeat client
  |     +-- api service
  |     +-- dashboards helper
  |
  +-- Oculox OpenSearch CA
        +-- opensearch node
        +-- opensearch endpoint
        +-- opensearch admin client
        +-- dashboards to opensearch trust
```

Dans un environnement client, cette hierarchie peut etre remplacee partiellement ou totalement par la PKI du client.

## Profils de certificats a creer dans EJBCA

| Profil | Usage | Type |
| --- | --- | --- |
| `oculox-web-server` | TLS public Nginx / portail | serveur |
| `oculox-keycloak-public` | endpoint public Keycloak si separe de Nginx | serveur |
| `oculox-logstash-server` | entree TLS Logstash | serveur |
| `oculox-filebeat-client` | authentification mTLS Filebeat | client |
| `oculox-opensearch-node` | identite TLS des noeuds OpenSearch | serveur |
| `oculox-opensearch-endpoint` | endpoint OpenSearch expose aux clients internes | serveur |
| `oculox-opensearch-admin` | administration securite OpenSearch | client |
| `oculox-service-client` | authentification de services internes | client |

Chaque profil doit imposer :

- une duree de validite controlee ;
- des Extended Key Usage adaptes ;
- des SAN obligatoires ;
- une taille de cle minimale ;
- une signature par l'Intermediate CA correspondant ;
- une politique de revocation.

## Phase 1 - Audit sans changement

Objectif : connaitre l'etat actuel sans modifier la plateforme.

Commandes cibles :

```bash
./oculox pki audit
./oculox pki status
```

La commande `audit` doit produire un inventaire complet :

- chemin du certificat ;
- chemin de la cle ;
- CA associee ;
- service consommateur ;
- subject ;
- issuer ;
- SAN ;
- date d'expiration ;
- usages serveur/client ;
- validation de chaine ;
- correspondance cle/certificat ;
- presence dans les volumes Docker ;
- statut du service.

La commande `status` doit donner une vue synthetique :

```text
WEB TLS                 OK
KEYCLOAK PUBLIC TLS     OK via Nginx
LOGSTASH TLS            OK
FILEBEAT CLIENT TLS     OK
OPENSEARCH NODE TLS     OK
OPENSEARCH ENDPOINT TLS OK
CA TRUST BUNDLE         OK
```

Cette phase ne doit redemarrer aucun service.

## Decision d'architecture multi-VM

Pour le statut actuel et le parcours cible trois VM, consulter
[Installation et bundles](installation_3_vm_et_bundles.md). L'enrolement REST mTLS
Cluster et Collecteur est implemente et teste avec des identites jetables.
La qualification depuis trois clones sur VM vierges reste a executer.

EJBCA est installe sur la VM Core Oculox. Il n'est pas versionne comme une
autorite locale separee dans chaque VM. Les autres roles consomment donc les
certificats issus de cette PKI centrale.

Ordre cible :

```text
VM Core      : EJBCA + CA + certificats Core
VM Cluster   : certificats OpenSearch emis par EJBCA + installation cluster
VM Core      : import du bundle cluster + finalisation Core
VM Collecteur: bundle collecteur + installation Hedgehog
```

Cette decision evite d'avoir plusieurs Root CA concurrentes. Elle impose en
revanche que l'etape d'installation du cluster puisse acceder a EJBCA par un
canal d'enrolement distant authentifie. Le transport de cles privees depuis Core
n'est pas la procedure normale retenue pour
la VM Cluster.

## Phase 2 - Manifeste PKI source de verite

Creer le fichier :

```text
dev/ejbca/pki-manifest.yml
```

Ce manifeste decrit les certificats attendus. Il ne genere rien. Il sert de source de verite pour Oculox.

Exemple cible :

```yaml
certificates:
  web_server:
    service: nginx-proxy
    profile: oculox-web-server
    type: server
    cert: nginx/certs/cert.pem
    key: nginx/certs/key.pem
    ca: nginx/ca-trust/oculox-web-ca.crt
    san_required:
      - public_endpoint
    reload:
      - nginx-proxy

  logstash_server:
    service: logstash
    profile: oculox-logstash-server
    type: server
    cert: dev/generated/pki/server.crt
    key: dev/generated/pki/server.key
    ca: dev/generated/pki/ca.crt
    san_required:
      - logstash
      - logstash-2
    reload:
      - logstash
      - logstash-2

  filebeat_client:
    service: filebeat
    profile: oculox-filebeat-client
    type: client
    cert: dev/generated/pki/client.crt
    key: dev/generated/pki/client.key
    ca: dev/generated/pki/ca.crt
    reload:
      - filebeat
```

Le manifeste doit permettre de tester la plateforme meme si les certificats proviennent :

- d'EJBCA ;
- d'une PKI client ;
- d'un mode developpement temporaire.

## Phase 3 - Installation EJBCA

Creer une zone dediee :

```text
dev/ejbca/
  docs/
  compose/
  config/
  scripts/
  profiles/
```

Livrables attendus :

- compose EJBCA de developpement ;
- variables d'environnement ;
- procedure de demarrage ;
- procedure de sauvegarde ;
- procedure de restauration ;
- procedure d'initialisation des CA ;
- documentation d'administration.

EJBCA doit etre separe de la plateforme Oculox principale au debut. L'objectif est de tester l'integration sans perturber les services existants.

## Phase 4 - Creation des CA dans EJBCA

Creer dans EJBCA :

- `Oculox Root CA` ;
- `Oculox Web CA` ;
- `Oculox Internal Services CA` ;
- `Oculox OpenSearch CA`.

Regles recommandees :

- Root CA protegee et rarement utilisee ;
- certificats services emis par les CA intermediaires ;
- durees de vie differentes selon les profils ;
- revocation activee ;
- CRL publiee ;
- OCSP prepare si retenu dans l'architecture.

## Phase 5 - Integration Oculox vers EJBCA

Statut actuel : implemente pour l'enrolement EJBCA en staging, le renouvellement controle et l'import de bundles client. La procedure detaillee et les tests sont documentes dans `dev/ejbca/docs/phases_5_6_7_integration_installation_validation.md`.

Ajouter les commandes :

```bash
./oculox pki enroll --provider ejbca
./oculox pki renew --provider ejbca --service nginx
./oculox pki renew --provider ejbca --service opensearch
./oculox pki import --provider customer
```

`enroll` doit :

1. lire `dev/ejbca/pki-manifest.yml` ;
2. determiner les certificats requis ;
3. generer une CSR si necessaire ;
4. demander la signature a EJBCA ;
5. recuperer le certificat signe ;
6. installer le certificat ;
7. mettre a jour les CA trust bundles ;
8. verifier la chaine ;
9. proposer le redemarrage controle.

`import --provider customer` doit :

1. verifier les certificats fournis par le client ;
2. verifier les SAN ;
3. verifier les usages ;
4. verifier les CA ;
5. refuser les certificats invalides ou expires ;
6. installer uniquement apres validation.

## Phase 6 - Installation sans interruption brutale

Statut actuel : implemente avec staging obligatoire par defaut, sauvegarde des fichiers actifs, remplacement atomique, redemarrage cible sur option `--restart` et rollback si la validation post-installation echoue.

Principe :

- toujours generer ou importer dans une zone temporaire ;
- verifier avant installation ;
- sauvegarder les certificats actifs ;
- remplacer de maniere atomique ;
- redemarrer uniquement les services concernes ;
- tester immediatement ;
- rollback automatique si le test echoue.

Exemple :

```bash
./oculox pki renew --provider ejbca --service nginx
./oculox validate web
```

Si `validate web` echoue :

- restaurer l'ancien certificat ;
- redemarrer Nginx ;
- marquer l'operation comme echouee ;
- conserver les logs.

## Phase 7 - Validation automatique

Statut actuel : implemente via `./oculox validate web|keycloak|dashboards|opensearch|ingestion|all`.

Ajouter les tests suivants :

```bash
./oculox validate pki
./oculox validate web
./oculox validate keycloak
./oculox validate dashboards
./oculox validate opensearch
./oculox validate ingestion
```

Les tests doivent verifier :

- HTTPS portail accessible ;
- certificat portail valide ;
- certificat contient le bon SAN ;
- Keycloak accessible via l'URL publique ;
- redirections OIDC correctes ;
- Dashboards se connecte a OpenSearch avec verification TLS active ;
- OpenSearch repond avec une chaine TLS valide ;
- Filebeat envoie vers Logstash ;
- Logstash accepte les evenements sans erreur TLS ;
- aucun service critique n'utilise `ssl verification disabled` sauf exception documentee.

## Phase 8 - Expiration, renouvellement et alertes

Ajouter :

```bash
./oculox pki expiry
```

Sortie attendue :

```text
web_server                 expires in 365 days    OK
logstash_server            expires in 280 days    OK
filebeat_client            expires in 280 days    OK
opensearch_node_1          expires in 620 days    OK
opensearch_endpoint        expires in 620 days    OK
```

Seuils recommandes :

- plus de 60 jours : OK ;
- moins de 60 jours : WARNING ;
- moins de 30 jours : CRITICAL ;
- expire : BLOCKING.

Le renouvellement automatique complet peut etre ajoute ensuite. La premiere version doit au minimum alerter clairement et permettre un renouvellement controle.

## Phase 9 - Mode client avec PKI externe

Oculox doit pouvoir fonctionner chez un client qui possede deja sa propre PKI.

Dans ce cas :

- EJBCA Oculox peut ne pas etre utilise ;
- le client fournit les certificats ;
- Oculox valide et installe ;
- les noms DNS/SAN doivent venir du plan d'adressage client ;
- les CA client doivent etre ajoutees dans les trust stores Oculox.

Commande cible :

```bash
./oculox pki import --provider customer --bundle ./customer-pki-bundle/
```

Le bundle client doit contenir :

```text
customer-pki-bundle/
  ca/
  nginx/
  logstash/
  filebeat/
  opensearch/
  manifest.yml
```

## Phase 10 - Documentation

Documents a produire :

```text
dev/ejbca/docs/architecture_pki_ejbca.md
dev/ejbca/docs/procedure_installation_ejbca.md
dev/ejbca/docs/procedure_enrollment_oculox.md
dev/ejbca/docs/procedure_import_pki_client.md
dev/ejbca/docs/procedure_renouvellement.md
dev/ejbca/docs/procedure_revocation.md
dev/ejbca/docs/procedure_rollback.md
```

La documentation doit expliquer :

- role d'EJBCA ;
- role d'Oculox ;
- chaines de certification ;
- profils ;
- services consommateurs ;
- commandes ;
- tests ;
- renouvellement ;
- revocation ;
- integration avec une PKI client ;
- comportement attendu sur VM neuve.

## Phase 11 - Ordre de developpement recommande

Ordre exact pour eviter de casser la plateforme :

1. Implementer `./oculox pki audit`.
2. Implementer `./oculox pki status`.
3. Creer `dev/ejbca/pki-manifest.yml`.
4. Documenter les certificats existants.
5. Ajouter `./oculox validate pki`.
6. Installer EJBCA en environnement separe.
7. Creer les CA et profils dans EJBCA.
8. Ajouter `./oculox pki enroll --provider ejbca`.
9. Tester d'abord le certificat Nginx.
10. Tester Keycloak via Nginx.
11. Tester Logstash/Filebeat.
12. Tester OpenSearch et Dashboards.
13. Ajouter le renouvellement controle.
14. Ajouter le mode import client.
15. Finaliser la documentation.
16. Faire une validation complete sur VM neuve.

## Tests de non-regression obligatoires

Avant chaque merge :

```bash
./oculox validate
./oculox validate pki
./oculox status
```

Tests fonctionnels a verifier :

- portail accessible ;
- login Keycloak ;
- SSO vers Dashboards ;
- Dashboards vers OpenSearch ;
- ingestion Filebeat vers Logstash ;
- absence d'erreurs TLS dans les logs ;
- certificats non expires ;
- CA trust correctement installee.

## Criteres d'acceptation

L'integration sera consideree correcte lorsque :

- tous les certificats actifs sont inventories ;
- EJBCA peut emettre les certificats necessaires ;
- Oculox peut installer ces certificats sans casser la plateforme ;
- les services critiques fonctionnent apres bascule ;
- les certificats peuvent etre renouveles ;
- les certificats peuvent etre importes depuis une PKI client ;
- un rollback est possible ;
- une VM neuve peut etre installee en suivant la documentation ;
- `./oculox validate pki` passe sans erreur.

## Points de vigilance

- Ne pas supprimer les certificats actuels avant validation complete.
- Ne pas melanger certificats plateforme et certificats extraits du trafic.
- Ne pas desactiver la verification TLS pour contourner un probleme.
- Ne pas imposer uniquement des IP dans les certificats : prevoir DNS et SAN.
- Ne pas faire dependre toute la plateforme d'EJBCA au premier demarrage sans mode de secours documente.
- Ne pas stocker de mots de passe EJBCA ou secrets dans Git.

## Position finale

La cible professionnelle est claire :

```text
EJBCA = autorite de certification
Oculox = consommateur, installateur, validateur et superviseur des certificats
```

Oculox doit donc etre developpe comme une plateforme compatible PKI, pas comme une PKI concurrente.

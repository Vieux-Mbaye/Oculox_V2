# Phases 3 et 4 - Installation EJBCA locale et creation des CA Oculox

> Rapport historique. La migration active et l'enrolement distant ont evolue
> depuis cette etape. Reference actuelle : [installation trois VM](installation_3_vm_et_bundles.md).

## Objectif

Ces phases installent EJBCA sur la meme machine que le Core Oculox, mais dans un compose separe du runtime principal.

Le but est de disposer d'une PKI centrale locale, sans modifier encore les certificats actifs utilises par Oculox.

La regle reste :

```text
EJBCA signe et gere les CA/certificats.
Oculox installe, verifie, renouvelle et supervise les certificats.
```

## Decision d'architecture

EJBCA tourne sur la meme machine que le Core Oculox.

Il n'est pas integre au `docker-compose.yml` principal d'Oculox et il n'est pas demarre par `./oculox start`.

Il est gere par des commandes dediees :

```bash
./oculox pki-ca init
./oculox pki-ca start
./oculox pki-ca status
./oculox pki-ca validate
./oculox pki-ca create-ca-plan
./oculox pki-ca harden
./oculox pki-ca verify-hardening
./oculox pki-ca stop
```

Cette separation est volontaire :

- Oculox peut continuer a demarrer meme si la PKI est arretee ;
- la PKI a son propre cycle de vie ;
- les sauvegardes PKI peuvent etre gerees separement ;
- une erreur EJBCA ne fait pas tomber la supervision ;
- la bascule vers EJBCA sera progressive.

## Exposition reseau

EJBCA est publie uniquement sur localhost par defaut :

```text
127.0.0.1:18080 -> conteneur EJBCA 8080
127.0.0.1:18443 -> conteneur EJBCA 8443
```

Cela signifie qu'EJBCA n'est pas expose directement sur le reseau.

URL locale :

```text
https://127.0.0.1:18443/ejbca/adminweb/
```

Healthcheck :

```text
https://127.0.0.1:18443/ejbca/publicweb/healthcheck/ejbcahealth
```

## Fichiers crees

### `dev/ejbca/compose/docker-compose.ejbca.yml`

Compose dedie EJBCA.

Services :

- `ejbca-db` : base MariaDB persistante ;
- `ejbca` : serveur EJBCA Community.

Volumes Docker :

- `oculox-ejbca-db-data` ;
- `oculox-ejbca-app-data`.

Reseau Docker :

- `oculox-ejbca`.

Limites memoire :

```yaml
ejbca:
  mem_limit: 2g

ejbca-db:
  mem_limit: 1g
```

Ces limites evitent qu'EJBCA consomme toute la RAM du Core.

### `dev/ejbca/config/ejbca.env.example`

Modele d'environnement.

Il contient :

- image EJBCA ;
- image MariaDB ;
- ports locaux ;
- hostname EJBCA ;
- limites RAM ;
- nom de base ;
- utilisateur de base ;
- variables de secrets.

Ce fichier ne contient pas de vrai secret.

### `dev/ejbca/generated/ejbca.env`

Fichier runtime genere par :

```bash
./oculox pki-ca init
```

Il contient les vrais mots de passe generes localement.

Ce fichier est ignore par Git.

### `dev/ejbca/profiles/ca-plan.yml`

Plan cible des CA et profils Oculox dans EJBCA.

Il declare :

- `Oculox Root CA` ;
- `Oculox Web CA` ;
- `Oculox Internal Services CA` ;
- `Oculox OpenSearch CA` ;
- les profils de certificats attendus.

### `dev/scripts/ejbca/manage-ejbca.sh`

Script de gestion EJBCA.

Il implemente :

```bash
init
config
pull
start
stop
restart
status
logs
validate
ca-plan
create-ca-plan
```

### `dev/scripts/ejbca/validate-ca-plan.py`

Validateur du plan CA/profils.

Il compare :

- `dev/ejbca/profiles/ca-plan.yml`
- `dev/ejbca/pki-manifest.yml`

Il verifie que :

- chaque CA a les champs requis ;
- chaque CA intermediaire reference une CA emettrice existante ;
- chaque profil reference une CA existante ;
- chaque profil cible une entree valide du manifeste PKI ;
- les profils obligatoires du manifeste existent dans le plan EJBCA.

## Fichier modifie

### `.gitignore`

Ajouts :

```text
dev/ejbca/generated/
dev/ejbca/data/
dev/ejbca/config/*.env
```

Objectif :

- ne pas versionner les secrets ;
- ne pas versionner les donnees EJBCA ;
- ne pas versionner les fichiers runtime.

### `oculox`

Ajout de la commande :

```bash
./oculox pki-ca <commande>
```

Elle appelle :

```bash
dev/scripts/ejbca/manage-ejbca.sh
```

## Fichiers supprimes

Aucun fichier n'a ete supprime.

## Commandes ajoutees

Initialiser les secrets runtime :

```bash
./oculox pki-ca init
```

Valider la configuration :

```bash
./oculox pki-ca config
```

Demarrer EJBCA :

```bash
./oculox pki-ca start
```

Voir l'etat :

```bash
./oculox pki-ca status
```

Valider EJBCA :

```bash
./oculox pki-ca validate
```

Valider le plan CA :

```bash
./oculox pki-ca ca-plan
```

Creer les CA Oculox dans EJBCA :

```bash
./oculox pki-ca create-ca-plan
```

Durcir l'acces administrateur EJBCA :

```bash
./oculox pki-ca harden
./oculox pki-ca verify-hardening
```

Arreter EJBCA :

```bash
./oculox pki-ca stop
```

## CA creees dans EJBCA

La commande suivante a ete executee :

```bash
./oculox pki-ca create-ca-plan
```

Elle a cree les CA suivantes :

```text
Oculox Root CA
Oculox Web CA
Oculox Internal Services CA
Oculox OpenSearch CA
```

EJBCA avait aussi cree automatiquement :

```text
ManagementCA
```

`ManagementCA` est la CA de bootstrap du conteneur EJBCA. Elle sert au demarrage initial de l'application et ne doit pas devenir la CA de production des services Oculox.

## Comportement idempotent

La commande :

```bash
./oculox pki-ca create-ca-plan
```

peut etre relancee.

Si les CA existent deja, elle affiche :

```text
CA deja presente : Oculox Root CA
CA deja presente : Oculox Web CA
CA deja presente : Oculox Internal Services CA
CA deja presente : Oculox OpenSearch CA
```

Elle ne recree pas les CA existantes.

## Validation effectuee

Commandes executees :

```bash
bash -n dev/scripts/ejbca/manage-ejbca.sh
python3 -m py_compile dev/scripts/ejbca/validate-ca-plan.py
./oculox pki-ca config
./oculox pki-ca start
./oculox pki-ca validate
./oculox pki-ca create-ca-plan
./oculox pki-ca create-ca-plan
```

Resultats :

```text
Plan EJBCA valide: 4 CA, 9 profils
Configuration EJBCA valide.
EJBCA repond en HTTPS dans le conteneur.
```

Etat conteneurs :

```text
oculox-ejbca      healthy
oculox-ejbca-db   healthy
```

Endpoint de sante :

```bash
curl -k https://127.0.0.1:18443/ejbca/publicweb/healthcheck/ejbcahealth
```

retourne HTTP 200.

## Consommation memoire observee

Apres demarrage :

```text
oculox-ejbca      environ 1.05 GiB / limite 2 GiB
oculox-ejbca-db   environ 134 MiB / limite 1 GiB
```

La machine reste autour de 10 GiB de RAM disponible apres demarrage.

## Explication du code pour debutant

### Fonction `compose`

Dans `manage-ejbca.sh`, cette fonction centralise l'appel Docker Compose :

```bash
compose() {
    docker compose \
        --project-directory "$PROJECT_DIR" \
        --env-file "$ENV_FILE" \
        -f "$COMPOSE_FILE" \
        "$@"
}
```

Elle evite de recopier partout :

- le chemin du projet ;
- le fichier d'environnement ;
- le fichier compose EJBCA.

### Fonction `init_env`

Elle cree :

```text
dev/ejbca/generated/ejbca.env
```

Elle genere des secrets avec :

```bash
openssl rand -base64 36
```

Puis elle protege le fichier :

```bash
chmod 0600
```

### Fonction `validate_runtime`

Elle verifie :

1. que l'environnement existe ;
2. que Docker Compose est valide ;
3. que le plan CA est coherent ;
4. que l'endpoint HTTPS EJBCA repond si le conteneur tourne.

### Fonction `create_ca_plan`

Elle cree les CA dans l'ordre :

1. `Oculox Root CA` ;
2. recuperation de l'ID EJBCA de cette Root CA ;
3. `Oculox Web CA`, signee par la Root CA ;
4. `Oculox Internal Services CA`, signee par la Root CA ;
5. `Oculox OpenSearch CA`, signee par la Root CA.

Elle ne touche pas aux certificats actifs d'Oculox.

## Point de securite important

Le conteneur EJBCA Community demarre en mode bootstrap avec un acces public superadmin local. Cet acces ne doit pas rester actif.

Mesures deja appliquees :

- EJBCA est bind uniquement sur `127.0.0.1` ;
- EJBCA n'est pas expose sur le reseau ;
- EJBCA n'est pas dans le compose Oculox principal ;
- les secrets runtime ne sont pas versionnes ;
- un certificat client admin `oculox-superadmin.p12` est genere localement ;
- le certificat admin est mappe au role `Super Administrator Role` ;
- la CA admin est ajoutee dans la truststore TLS EJBCA/WildFly ;
- le membre public bootstrap a ete retire du role `Super Administrator Role` ;
- le role `Public Access Role` a ete supprime.

Commandes de preuve :

```bash
./oculox pki-ca verify-hardening
docker exec oculox-ejbca /opt/keyfactor/bin/ejbca.sh roles listadmins --role 'Super Administrator Role'
curl -ksS https://127.0.0.1:18443/ejbca/adminweb/
```

Resultat attendu :

- `ADMIN CERT ROLE OK` ;
- `PUBLIC SUPERADMIN OK` ;
- `PUBLIC ACCESS ROLE OK` ;
- `ADMIN P12 EXPORT OK` ;
- `WEB WITHOUT CERT OK` ;
- `WEB WITH ADMIN CERT OK` ;
- `roles listadmins` montre `ManagementCA WITH_COMMONNAME "OculoxSuperAdmin"` et le compte CLI local `ejbca`, mais plus `TRANSPORT_CONFIDENTIAL` ;
- l'acces Web sans certificat affiche `Authorization Denied`.
- l'acces Web avec certificat affiche `Welcome OculoxSuperAdmin to EJBCA Administration`.

Mesures restantes avant usage production :

- sauvegarder les volumes EJBCA ;
- tester la restauration ;
- definir la politique de sauvegarde du P12 admin ;
- creer des roles operateurs EJBCA moins privilegies que SuperAdmin ;
- ne jamais exposer EJBCA directement sans filtrage reseau et controle par certificat client.

## Ce qui n'est pas encore fait

Ces phases ne remplacent pas encore les certificats Oculox actifs.

Non encore fait :

- creation automatique des profils EJBCA applicatifs ;
- enrollment des certificats Nginx/Logstash/Filebeat/OpenSearch ;
- renouvellement automatique ;
- revocation ;
- integration CRL/OCSP dans les services Oculox ;
- rollback de certificats emis par EJBCA.

Ces sujets appartiennent aux phases suivantes.

## References officielles

- Image Docker EJBCA Community : `keyfactor/ejbca-ce`
- EJBCA CLI : `/opt/keyfactor/bin/ejbca.sh`
- Commande EJBCA utilisee pour creer les CA : `ejbca.sh ca init`

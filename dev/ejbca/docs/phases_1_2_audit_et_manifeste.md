# Phases 1 et 2 - Audit PKI et manifeste source de verite

> Rapport historique de mise en place. Pour l'installation actuelle, utiliser
> [la procedure trois VM](installation_3_vm_et_bundles.md) et le
> [rapport de livraison](livraison_ejbca_2026-09-30.md).

## Objectif

Ces deux phases preparent l'integration EJBCA sans modifier les certificats actifs de la plateforme.

Le but n'est pas encore de demander des certificats a EJBCA. Le but est de rendre Oculox capable de repondre clairement aux questions suivantes :

- quels certificats existent ;
- quels certificats sont obligatoires ;
- quel service utilise chaque certificat ;
- ou sont les cles privees ;
- quelle CA signe quoi ;
- quand les certificats expirent ;
- quels SAN sont attendus ;
- quel usage est attendu : serveur, client ou CA ;
- est-ce que les chaines de confiance sont valides ;
- est-ce que la cle privee correspond au certificat.

## Fichiers ajoutes

### `dev/ejbca/pki-manifest.yml`

Ce fichier est la source de verite PKI cote Oculox.

Il ne cree pas de certificat et ne remplace pas EJBCA.

Il declare simplement les certificats attendus par la plateforme :

- nom logique du certificat ;
- service consommateur ;
- zone fonctionnelle ;
- profil EJBCA cible ;
- type de certificat ;
- chemin du certificat ;
- chemin de la cle privee ;
- CA attendue ;
- SAN attendus ;
- usage attendu ;
- services a redemarrer lors d'une future rotation.

Exemple :

```yaml
logstash_server:
  service: logstash
  zone: ingestion
  profile: oculox-logstash-server
  type: server
  required: true
  cert: dev/generated/pki/server.crt
  key: dev/generated/pki/server.key
  ca: dev/generated/pki/ca.crt
  expected_usage:
    - serverAuth
  san_required:
    - logstash
    - logstash-2
```

Interpretation :

- `logstash_server` est le nom logique dans Oculox ;
- `service: logstash` indique le service qui utilise ce certificat ;
- `profile: oculox-logstash-server` indique le profil qui devra exister dans EJBCA ;
- `type: server` indique un certificat serveur TLS ;
- `required: true` rend ce certificat obligatoire dans l'audit ;
- `cert`, `key`, `ca` donnent les chemins a verifier ;
- `expected_usage` impose l'usage TLS attendu ;
- `san_required` impose les noms qui doivent etre presents dans le certificat.

### `dev/scripts/pki-audit.py`

Ce script implemente l'audit PKI en lecture seule.

Il ne fait jamais :

- de generation de certificat ;
- de suppression de certificat ;
- de remplacement de certificat ;
- de redemarrage de service ;
- de modification de configuration.

Il lit le manifeste, puis utilise `openssl` pour verifier les certificats.

Commandes supportees :

```bash
./dev/scripts/pki-audit.py audit
./dev/scripts/pki-audit.py status
./dev/scripts/pki-audit.py expiry
./dev/scripts/pki-audit.py audit --json
```

### `./oculox`

Le script principal expose maintenant les commandes PKI :

```bash
./oculox pki audit
./oculox pki status
./oculox pki expiry
./oculox validate pki
```

`./oculox validate pki` est volontairement limite a la verification PKI. Il ne remplace pas encore la validation complete de la plateforme.

## Fonctionnement du script d'audit

### Chargement du manifeste

Le script lit par defaut :

```text
dev/ejbca/pki-manifest.yml
```

Il verifie que le fichier contient bien une section :

```yaml
certificates:
```

Si le manifeste est absent ou invalide, le script s'arrete.

### Resolution des chemins

Tous les chemins relatifs sont interpretes depuis la racine du depot Oculox.

Exemple :

```yaml
cert: nginx/certs/cert.pem
```

devient :

```text
/home/kakashi_/ICSHUB/Oculox/nginx/certs/cert.pem
```

### Verification de presence

Pour chaque entree, le script verifie :

- presence du certificat ;
- presence de la cle si declaree ;
- presence de la CA si declaree.

Si un certificat obligatoire manque, le statut devient `FAIL`.

Si un certificat optionnel manque, le statut devient `SKIP`.

### Lecture OpenSSL

Le script execute :

```bash
openssl x509 -in <certificat> -noout -subject -issuer -serial -dates
```

Il extrait :

- subject ;
- issuer ;
- serial ;
- date de debut ;
- date de fin.

### Verification expiration

Les seuils viennent du manifeste :

```yaml
defaults:
  warning_days: 60
  critical_days: 30
```

Regles :

- plus de 60 jours : `OK` ;
- moins de 60 jours : `WARN` ;
- moins de 30 jours : `FAIL` ;
- expire : `FAIL`.

### Verification SAN

Le script lit l'extension :

```bash
openssl x509 -in <certificat> -noout -ext subjectAltName
```

Puis il compare avec :

```yaml
san_required:
```

ou avec :

```yaml
san_required_from:
```

Exemple :

```yaml
san_required_from:
  - dev/generated/public-endpoint.env:OCULOX_PUBLIC_HOST
```

Cela signifie :

1. lire le fichier `dev/generated/public-endpoint.env` ;
2. extraire la variable `OCULOX_PUBLIC_HOST` ;
3. verifier que cette valeur est presente dans le SAN du certificat.

### Verification Extended Key Usage

Le script lit :

```bash
openssl x509 -in <certificat> -noout -ext extendedKeyUsage
```

Puis il verifie les usages declares :

```yaml
expected_usage:
  - serverAuth
  - clientAuth
```

### Verification cle privee / certificat

Le script extrait la cle publique du certificat et la cle publique derivee de la cle privee.

Si les deux empreintes sont identiques, alors la cle privee correspond au certificat.

### Verification chaine CA

Si une CA est declaree, le script lance :

```bash
openssl verify -CAfile <ca> <certificat>
```

Si OpenSSL valide la chaine, le controle est `OK`.

### Verification CA

Pour les entrees declarees comme CA :

```yaml
expected_ca: true
```

Le script verifie que le certificat contient :

```text
Basic Constraints: CA:TRUE
```

## Statuts utilises

| Statut | Signification |
| --- | --- |
| `OK` | Tous les controles obligatoires passent |
| `WARN` | Fonctionnel mais attention necessaire |
| `FAIL` | Erreur bloquante pour une entree obligatoire |
| `SKIP` | Entree optionnelle absente |
| `INFO` | Information non bloquante |

## Commandes a utiliser

Audit detaille :

```bash
./oculox pki audit
```

Statut synthetique :

```bash
./oculox pki status
```

Expiration :

```bash
./oculox pki expiry
```

Validation PKI :

```bash
./oculox validate pki
```

Rapport JSON exploitable par CI ou par un futur tableau de bord :

```bash
./oculox pki audit --json
```

## Comportement attendu

Sur une installation Oculox preparee, les certificats obligatoires doivent etre en `OK`.

Les certificats du cluster OpenSearch dedie peuvent etre en `SKIP` si le cluster dedie n'a pas encore ete installe. Ils sont declares comme optionnels car cette partie depend du mode de deploiement.

## Ce qui n'a pas ete fait dans ces phases

Ces phases ne font pas encore :

- installation EJBCA ;
- creation des CA dans EJBCA ;
- creation des profils dans EJBCA ;
- enrollment automatique ;
- renouvellement ;
- rotation ;
- revocation ;
- rollback.

Ces fonctions appartiennent aux phases suivantes.

## Fichiers modifies

### `oculox`

Ajouts :

```bash
./oculox pki audit
./oculox pki status
./oculox pki expiry
./oculox validate pki
```

Ces commandes appellent :

```bash
./dev/scripts/pki-audit.py
```

### `dev/ejbca/pki-manifest.yml`

Nouveau manifeste PKI source de verite.

### `dev/scripts/pki-audit.py`

Nouveau moteur d'audit PKI.

### `dev/ejbca/docs/phases_1_2_audit_et_manifeste.md`

Documentation de ces deux phases.

## Fichiers supprimes

Aucun fichier n'a ete supprime pour ces phases.

## Regle de securite

Le script d'audit ne doit jamais afficher le contenu des cles privees.

Il verifie seulement :

- leur existence ;
- leur lisibilite par OpenSSL ;
- leur correspondance avec le certificat.

Il ne doit pas copier, publier ou journaliser la cle privee.

## Suite logique

Une fois ces deux phases validees, la phase suivante consiste a installer EJBCA dans `dev/ejbca/`, puis a creer les CA et les profils correspondant au manifeste.

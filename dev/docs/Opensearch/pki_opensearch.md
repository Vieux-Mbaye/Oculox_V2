# Étape PKI - PKI OpenSearch

## 1. Objet

Cette étape cree les identites cryptographiques requises avant le premier
demarrage du cluster et remplace le contrat de certificats mono-noeud embarque
dans l'image Malcolm.

Le cluster n'a pas ete demarre pendant cette étape. La VM reste sans conteneur
et sans volume OpenSearch.

## 2. Architecture de confiance

La PKI obtenue contient :

| Identite | Usage | SAN | Garde de la cle |
|---|---|---|---|
| Oculox OpenSearch Root CA | Signature de la PKI OpenSearch | sans objet | poste d'administration uniquement |
| `opensearch-1` | TLS transport et HTTPS interne | `DNS:opensearch-1`, `IP:172.31.241.2` | noeud 1 |
| `opensearch-2` | TLS transport et HTTPS interne | `DNS:opensearch-2`, `IP:172.31.241.3` | noeud 2 |
| `opensearch-3` | TLS transport et HTTPS interne | `DNS:opensearch-3`, `IP:172.31.241.4` | noeud 3 |
| endpoint | HTTPS du proxy stable | `IP:192.168.1.241` | proxy, a partir de la étape endpoint |
| administrateur | `securityadmin.sh` et administration Security | identite cliente | poste d'administration uniquement |

Les cinq certificats feuilles possedent cinq cles privees differentes. Les
trois noeuds ne partagent donc aucune cle privee. Le certificat endpoint n'est
pas monte dans les noeuds : il sera utilise par le proxy qui portera l'adresse
stable pendant la étape endpoint.

La PKI OpenSearch est independante de la PKI Beats. Elle ne remplace pas les
certificats mTLS Filebeat/Logstash et n'est pas geree par Keycloak.

## 3. Generation

Le generateur versionne est :

```text
dev/scripts/opensearch-cluster/generate-pki.sh
```

Commande executee :

```bash
./dev/scripts/opensearch-cluster/generate-pki.sh \
  --endpoint-ip 192.168.1.241
```

Le script :

- exige explicitement l'IP de deploiement ;
- cree une CA RSA 4096 bits et des cles feuilles RSA 3072 bits ;
- produit des cles PEM PKCS#8 non chiffrees, lisibles uniquement par leur
  proprietaire ;
- cree les SAN et Extended Key Usage adaptes a chaque identite ;
- refuse d'ecraser une PKI existante sans `--force` ;
- n'affiche aucune cle privee ;
- produit un manifeste sans contenu secret.

Les artefacts sont crees dans :

```text
dev/generated/opensearch-cluster/pki/
|-- ca/
|-- nodes/
|   |-- opensearch-1/
|   |-- opensearch-2/
|   `-- opensearch-3/
|-- endpoint/
|-- admin/
`-- client-trust/
```

Ce repertoire est ignore par Git. La copie cliente de la CA se trouve dans :

```text
client-trust/oculox-opensearch-ca.crt
```

Elle sera installee dans Core et Hedgehog pendant leur bascule vers le nouvel
endpoint, conformement a la étape d'inventaire1. La distribuer maintenant ne rendrait pas
leurs clients actuels plus surs, car ils ne ciblent pas encore ce cluster.

## 4. Configuration OpenSearch

Le fichier suivant remplace `opensearch.yml` dans chaque conteneur :

```text
dev/config/opensearch-cluster/opensearch.yml
```

Il configure separement :

```text
TLS HTTP      : certs/node.crt, certs/node.key, certs/ca.crt
TLS transport : certs/node.crt, certs/node.key, certs/ca.crt
```

Les chemins sont relatifs au repertoire de configuration OpenSearch. La
verification des noms est activee sur le transport Docker. Les IP privees sont
fixees dans le sous-reseau `172.31.241.0/28`, car OpenSearch annonce son IP de
transport aux autres noeuds. Les trois DN de
noeud sont listes explicitement dans `plugins.security.nodes_dn` et le DN
administrateur est declare dans `plugins.security.authcz.admin_dn`.

Le mode HTTP `clientauth_mode: OPTIONAL` permet au certificat administrateur
d'etre presente pendant la étape Security sans imposer un certificat client a tous les
clients applicatifs. Ces derniers utiliseront des comptes de service limites,
avec verification obligatoire de la CA cote client.

La variable suivante reste imposee aux trois services :

```text
OPENSEARCH_SKIP_SELF_SIGNED_KEY_GEN=true
```

L'image Malcolm execute normalement `setup-post-start.sh` sur chaque noeud et
tenterait d'initialiser le Security index trois fois. Le garde-fou versionne
`setup-post-start.sh` neutralise cette action. La étape Security executera
l'initialisation une seule fois, avec le certificat administrateur conserve
hors des conteneurs.

## 5. Montage Compose

Chaque service monte en lecture seule :

- le fichier commun `opensearch.yml` ;
- le garde-fou de post-demarrage ;
- son propre repertoire `nodes/opensearch-N` vers
  `/usr/share/opensearch/config/certs`.

La cle de CA, la cle administrateur et la cle endpoint ne sont pas montees dans
les noeuds OpenSearch.

## 6. Preuves cryptographiques

Test execute :

```bash
./dev/tests/opensearch-cluster/test_pki.py
```

Resultat :

```text
ca_chain=PASS
node_certificates=3/3 PASS
endpoint_san=IP:192.168.1.241 PASS
admin_certificate=PASS
unique_leaf_private_keys=5/5 PASS
compose_read_only_mounts=3/3 PASS
healthcheck_tls_verification=PASS
generated_pki_git_tracking=NONE PASS
client_trust_bundle=PASS
PKI_TEST_RESULT=PASS
```

Les tests des phases 4 et 5 restent egalement `PASS` apres les modifications.

## 7. Validation sur la VM

Les fichiers non sensibles et les trois paquets de noeud ont ete copies dans
un repertoire temporaire de `192.168.1.241`. Docker Compose 5.4.0 a valide le
Compose complet avec le fichier d'amorcage et OpenSSL a valide les trois SAN
DNS et IP contre la CA.

```text
opensearch-1/node.crt: OK
opensearch-2/node.crt: OK
opensearch-3/node.crt: OK
VM_PKI_CONFIG=PASS
containers=0
volumes=0
```

Le repertoire temporaire a ensuite ete supprime. Aucune cle de CA ni cle
administrateur n'a ete transferee a la VM.

## 8. Sources officielles

- Configuration TLS OpenSearch :
  https://docs.opensearch.org/latest/security/configuration/tls/
- Parametres du plugin Security :
  https://docs.opensearch.org/latest/install-and-configure/configuring-opensearch/security-settings/
- Generation de certificats :
  https://docs.opensearch.org/latest/security/configuration/generate-certificates/
- Utilisation de `securityadmin.sh` :
  https://docs.opensearch.org/latest/security/configuration/security-admin/

## 9. Decision de sortie

La étape PKI est validee. La configuration et les certificats sont prets pour le
premier demarrage controle avec `compose.bootstrap.yml`. Les preuves runtime de
formation du cluster et l'initialisation unique du Security index restent les
travaux suivants ; aucun contournement TLS ne sera utilise.

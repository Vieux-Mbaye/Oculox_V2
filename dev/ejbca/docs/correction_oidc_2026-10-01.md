# Correction OIDC apres migration EJBCA

Date : 1 octobre 2026. Core `192.168.1.174`, Cluster `192.168.1.200`.
Ces IP sont celles de la recette, pas des valeurs codees dans les installateurs.

## Cause Et Correction Active

OpenSearch utilisait encore `Oculox Development Web CA` dans son fichier
`idp-trust/keycloak-ca.crt`, alors que Keycloak public, via Nginx, presentait
un certificat signe par `Oculox Web CA` EJBCA. Les journaux correspondaient
aux echecs Dashboards : `SSLHandshakeException`, `PKIX path building failed`
pendant la lecture du document discovery Keycloak. La CA OpenSearch vers Core
etait deja migree; c'est la confiance inverse Cluster vers Keycloak qui manquait.

La commande `oidc-trust` a remplace uniquement la confiance IdP avec la chaine
Web du bundle d'agent epingle. Les trois noeuds ont ete redemarres un par un,
en attendant trois noeuds verts a chaque fois. Aucune reemission ni nouvelle
migration des certificats OpenSearch actifs n'a ete faite. Aucun changement
des utilisateurs, roles, mappings ou parametres Security actifs n'a ete fait;
les documents Security et rolesmapping avant/apres sont strictement identiques.
La sauvegarde distante de confiance et de ces documents est :

```text
dev/generated/opensearch-cluster/oidc-backups/20261001T090327872853Z-trust/
```

L'ancien gestionnaire distant a ete sauvegarde dans
`dev/generated/opensearch-cluster/oidc-source-backups/20261001/` avant mise a
jour; ses ajustements de stockage existants ont ete conserves. Les scripts
distants non suivis par Git n'ont pas ete supprimes.

## Preuves Obtenues

- Cluster : phase EJBCA toujours `retire`, trois noeuds verts.
- Les trois noeuds valident HTTPS, issuer discovery et JWKS avec leur CA montee.
- Jetons signes par le vrai Keycloak : `read_access` traduit en
  `dashboards_read_access`, sans `all_access`, sur chacun des trois noeuds.
- Jetons `admin` traduits en `all_access` sur chacun des trois noeuds.
- Un jeton signe avec une audience incorrecte est refuse avec HTTP 401.
- Le client Keycloak temporaire de recette a ete supprime en fin de test.
  Aucun utilisateur humain, MFA ni client applicatif existant n'a ete modifie.
- `./oculox validate all`, `./oculox pki status`, `./oculox verify clients` : PASS.
- Tests sources EJBCA : 20 tests PKI, six scenarios de configuration Cluster,
  trois tests rendu OIDC, huit tests confiance OIDC et contrat VM neuf : PASS.
- Suite Keycloak existante : 42 tests PASS. Ses tests de PKI de developpement
  activent explicitement cette exception uniquement dans leurs repertoires
  temporaires; tous leurs fichiers de configuration sont aussi isoles, y
  compris celui du helper Dashboards. L'installation normale ne recree pas
  de CA locale. La suite est integree au controle de livraison des sources.

La recette JWT/RBAC valide le plugin Security reel, pas une simple redirection
HTTP. Elle ne remplace pas une connexion humaine dans le navigateur avec MFA.
L'ancienne URL de callback capturee ne doit pas etre rechargee : son code OIDC
est a usage unique. Repartir du lien Dashboards du portail pour un nouveau flux.

## Protection Des Installations Neuves

Suivre [la procedure trois VM](installation_3_vm_et_bundles.md), mise a jour.

1. Le bundle public de l'agent Cluster fournit la chaine Web EJBCA et la racine
   epinglee; aucune cle privee n'est transferee.
2. L'installation Cluster installe la confiance IdP sans supposer que Keycloak
   soit deja disponible. Une confiance existante divergente n'est pas ecrasee
   silencieusement : une rotation explicite est exigee.
3. Apres finalisation du Core, provisionner Keycloak et activer portail et
   Dashboards, puis configurer OIDC sur Cluster avec l'URL IP/DNS du site.
4. `configure-oidc` part des documents Security actifs, sauvegarde, conserve
   les mappings propres au client et Basic technique. Il ne regenere pas les
   roles ou les mots de passe. En cas d'echec d'application, il restaure les
   documents sauvegardes via securityadmin.
5. `cluster validate` controle discovery/JWKS si OIDC est actif. Pour la
   qualification finale, `cluster verify-oidc` est obligatoire et refuse un
   cluster Basic seul, une CA obsolete ou une verification TLS desactivee.
6. Une rotation Web ulterieure passe par le renouvellement du bundle public
   d'agent, `cluster oidc-trust`, `cluster verify-oidc`, puis la recette JWT.

Commandes de recette sur Core et Cluster :

```bash
# Cluster
./oculox cluster verify-oidc
./oculox cluster validate
# Core : cree puis supprime un client de test
python3 dev/tests/keycloak/test_live_opensearch_oidc.py --run-live
# Option : avec cle SSH operateur, controles directs sur les trois noeuds
python3 dev/tests/keycloak/test_live_opensearch_oidc.py --run-live --cluster-ssh <USER>@<CLUSTER>
./oculox validate all
./oculox verify clients
```

Le test accepte aussi `--sshpass-env` si `SSHPASS` est fourni hors du depot.
Il exige la cle d'hote SSH deja approuvee. Les jetons transitent dans stdin,
pas dans les arguments SSH, et ne sont ni sauvegardes ni affiches.

## Limites De Qualification

Le defaut de confiance observe est corrige et teste sur le cluster actif.
L'installation complete depuis trois VM vierges, le parcours humain MFA et
l'endurance du site restent a exercer. Ne pas annoncer une garantie absolue
ni une qualification production a partir des seuls tests ci-dessus.
Pour la recette VM neuve, utiliser la revision publiee sur GitHub, branche
`main`, et verifier son identifiant avec celui du compte rendu de publication :

```bash
git clone --branch main https://github.com/Vieux-Mbaye/Oculox_V2.git
cd Oculox_V2
git rev-parse HEAD
python3 dev/tests/test_ejbca_delivery.py
```

Les mentions de changements uniquement locaux dans le rapport du 30 septembre
decrivent l'etat historique avant cette publication. Aucun certificat prive,
bundle secret ni donnees d'exploitation ne doit etre present dans le clone.

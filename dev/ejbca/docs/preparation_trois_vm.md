# Preparation trois VM : corrections et preuves

> Archive de l'etat intermediaire avant l'enrolement distant. Les tableaux
> ci-dessous ne decrivent plus le code actuel. Pour installer, utiliser
> [la procedure trois VM a jour](installation_3_vm_et_bundles.md).

Date : 30 septembre 2026. Statut : en cours, non livrable comme installation
automatisee de bout en bout. Aucune VM vierge n'a encore ete testee.

## Corrections implementees

### Generation locale des cles

`dev/scripts/ejbca/pki-lifecycle.py`, fonction `enroll_one` :

1. Cree un repertoire de staging prive (0700).
2. Cree exclusivement `key.key` (0600) : une cle existante n'est pas ecrasee.
3. OpenSSL genere une cle RSA 3072 puis une demande PKCS#10 `request.csr`.
4. EJBCA recoit une entite `USERGENERATED` et un mot de passe d'enrolement.
5. Seule la CSR publique est copiee dans le conteneur EJBCA.
6. `createcert` signe la demande ; le certificat est rapatrie, pas la cle.
7. Les fichiers publics temporaires du conteneur sont retires meme si
   l'emission echoue. Le staging local reste disponible pour diagnostic.
8. Les metadonnees enregistrent `key_origin: local` et
   `issuance_transport: local-docker-cli`, sans mot de passe.

EJBCA applique le Subject DN et les SAN de son entite finale. La CSR utilise un
CN technique ; elle ne constitue pas une autorisation de choisir librement des
identites. La restriction effective des profils et roles reste a developper.
Cette implementation ne constitue pas encore un client distant EJBCA.

`validate_material` verifie les SAN comme valeurs DNS/IP completes, et non
comme sous-chaines du texte du certificat. Les usages inconnus sont refuses.

### Conservation des certificats externes

`dev/scripts/generate-web-pki.sh` refuse de remplacer un certificat actif par
une CA de developpement s'il n'est pas verifiable avec cette ancienne CA,
meme quand une ancienne cle CA existe encore. Il valide le certificat externe
avec son veritable bundle et conserve ce materiel. `--force` ne contourne pas
cette protection. Le mode explicite `provided` permet un import controle.

`dev/scripts/generate-beats-pki.sh` refuse de recreer une CA lorsqu'un bundle
CA existe sans sa cle privee. Une identite manquante/incompatible exige alors
un reenrolement. Le controle de hostname/IP ne repose plus sur une recherche
de sous-chaine du SAN.

Pendant le test web, une ancienne cle CA residuelle a revele un retour possible
au certificat de developpement. Les fichiers EJBCA ont ete restaures depuis le
staging correspondant au certificat effectivement servi par Nginx, puis le
generateur corrige a ete relance avec succes. Nginx n'a pas ete redemarre : son
certificat en memoire est reste celui d'EJBCA.

## Tests executes

```bash
python3 -m unittest discover -s dev/tests -p 'test_pki_*.py' -v
./oculox pki enroll --provider ejbca --service filebeat_client
./oculox pki enroll --provider ejbca --service logstash_server
./oculox validate all
./oculox verify clients
bash -n dev/scripts/generate-web-pki.sh dev/scripts/generate-beats-pki.sh oculox
```

Resultats : sept tests automatises reussis ; emissions reelles Filebeat et
Logstash en staging avec chaine/cle/EKU/SAN valides ; validation des endpoints
HTTPS et OpenSearch reussie ; comptes techniques et sept pipelines par
Logstash verifies. Ces controles ne simulent pas une connexion humaine SSO
complete ni l'installation sur VM neuve.

Le nouveau `dev/tests/test_pki_local_csr.py` controle la signature de la CSR,
les permissions, le transfert exclusif de la CSR, l'absence de P12 service,
la non-destruction d'une cle existante et le refus du retour a une CA locale,
y compris lorsqu'une ancienne cle CA traine encore sur disque.

Aucun ancien certificat, sauvegarde ou donnee metier n'a ete supprime.
Les certificats emis pour les tests ne sont pas installes dans les services.
Les comptes de test EJBCA et leurs certificats restent dans l'audit d'emission.

## Conditions restantes avant livraison

| Exigence | Situation actuelle |
| --- | --- |
| Cles/CSR locales | Emission locale testee pour Filebeat et Logstash |
| Transport distant mTLS | Non implemente/valide |
| Profils EJBCA limites par role et identite | Profils generiques encore utilises |
| Installation des trois roles avec `--pki-config` | Non implementee |
| Collecteur sans cle CA locale | Generateur historique encore a remplacer |
| Rotation coordonnee de confiance | Non validee entre VM |
| Renouvellement automatique et revocation effective | Non valides de bout en bout |
| Restauration de sauvegarde EJBCA | Test isole encore necessaire |
| Bascule du cluster distant vers EJBCA | Non effectuee : cluster toujours sur son ancienne CA |
| Trois VM vierges | En attente des VM et des tests reels |

Ne pas supprimer les anciennes sauvegardes ni annoncer une PKI entierement
centralisee sur la base des seuls tests de staging.

## IP maintenant, DNS chez un client

Une IP utilisee comme endpoint doit figurer comme SAN de type IP, pas DNS.
Lorsqu'elle change, il faut reenroler le certificat et actualiser les endpoints.
Un nom DNS client doit figurer comme SAN DNS ; ses changements d'adresse ne
necessitent pas un nouveau certificat tant que le nom reste identique.
Les adresses de test actuelles sont de la configuration runtime, pas des valeurs
a reproduire dans une installation neuve. Aucun domaine public n'est obligatoire.

## EJBCA Community

La documentation officielle distingue les API d'enrolement disponibles en
Community des API completes de gestion disponibles en Enterprise. Le parcours
ne doit donc pas presupposer l'API Enterprise pour provisionner les profils.
L'activation REST, la confiance TLS et les roles mTLS doivent etre testes avant
exposition distante. Source :
[interface REST EJBCA](https://docs.keyfactor.com/ejbca/latest/ejbca-rest-interface).

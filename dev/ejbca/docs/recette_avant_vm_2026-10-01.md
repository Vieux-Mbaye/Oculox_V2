# Recette EJBCA avant les VM neuves

Verifications completees le 2 octobre 2026.

Cette note complete la [procedure trois VM](installation_3_vm_et_bundles.md).
Elle decrit les preuves obtenues sur le Core et le Cluster existants, sans
pretendre qu'une installation depuis trois VM vierges a deja reussi.

## Corrections de cette recette

- `./oculox validate all` controle maintenant la disponibilite EJBCA si la
  PKI centrale est configuree. Une panne EJBCA ne peut plus passer inapercue
  derriere des certificats de service encore valides.
- Un agent Collecteur recoit un profil d'entite EJBCA propre a son identite.
  Les SAN `filebeat` et le nom du Collecteur sont fixes et non modifiables.
  Son role refuse le profil Filebeat partage. Un appel REST direct ne peut donc
  pas demander le SAN d'un autre Collecteur avec cette identite d'agent.
- Le Cluster recoit cinq profils d'entite propres a son identite. Le Core
  approuve explicitement l'IP et le DNS eventuel de l'endpoint ; les SAN
  correspondants sont fixes dans EJBCA, comme les noms des trois noeuds.
- Les profils limites `enroll-v2` fixent aussi CN, OU, O et C, obligatoires
  et non modifiables. Le certificat administrateur OpenSearch conserve son DN
  exact. Les anciens profils limites v1 sont refuses au renouvellement des
  agents ; les certificats actifs de service ne sont pas remplaces.
- La comparaison du profil exporte ignore les espaces de presentation XML
  et l'extension du tableau de champs par des zeros de fin (champs absents).
  Le renouvellement reste repetable ; tout champ active ou regle modifiee
  continue a provoquer un refus de derive.
- Le controle OIDC du Cluster compare les certificats de la chaine Web CA,
  pas le texte PEM. Le renouvellement de l'agent avec la meme CA ne redemarre
  plus inutilement les trois noeuds ; une vraie rotation de CA garde la
  procedure de sauvegarde et de rechargement progressif.
- La procedure d'installation indique le clonage de `main`, l'ordre des CA
  avant les certificats et le diagnostic d'un reseau EJBCA indisponible.
- Les trois installateurs activent le timer systemd quotidien d'expiration
  apres le demarrage valide. Une erreur d'installation du timer bloque la
  procedure au lieu de laisser la surveillance inactive.
- Le renouvellement REST cree une nouvelle entite et une nouvelle cle privee
  sur la VM. Les CA Services et OpenSearch acceptent les DN renouveles, mais
  ceux-ci restent imposes par les profils v2. L'agent ne recoit aucun droit de
  modification d'entite et ne peut pas reprendre celle d'un autre agent.

## Preuves executees

| Controle | Resultat |
|---|---|
| `python3 dev/tests/test_ejbca_delivery.py` | PASS, tests de sources et contrats d'installation |
| `python3 dev/tests/test_ejbca_live.py --run` | PASS, agents temporaires Cluster/Collecteur, renouvellement et revocation |
| REST EJBCA, profil Web demande par agent Collecteur | Refuse |
| REST EJBCA, profil Filebeat partage demande par agent Collecteur | Refuse |
| REST EJBCA, SAN d'un autre Collecteur avec profil propre | Refuse |
| REST EJBCA, profil Cluster partage ou IP d'endpoint non approuvee | Refuse |
| REST EJBCA, CN/OU/O/C et DNS d'endpoint non approuves | Refuse avec les profils v2 |
| REST EJBCA, modification d'une entite appartenant a un autre agent | Refuse pour Cluster et Collecteur |
| Ancien certificat d'agent revoque, demande valide sous profil autorise | Refuse ; nouvelle cle toujours utilisable |
| Endpoint de test emis pour l'IP approuvee | PASS, puis certificat de test revoque |
| `./oculox pki-ca validate` et `verify-hardening` | PASS |
| Rendu du timer d'expiration et `systemd-analyze verify` | PASS ; activation automatique ajoutee aux trois installateurs |
| CA arretee : `validate all` en echec, clients techniques toujours fonctionnels | PASS, erreur EJBCA detectee et lecture/ecriture Arkime maintenue |
| Reprise puis recreation EJBCA/MariaDB avec volumes conserves | PASS, sante, durcissement et validation globale retrouves |
| `./oculox validate all` et `./oculox verify clients` | PASS sur Core actif |
| `./oculox cluster validate` sur la VM Cluster existante | PASS, trois noeuds, TLS et OIDC |
| Sauvegarde chiffree finale puis `pki-ca restore-test` | PASS, base isolee, quatre CA, HTTPS et signature CRL |

Les tests REST creent puis revoquent des identites jetables ; ils ne
remplacent aucun certificat actif. Les profils d'entite de ces tests restent
dans la base EJBCA pour la tracabilite et ne donnent aucun droit sans role
d'agent actif.

L'agent `cluster-01` de la VM existante a aussi ete renouvele avec les profils
limites et son IP `192.168.1.200`. Sa cle privee a ete regeneree sur cette VM.
Les certificats actifs des trois noeuds n'ont pas ete remplaces. Un certificat
endpoint emis uniquement pour verifier l'enrolement a ete revoque et son
staging deplace hors du repertoire de rotation.
Le certificat public de l'ancien agent a ete revoque par son numero de serie.
`cluster validate` et les trois controles discovery/JWKS sont repasses apres
le renouvellement de cet agent.

## Incident et continuite

Pendant l'audit, EJBCA renvoyait HTTP 500 : sa base repondait localement,
mais le trafic entre les conteneurs EJBCA et MariaDB expirait. Une sauvegarde
chiffree et son controle ont precede un arret/demarrage du seul Compose
EJBCA, sans suppression de volumes. La pile est revenue saine et le Core ainsi
que le Cluster ont continue a utiliser leurs certificats actifs. La cause
precise de la panne du pont Docker precedent n'est pas demontree ; surveiller
la disponibilite EJBCA et garder une sauvegarde hors machine.

## Cycle de vie

| Operation | Mode actuel |
|---|---|
| Surveillance d'expiration | Automatique chaque jour apres installation du timer ; alerte journal a 60 jours |
| Renouvellement Core et Collecteur | Commande explicite, nouvelle cle locale, validation et sauvegarde |
| Renouvellement Cluster | Semi-automatique : commandes d'emission puis rotation coordonnee et retour au vert |
| Renouvellement d'agent | CSR locale, autorisation Core, installation du bundle public puis revocation de l'ancien certificat |
| Revocation de service et rechargement CRL | Action operateur ; le controle de revocation de chaque consommateur reste a qualifier |
| Sauvegarde et restauration | Commandes explicites ; planifier la sauvegarde hors VM en exploitation |

Ce deploiement n'est pas une PKI hautement disponible : pendant un arret
EJBCA, les services avec certificats valides continuent, mais l'emission et
le renouvellement sont interrompus. Le redemarrage complet des VM et la
reprise apres panne de l'hote restent a tester lors de la recette.

## Limite du GO

GO pour **la recette sur trois VM neuves**, avec arret a chaque controle en
echec. Ce n'est pas une qualification de production ni une garantie de
"100 %" avant la recette reelle. Restent a prouver sur les VM : installation
depuis le clone, navigateur et MFA humains, capture Collecteur de bout en
bout, rotation/retour arriere sous charge, restauration sur Core de secours,
et verification effective de la revocation par chaque consommateur TLS.

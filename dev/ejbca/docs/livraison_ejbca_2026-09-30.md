# Livraison EJBCA : etat et recette

> Complement du 1 octobre : le controle des clients techniques ci-dessous ne
> couvrait pas l'OIDC humain. Une confiance Web obsolete sur le cluster a ete
> identifiee et corrigee. Lire [la recette corrective OIDC](correction_oidc_2026-10-01.md)
> pour les preuves ajoutees et les commandes VM neuves.

Date : 30 septembre 2026. Procedure de reference :
[Installation trois VM](installation_3_vm_et_bundles.md).

## Ce qui est livre

- Bootstrap Core separe de sa finalisation : PKI, Cluster, puis Core et Collecteur.
- EJBCA 9.6.3 CE fige par digest; quatre CA et huit couples de profils verifies
  contre les exports de l'instance reelle. Un profil divergent est refuse,
  pas remplace silencieusement.
- Enrolement REST mTLS avec roles Cluster/Collecteur limites. Les cles de
  service et d'agent sont generees sur leur VM. Le transfert initial concerne
  seulement une CSR, puis des certificats publics et une configuration.
- Verification de chaque chaine publique contre l'empreinte Root CA epinglee.
  Un bundle avec une autre racine, meme ajoutee a la chaine legitime, est refuse.
- Installateurs sans creation normale de CA locale. Les anciens generateurs
  restent disponibles uniquement avec une option explicite de developpement.
  Chaque installation PKI valide ses propres fichiers; la validation globale
  intervient apres installation des identites requises.
- IP de publication et DNS client distincts; SAN IP/DNS verifies. Nginx sert
  la chaine intermediaire complete. Keycloak public utilise ce HTTPS Nginx.
- Renouvellement des services, des agents et du Collecteur; rotation repetable
  du Cluster avec la meme CA, precontrole, verrou, sauvegarde et retour arriere.
- Revocation exacte par serie avec export CRL; retrait des droits d'un agent
  avant revocation pour bloquer immediatement ses nouvelles demandes.
- Sauvegarde chiffree, verification d'archive, restauration isolee sans ports,
  restauration explicite sur place et parcours de secours sur Core neuf.
- Surveillance quotidienne de l'expiration par timer systemd, sans rotation
  automatique des noeuds a l'aveugle.
- Sources livrables sans certificats prives ni donnees d'exploitation. Les
  anciens rapports sont identifies comme historiques; aucune donnee utile
  ni modification preexistante n'a ete effacee pour nettoyer l'arbre.

## Tests effectues ici

| Controle | Resultat et portee |
|---|---|
| Tests unitaires PKI | 20 tests : confiance epinglee, politiques, SAN DNS, profils divergents, audits par role, bootstrap partiel, permissions et retour arriere |
| Configuration Cluster | Six scenarios de configuration et contrat statique Core/Cluster/Collecteur valides |
| Agents reels Cluster et Collecteur | Emission autorisee, profil Web interdit, renouvellement avec nouvelle cle locale, revocation du service avec CRL signee, puis refus d'emission apres retrait de l'agent : PASS |
| Profils EJBCA reels | Huit couples certificat/entite exportes et verifies : PASS |
| Restauration isolee | Base restauree, quatre CA retrouvees, HTTPS effectivement servi verifie avec Root CA, nouvelle CRL signee : PASS |
| PKI Core active | Nginx, Logstash, Filebeat, confiance OpenSearch et HTTPS API EJBCA controles |
| Clients Core actifs | Logstash x2, Arkime x2, Dashboards, helper, PCAP monitor et API : TLS/authentification valides; ecriture/lecture/suppression de test Arkime valide |
| Cluster distant actif | Etat `retire`, trois noeuds verts, chaine EJBCA active. La migration de CA existante n'a pas ete refaite |
| Rotation normale sur Cluster | `rotate --check` passe sur la VM distante, sans remplacement actif. La rotation complete repetable reste a exercer en recette |
| Surveillance | Controle local et syntaxe des unites systemd valides; timer non installe sur les machines actives |

Commandes de verification reproductibles :

```bash
python3 dev/tests/test_ejbca_delivery.py
python3 dev/tests/test_ejbca_live.py --run
./oculox pki-ca provision-profiles --verify-only
./oculox pki-ca verify-hardening
./oculox pki status
./oculox pki monitor check
./oculox validate
./oculox validate all
./oculox verify clients
```

Le test `--run` cree des identites temporaires dans EJBCA reel, puis retire leurs
roles et les revoque. Il ne remplace aucun certificat de service actif.
`test_ejbca_delivery.py` ne provisionne rien : il verifie uniquement sources,
configurations et regressions, y compris dans une copie sans secrets locaux.

## Incidents distingues de la PKI

L'image de terminal initiale montrait un refus de chaine OpenSearch par ses
clients : confiance CA incoherente ou non rechargee apres rotation. Elle ne
prouvait pas une panne d'EJBCA. L'import Java traite maintenant tous les
certificats du bundle, et les clients charges au demarrage sont recharges
lors de la transition de confiance.

Pendant les derniers controles, Logstash a aussi subi `Java heap space` avec
un tas de 3 Gio. Cela est independant de TLS. Le processus degrade a ete
redemarre seul; les deux pipelines sont revenus verts et les connexions
OpenSearch ont ete revalidees. Le dimensionnement du Core et l'endurance sous
charge doivent etre testes sur les VM cibles; un etat sain ponctuel ne prouve
pas l'absence de saturation future.

## Recette encore necessaire sur trois VM neuves

1. Installer exactement les memes sources sur les trois VM et suivre la
   procedure de reference depuis zero, avec leurs IP reelles et leurs comptes.
2. Verifier absence de cle de CA locale et absence de transfert de cle privee;
   verifier les certificats effectivement servis, pas seulement le staging.
3. Tester un DNS client stable, ses SAN et la resolution depuis chaque VM.
4. Confirmer le portail/OIDC avec un navigateur et injecter une capture du
   Collecteur pour constater les documents correspondants dans OpenSearch.
5. Exercer une rotation complete `rotate`, son retour arriere, le renouvellement
   Filebeat et celui de l'API EJBCA. Installer et declencher le timer d'expiration.
6. Tester `restore --fresh` sur une VM de secours avec l'archive chiffree et
   verifier les memes CA, profils, droits et operations d'enrolement.
7. Qualifier la consultation CRL/OCSP par chaque application et le refus d'un
   certificat de service revoque. La presence d'une CRL seule ne suffit pas;
   le refus des agents revoques est deja teste cote autorisation EJBCA.
8. Effectuer un test de charge et de redemarrage du Core, du Cluster et du
   Collecteur. Trois conteneurs OpenSearch sur une VM ne tolerent pas sa perte.

Ces essais ne sont pas annonces comme deja passes. Le parcours est implemente
et pret pour cette recette, mais la qualification production exige ces preuves.

## Sources et sauvegardes

Le travail reste dans l'arbre local, avec les changements preexistants preserves.
Aucun commit ni push n'a ete fait automatiquement. Un clone distant ne
contient donc pas encore ces ajouts tant qu'ils n'ont pas ete publies.

Le script suivant produit une archive des sources courantes, avec un manifeste
SHA-256 par fichier, sans Git interne, secrets locaux ou donnees generees :

```bash
python3 dev/scripts/build-installation-source.py --output <NOUVELLE_ARCHIVE_HORS_DEPOT>.tar.gz
```

Avant les VM, employer cette archive verifiee ou publier les changements
revus dans le depot voulu. L'archive permet les installateurs et les tests de
sources; `./oculox validate` verifie aussi l'historique Git et s'execute donc
dans un clone Git contenant ces sources. Les archives de sauvegarde EJBCA et
leurs phrases de passe ne font jamais partie de l'archive des sources.

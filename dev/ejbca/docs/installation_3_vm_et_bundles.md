# Installation Oculox avec EJBCA sur trois VM

Etat du 1 octobre 2026 : les commandes ci-dessous sont implementees. Le
Core et le cluster existants ont ete testes, mais **aucune installation depuis
trois VM vierges n'a encore ete validee**. Garder les sauvegardes et suivre
les controles a chaque etape. L'IP est un parametre : remplacer tous les
champs entre chevrons par les valeurs du site. Un DNS stable est recommande
chez un client, mais aucune zone DNS n'est exigee pour le laboratoire.

## Avant de commencer

Pour Debian 12/13, installer les outils initiaux sur les trois VM :

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-yaml openssl jq ca-certificates gpg openssh-server
sudo systemctl enable --now ssh
```

Docker et les reglages systeme sont prepares ensuite par les installateurs.
Employer un compte operateur avec sudo. Pour `install cluster --check`, Docker
et son acces operateur doivent deja etre prepares; sur une VM sans Docker,
l'installation complete prepare ces dependances avant de verifier le Compose.

Trois noeuds OpenSearch dans une VM donnent une tolerance aux pannes de
conteneurs, pas a la perte de cette VM ou de son disque.

- Cloner la meme revision du depot sur les trois VM. Synchroniser l'heure et
  verifier le routage Core/Cluster/Collecteur. Ne jamais committer `config/*.env`,
  `dev/generated/`, `dev/ejbca/generated/`, les bundles ou les sauvegardes.
- Le Core doit etre joignable par le Cluster et le Collecteur sur le port
  EJBCA HTTPS configure (`18443` par defaut). Restreindre ce port par pare-feu
  aux machines autorisees. Le port HTTP de bootstrap (`18080`) reste local.
- Les trois noeuds Cluster doivent aussi joindre l'URL publique Keycloak du
  Core en HTTPS (443 par defaut). Autoriser la sortie du reseau `idp-egress`,
  la resolution DNS choisie et les endpoints discovery/JWKS. L'acces a EJBCA
  sur 18443 ne suffit pas pour l'authentification humaine OpenSearch.
- La confiance initiale envers la Root CA EJBCA doit passer par un canal
  authentifie : comparer son SHA-256 affiche sur le Core avec une valeur
  communiquee hors du canal de transfert. `SHA256SUMS` seul ne prouve pas
  l'identite du Core.
- Les administrateurs EJBCA utilisent leur certificat client; ne pas remettre
  un acces administrateur public pour simplifier l'installation.
- Une cle privee de service ou d'agent ne quitte pas sa VM. EJBCA garde les
  cles de CA. Les bundles de comptes OpenSearch restent des secrets distincts.

## 1. Core : socle et PKI centrale

```bash
cd ~/Oculox_V2
./oculox bootstrap principal --server-name <IP_OU_DNS_CORE>
./oculox pki-ca init
./oculox pki-ca start
./oculox pki-ca create-ca-plan
./oculox pki-ca provision-profiles
./oculox pki-ca harden
./oculox pki-ca verify-hardening
./oculox pki-ca configure-api --public-host <IP_OU_DNS_CORE> --bind-address <IP_LOCALE_CORE>
./oculox pki-ca provision-profiles --verify-only
./oculox pki-ca validate
```

`bootstrap` lance l'assistant systeme officiel, cree `config/*.env` et fixe le
nom/IP public sans demarrer le Core ni creer de CA locale. Si le groupe Docker
vient d'etre ajoute, ouvrir une nouvelle session avant `pki-ca start`.
`create-ca-plan` cree la Root CA et les intermediaires Web, Services internes et
OpenSearch dans EJBCA. `provision-profiles` cree les profils de certificat et
d'entite finale. `harden` impose l'administration par certificat client.
L'image EJBCA est figee par digest dans le fichier exemple. `pki-ca start`
attend la sante des conteneurs avant de rendre la main. `configure-api` emet le certificat HTTPS d'EJBCA et charge la CA qui signe les
agents d'enrolement dans sa confiance TLS.

Choisir une phrase de passe forte dans un fichier 0600 hors du depot puis
effectuer une sauvegarde chiffree. La valeur n'est jamais passee en argument :

```bash
./oculox pki-ca backup --output <CHEMIN_BACKUP>.gpg --passphrase-file <FICHIER_0600>
./oculox pki-ca backup-check --archive <CHEMIN_BACKUP>.gpg --passphrase-file <FICHIER_0600>
```

Conserver l'archive et la phrase de passe en lieux separes. `backup-check`
teste le dechiffrement et les fichiers attendus, pas une restauration complete.
`restore` exige `--confirm REPLACE-EJBCA-DATABASE` et remplace la base EJBCA :
ne l'utiliser qu'en procedure de sinistre, avec une sauvegarde supplementaire
et une fenetre d'exploitation. Une sauvegarde de recuperation chiffree est
creee avant le remplacement. Un echec laisse EJBCA arrete pour eviter de signer
avec une base partiellement restauree. Tester l'archive sans toucher au Core :

```bash
./oculox pki-ca restore-test --archive <CHEMIN_BACKUP>.gpg --passphrase-file <FICHIER_0600>
```

Cette commande restaure la base et demarre une autre instance EJBCA sans port
publie, avec reseau et volumes distincts. Elle controle les quatre CA, la chaine
TLS et une signature CRL, puis retire uniquement ses ressources temporaires.
Sur un Core de remplacement sans conteneur ni volume EJBCA existant :

```bash
./oculox pki-ca restore --fresh --bind-address <IP_LOCALE_CORE> \
  --archive <CHEMIN_BACKUP>.gpg --passphrase-file <FICHIER_0600> \
  --confirm REPLACE-EJBCA-DATABASE
./oculox pki-ca configure-api --public-host <IP_OU_DNS_CORE> --bind-address <IP_LOCALE_CORE>
./oculox pki-ca verify-hardening
```

La racine reste celle de la sauvegarde; ne pas executer `create-ca-plan` pour
remplacer cette identite. Le parcours `--fresh` doit encore etre execute sur
une VM neuve; la restauration isolee a ete testee ici.

Emettre les certificats Core, apres `bootstrap` pour que les SAN contiennent
l'adresse choisie :

```bash
./oculox pki enroll --provider ejbca --service web_server --install
./oculox pki enroll --provider ejbca --service web_ca --install
./oculox pki enroll --provider ejbca --service ingestion_ca --install
./oculox pki enroll --provider ejbca --service logstash_server --install
./oculox pki enroll --provider ejbca --service filebeat_client --install
./oculox pki status
```

## 2. Cluster : identite d'enrolement et certificats locaux

Sur la VM Cluster :

```bash
cd ~/Oculox_V2
./oculox pki agent-init --role cluster --identity cluster-01
```

Si Docker n'est pas encore installe sur Cluster, executer d'abord
`./oculox cluster prepare-host`, puis ouvrir une nouvelle session si le groupe
Docker vient d'etre attribue. Reprendre avec la CSR publique :

```bash
scp dev/generated/pki/remote-agent/agent.csr <USER_CORE>@<IP_CORE>:~/cluster-01.csr
```

La CSR est publique. Sur Core, apres verification de l'identite de la VM et
de sa cle SSH :

```bash
./oculox pki-ca authorize-agent --role cluster --identity cluster-01 \
  --csr ~/cluster-01.csr --output ~/cluster-01-enrollment
```

Cette commande cree dans EJBCA un role d'enrolement limite aux profils
OpenSearch, signe la CSR et affiche l'empreinte de la Root CA. Elle ne renvoie
jamais une cle privee. Transferer le repertoire public au Cluster via SSH :

```bash
scp -r ~/cluster-01-enrollment <USER_CLUSTER>@<IP_CLUSTER>:~/
```

Sur Cluster, comparer l'empreinte Root CA avec celle obtenue sur Core par un
canal independant, puis installer l'agent :

```bash
./oculox pki agent-install --bundle ~/cluster-01-enrollment \
  --root-sha256 <EMPREINTE_SHA256_CORE>
cp dev/config/opensearch-cluster/cluster.yml.example ~/oculox-cluster.yml
# Editer endpoint.ip (IP locale), endpoint.dns (DNS client optionnel), heap et stockage.
./oculox install cluster --config ~/oculox-cluster.yml --check
./oculox install cluster --config ~/oculox-cluster.yml
./oculox cluster validate
./oculox cluster client-bundle core ~/oculox-bundle-core
```

`install cluster` genere les cinq cles/CSR sur **Cluster**, demande les
certificats a EJBCA par mTLS, initialise OpenSearch Security puis publie
l'endpoint. Il installe aussi la chaine Web EJBCA de l'agent dans `idp-trust`.
Cette confiance est distincte de la CA OpenSearch. Le Core applicatif n'etant
pas encore demarre, l'activation OIDC intervient obligatoirement a l'etape 3.
`--check` ne signe rien et ne prouve pas que le cluster demarrera.
Pour un cluster existant, ne pas relancer l'installation : utiliser les phases
`trust`, `leaf`, `retire` de `migrate-ejbca.py`, chacune avec sauvegarde et
controle du cluster. Verifier les DN `nodes_dn` avant `leaf`.

Si `endpoint.dns` est renseigne, les clients utilisent ce DNS et le certificat
contient le SAN DNS ainsi que le SAN IP de `endpoint.ip`. Le DNS doit resoudre
vers cette IP depuis Core et Collecteur. La publication Docker reste liee a
l'IP locale; renseigner un DNS ne cree pas une zone DNS.

Le bundle Core contient CA publique, URL et comptes techniques OpenSearch
limites, avec leurs mots de passe. Ce n'est **pas** un bundle de certificats
prives. Le transferer sur Core par SSH authentifie et proteger son repertoire.

## 3. Core : branchement du cluster et demarrage

Sur Core :

```bash
scp -r <USER_CLUSTER>@<IP_CLUSTER>:~/oculox-bundle-core ~/oculox-bundle-core
cd ~/oculox-bundle-core
sha256sum -c SHA256SUMS
cd ~/Oculox_V2
./oculox resume-install principal --server-name <IP_OU_DNS_CORE> \
  --opensearch-bundle ~/oculox-bundle-core
./oculox keycloak provision --admin-username <ADMIN_KEYCLOAK>
./oculox keycloak activate-portal
./oculox keycloak activate-dashboards
./oculox restart keycloak nginx-proxy dashboards
./oculox validate all
./oculox verify clients
./oculox keycloak verify-hardening
```

`resume-install` utilise la configuration creee par `bootstrap`, lance
`auth_setup`, prepare le role, importe le bundle et demarre Core. Confirmer
que Keycloak est provisionne et OIDC Dashboards active. Les identites initiales
sont dans `dev/generated/keycloak-initial-credentials.env` (0600); les actions
de changement de mot de passe/MFA restent a realiser par chaque utilisateur.
Consulter `dev/keycloak/11_configuration_keycloak_detaillee_keep_it_simple.md`.
Puis, **sur Cluster**, maintenant que Keycloak repond :

```bash
./oculox cluster configure-oidc --keycloak-auth-url https://<IP_OU_DNS_CORE>/keycloak
./oculox cluster verify-oidc
./oculox cluster validate
```

La CA est prise dans `remote-agent/api-ca.crt`, deja verifiee contre la Root
CA epinglee lors de l'installation de l'agent. Ne pas copier un certificat
serveur a la place de cette chaine. La commande sauvegarde les parametres
Security **actifs**, conserve Basic technique et les mappings existants, puis
ajoute OIDC et les mappings humains. Elle ne regenere ni utilisateurs ni roles.
Les noms DNS et IP sont parametrables; l'URL doit correspondre au SAN Web,
a l'issuer Keycloak et aux redirect URIs Dashboards du Core.

Sur **Core**, effectuer la recette avec une identite Keycloak temporaire :

```bash
python3 dev/tests/keycloak/test_live_opensearch_oidc.py --run-live
./oculox validate all
./oculox verify clients
```

Ce test verifie les jetons signes et deux mappings distincts (lecture/admin),
puis supprime son client temporaire; il ne modifie aucun utilisateur humain ni
MFA. Terminer par une nouvelle connexion au portail et a Dashboards avec les
profils humains prevus. Un HTTP 302 seul ne valide pas une session OIDC.

### Rotation Web Et Correction D'un Cluster Existant

La migration des certificats OpenSearch ne remplace pas automatiquement la CA
que les noeuds utilisent pour joindre Keycloak. Apres changement de la CA Web,
renouveler/reinstaller le bundle public de l'agent (meme racine epinglee), puis
sur Cluster :

```bash
./oculox cluster oidc-trust
./oculox cluster verify-oidc
```

`oidc-trust` ne reecrit pas Security ni les mappings. Il precontrole discovery
et JWKS depuis les trois noeuds avec la nouvelle CA, sauvegarde l'ancienne,
recharge les noeuds un par un en attendant trois noeuds verts, puis verifie
la confiance montee. En cas d'echec, il restaure la confiance precedente.
La validation du cluster controle aussi OIDC quand ce domaine est actif;
`verify-oidc` reste obligatoire pour la recette finale, car il refuse un cluster
reste en Basic seul. Conserver les sauvegardes `oidc-backups` protegees.

## 4. Collecteur : identite et certificat client

Sur le Core, apres avoir confirme que le certificat Logstash actif contient
l'IP/DNS utilise par les collecteurs :

```bash
./oculox collector-bundle collector-01 <IP_OU_DNS_CORE> ~/collector-01-public
```

Ce bundle contient la CA publique et `endpoints.env`, **aucune cle client**.
Le transferer au Collecteur. Sur ce dernier, generer l'agent et transferer
seulement sa CSR au Core :

```bash
./oculox pki agent-init --role collector --identity collector-01
scp dev/generated/pki/remote-agent/agent.csr <USER_CORE>@<IP_CORE>:~/collector-01.csr
```

Sur Core :

```bash
./oculox pki-ca authorize-agent --role collector --identity collector-01 \
  --csr ~/collector-01.csr --output ~/collector-01-enrollment
scp -r ~/collector-01-enrollment <USER_COLLECTOR>@<IP_COLLECTOR>:~/
```

Sur Collecteur, verifier l'empreinte et installer l'agent puis le role :

```bash
./oculox pki agent-install --bundle ~/collector-01-enrollment \
  --root-sha256 <EMPREINTE_SHA256_CORE>
./oculox install hedgehog --principal-host <IP_OU_DNS_CORE> \
  --collector-name collector-01 --bundle ~/collector-01-public
./oculox validate ingestion
```

L'installateur demande le certificat Filebeat a EJBCA et conserve sa cle sur
Collecteur. Si Arkime doit joindre directement OpenSearch, ajouter un bundle
OpenSearch `hedgehog` distinct cree sur Cluster et l'option
`--opensearch-bundle <repertoire>` a `install hedgehog`.

## Exploitation et limites

- `./oculox pki expiry`, `./oculox validate all` et `./oculox verify clients`
  donnent des controles locaux. `./oculox pki renew --provider ejbca --service
  <SERVICE> --install --restart` reenrole un service Core. Pour HTTPS EJBCA,
  utiliser `pki-ca configure-api` afin de renouveler aussi le keystore WildFly.
- `./oculox pki-ca revoke-agent --role <role> --identity <nom> --dry-run`
  montre l'agent vise. Sans `--dry-run`, sa permission d'emission est retiree
  dans EJBCA, son certificat est revoque et une CRL est generee. La presence
  d'une CRL ne prouve pas que tous les consommateurs la consultent : pour un
  certificat de nœud compromis, appliquer aussi une rotation de confiance.
- Une IP employee comme URL doit etre un SAN IP. Lors d'un changement d'IP,
  reenroler le certificat correspondant et mettre a jour les endpoints. Avec
  un DNS stable, le DNS doit etre un SAN DNS ; l'IP peut changer sous ce nom.
- Les tests reels d'installation neuve sur trois VM et la detection de
  revocation par chaque consommateur restent a effectuer avant la qualification
  production. Le resultat detaille des tests locaux et distants est dans
  [le rapport de livraison](livraison_ejbca_2026-09-30.md).

### Renouvellement normal du cluster

Sur Cluster, reenroler en staging les cinq identites (cles nouvelles locales),
puis effectuer une rotation avec la meme CA. Cette commande est reutilisable,
y compris apres l'etat `retire`; elle ne relance pas la migration de CA :

```bash
for service in opensearch_node_1 opensearch_node_2 opensearch_node_3 opensearch_admin_client opensearch_endpoint; do
  ./oculox pki request --service "$service" || exit 1
done
./oculox cluster pki-migrate rotate --check
./oculox cluster pki-migrate rotate
./oculox cluster validate
```

`--check` ne remplace rien. La rotation verifie chaine, cles, EKU, SAN et DN,
fige les cinq chemins de staging, sauvegarde puis redemarre un noeud a la fois
avec retour au vert obligatoire. `--staging-root <DIR>` permet de choisir un
ensemble contenant les cinq repertoires de service. Conserver la sauvegarde
affichee pour `pki-migrate rollback --backup <DIR>`.

### Renouvellement des agents et du collecteur

Sur la VM qui possede l'agent :

```bash
./oculox pki agent-init --role <cluster-ou-collector> --identity <identite> --renew
```

Transferer seulement `pending.csr` au Core. Sur Core, executer `authorize-agent`
avec la meme identite et `--renew`; transferer le nouveau repertoire public.
Sur la VM, executer `agent-install --renew --bundle <DIR> --root-sha256 <EMPREINTE>`
puis `pki agent-status --online`. Les anciennes cle et configuration sont
sauvegardees localement. Pour renouveler Filebeat sur Collecteur :

```bash
./oculox pki request --service filebeat_client --install --restart
./oculox validate ingestion
```

### Revocation et surveillance

Sur Core, pour un certificat de service precis (copie publique uniquement) :

```bash
./oculox pki-ca revoke-certificate --certificate <CERTIFICAT_PUBLIC> --dry-run
./oculox pki-ca revoke-certificate --certificate <CERTIFICAT_PUBLIC> \
  --reason key-compromise --output-crl <NOUVEAU_FICHIER_CRL>
```

Les motifs disponibles sont `key-compromise`, `superseded`, `cessation` et
`privilege-withdrawn`. Les certificats de CA sont refuses par cette commande.
La revocation est par numero de serie, sans revoquer toutes les autres identites.
Une CRL est signee et exportee; sa consultation par chaque application est une
configuration distincte. Ne pas annoncer qu'un certificat revoque est refuse
par Logstash ou tous les clients tant que ce refus n'a pas ete teste. Pour un
agent compromis, `revoke-agent` retire aussi immediatement son role d'emission;
le refus de nouvelles demandes a ete teste sur EJBCA reel.

Sur chaque VM, activer la surveillance d'expiration :

```bash
./oculox pki monitor check
./oculox pki monitor install
systemctl status oculox-pki-expiry.timer
journalctl -u oculox-pki-expiry.service
```

Le timer quotidien ecrit `PKI_ALERT` dans le journal et echoue des le seuil
d'avertissement (60 jours par defaut), sans renouvellement automatique aveugle.
`monitor install --render-only` genere les unites sans les installer.

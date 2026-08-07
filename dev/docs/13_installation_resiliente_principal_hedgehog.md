# Installation Résiliente Oculox Principal Et Hedgehog

## 1. Objectif

Cette procédure permet de partir de serveurs neufs et d'installer la plateforme
avec une interface commune. Elle conserve les mécanismes officiels Malcolm pour
la préparation du système, les profils et les secrets, puis ajoute les éléments
Oculox suivants :

- deux instances Logstash indépendantes sur le Principal ;
- une file persistante distincte par instance Logstash ;
- la répartition Filebeat entre les deux instances ;
- un transport Beats protégé par TLS mutuel ;
- un certificat client propre à chaque collecteur Hedgehog ;
- une politique de redémarrage automatique des conteneurs ;
- des commandes communes de démarrage, d'arrêt, d'état et de validation.

Le dépôt reste unique. C'est le rôle choisi lors de l'installation qui détermine
les services réellement démarrés.

Chaque machine doit néanmoins utiliser son propre clone et ses propres volumes.
Le lanceur refuse de transformer un dépôt déjà préparé pour un rôle en un autre
rôle. Cette protection évite de mélanger les secrets du Principal, les identités
des collecteurs et les données persistantes.

## 2. Préparation Des Serveurs

Chaque serveur doit disposer d'un système Linux supporté, de ressources adaptées
au rôle, d'une synchronisation horaire et d'une résolution DNS cohérente. Le nom
ou l'adresse utilisé pour joindre le Principal doit rester stable : cette valeur
est inscrite dans le certificat présenté par Logstash.

Le pare-feu doit autoriser :

| Sens | Port | Usage |
|---|---:|---|
| Analystes vers Principal | 443/TCP | Interface HTTPS |
| Hedgehog vers Principal | 5044/TCP | Première instance Logstash |
| Hedgehog vers Principal | 5045/TCP | Deuxième instance Logstash |

Les ports 5044 et 5045 doivent être autorisés uniquement depuis les adresses des
collecteurs. Le chiffrement TLS ne remplace pas ce filtrage réseau.

## 3. Installation Du Principal

Depuis la racine du dépôt cloné sur le serveur Principal :

```bash
./oculox install principal --server-name <nom-DNS-ou-IP-du-principal>
```

Cette commande réalise la chaîne suivante :

1. `scripts/install.py --tui` prépare le système avec l'assistant officiel ;
2. les fichiers `config/*.env` créés par l'étape privilégiée sont rendus à
   l'opérateur qui a lancé `oculox` ;
3. le répertoire d'état local `dev/generated/` est créé avec des permissions
   réservées à cet opérateur, même si le dépôt a été cloné par `root` ;
4. les valeurs `PUID=0` et `PGID=0`, lorsqu'elles proviennent des valeurs par
   défaut de l'exécution avec `sudo`, sont remplacées par l'UID et le GID de cet
   opérateur ; une identité non nulle choisie dans l'assistant est conservée ;
5. la configuration Compose officielle et la surcharge de résilience Oculox
   sont fusionnées dans un fichier local sous `dev/generated/` ;
6. le profil `malcolm` est imposé pour éviter une divergence de rôle ;
7. le lanceur vérifie l'accès non privilégié à Docker avant d'appeler les outils
   d'authentification ; si l'installateur vient d'ajouter l'opérateur au groupe
   `docker`, il recharge automatiquement ce groupe dans un sous-processus ;
8. `scripts/auth_setup` crée interactivement les comptes et secrets officiels ;
9. l'autorité Oculox et le certificat serveur sont générés localement ;
10. Filebeat est configuré vers `logstash:5044` et `logstash-2:5044` ;
11. les configurations Principal et Hedgehog sont validées sans les démarrer ;
12. les images sont récupérées et le script officiel `scripts/start` démarre le
    profil Principal complet.

La reprise de propriété de `config/` est nécessaire parce que l'installation
système officielle exige les privilèges administrateur sous Linux, alors que
les étapes Oculox suivantes s'exécutent volontairement avec le compte de
l'opérateur. Elle évite qu'une installation neuve échoue sur un fichier
`config/process.env` appartenant à `root`.

Les dossiers `postgres/`, `valkey/`, `opensearch/`, `pcap/`, `zeek-logs/`,
`suricata-logs/` et les autres répertoires de travail suivent le même principe
de séparation : ils contiennent des données persistantes ou générées et ne
doivent jamais être versionnés. Docker Compose ne crée pas implicitement tous
les montages bind. Le lanceur Oculox délègue donc le démarrage au script
officiel `scripts/start`, après avoir produit la configuration Compose
effective. Ce script amont crée les répertoires et fichiers techniques attendus
par Malcolm, notamment les fichiers `.opensearch.*.curlrc`, les fichiers Nginx
et les chemins de données. Cette délégation évite de maintenir une liste locale
incomplète de montages et supprime les erreurs de type `bind source path does
not exist` lors d'une installation neuve.

Les mots de passe ne sont jamais fournis comme arguments. Ils restent gérés par
l'assistant officiel. Lorsqu'une installation neuve ajoute l'opérateur au groupe
`docker`, le noyau ne modifie pas les groupes du shell déjà ouvert. Le lanceur
détecte ce cas avant `scripts/auth_setup` et reprend automatiquement sous l'UID
de l'opérateur avec `docker` comme groupe primaire. `sudo` sert uniquement à
établir ce groupe dans le nouveau processus : `auth_setup` ne s'exécute pas avec
l'UID `root`, et les secrets restent donc la propriété de l'opérateur.

Si la reprise automatique est impossible (service Docker arrêté ou groupe
absent), le lanceur s'arrête sans réexécuter l'assistant système. Après
correction ou reconnexion, la commande explicite suivante reprend à l'étape
d'authentification :

```bash
./oculox resume-install principal --server-name <nom-DNS-ou-IP-du-principal>
```

Pour Hedgehog, reprendre avec la commande `resume-install hedgehog` et les mêmes
options `--principal-host`, `--collector-name` et `--bundle` que lors du premier
lancement. `resume-install` exige que `config/process.env` existe : elle ne peut
donc pas masquer une installation système qui n'a jamais abouti.

## 4. Création D'un Bundle Hedgehog

Sur le Principal, créer une identité distincte pour chaque collecteur :

```bash
./oculox collector-bundle <nom-collecteur> <nom-DNS-ou-IP-du-principal>
```

Le bundle produit contient uniquement l'autorité publique, le certificat client,
la clé privée du collecteur, les destinations et leurs empreintes. La clé privée
de l'autorité et celle du serveur ne quittent jamais le Principal.

Le répertoire doit être transféré vers le collecteur par un canal administré et
chiffré, puis supprimé de la zone de transfert après import. Un bundle ne doit
pas être réutilisé entre plusieurs collecteurs.

## 5. Installation Du Collecteur Hedgehog

Depuis la racine du même dépôt cloné sur le collecteur :

```bash
./oculox install hedgehog \
  --principal-host <nom-DNS-ou-IP-du-principal> \
  --collector-name <nom-collecteur> \
  --bundle <répertoire-du-bundle>
```

La commande sélectionne le profil `hedgehog`, vérifie les empreintes du bundle,
importe l'identité du collecteur et génère les cinq configurations Filebeat vers
les destinations suivantes :

```text
<principal>:5044
<principal>:5045
```

Filebeat utilise `loadbalance: true`. Les connexions sont distribuées entre les
deux Logstash disponibles. En cas d'indisponibilité temporaire de l'une des deux
instances, Filebeat continue avec l'autre et reprend les envois grâce à ses
registres persistants.

## 6. Exploitation Courante

Les mêmes commandes sont utilisées sur les deux rôles :

```bash
./oculox start
./oculox restart [service...]
./oculox status
./oculox logs [service...]
./oculox pull
./oculox validate
./oculox stop
```

`start`, `status` et `stop` lisent le rôle conservé localement dans
`dev/generated/deployment.env`. Au démarrage, `oculox` génère
`dev/generated/docker-compose.runtime.yml` en fusionnant le Compose officiel et
la surcharge Oculox, puis appelle `scripts/start` avec ce fichier. Les
préparations officielles de Malcolm sont ainsi conservées sans perdre la seconde
instance Logstash ni les configurations Filebeat résilientes. Le nom du projet
Compose reste dérivé du nom du clone afin que `start`, `status`, `logs` et
`stop` ciblent toujours les mêmes conteneurs. Il ne faut donc pas remplacer
`./oculox start` par un `docker compose up` isolé.

`restart` et `logs` acceptent un ou plusieurs noms de services. Sans nom,
`restart` redémarre le profil complet et `logs` affiche les 200 dernières lignes
de tous ses services. `pull` récupère les images du profil sélectionné sans
modifier les données persistantes.

`stop` exécute `docker compose down` sans `--volumes`. Les index, les registres
Filebeat et les files persistantes Logstash sont conservés.

## 7. Contrôles De Preuve

```bash
./oculox validate
./oculox status
./dev/scripts/check-beats-certificates.sh 90
```

Sur le Principal, la présence des deux chemins d'ingestion se vérifie avec :

```bash
docker compose \
  --project-directory . \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  --profile malcolm ps logstash logstash-2
```

Sur le collecteur, les destinations actives doivent être lues dans les fichiers
générés, sans afficher les secrets :

```bash
grep -R -nE 'hosts:|loadbalance:|verification_mode:' dev/generated/filebeat
```

Le résultat attendu contient les ports 5044 et 5045, `loadbalance: true` et
`verification_mode: full`.

## 8. Ce Que La Résilience Couvre

Cette architecture protège l'ingestion contre l'arrêt d'un processus ou d'un
conteneur Logstash. Chaque instance dispose de sa propre file persistante et
Filebeat peut répartir les connexions ou utiliser l'instance restante.

Elle ne constitue pas encore une haute disponibilité de site :

- les deux Logstash sont sur le même serveur Principal ;
- l'hôte Principal reste un point unique de panne ;
- OpenSearch reste une instance unique ;
- les volumes Docker restent locaux au serveur.

Une résilience aux pannes d'hôte exige au minimum deux nœuds d'ingestion placés
sur des machines différentes et un cluster OpenSearch d'au moins trois nœuds,
avec une stratégie de sauvegarde et de restauration testée. Cette extension doit
être réalisée lors de la phase de clusterisation OpenSearch ; elle ne doit pas
être annoncée comme déjà acquise par ce déploiement.

## 9. Données Versionnées Et Données Locales

Le dépôt Git contient le code d'orchestration, les scripts, les modèles et la
documentation. Il ne contient pas :

- les fichiers `config/*.env` générés par l'assistant ;
- les mots de passe et secrets d'authentification ;
- les clés privées et certificats d'une installation ;
- les bundles de collecteurs ;
- les index, PCAP, journaux et résultats de benchmark.

Cette séparation permet de déployer la même architecture depuis Git sans copier
les identités ou les données d'un environnement vers un autre.

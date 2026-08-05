# Phase 11 - Documentation Et Livraison Git

## 1. Objectif

La phase 11 transforme les développements validés en une livraison traçable,
compréhensible et réversible. Elle ne consiste pas seulement à envoyer des
fichiers vers Gitea. Elle doit prouver :

- ce qui a été modifié ;
- pourquoi ces modifications existent ;
- comment elles ont été validées ;
- ce qui est volontairement exclu de Git ;
- comment installer et exploiter la solution ;
- comment revenir en arrière en cas de problème.

Le dépôt livré conserve le code officiel Malcolm et ajoute les fonctions
Oculox dans `dev/` et dans le lanceur racine `oculox`. Cette séparation réduit
le risque lors des futures mises à jour de Malcolm.

## 2. Vocabulaire Git À Comprendre

### 2.1 Répertoire de travail

Le répertoire de travail contient les fichiers visibles sur le disque. Un
fichier modifié n'est pas encore enregistré dans l'historique Git.

```bash
git status --short
```

Cette commande classe les changements :

- `M` : fichier déjà connu de Git et modifié ;
- `A` : nouveau fichier ajouté à l'index ;
- `D` : fichier supprimé ;
- `??` : nouveau fichier que Git ne suit pas encore.

### 2.2 Index Git

L'index est la zone de préparation du prochain commit. La commande `git add`
n'envoie rien vers le serveur : elle sélectionne seulement les fichiers qui
entreront dans le prochain commit.

```bash
git add <fichier-ou-répertoire>
git diff --cached --stat
```

La deuxième commande montre le contenu préparé sans afficher tout le détail.

### 2.3 Commit

Un commit est une photographie cohérente des fichiers sélectionnés. Il possède
un identifiant unique et un message expliquant son objectif.

```bash
git commit -m "Message décrivant le changement"
```

Un commit local n'est pas encore disponible dans Gitea.

### 2.4 Branche Et Dépôts Distants

La branche de livraison est `main`. La branche technique
`upgrade/v26.07.1` est conservée localement comme référence de la migration et
pointe actuellement sur le même commit que `main`.

Les dépôts distants ont chacun un rôle précis :

- `origin` : nouveau dépôt de livraison `vmbaye/Oculox_V2` dans Gitea ;
- `upstream` : dépôt officiel Malcolm, utilisé pour suivre les versions amont ;
- `legacy` : ancien dépôt interne Oculox, conservé comme référence historique.

```bash
git branch --show-current
git remote -v
```

La publication est effectuée avec :

```bash
git push -u origin main
```

L'option `-u` mémorise la branche distante associée. Les prochains envois
pourront ensuite utiliser simplement `git push`.

La connexion ouverte dans un navigateur ne fournit pas automatiquement les
identifiants au client Git du terminal. Pour une URL HTTPS, il faut créer un
jeton d'accès personnel dans Gitea et l'utiliser comme mot de passe lors du
premier `git push`. Le jeton ne doit jamais être écrit dans une commande, un
fichier du dépôt ou la documentation.

Une clé SSH enregistrée dans le compte Gitea constitue l'autre méthode
recommandée. Dans ce cas, l'URL peut être remplacée ainsi :

```bash
git remote set-url origin git@gitea.tcric.hq:vmbaye/Oculox_V2.git
git push -u origin main
```

## 3. Contenu De La Livraison

### 3.1 Architecture Et Déploiement Résilient

Le commit `981926e1` (`Ajout architecture Oculox résiliente`) apporte :

- la surcharge Compose avec deux instances Logstash ;
- une file persistante distincte pour chaque instance ;
- les paramètres persistants des pipelines Logstash ;
- le TLS mutuel entre Filebeat et Logstash ;
- la génération de la PKI locale ;
- la création d'un bundle d'identité propre à chaque collecteur ;
- la génération des configurations Filebeat avec répartition de charge ;
- les rôles Principal et Hedgehog ;
- le lanceur unifié `oculox` ;
- les modes locaux simple et double Logstash.

Ce commit est fonctionnellement autonome : il contient le code nécessaire au
déploiement, sans les résultats de tests ni les secrets générés.

### 3.2 Supervision Et Tests De Résilience

Le commit `d758c7ca` (`Ajout supervision et tests de résilience`) apporte :

- la collecte des métriques Logstash, OpenSearch, Docker et système ;
- les seuils de supervision ;
- les requêtes Prometheus proposées ;
- la spécification des tableaux de bord ;
- le test de répartition entre les deux Logstash ;
- le test de perte d'une instance puis de réintégration ;
- le test d'indisponibilité et de reprise d'OpenSearch ;
- le test des files persistantes ;
- le test de persistance des registres Filebeat ;
- le test de redémarrage complet ;
- le contrôle automatisé de l'hygiène du dépôt.

### 3.3 Documentation

Le dernier lot rassemble les guides des phases 5 à 11, les procédures
d'installation Principal/Hedgehog, l'explication de l'arborescence, les
preuves de validation, les limites connues et les fichiers `README.md`.

## 4. Éléments Volontairement Exclus De Git

Les éléments suivants sont générés localement et ne doivent jamais être
commités :

- `config/*.env` contenant la configuration réelle et certains secrets ;
- `dev/generated/`, notamment la clé privée de l'autorité de certification ;
- `dev/tests/results/` contenant les résultats bruts ;
- `dev/monitoring/data/` contenant les métriques collectées ;
- les PCAP de test ;
- les logs Zeek, Suricata, Filebeat et filescan ;
- les bases, index et volumes Docker.

Les fichiers `.gitignore` ne chiffrent pas ces données. Ils demandent seulement
à Git de ne pas les proposer dans les commits. Les permissions système, la
gestion des secrets et les sauvegardes restent nécessaires.

## 5. Validation Effectuée Avant Livraison

Le contrôle principal est :

```bash
./dev/scripts/audit-dev-repository.sh
```

Il vérifie :

1. la présence des outils nécessaires ;
2. l'intégration de Malcolm `v26.07.1` ;
3. l'absence d'erreurs de format dans le diff ;
4. l'absence d'artefacts et de clés privées versionnés ;
5. la syntaxe des scripts Bash ;
6. la compilation syntaxique des scripts Python ;
7. la syntaxe YAML ;
8. les configurations Compose Principal simple, Principal résilient et
   Hedgehog ;
9. les permissions des fichiers sensibles ;
10. l'état du répertoire de travail Git.

Les validations complémentaires sont :

```bash
./dev/scripts/validate-compose.sh
./dev/tests/run-phase9-resilience.sh <identifiant>
./dev/tests/run-phase10-benchmark.sh <identifiant>
```

Le test de phase 9 a validé la répartition, le fonctionnement avec une seule
instance, la réintégration automatique, la persistance des événements pendant
une indisponibilité OpenSearch, la reprise Filebeat et le redémarrage complet.

Le test de phase 10 compare les modes simple et double sur la machine locale.
Il valide le code et la méthode, mais ne constitue pas un dimensionnement de
production.

## 6. Installation Après Clonage

### 6.1 Principal Oculox

```bash
git clone <URL-GITEA> Oculox
cd Oculox
git switch main
./oculox install principal --server-name <nom-DNS-ou-IP>
./oculox validate
./oculox status
```

Le lanceur appelle d'abord les assistants officiels Malcolm. Il applique
ensuite le rôle Principal, génère la PKI d'ingestion, prépare Filebeat et active
les deux instances Logstash.

### 6.2 Collecteur Hedgehog

Le Principal crée une identité distincte pour le collecteur :

```bash
./oculox collector-bundle <nom-collecteur> <adresse-principal>
```

Après transfert sécurisé du bundle vers le collecteur :

```bash
./oculox install hedgehog \
  --principal-host <adresse-principal> \
  --collector-name <nom-collecteur> \
  --bundle <répertoire-bundle>
./oculox validate
./oculox status
```

La clé privée de l'autorité de certification ne quitte jamais le Principal.
Le collecteur reçoit uniquement son certificat, sa clé privée et le certificat
public de l'autorité.

## 7. Exploitation Courante

```bash
./oculox start
./oculox status
./oculox logs [service...]
./oculox restart [service...]
./oculox validate
./oculox stop
```

Pour le développement local à ressources limitées :

```bash
./dev/scripts/platform-mode.sh single-ingest
./dev/scripts/platform-mode.sh dual-ingest
./dev/scripts/platform-mode.sh status
./dev/scripts/platform-mode.sh dual-stop
```

Ces modes ne remplacent pas l'installation normale. Ils permettent seulement
de tester un sous-ensemble de services sans démarrer toute la plateforme.

## 8. Retour Arrière

### 8.1 Retour Du Mode Double Au Mode Simple

```bash
./dev/scripts/platform-mode.sh dual-stop
./dev/scripts/platform-mode.sh single-ingest
```

Les volumes ne sont pas supprimés. Les files persistantes restent donc
disponibles pour l'analyse ou une reprise ultérieure.

### 8.2 Annulation D'un Commit Déjà Publié

La commande recommandée est :

```bash
git revert <identifiant-du-commit>
git push
```

`git revert` crée un nouveau commit qui annule proprement l'ancien. Il conserve
l'historique partagé. Il faut éviter `git reset --hard` sur une branche déjà
publiée, car cette commande réécrit l'état local et peut supprimer du travail.

### 8.3 Retour À La Version Avant Mise À Jour

Le tag local `backup/local-26.06.0-before-upgrade` identifie l'état précédant
la migration vers Malcolm `v26.07.1`. Il sert de référence de comparaison ou de
restauration contrôlée. Les données persistantes doivent cependant être
sauvegardées séparément : un tag Git ne sauvegarde ni OpenSearch, ni PostgreSQL,
ni les PCAP, ni les volumes Docker.

## 9. Limites Connues

- Deux Logstash assurent la continuité de l'ingestion, mais ne rendent pas
  OpenSearch hautement disponible.
- L'OpenSearch du développement local reste une instance unique.
- Les valeurs de performance locales ne sont pas des engagements de capacité.
- La qualification finale doit être répétée sur les VM cibles avec ressources
  dédiées, stockage NVMe/SSD et réseau dimensionné.
- La sauvegarde des volumes et la restauration complète restent à intégrer à
  la procédure d'exploitation de production.
- Les certificats générés doivent être renouvelés avant expiration et leur clé
  privée protégée hors des dépôts Git.

## 10. Critères De Fin De Phase

La phase 11 est terminée lorsque :

- les commits sont ciblés et compréhensibles ;
- l'audit du dépôt retourne `PASS` ;
- les configurations Compose sont valides ;
- aucun secret ou artefact runtime n'est suivi ;
- la branche est publiée dans Gitea ;
- la branche distante contient les mêmes commits que la branche locale ;
- une autre personne peut retrouver les procédures d'installation, de test,
  d'exploitation et de retour arrière dans `dev/docs/`.

## 11. Commandes De Preuve De Livraison

```bash
git status --short --branch
git log --oneline --decorate -5
git diff --check
./dev/scripts/audit-dev-repository.sh
git ls-remote --heads origin main
```

Ces commandes prouvent respectivement l'état local, les commits produits,
l'hygiène du diff, la validité technique et la présence de la branche dans
Gitea.

## 12. Première Publication Dans Un Nouveau Dépôt Gitea

### 12.1 Organisation Des Dépôts Distants

Lorsqu'un nouveau dépôt Gitea doit remplacer l'ancien dépôt interne sans perdre
la référence historique ni le lien avec Malcolm officiel, la configuration est
réalisée ainsi :

```bash
git remote rename origin legacy
git remote add origin git@gitea.tcric.hq:vmbaye/Oculox_V2.git
git remote -v
```

Cette organisation permet d'utiliser :

- `origin` pour les développements Oculox V2 ;
- `upstream` pour suivre les versions officielles Malcolm ;
- `legacy` pour consulter l'ancien dépôt interne.

La branche validée est ensuite publiée :

```bash
git switch main
git push -u origin main
```

L'option `-u` associe la branche locale `main` à `origin/main`. Après cette
première publication, les commandes courantes deviennent simplement :

```bash
git pull --ff-only
git push
```

`git pull --ff-only` refuse les fusions implicites. Cette protection évite de
créer un commit de fusion accidentel lors d'une simple synchronisation.

### 12.2 Vérification De L'Égalité Locale Et Distante

```bash
git status --short --branch
git rev-parse main
git rev-parse origin/main
git rev-list --left-right --count main...origin/main
```

Le contrôle final effectué après la première publication a retourné :

```text
main...origin/main
LOCAL   e662ff6196fd6af5383903ec860218d71880e9c9
TRACKED e662ff6196fd6af5383903ec860218d71880e9c9
0  0
```

Les deux identifiants identiques prouvent que la branche locale et sa référence
distante pointent sur le même commit. Les deux zéros signifient qu'aucune des
branches n'est en avance sur l'autre.

### 12.3 Résolution Du Refus HTTP 413

Le premier essai par HTTPS a été refusé avec `HTTP 413`. Cette erreur signifie
que le reverse proxy placé devant Gitea a rejeté le paquet Git HTTP, dont la
taille compressée était d'environ 258 Mio. Elle ne correspond ni à une erreur
du code ni à un problème d'identification.

La publication par SSH évite la limite de taille du corps HTTP :

```bash
cat ~/.ssh/id_ed25519.pub
git remote set-url origin git@gitea.tcric.hq:vmbaye/Oculox_V2.git
ssh -T git@gitea.tcric.hq
git push -u origin main
```

La clé publique affichée par la première commande doit être enregistrée dans
les paramètres SSH du compte Gitea. Une clé privée ou un jeton d'accès ne doit
jamais être copié dans le dépôt, la documentation, une URL Git ou un message.

### 12.4 Résultat De Livraison

La première publication SSH a transféré les 64 575 objets du dépôt, résolu les
48 398 deltas et créé la branche distante `main`. La branche locale suit
désormais `origin/main`. La phase 11 est donc techniquement terminée lorsque le
présent commit documentaire est lui aussi publié avec `git push`.

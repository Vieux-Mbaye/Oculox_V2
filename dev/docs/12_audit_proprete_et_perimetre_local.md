# Audit De Propreté Et Périmètre Local Oculox

## 1. Objet

Cette revue vérifie que l’environnement Oculox local peut servir de dépôt de
développement maîtrisé. Elle porte sur le code, l’orchestration, les fichiers
sensibles, les scripts, les données générées et la reproductibilité.

La machine locale n’est pas l’environnement de qualification de capacité. Les
tests qui y sont réalisés démontrent le fonctionnement des modifications et
permettent des comparaisons exploratoires. Les performances contractuelles,
les limites de débit et le dimensionnement devront être mesurés sur un serveur
représentatif de la cible.

## 2. Référence Logicielle

Le dépôt repose sur Malcolm `v26.07.1`. La branche de développement contient
le tag amont correspondant et conserve deux remotes distincts :

- `upstream` pour le projet officiel Malcolm ;
- `origin` pour le dépôt interne Oculox.

Les adaptations de résilience restent sous `dev/`. Les fichiers officiels à la
racine servent de base et les différences locales sont appliquées par des
surcharges Docker Compose explicites.

## 3. Contrôles De Code

Les contrôles suivants sont automatisés par
`dev/scripts/audit-dev-repository.sh` :

| Contrôle | Finalité |
|---|---|
| `git diff --check` | détecter les espaces incorrects et fins de ligne invalides |
| `bash -n` | vérifier la syntaxe de tous les scripts Bash de développement |
| `python3 -m py_compile` | vérifier la syntaxe des scripts Python sans les exécuter |
| Chargement PyYAML | vérifier tous les fichiers YAML de développement |
| Docker Compose `config --quiet` | valider les configurations à un et deux Logstash |
| Recherche de clés privées | empêcher leur ajout dans les sources livrables, suivies ou non |
| Contrôle `.gitignore` | exclure PKI, PCAP, résultats et métriques générés |
| Permissions | imposer `600` aux `.env` et clés privées locales |

Le collecteur de métriques impose désormais un délai maximal de 30 secondes à
chaque commande externe. Une API Docker ou un conteneur bloqué ne peut donc
plus suspendre indéfiniment une campagne de supervision.

## 4. Hygiène Des Entrées Et Des Scripts

Les identifiants de campagne sont limités aux lettres, chiffres, points,
tirets et underscores. Cette validation empêche un identifiant de sortir des
répertoires prévus ou de créer un chemin ambigu.

Les paramètres `EVENT_COUNT` et `FILES` du comparatif local doivent être des
entiers strictement positifs. Le nombre d’événements doit être divisible par
le nombre de fichiers, ce qui garantit des lots de taille identique.

Les événements synthétiques utilisent l’heure courante. Aucun décalage vers
une date future n’est appliqué, afin d’éviter la création d’index temporels
anormaux dans OpenSearch.

## 5. Orchestration Locale

Deux compositions sont validées :

1. le mode simple avec un Logstash ;
2. le mode double avec deux Logstash et répartition Filebeat.

Le mode `stop` charge la surcharge locale avant d’exécuter `docker compose
down`. Il arrête donc également `logstash-2`, que le Compose officiel ne
connaît pas, sans supprimer les volumes nommés.

Le mode `dual-core` prépare les configurations et la PKI avant le démarrage.
Un clone neuf ne dépend donc pas de fichiers générés lors d’une ancienne
session.

## 6. Protection Des Données Sensibles

Les vrais fichiers `config/*.env` sont ignorés par Git et protégés avec la
permission `600`. Les clés privées générées sont également en `600`.

Les éléments suivants restent locaux et ne sont pas versionnés :

- `dev/generated/`, notamment la PKI de développement ;
- `dev/tests/results/` ;
- `dev/monitoring/data/` ;
- les captures `*.pcap` et `*.pcapng` ;
- les archives et exports de benchmark.

La PKI générée est réservée au laboratoire local. En environnement serveur,
les certificats doivent provenir de la PKI de l’organisation, la clé de
l’autorité ne doit pas être déployée avec les services et les secrets doivent
être gérés hors du dépôt.

## 7. État Des Validations Fonctionnelles

Les essais locaux ont démontré :

- la génération reproductible des configurations Filebeat ;
- le TLS mutuel entre Filebeat et les deux Logstash ;
- la répartition des lots entre les deux destinations ;
- le basculement lors de la perte de l’une des instances ;
- la reprise à partir des files persistantes Logstash ;
- la reprise depuis le registre Filebeat ;
- la conservation des données après un redémarrage Compose sans suppression
  des volumes ;
- l’indexation du nombre exact d’événements des jeux contrôlés.

Ces résultats qualifient les mécanismes. Ils ne prouvent pas la haute
disponibilité d’un système dont les deux Logstash et OpenSearch résident sur
le même hôte.

## 8. Éléments À Qualifier Sur Le Serveur Cible

Avant toute conclusion de capacité ou de mise en production, il faudra :

1. définir les ressources CPU, RAM, stockage et réseau dédiées ;
2. séparer les instances sur plusieurs hôtes ou domaines de panne ;
3. remplacer la PKI locale par des certificats d’organisation ;
4. intégrer la gestion des secrets et le contrôle d’accès ;
5. définir la rétention OpenSearch, PCAP, Zeek et Suricata ;
6. installer une supervision externe et des alertes persistantes ;
7. exécuter des campagnes répétées avec trafic représentatif, ordre alterné,
   période de stabilisation et critères d’arrêt ;
8. tester l’endurance, les pertes, les files, les redémarrages et le retour à
   la normale ;
9. documenter le retour arrière et les sauvegardes avant déploiement.

## 9. Commande De Contrôle

Depuis la racine du dépôt :

```bash
./dev/scripts/audit-dev-repository.sh
```

Un résultat réussi signifie que le dépôt passe les contrôles statiques définis
ci-dessus. Il ne signifie pas que la plateforme est dimensionnée pour une
charge de production.

## 10. État De Livraison Git

Le code de développement est structuré et contrôlable, mais la livraison Git
reste une opération distincte. Avant de pousser le lot, il faut relire la
liste exacte des fichiers, écarter les changements runtime étrangers au lot,
puis créer un commit ciblé. Aucun résultat volumineux, secret ou fichier
généré ne doit apparaître dans ce commit.

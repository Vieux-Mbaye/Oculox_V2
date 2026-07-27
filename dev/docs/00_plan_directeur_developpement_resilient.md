# Plan Directeur De Développement D'une Architecture Oculox Résiliente

## 1. Objectif Général

L'objectif est de construire progressivement un environnement local Oculox/Malcolm maîtrisé, reproductible et versionné, intégrant :

- la capture locale du trafic ;
- les analyseurs Zeek, Suricata et Arkime ;
- Filebeat comme agent de lecture et de transport des logs ;
- deux instances Logstash pour répartir le traitement ;
- une file persistante distincte pour chaque Logstash ;
- OpenSearch comme stockage indexé ;
- une supervision complète de la chaîne ;
- des tests fonctionnels, de résilience et de performance.

L'architecture cible initiale est la suivante :

```text
Capture locale
    |
    +--> Zeek ------> logs Zeek ------+
    |                                 |
    +--> Suricata --> eve.json -------+--> Filebeat
                                               |
                                        loadbalance: true
                                          /          \
                                         v            v
                                   logstash       logstash-2
                                      | PQ 1         | PQ 2
                                      +-------+-------+
                                              |
                                              v
                                          OpenSearch
                                              |
                                   Dashboards / Arkime
```

Le premier objectif porte sur la résilience de la couche Logstash. La haute disponibilité complète d'OpenSearch sera étudiée séparément, car deux Logstash ne rendent pas automatiquement toute la plateforme hautement disponible.

---

# Phase 1 - Comprendre L'existant

## But

Comprendre exactement ce que fait Malcolm avant de modifier sa configuration.

## 1. Identifier Les Fichiers D'orchestration

Étudier :

- `docker-compose.yml` ;
- `docker-compose-dev.yml` ;
- les éventuels fichiers `docker-compose.override.yml` ;
- les fichiers `config/*.env` ;
- les modèles `config/*.env.example`.

## 2. Comprendre La Structure D'un Service Docker Compose

Étudier précisément :

- `image` ;
- `build` ;
- `profiles` ;
- `env_file` ;
- `volumes` ;
- `networks` ;
- `depends_on` ;
- `healthcheck` ;
- `ports` ;
- `ulimits`.

## 3. Étudier Le Chemin Des Données

```text
Capture locale
→ Zeek / Suricata / Arkime
→ fichiers de logs
→ Filebeat
→ Logstash
→ OpenSearch
→ Dashboards / Arkime
```

## 4. Étudier Les Mécanismes D'ingestion Et De Persistance

Étudier :

- la configuration Filebeat ;
- `LOGSTASH_HOST` ;
- l'entrée Beats de Logstash sur TCP `5044` ;
- les pipelines Logstash ;
- les workers et les lots ;
- la file persistante Logstash ;
- les certificats TLS ;
- les volumes persistants.

## Livrables

Les documents sont disponibles dans `dev/phase1/` :

1. `01_identifier_fichiers_orchestration.md` ;
2. `02_structure_service_docker_compose.md` ;
3. `03_chemin_des_donnees.md` ;
4. `04_filebeat_logstash_tls_persistance.md`.

## État

**Terminée.**

---

# Phase 2 - Préparer Le Dépôt De Développement

## But

Disposer d'un environnement propre, reproductible et versionné.

## Organisation

```text
dev/
├── phase1/
├── compose/
├── config/
├── scripts/
├── tests/
├── monitoring/
└── docs/
```

## Principes

- conserver les fichiers Malcolm d'origine ;
- placer les changements locaux dans des fichiers dédiés ;
- ne jamais versionner les secrets ;
- utiliser une surcharge Compose explicite ;
- valider la configuration fusionnée avant tout démarrage.

## Fichiers Initiaux

- `dev/compose/docker-compose.dev.yml` ;
- `dev/config/dev.env.example` ;
- `dev/scripts/validate-compose.sh` ;
- `dev/.gitignore` ;
- fichiers `README.md` expliquant le rôle de chaque répertoire.

## Validation

```bash
./dev/scripts/validate-compose.sh
```

La commande fusionne le Compose d'origine et la surcharge de développement, puis vérifie la syntaxe sans démarrer de conteneur.

## État

**Terminée.** La structure et la validation Compose sont en place. Les fichiers sont prêts à être versionnés ; le commit Git sera réalisé avec le lot documentaire validé.

---

# Phase 3 - Définir L'architecture Cible

## But

Décider précisément ce qui sera construit avant de modifier l'orchestration.

## Architecture Retenue

```text
Filebeat
   |
   +--> logstash (instance logique 1)
   |
   +--> logstash-2
            |
            v
        OpenSearch
```

## Décisions À Formaliser

1. noms des deux services Logstash ;
2. ports et réseau Docker ;
3. ressources CPU et mémoire ;
4. heap JVM de chaque instance ;
5. nombre de workers et taille des lots ;
6. volumes de queue séparés ;
7. stratégie de certificats TLS ;
8. stratégie Filebeat de répartition ;
9. contrôles de santé ;
10. comportement attendu en cas de panne.

## Livrable

La décision d'architecture est documentée dans :

```text
dev/docs/02_architecture_cible_deux_logstash.md
```

Elle précise :

- le besoin ;
- l'architecture choisie ;
- les alternatives étudiées ;
- les risques ;
- les critères de validation.

## Point Important

Deux Logstash améliorent la capacité de traitement et la tolérance à la panne de cette couche. OpenSearch reste initialement une destination unique et constitue encore un point de défaillance potentiel.

## État

**Terminée.** La conception est validée sans démarrage de nouveaux conteneurs. Le disque local dispose désormais d'environ 213 Gio libres et ne constitue plus un blocage immédiat.

---

# Phase 4 - Établir Une Baseline À Un Logstash

## But

Mesurer le comportement de la configuration d'origine avant de la modifier.

## Contrôles

- santé des conteneurs ;
- configuration effective de Filebeat ;
- pipelines Logstash actifs ;
- utilisation CPU et mémoire ;
- utilisation de la heap JVM ;
- workers et backpressure ;
- taille des files ;
- débit d'entrée et de sortie ;
- état OpenSearch ;
- nombre d'événements indexés.

## Test Fonctionnel

Injecter un jeu de données connu et vérifier :

```text
événements produits
→ événements lus par Filebeat
→ événements reçus par Logstash
→ événements indexés dans OpenSearch
```

## Livrable

Produire un rapport de référence permettant de comparer objectivement les architectures à un et deux Logstash.

---

# Phase 5 - Créer Deux Instances Logstash

## But

Dupliquer proprement la couche de traitement Logstash.

## Services Prévus

```text
logstash
logstash-2
```

Les deux instances utiliseront :

- la même image ;
- les mêmes pipelines ;
- les mêmes règles de parsing ;
- les mêmes règles d'enrichissement ;
- la même destination OpenSearch.

Chaque instance possédera néanmoins :

- son propre nom ;
- son propre contrôle de santé ;
- ses propres ressources ;
- son propre volume de file persistante ;
- son propre état d'exécution.

## Règle Critique

Les deux instances ne doivent jamais partager le même `path.queue` :

```text
logstash   → volume logstash-pq-1
logstash-2 → volume logstash-pq-2
```

Une file persistante Logstash n'est pas un stockage partagé destiné à plusieurs processus.

---

# Phase 6 - Configurer Filebeat En Répartition De Charge

## But

Permettre à Filebeat d'utiliser simultanément les deux instances Logstash.

## Configuration Cible

La configuration sera proche de :

```yaml
output.logstash:
  hosts:
    - "logstash:5044"
    - "logstash-2:5044"
  loadbalance: true
```

## Signification

Avec `loadbalance: true`, Filebeat maintient des connexions vers les deux destinations et répartit les événements.

Filebeat effectue ici une répartition côté client. Il ne devient pas un équipement de load balancing réseau indépendant.

## Contrôles

- les deux connexions TLS sont établies ;
- les deux Logstash reçoivent des événements ;
- la répartition est mesurable ;
- Filebeat réessaie lorsqu'une instance tombe ;
- la reprise ne dépend pas d'une adresse IP temporaire de conteneur.

---

# Phase 7 - Sécuriser Le Transport Et La Persistance

## But

Éviter que la distribution réduise la sécurité ou la capacité de reprise.

## TLS

Vérifier pour chaque instance Logstash :

- le certificat serveur ;
- la clé privée ;
- l'autorité de certification ;
- les noms présents dans le certificat ;
- la validation stricte côté Filebeat ;
- l'authentification du client ;
- les dates d'expiration ;
- la procédure de rotation.

## Files Persistantes

Activer explicitement une file sur les pipelines retenus.

Pour chaque instance :

```text
queue.type: persisted
queue.max_bytes: valeur dimensionnée
path.queue: chemin unique
```

## Registre Filebeat

Conserver un registre persistant afin que Filebeat sache où reprendre dans chaque fichier.

## Test De Reprise

1. envoyer des événements ;
2. arrêter `logstash` ;
3. vérifier que `logstash-2` continue ;
4. redémarrer `logstash` ;
5. vérifier sa reconnexion ;
6. contrôler les pertes et les doublons.

---

# Phase 8 - Mettre En Place La Supervision

## But

Observer la répartition des événements et identifier précisément les points de saturation.

## Métriques Filebeat

- événements lus ;
- événements publiés ;
- erreurs de publication ;
- connexions actives ;
- retries ;
- files internes ;
- progression des registres.

## Métriques Logstash

Pour chaque instance et chaque pipeline :

- `events.in` ;
- `events.out` ;
- `worker_utilization` ;
- `queue_backpressure` ;
- durée de traitement ;
- CPU ;
- mémoire ;
- heap JVM ;
- occupation de la file persistante.

## Métriques OpenSearch

- santé du cluster ;
- débit d'indexation ;
- latence ;
- CPU ;
- heap JVM ;
- espace disque ;
- refus d'écriture ;
- tâches en attente.

## Livrables

- requêtes Prometheus ;
- tableaux de bord ;
- seuils d'alerte ;
- scripts de collecte ;
- procédure de diagnostic.

---

# Phase 9 - Réaliser Les Tests Fonctionnels Et De Résilience

## But

Prouver que la distribution fonctionne correctement et que la chaîne reprend après une panne.

## Test 1 - Fonctionnement Normal

Les deux Logstash doivent recevoir et traiter des événements.

## Test 2 - Arrêt De `logstash`

`logstash-2` doit continuer à recevoir des événements.

## Test 3 - Arrêt De `logstash-2`

`logstash` doit continuer à recevoir des événements.

## Test 4 - Retour D'une Instance

L'instance redémarrée doit revenir dans la répartition sans intervention manuelle sur Filebeat.

## Test 5 - Ralentissement OpenSearch

Observer :

- les queues ;
- la backpressure ;
- les retries ;
- le comportement des fichiers sources ;
- la reprise après stabilisation.

## Test 6 - Redémarrage De Filebeat

Vérifier la reprise à partir du registre persistant.

## Test 7 - Redémarrage Complet

Vérifier :

- la conservation des files persistantes ;
- la conservation des registres Filebeat ;
- la conservation des index ;
- la reconnexion TLS ;
- le retour à un état healthy.

## Critères Principaux

- aucune perte inexpliquée ;
- aucune file persistante partagée ;
- aucun secret exposé ;
- services redevenus healthy ;
- OpenSearch green ;
- résultats reproductibles.

---

# Phase 10 - Réaliser Le Benchmark Comparatif

## But

Mesurer le gain réel obtenu avec deux Logstash.

## Comparaison

```text
Configuration A : un Logstash
Configuration B : deux Logstash
```

## Mesures

- événements par seconde ;
- débit réseau ;
- CPU moyen et maximal ;
- mémoire ;
- heap JVM ;
- backpressure ;
- durée de traitement ;
- croissance des files ;
- latence d'indexation ;
- temps de retour à la normale ;
- erreurs, doublons et pertes.

## Paliers

```text
faible charge
→ charge moyenne
→ charge élevée
→ seuil de saturation
→ reprise
```

Le même PCAP, la même méthode d'injection et les mêmes critères doivent être utilisés pour les deux configurations.

## Résultat Attendu

Le rapport devra indiquer si le deuxième Logstash :

- augmente réellement la capacité ;
- réduit la backpressure ;
- améliore la reprise ;
- déplace le point de saturation vers OpenSearch ;
- apporte une résilience mesurable.

---

# Phase 11 - Documenter Et Livrer Dans Git

## But

Produire un projet compréhensible, vérifiable et maintenable.

## Livrables Finaux

- architecture cible ;
- surcharge Docker Compose ;
- modèles de configuration ;
- scripts de démarrage ;
- scripts de validation ;
- tests fonctionnels ;
- tests de résilience ;
- tableaux de bord ;
- rapport comparatif ;
- procédure de retour arrière ;
- guide d'exploitation ;
- limites connues.

## Stratégie Git

Les commits devront rester ciblés :

```text
Phase 3 : documenter l'architecture à deux Logstash
Phase 5 : ajouter les deux services Logstash
Phase 6 : activer la répartition Filebeat
Phase 7 : ajouter les files persistantes séparées
Phase 8 : ajouter la supervision
Phase 9 : ajouter les tests de résilience
```

Chaque commit devra être compréhensible et réversible indépendamment des étapes suivantes.

---

# État D'avancement

| Phase | État |
|---|---|
| Phase 1 - Comprendre l'existant | Terminée |
| Phase 2 - Préparer le dépôt | Terminée, commit Git à réaliser avec le lot validé |
| Phase 3 - Définir l'architecture cible | Terminée |
| Phase 4 - Établir la baseline | Prochaine étape |
| Phase 5 - Créer deux Logstash | À faire |
| Phase 6 - Configurer la répartition Filebeat | À faire |
| Phase 7 - Sécuriser transport et persistance | À faire |
| Phase 8 - Mettre en place la supervision | À faire |
| Phase 9 - Tester la résilience | À faire |
| Phase 10 - Réaliser le benchmark comparatif | À faire |
| Phase 11 - Documenter et livrer | À faire |

La prochaine étape est la **Phase 4 : établir une baseline mesurée avec le Logstash unique actuel**. Aucun deuxième Logstash ne doit être déployé avant cette mesure de référence.

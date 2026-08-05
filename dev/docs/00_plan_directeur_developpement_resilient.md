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

# Phase 6 - Sécuriser Et Répartir L'ingestion

## But

Permettre à Filebeat d'utiliser simultanément les deux instances Logstash,
protéger le transport par TLS mutuel et rendre les réémissions idempotentes
dans OpenSearch.

## Configuration Cible

La configuration sera proche de :

```yaml
output.logstash:
  hosts:
    - "logstash:5044"
    - "logstash-2:5044"
  loadbalance: true
  ssl.enabled: true
  ssl.certificate_authorities: ["/certs/ca.crt"]
  ssl.certificate: "/certs/client.crt"
  ssl.key: "/certs/client.key"
  ssl.verification_mode: full
```

## Signification

Avec `loadbalance: true`, Filebeat maintient des connexions vers les deux destinations et répartit les événements.

Filebeat effectue ici une répartition côté client. Il ne devient pas un équipement de load balancing réseau indépendant.

Le mode `full` oblige Filebeat à vérifier la chaîne de confiance et le nom DNS
de chaque serveur Logstash. De leur côté, les deux Logstash exigent un
certificat client signé par l'autorité de confiance. Le transport est donc
authentifié dans les deux sens.

Filebeat garantit une livraison au moins une fois : une réémission peut se
produire après une interruption. Malcolm calcule cependant un `event.hash`
stable et l'utilise comme identifiant OpenSearch. La réémission du même
événement remplace le document existant au lieu d'en créer un second.

## Contrôles

- les deux connexions TLS sont établies ;
- un client sans certificat est refusé ;
- les deux Logstash reçoivent des événements ;
- la répartition est mesurable ;
- Filebeat réessaie lorsqu'une instance tombe ;
- une réémission identique ne crée pas de document supplémentaire ;
- la reprise ne dépend pas d'une adresse IP temporaire de conteneur.

## État

**Terminée.** La conception, l'implémentation et les essais sont documentés
dans `dev/docs/07_phase6_repartition_tls_idempotence.md`.

---

# Phase 7 - Industrialiser La Persistance Et La Gestion Des Certificats

## But

Transformer les mécanismes validés en phase 6 en procédures d'exploitation
durables.

## Cycle De Vie Des Certificats

Définir pour chaque environnement :

- les dates d'expiration ;
- la procédure de rotation sans interruption ;
- le stockage protégé de la clé d'autorité ;
- la révocation d'un certificat compromis ;
- l'intégration à la PKI de l'organisation.

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

## Tests Complémentaires De Persistance

1. interrompre OpenSearch pendant une ingestion contrôlée ;
2. mesurer la croissance des files persistantes Logstash ;
3. redémarrer Filebeat et vérifier la reprise depuis son registre ;
4. redémarrer simultanément les deux Logstash ;
5. vérifier les événements avant et après reprise ;
6. dimensionner les files selon le débit et la durée d'indisponibilité visés.

## État

**Terminée.** Les files ont été activées sur les sept pipelines des deux
Logstash. La reprise a été validée après indisponibilité OpenSearch,
redémarrage simultané des Logstash et redémarrage Filebeat. Les résultats, le
dimensionnement et le cycle de vie TLS sont documentés dans
`dev/docs/08_phase7_persistance_reprise_certificats.md`.

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

## État

**Terminée.** Les collecteurs, seuils, modes complet/léger, résultats de
validation et procédures sont documentés dans
`dev/docs/09_phase8_supervision.md`.

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

## État

**Terminée.** Le basculement dans les deux sens, la réintégration, les files
persistantes, le registre Filebeat, le redémarrage complet et TLS ont été
validés. Voir `dev/docs/10_phase9_tests_resilience.md`.

---

# Phase 10 - Réaliser La Comparaison Locale

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

## État

**Terminée dans le périmètre de développement local.** Les deux modes ont
indexé intégralement les paliers de 10 000,
25 000 et 50 000 documents. La répartition est validée ; un gain de 15,09 %
est observé au palier moyen, mais il n'est pas stable aux autres paliers en
raison de la pression mémoire de l'hôte partagé. Voir
`dev/docs/11_phase10_benchmark_comparatif.md`.

Ces valeurs ne constituent pas un dimensionnement de production. La campagne
de capacité devra être répétée sur le serveur cible.

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
| Phase 4 - Établir la baseline | Terminée |
| Phase 5 - Créer deux Logstash | Terminée et validée en mode local réduit |
| Phase 6 - Configurer la répartition Filebeat | Terminée : répartition, mTLS et idempotence validés |
| Phase 7 - Sécuriser transport et persistance | Terminée : persistance et reprise validées |
| Phase 8 - Mettre en place la supervision | Terminée et validée sous charge |
| Phase 9 - Tester la résilience | Terminée : basculement et reprise validés |
| Phase 10 - Réaliser la comparaison locale | Terminée : comportement local documenté, capacité serveur non qualifiée |
| Phase 11 - Documenter et livrer | Revue technique terminée, commit ciblé à préparer |

La prochaine étape est la **préparation du commit de livraison**, puis la
**qualification sur un serveur cible représentatif**. La mise en cluster
d'OpenSearch ne doit débuter qu'après définition d'un dimensionnement
multi-hôte et de critères de validation de production.

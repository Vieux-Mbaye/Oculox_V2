# Procédure De Démarrage Et De Validation Avec Preuves

## 1. Objet

Cette procédure permet de redémarrer l'environnement local résilient Oculox, de vérifier sa configuration, de rejouer les tests de résilience et de conserver des preuves lisibles.

Elle valide le chemin suivant :

```text
Fichier de logs de test
        |
        v
Filebeat avec équilibrage de charge et TLS
        |
        +---------------------+
        |                     |
        v                     v
Logstash 1              Logstash 2
files persistantes      files persistantes
        |                     |
        +----------+----------+
                   |
                   v
              OpenSearch
```

Le mode utilisé est `dual-ingest`. Il ne démarre que quatre services :

- `oculox-filebeat-1` ;
- `oculox-logstash-1` ;
- `oculox-logstash-2-1` ;
- `oculox-opensearch-1`.

Ce mode est préférable sur le poste local, car la plateforme Malcolm complète consomme beaucoup plus de mémoire et n'est pas nécessaire pour vérifier la résilience de la chaîne d'ingestion.

> **Attention :** le test de phase 9 arrête volontairement Logstash et OpenSearch pendant quelques secondes. Il doit être exécuté uniquement sur l'environnement local de développement, sans utilisateur ni ingestion utile en cours.

> **Interdiction :** ne jamais utiliser `docker compose down -v`. L'option `-v` supprimerait les volumes qui conservent OpenSearch, les registres Filebeat et les files persistantes Logstash.

## 2. Organisation Des Terminaux

Utiliser idéalement trois terminaux ouverts dans le même répertoire :

| Terminal | Usage |
|---|---|
| Terminal 1 | Démarrage, contrôles et lancement des tests |
| Terminal 2 | Surveillance des conteneurs et files persistantes |
| Terminal 3 | Surveillance de la RAM, du CPU et du disque |

Dans chaque terminal :

```bash
cd /home/kakashi_/ICSHUB/Oculox
```

Les variables shell, notamment `RUN_ID`, ne sont valables que dans le terminal où elles ont été définies.

## 3. Préparer Le Dossier De Preuves

Dans le terminal 1 :

```bash
RUN_ID="validation_resilience_$(date -u +%Y%m%d_%H%M%S)"
export RUN_ID
EVIDENCE_DIR="dev/tests/results/manual/${RUN_ID}"
export EVIDENCE_DIR
mkdir -p "$EVIDENCE_DIR/screenshots"
printf 'RUN_ID=%s\nEVIDENCE_DIR=%s\n' "$RUN_ID" "$EVIDENCE_DIR"
```

Exemple de valeur :

```text
RUN_ID=validation_resilience_20260729_101500
```

Conserver cette valeur. Elle identifie de manière unique la campagne et évite de mélanger les preuves de plusieurs exécutions.

### Preuve P01 — Identification De La Campagne

Faire une capture de la sortie précédente et l'enregistrer sous :

```text
P01_identification_campagne.png
```

## 4. Vérifications Avant Démarrage

### 4.1 Vérifier La Version Et L'état Du Dépôt

```bash
git log -1 --oneline
git status --short
```

La première commande identifie précisément la version du code testée. La seconde révèle les modifications locales. Une arborescence modifiée n'interdit pas le test, mais elle doit être signalée dans le compte rendu pour garantir sa reproductibilité.

Enregistrer également ces informations dans un fichier texte :

```bash
{
    date -u +"date_utc=%Y-%m-%dT%H:%M:%SZ"
    git log -1 --oneline
    git status --short
} | tee "$EVIDENCE_DIR/git-state.txt"
```

### Preuve P02 — Version Testée

```text
P02_version_et_etat_git.png
```

### 4.2 Vérifier Les Ressources De L'hôte

```bash
{
    printf '%s\n' '=== CPU ==='
    nproc
    lscpu | grep -E 'CPU\(s\)|Model name|Hypervisor'
    printf '%s\n' '=== RAM ==='
    free -h
    printf '%s\n' '=== DISQUE ==='
    df -h .
} | tee "$EVIDENCE_DIR/host-before.txt"
```

Les contrôles minimaux sont les suivants :

- au moins 16 Gio de mémoire disponible sont recommandés pour le mode double local ;
- le disque ne doit pas être proche de la saturation ;
- aucune charge CPU importante étrangère au test ne doit être active.

Si la RAM disponible est insuffisante, arrêter les applications lourdes avant de continuer. Ne pas lancer le mode `full` pour cette campagne.

### Preuve P03 — Ressources Initiales

```text
P03_ressources_initiales.png
```

### 4.3 Valider Le Code Et La Configuration Compose

```bash
./dev/scripts/audit-dev-repository.sh | tee "$EVIDENCE_DIR/audit-repository.txt"
./dev/scripts/validate-compose.sh | tee "$EVIDENCE_DIR/validation-compose.txt"
./dev/scripts/platform-mode.sh check | tee "$EVIDENCE_DIR/platform-check.txt"
```

Les trois commandes doivent terminer sans erreur. Elles contrôlent notamment la structure du dépôt, la syntaxe des surcharges Compose et la cohérence de la configuration finale.

### Preuve P04 — Validation Statique

Faire une capture montrant la fin des trois contrôles :

```text
P04_validation_statique.png
```

## 5. Démarrer Les Services Essentiels

### 5.1 Arrêter Une Éventuelle Ancienne Exécution

```bash
./dev/scripts/platform-mode.sh dual-stop
```

Cette commande arrête les conteneurs locaux, mais conserve les volumes. Elle remet l'orchestration dans un état connu avant le démarrage.

### 5.2 Démarrer La Chaîne Résiliente

```bash
./dev/scripts/platform-mode.sh dual-ingest | tee "$EVIDENCE_DIR/startup.txt"
```

Le script réalise trois opérations :

1. il génère la configuration Filebeat destinée aux deux Logstash ;
2. il prépare les certificats TLS locaux ;
3. il démarre OpenSearch, les deux Logstash et Filebeat.

Le premier démarrage peut prendre plusieurs minutes, surtout pour OpenSearch et Logstash.

### 5.3 Attendre L'état `healthy`

```bash
watch -n 3 'docker ps --filter name=oculox- --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"'
```

Quitter `watch` avec `Ctrl+C` lorsque les quatre conteneurs sont `healthy`.

Confirmer ensuite l'état dans un fichier :

```bash
docker ps --filter name=oculox- \
    --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}' \
    | tee "$EVIDENCE_DIR/containers-started.txt"
```

Les quatre noms attendus sont :

```text
oculox-opensearch-1
oculox-logstash-1
oculox-logstash-2-1
oculox-filebeat-1
```

### Preuve P05 — Services Essentiels

```text
P05_quatre_services_healthy.png
```

## 6. Vérifier La Configuration Active

### 6.1 Vérifier L'équilibrage Filebeat

```bash
sed -n '45,60p' dev/generated/filebeat/filebeat-tcp.yml \
    | tee "$EVIDENCE_DIR/filebeat-output.txt"
```

La sortie doit montrer :

```yaml
hosts:
  - logstash:5044
  - logstash-2:5044
loadbalance: true
ssl.verification_mode: full
```

`hosts` contient les deux destinations. `loadbalance: true` autorise Filebeat à distribuer les lots entre elles. `ssl.verification_mode: full` impose la vérification du certificat et du nom du serveur.

### Preuve P06 — Équilibrage Et TLS Filebeat

```text
P06_filebeat_deux_destinations_tls.png
```

### 6.2 Vérifier Les Certificats Beats/TLS

```bash
./dev/scripts/check-beats-certificates.sh 90 \
    | tee "$EVIDENCE_DIR/tls-check.txt"
```

Le contrôle doit réussir pour les deux Logstash. Il vérifie la chaîne de certification, les noms attendus et la durée de validité minimale.

### Preuve P07 — Certificats Valides

```text
P07_validation_certificats_tls.png
```

### 6.3 Vérifier OpenSearch

```bash
docker exec oculox-opensearch-1 curl \
    -K /var/local/curlrc/.opensearch.primary.curlrc \
    -sk https://localhost:9200/_cluster/health \
    | jq '{status,number_of_nodes,active_shards_percent_as_number,unassigned_shards}' \
    | tee "$EVIDENCE_DIR/opensearch-before.json"
```

Le résultat attendu est :

- `status: green` ;
- `number_of_nodes: 1` dans l'environnement local actuel ;
- `active_shards_percent_as_number: 100` ;
- `unassigned_shards: 0`.

Le doublement concerne ici Logstash, pas OpenSearch. OpenSearch reste donc un nœud unique dans cet environnement de développement.

### Preuve P08 — OpenSearch Sain

```text
P08_opensearch_green.png
```

### 6.4 Vérifier Les Files Persistantes

```bash
./dev/scripts/collect-phase7-state.sh \
    | tee "$EVIDENCE_DIR/persistent-queues-before.txt"
```

Pour chaque Logstash, les sept pipelines doivent afficher `type=persisted`. À l'état stable, `events=0` est normal : aucune donnée n'attend d'être traitée.

Les tailles configurées sont :

- 512 Mio pour `malcolm-input` ;
- 1 Gio pour `malcolm-output` ;
- 512 Mio pour chacun des cinq autres pipelines actifs.

Cela représente une capacité théorique de 4 Gio par Logstash. Les files des deux instances sont indépendantes ; elles ne constituent pas une copie l'une de l'autre.

### Preuve P09 — Files Persistantes Initiales

```text
P09_files_persistantes_vides.png
```

## 7. Surveiller Pendant Les Tests

### 7.1 Terminal 2 — Conteneurs Et Files

Dans le terminal 2 :

```bash
cd /home/kakashi_/ICSHUB/Oculox
watch -n 2 './dev/scripts/collect-phase7-state.sh'
```

Pendant l'arrêt volontaire d'OpenSearch, les valeurs `events` de certaines files doivent devenir supérieures à zéro. Après le redémarrage d'OpenSearch, elles doivent revenir à zéro lorsque les événements ont été rejoués.

### 7.2 Terminal 3 — Ressources Hôte Et Conteneurs

Dans le terminal 3 :

```bash
cd /home/kakashi_/ICSHUB/Oculox
watch -n 2 'free -h; printf "\n"; docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}\t{{.BlockIO}}" oculox-filebeat-1 oculox-logstash-1 oculox-logstash-2-1 oculox-opensearch-1'
```

Cette vue montre la pression exercée sur la machine. Elle ne remplace pas les résultats fonctionnels : un test n'est réussi que si le nombre d'événements attendu est retrouvé dans OpenSearch.

## 8. Test Obligatoire De Résilience

### 8.1 Ce Que Le Test Vérifie

Le script de phase 9 exécute automatiquement les scénarios suivants :

1. répartition normale entre les deux Logstash ;
2. ingestion avec Logstash 1 arrêté ;
3. ingestion avec Logstash 2 arrêté ;
4. retour automatique de l'instance rétablie ;
5. arrêt d'OpenSearch, mise en file sur disque, puis reprise ;
6. redémarrage de Filebeat pendant l'indisponibilité des deux Logstash ;
7. arrêt et redémarrage complet de la composition sans suppression des volumes ;
8. nouvelle validation TLS.

Les événements générés possèdent un marqueur unique dérivé du `RUN_ID`. Le script recherche ensuite ce marqueur dans OpenSearch et compare le nombre indexé au nombre attendu. Cette vérification de cardinalité permet de prouver la livraison de bout en bout.

### 8.2 Lancer Le Test

Dans le terminal 1 :

```bash
PHASE9_RUN_ID="phase9_preuves_$(date -u +%Y%m%d_%H%M%S)"
export PHASE9_RUN_ID
set -o pipefail
./dev/tests/run-phase9-resilience.sh "$PHASE9_RUN_ID" \
    2>&1 | tee "$EVIDENCE_DIR/phase9-console.log"
PHASE9_EXIT=${PIPESTATUS[0]}
printf 'phase9_exit_code=%s\n' "$PHASE9_EXIT" \
    | tee "$EVIDENCE_DIR/phase9-exit-code.txt"
```

Le test dure généralement entre 15 et 25 minutes. Ne pas l'interrompre. Laisser les terminaux 2 et 3 visibles pendant toute l'exécution.

### Preuve P10 — Mise En File Pendant La Panne OpenSearch

Lorsque le terminal 2 affiche des files avec `events` supérieur à zéro, enregistrer :

```text
P10_files_remplies_pendant_panne_opensearch.png
```

Cette preuve montre que les événements sont écrits sur disque pendant l'indisponibilité d'OpenSearch au lieu d'être immédiatement perdus.

### Preuve P11 — Ressources Pendant Le Test

Au moment où les CPU ou les mémoires sont les plus sollicités dans le terminal 3 :

```text
P11_ressources_pendant_resilience.png
```

### 8.3 Lire Les Résultats

```bash
PHASE9_DIR="dev/tests/results/phase9/${PHASE9_RUN_ID}"
export PHASE9_DIR
cat "$PHASE9_DIR/results.tsv"
cat "$PHASE9_DIR/metadata.txt"
cat "$PHASE9_DIR/tls-check.txt"
```

Pour une présentation plus lisible du tableau :

```bash
column -t -s $'\t' "$PHASE9_DIR/results.tsv"
```

### Preuve P12 — Résultats De Résilience

```text
P12_resultats_phase9_pass.png
```

La capture doit montrer toutes les lignes du tableau et `PASS` dans la colonne `status`.

### 8.4 Critères D'acceptation

La phase 9 est validée uniquement si :

- `PHASE9_RESULT=PASS` est présent dans `metadata.txt` ;
- toutes les lignes de `results.tsv` sont `PASS` ;
- `normal` retrouve exactement 6 000 événements ;
- les deux Logstash reçoivent chacun un nombre strictement positif d'événements ;
- chaque test avec une instance arrêtée retrouve exactement 3 000 événements ;
- la réintégration utilise de nouveau les deux instances ;
- la panne OpenSearch produit une file strictement supérieure à zéro ;
- les 5 000 événements de cette panne sont retrouvés après reprise ;
- les 4 000 événements survivent au redémarrage Filebeat ;
- les 2 000 événements survivent au redémarrage Compose ;
- la vérification TLS réussit.

Un code de sortie différent de zéro ou une ligne `FAIL` bloque la validation. Il ne faut pas transformer manuellement un échec en succès dans le rapport.

## 9. Contrôles Après Le Test De Résilience

### 9.1 Vérifier L'état Final Collecté Automatiquement

```bash
jq '{
  timestamp_utc,
  host,
  containers: (.containers | with_entries(.value = {
    status: .value.status,
    cpu: .value.resources.cpu_percent,
    memory: .value.resources.memory_usage
  })),
  opensearch: {
    available: .opensearch.available,
    status: .opensearch.health.status,
    nodes: .opensearch.health.number_of_nodes,
    unassigned_shards: .opensearch.health.unassigned_shards
  },
  alerts
}' "$PHASE9_DIR/final-state.json" \
    | tee "$EVIDENCE_DIR/phase9-final-summary.json"
```

### 9.2 Vérifier Que Les Files Se Sont Vidées

```bash
./dev/scripts/collect-phase7-state.sh \
    | tee "$EVIDENCE_DIR/persistent-queues-after.txt"
```

Après stabilisation, toutes les files doivent revenir à `events=0`. Une valeur non nulle juste à la fin du script peut signifier que la vidange est encore en cours. Attendre 30 secondes et contrôler de nouveau avant de conclure à un blocage.

### 9.3 Vérifier Une Dernière Fois OpenSearch

```bash
docker exec oculox-opensearch-1 curl \
    -K /var/local/curlrc/.opensearch.primary.curlrc \
    -sk https://localhost:9200/_cluster/health \
    | jq '{status,number_of_nodes,active_shards_percent_as_number,unassigned_shards}' \
    | tee "$EVIDENCE_DIR/opensearch-after.json"
```

### Preuve P13 — État Final Sain

Rassembler dans une même capture les conteneurs `healthy`, OpenSearch `green` et les files revenues à zéro :

```text
P13_etat_final_sain.png
```

## 10. Benchmark Comparatif Optionnel

Le benchmark de phase 10 compare un Logstash à deux Logstash. Il est distinct du test de résilience : il mesure un débit documentaire dans l'environnement local, mais ne constitue pas une certification de capacité de production.

Ce test est plus gourmand en RAM. Le lancer uniquement après la réussite de la phase 9 et lorsque la machine ne fait rien d'autre.

### 10.1 Contrôle Avant Benchmark

```bash
free -h
df -h .
./dev/scripts/platform-mode.sh status
```

### 10.2 Lancer Le Benchmark

La campagne de référence utilise 50 000 événements répartis dans 50 écritures distinctes :

```bash
PHASE10_RUN_ID="phase10_preuves_$(date -u +%Y%m%d_%H%M%S)"
export PHASE10_RUN_ID
set -o pipefail
EVENT_COUNT=50000 FILES=50 \
    ./dev/tests/run-phase10-benchmark.sh "$PHASE10_RUN_ID" \
    2>&1 | tee "$EVIDENCE_DIR/phase10-console.log"
PHASE10_EXIT=${PIPESTATUS[0]}
printf 'phase10_exit_code=%s\n' "$PHASE10_EXIT" \
    | tee "$EVIDENCE_DIR/phase10-exit-code.txt"
```

Le script démarre successivement :

1. OpenSearch, Filebeat et un seul Logstash ;
2. OpenSearch, Filebeat et deux Logstash.

Il mesure pour chaque mode le nombre d'événements indexés, la durée, le débit documentaire, le nombre d'événements reçu par chaque Logstash et l'état OpenSearch.

### 10.3 Lire Les Résultats

```bash
PHASE10_DIR="dev/tests/results/phase10/${PHASE10_RUN_ID}"
export PHASE10_DIR
column -t -s $'\t' "$PHASE10_DIR/comparison.tsv"
cat "$PHASE10_DIR/comparison-summary.txt"
cat "$PHASE10_DIR/metadata.txt"
```

Afficher les principales ressources observées dans chaque mode :

```bash
jq '{
  start_utc,
  end_utc,
  duration_seconds,
  host,
  containers,
  logstash,
  opensearch_statuses,
  alerts
}' "$PHASE10_DIR/single/monitoring-summary.json" \
    > "$EVIDENCE_DIR/phase10-single-summary.json"

jq '{
  start_utc,
  end_utc,
  duration_seconds,
  host,
  containers,
  logstash,
  opensearch_statuses,
  alerts
}' "$PHASE10_DIR/dual/monitoring-summary.json" \
    > "$EVIDENCE_DIR/phase10-dual-summary.json"
```

### Preuve P14 — Comparaison Simple Et Double

```text
P14_comparaison_phase10.png
```

### Preuve P15 — Ressources Du Mode Simple

```text
P15_ressources_mode_simple.png
```

### Preuve P16 — Ressources Du Mode Double

```text
P16_ressources_mode_double.png
```

### 10.4 Critères D'acceptation Du Benchmark

- `PHASE10_RESULT=PASS` doit être présent dans `metadata.txt` ;
- `events_indexed` doit être égal à `events_expected` dans les deux modes ;
- OpenSearch doit rester `green` ;
- le mode double doit montrer une activité strictement positive sur les deux Logstash ;
- aucune perte ne doit être masquée par une simple mesure de vitesse.

Le gain de débit peut être positif ou négatif sur un poste local. Deux Logstash améliorent la disponibilité, mais consomment davantage de RAM et peuvent entrer en concurrence pour le CPU, le disque et OpenSearch. La résilience et la performance sont deux propriétés différentes.

## 11. Arrêter Proprement L'environnement

Après la collecte de toutes les preuves :

```bash
./dev/scripts/platform-mode.sh dual-stop
free -h
docker ps --filter name=oculox-
```

La liste des conteneurs Oculox actifs doit être vide et la mémoire doit être libérée progressivement.

### Preuve P17 — Arrêt Propre

```text
P17_arret_propre.png
```

## 12. Inventaire Final Des Preuves

| Référence | Fichier recommandé | Contenu démontré |
|---|---|---|
| P01 | `P01_identification_campagne.png` | Identifiant unique du test |
| P02 | `P02_version_et_etat_git.png` | Version exacte du code |
| P03 | `P03_ressources_initiales.png` | CPU, RAM et disque avant test |
| P04 | `P04_validation_statique.png` | Dépôt et Compose valides |
| P05 | `P05_quatre_services_healthy.png` | Services essentiels démarrés |
| P06 | `P06_filebeat_deux_destinations_tls.png` | Équilibrage Filebeat et vérification TLS |
| P07 | `P07_validation_certificats_tls.png` | Certificats valides |
| P08 | `P08_opensearch_green.png` | OpenSearch sain avant test |
| P09 | `P09_files_persistantes_vides.png` | Sept files persistantes par instance |
| P10 | `P10_files_remplies_pendant_panne_opensearch.png` | Mise en attente sur disque |
| P11 | `P11_ressources_pendant_resilience.png` | Pression CPU et RAM pendant le test |
| P12 | `P12_resultats_phase9_pass.png` | Tous les scénarios de résilience réussis |
| P13 | `P13_etat_final_sain.png` | Reprise complète et files vidées |
| P14 | `P14_comparaison_phase10.png` | Résultats simple contre double |
| P15 | `P15_ressources_mode_simple.png` | Ressources avec un Logstash |
| P16 | `P16_ressources_mode_double.png` | Ressources avec deux Logstash |
| P17 | `P17_arret_propre.png` | Environnement arrêté sans suppression de volume |

Les fichiers texte et JSON se trouvent dans :

```text
dev/tests/results/manual/<RUN_ID>/
dev/tests/results/phase9/<PHASE9_RUN_ID>/
dev/tests/results/phase10/<PHASE10_RUN_ID>/
```

## 13. Conclusion À Utiliser Dans Le Compte Rendu

La configuration résiliente est validée si les deux instances Logstash reçoivent des événements en fonctionnement normal, si chacune peut assurer seule l'ingestion pendant l'arrêt de l'autre, si l'instance rétablie est automatiquement réintégrée, si les événements sont conservés dans les files persistantes pendant une indisponibilité d'OpenSearch, et si les quantités attendues sont intégralement retrouvées après reprise. Le résultat doit également confirmer le maintien du transport TLS, des registres Filebeat, des volumes OpenSearch et d'un état final sain.

Les résultats obtenus localement démontrent le fonctionnement du développement et sa capacité de reprise. Ils ne remplacent pas un benchmark sur un serveur dimensionné ni une validation d'un cluster OpenSearch de production.

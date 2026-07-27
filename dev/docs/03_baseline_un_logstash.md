# Phase 4 - Baseline De Référence Avec Un Logstash

## 1. Pourquoi Démarrer Le Projet Avant Cette Phase

Une baseline est une mesure du comportement réel d'un système. Un projet arrêté permet d'étudier ses fichiers, mais ne permet pas de mesurer la mémoire, le CPU, les pipelines, les files d'attente ou le traitement d'un PCAP. La plateforme d'origine a donc été démarrée avec **une seule instance Logstash**, avant toute modification d'architecture.

Cette phase ne cherche pas la capacité maximale. Elle crée un point de comparaison reproductible pour déterminer ensuite ce que deux instances Logstash améliorent réellement.

## 2. Environnement Mesuré

| Élément | Valeur |
|---|---:|
| Version des images Malcolm | `26.06.0` |
| CPU de l'hôte | 12 vCPU |
| RAM de l'hôte | 30 Gio |
| Espace disque disponible avant démarrage | 213 Gio |
| Profil Compose | `malcolm` |
| Services Compose | 27 |
| Instances Logstash | 1 |
| Heap JVM Logstash | 3 Gio |
| Workers Logstash par défaut | 3 |
| Heap JVM OpenSearch | 8 Gio |
| Authentification | Basic via Nginx HTTPS |
| Transport Filebeat vers Logstash | Beats avec TLS |

Le heap OpenSearch proposé automatiquement était de 15 Gio. Il a été ramené à 8 Gio dans `config/opensearch.env`, car d'autres conteneurs utilisent déjà cet hôte. Le heap est la zone mémoire réservée aux objets Java ; une valeur trop élevée aurait exposé l'hôte à une saturation mémoire.

## 3. Mise En Service Et Santé

Le démarrage a été réalisé avec le script officiel :

```bash
./scripts/start --quiet
```

Après stabilisation, les 27 services sont `healthy`. OpenSearch est `green`, avec 23 shards primaires actifs, aucun shard non assigné et aucune tâche en attente. L'URL HTTPS renvoie `401` sans identifiants, ce qui confirme que l'entrée Web est active et protégée.

Le service `filescan` était initialement `unhealthy`. Son serveur fonctionnait, mais la tâche de nettoyage quittait avec une erreur parce que les deux seuils de purge étaient désactivés. Le seuil local suivant a été appliqué :

```dotenv
FILESCAN_PRUNE_THRESHOLD_TOTAL_DISK_USAGE_PERCENT=90
```

Après la recréation du seul conteneur `filescan`, son état est devenu `healthy`. Ce seuil autorise un nettoyage lorsque l'occupation globale atteint 90 % ; il ne supprime rien pendant la baseline à 58 % d'occupation.

## 4. Fonctionnement Des Mesures

Les métriques proviennent des sources suivantes :

| Question | Source |
|---|---|
| Les conteneurs fonctionnent-ils ? | `docker compose ps` et healthchecks |
| Combien consomment-ils ? | `docker stats --no-stream` |
| Que font les pipelines Logstash ? | API Logstash `:9600/_node/stats/pipelines` |
| Quel est l'état de la JVM ? | API Logstash `:9600/_node/stats/jvm` |
| Une file persistante se remplit-elle ? | Répertoires de queue Logstash |
| OpenSearch accepte-t-il les écritures ? | API `_cluster/health` et `_count` |
| Le jeu d'essai est-il identique ? | `capinfos` et SHA-256 |

Le script [collect-single-logstash-baseline.sh](../scripts/collect-single-logstash-baseline.sh) automatise une photographie de ces mesures. Il ne modifie aucun service.

## 5. Baseline Au Repos

| Composant | CPU | Mémoire |
|---|---:|---:|
| Logstash | 5,17 % | 3,60 Gio |
| OpenSearch | 2,26 % | 9,12 Gio |
| Filebeat | 0,02 % | 106 Mio |

La JVM Logstash utilise environ 2,51 Gio sur un maximum de 3 Gio, soit 77 % du heap au moment de la mesure. Cette valeur est importante : le processus conserve déjà une part significative de sa mémoire Java au repos, même si cela ne signifie pas que l'hôte manque de RAM.

Les sept pipelines actifs sont :

- `malcolm-input` : reçoit les lots Beats/TLS ;
- `malcolm-zeek` : parse les événements Zeek ;
- `malcolm-suricata` : parse les événements Suricata ;
- `malcolm-filescan` : parse les résultats d'analyse de fichiers ;
- `malcolm-beats` : traite les autres événements Beats ;
- `malcolm-enrichment` : normalise et enrichit ;
- `malcolm-output` : écrit vers OpenSearch.

Au repos, leur backpressure est nul et les deux chemins de queue observés occupent `0` octet. Le backpressure indique que l'étape suivante ne consomme pas assez vite ; une valeur nulle signifie ici qu'aucun pipeline n'attend durablement.

## 6. Jeu De Données De Référence

La fixture retenue est `dev/tests/fixtures/phase4_baseline_input.pcap`.

| Propriété | Valeur |
|---|---:|
| Taille | 4 767 428 octets |
| Paquets | environ 56 000 |
| Durée représentée | 10 799,8 secondes |
| Début de capture | 14 avril 2026 à 17:13:04 UTC |
| Fin de capture | 14 avril 2026 à 20:13:04 UTC |
| SHA-256 | `f5a18a7e11e5488d782d990d10d77a799d8389a5c991c1a17af7803cef8cea55` |

L'empreinte SHA-256 identifie exactement le contenu du PCAP. La comparaison future à deux Logstash devra employer ce même fichier ; sinon la comparaison ne serait pas défendable.

## 7. Validation De Bout En Bout

Le fichier a été déposé dans `pcap/upload`. `pcap-monitor` l'a pris en charge automatiquement, puis l'a déplacé vers `pcap/processed` en 10 secondes.

```text
PCAP connu
→ orchestration pcap-monitor
→ analyse Zeek / Suricata / Arkime
→ collecte Filebeat
→ parsing et enrichissement Logstash
→ indexation OpenSearch
```

Le nombre de documents réseau est passé de `0` à `4 423`. Il est normal que ce total soit inférieur aux 56 000 paquets : les documents représentent des sessions, des transactions protocolaires, des alertes et des métadonnées, et non une copie de chaque paquet.

Les deltas principaux observés dans Logstash sont :

| Pipeline | Entrées supplémentaires | Sorties supplémentaires | Utilisation workers observée | Backpressure observée |
|---|---:|---:|---:|---:|
| `malcolm-input` | 36 534 | 36 283 | 22,04 % | 0,2763 |
| `malcolm-suricata` | 35 175 | 34 424 | 72,45 % | 0,0990 |
| `malcolm-zeek` | 1 162 | 639 | 9,97 % | 0,0575 |
| `malcolm-enrichment` | 35 149 | 34 393 | 76,63 % | 0,3441 |
| `malcolm-output` | 34 393 | 34 268 | 71,70 % | 0,0317 |

Ces nombres sont des compteurs internes entre pipelines. Ils ne doivent pas être additionnés pour obtenir un nombre de paquets : un même événement traverse plusieurs étapes et peut être filtré, enrichi, regroupé ou routé.

À la fin immédiate du traitement, Logstash atteignait 478,12 % CPU et OpenSearch 92,14 %. Dans la convention Docker, 100 % correspond approximativement à un cœur logique ; Logstash utilisait donc environ 4,8 cœurs pendant cette photographie. Aucun service n'est devenu `unhealthy`.

## 8. Retour À L'état Stable

Soixante secondes après le traitement :

| Composant | CPU | Mémoire |
|---|---:|---:|
| Logstash | 6,54 % | 3,72 Gio |
| OpenSearch | 1,15 % | 9,26 Gio |
| Filebeat | 0,09 % | 116 Mio |

Le backpressure est revenu à `0` sur les sept pipelines. Cela confirme que la charge était transitoire, que les files ont été absorbées et que la chaîne n'est pas restée bloquée après l'ingestion.

## 9. Conclusion De La Phase 4

La baseline à un Logstash est **validée** :

- la plateforme locale `26.06.0` démarre avec 27 services sains ;
- l'accès est protégé par HTTPS et authentification ;
- OpenSearch est `green` ;
- les sept pipelines Logstash sont actifs ;
- le PCAP de référence est traité automatiquement de bout en bout ;
- 4 423 documents sont indexés ;
- aucune file persistante ne reste occupée ;
- tous les pipelines reviennent à une contre-pression nulle après le test.

Cette référence montre aussi les points à comparer en phase 5 : CPU Logstash en traitement, heap JVM, pression sur `malcolm-enrichment`, vitesse de retour au repos et continuité de service lors de l'arrêt volontaire d'une instance Logstash.

## 10. Reproduction

Pour prendre une nouvelle photographie au repos :

```bash
cd /home/kakashi_/ICSHUB/Oculox
./dev/scripts/collect-single-logstash-baseline.sh
```

Les résultats sont écrits dans `dev/tests/results/phase4/`, répertoire volontairement ignoré par Git. Les secrets sont conservés dans `dev/config/baseline-access.env`, également ignoré et protégé par des permissions `600`.

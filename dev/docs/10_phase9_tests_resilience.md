# Phase 9 - Tests Fonctionnels Et De Résilience

## 1. Objectif

Cette phase vérifie que la répartition Filebeat fonctionne, qu'une instance
Logstash peut disparaître sans interrompre l'ingestion et que les données
persistantes permettent une reprise après incident.

Le test est automatisé par :

```text
dev/tests/run-phase9-resilience.sh
```

Il ne supprime aucun volume. Chaque événement porte un marqueur unique ; le
nombre produit est comparé au nombre retrouvé dans OpenSearch.

## 2. Conditions De Validation

- les deux destinations utilisent TLS mutuel ;
- les files Logstash sont distinctes et persistantes ;
- le registre Filebeat est persistant ;
- OpenSearch reste ou redevient `green` ;
- chaque test retrouve le nombre exact de documents attendu ;
- aucun redémarrage manuel de Filebeat n'est nécessaire au retour d'un
  Logstash.

## 3. Résultats

| Essai | Attendu | Résultat | Verdict |
|---|---:|---:|---|
| Fonctionnement normal | 6 000 | 6 000 | PASS |
| Répartition initiale | activité sur les deux | 3 200 / 2 800 | PASS |
| Arrêt de `logstash` | 3 000 | 3 000 via `logstash-2` | PASS |
| Arrêt de `logstash-2` | 3 000 | 3 000 via `logstash` | PASS |
| Retour d'une instance | 20 000 | 20 000 | PASS |
| Réintégration multilot | activité sur les deux | 5 600 / 14 400 | PASS |
| OpenSearch indisponible | file non vide | 4 425 événements en file | PASS |
| Reprise OpenSearch | 5 000 | 5 000 | PASS |
| Redémarrage Filebeat | 4 000 | 4 000 | PASS |
| Avant redémarrage complet | 2 000 | 2 000 | PASS |
| Après redémarrage complet | 2 000 | 2 000 | PASS |
| TLS après redémarrage | succès | succès | PASS |

## 4. Lecture Technique

### 4.1 Répartition

`loadbalance: true` ne garantit pas une division mathématique permanente à
50/50. Filebeat maintient des connexions vers les deux serveurs et distribue
les lots disponibles. La répartition observée à `3 200/2 800`, puis
`5 600/14 400`, prouve que les deux destinations reçoivent des événements.

Un premier essai basé sur un seul ajout de 6 000 événements a été reçu par une
seule connexion. Ce résultat ne démontrait pas un défaut : un seul lot peut
légitimement emprunter un seul canal. Le protocole a donc été corrigé en 40
ajouts de 500 événements espacés d'une seconde. Cette méthode a démontré la
réintégration automatique sans redémarrer Filebeat.

### 4.2 Perte D'une Instance

Lorsque `logstash` est arrêté, Filebeat poursuit vers `logstash-2`, et
inversement. Les deux séries de 3 000 événements ont été indexées intégralement.
La couche d'ingestion tolère donc la perte d'une instance.

### 4.3 Indisponibilité OpenSearch

Pendant l'arrêt d'OpenSearch, 4 425 événements ont été observés dans les files
persistantes. Après le retour du stockage, les 5 000 événements du test ont été
indexés. Les files jouent leur rôle de tampon disque ; elles ne remplacent pas
une rétention illimitée et doivent être dimensionnées selon le débit et la
durée de panne visés.

### 4.4 Registre Filebeat Et Redémarrage Complet

Le registre Filebeat conserve la position de lecture. Après son redémarrage,
les 4 000 événements en attente ont été repris. Le redémarrage Compose complet
a également conservé les 2 000 documents de référence, les files, le registre
et la chaîne TLS, car les volumes nommés n'ont pas été supprimés.

## 5. Reproduction

```bash
./dev/tests/run-phase9-resilience.sh phase9_$(date -u +%Y%m%d_%H%M%S)
```

Les preuves sont placées dans :

```text
dev/tests/results/phase9/<RUN_ID>/
```

Le fichier `results.tsv` constitue la matrice de décision. Les fichiers de
logs associés permettent de diagnostiquer une éventuelle étape en échec.

## 6. Limites

- la panne simultanée des deux Logstash interrompt la réception immédiate ;
  Filebeat reprend tant que les fichiers sources et son registre subsistent ;
- OpenSearch reste un nœud unique et demeure un point de défaillance ;
- les deux Logstash tournent sur le même hôte : une panne de cet hôte affecte
  les deux instances ;
- ce test démontre la résilience fonctionnelle, pas encore la haute
  disponibilité entre plusieurs machines.

## 7. Conclusion

La phase 9 est validée. La répartition, le basculement dans les deux sens, la
réintégration, la mise en file pendant une panne OpenSearch, la reprise du
registre Filebeat et la persistance après redémarrage complet sont démontrés
sans perte sur les jeux de données contrôlés.

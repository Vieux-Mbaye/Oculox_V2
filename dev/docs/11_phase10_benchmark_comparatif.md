# Phase 10 - Comparaison Locale Un Et Deux Logstash

> **Portée :** cette campagne qualifie le comportement du code sur la machine
> de développement. Elle ne constitue ni un benchmark de préproduction ni un
> engagement de capacité. Les vrais essais de charge seront rejoués sur un
> serveur représentatif de la cible.

## 1. Objectif

La comparaison mesure séparément :

1. la capacité d'une configuration à un Logstash ;
2. la capacité de la même chaîne avec deux Logstash ;
3. la répartition réelle des événements ;
4. l'effet du deuxième processus sur le CPU, la heap et la RAM de l'hôte.

Le but n'est pas de favoriser une architecture, mais de vérifier si la seconde
instance apporte un gain de débit sur la machine locale actuelle.

## 2. Protocole

Le script utilisé est :

```text
dev/tests/run-phase10-benchmark.sh
```

Pour chaque mode, il :

1. arrête complètement la pile sans supprimer les volumes ;
2. démarre soit un seul Logstash, soit les deux ;
3. vérifie les états `healthy` et OpenSearch `green` ;
4. génère 50 lots de 1 000 événements dans le même fichier Zeek ;
5. mesure le temps jusqu'à l'indexation exacte des 50 000 documents ;
6. mesure le passage dans chaque Logstash ;
7. collecte CPU, mémoire, heap, files et backpressure.

L'utilisation d'un même fichier `conn.log` est volontaire. Créer un nom de
fichier différent pour chaque lot ferait apparaître de nouveaux champs Zeek
dynamiques et mesurerait une explosion de mapping OpenSearch plutôt que la
capacité de l'architecture.

Les événements utilisent un décalage temporel contrôlé vers un index de test
récent, ce qui évite de mélanger la campagne avec un ancien index déjà pollué.

## 3. Résultats Finaux

Trois paliers ont été exécutés. Pour chacun, les deux modes ont indexé le
nombre exact de documents attendu et OpenSearch est resté `green`.

| Palier | Mode simple | Mode double | Écart du mode double |
|---:|---:|---:|---:|
| 10 000 | 417,28 docs/s | 131,32 docs/s | -68,53 % |
| 25 000 | 312,33 docs/s | 359,45 docs/s | +15,09 % |
| 50 000 | 594,10 docs/s | 518,94 docs/s | -12,65 % |

La répartition est effective à chaque palier : `3 200/6 800`,
`13 800/11 200`, puis `22 800/27 200`. Le palier moyen montre un gain de
15,09 %, mais les deux autres montrent une baisse. Deux JVM concurrentes sur
le même hôte n'apportent donc pas automatiquement deux fois plus de capacité.

Les débits ne sont pas proportionnels au nombre d'événements. Chaque palier
est une exécution unique et inclut les latences de détection du fichier, de
rafraîchissement des index et de montée en régime des JVM. Ces résultats sont
valides pour la campagne locale, mais ne constituent pas une courbe de
capacité statistique. Une qualification de production devra répéter chaque
palier et alterner l'ordre simple/double.

## 4. Ressources Mesurées

### 4.1 Mode Simple

| Indicateur | Maximum |
|---|---:|
| CPU `logstash` | 710,48 % |
| CPU OpenSearch | 346,67 % |
| Heap `logstash` | 85 % |
| RAM hôte, début / fin | 82,129 % / 84,255 % |
| Disque hôte, début / fin | 60,413 % / 60,442 % |

Le pipeline `malcolm-enrichment` atteint 74,63 % d'utilisation des workers et
`malcolm-output` 70,78 %. Les files restent très petites ; le traitement suit
donc la charge sans accumulation durable.

### 4.2 Mode Double

| Indicateur | `logstash` | `logstash-2` |
|---|---:|---:|
| CPU maximal | 491,83 % | 495,48 % |
| Heap maximale | 89 % | 87 % |
| Workers `malcolm-enrichment` | 53,23 % | 71,24 % |
| Workers `malcolm-zeek` | 55,18 % | 62,54 % |

OpenSearch atteint 423,51 % de CPU. La RAM hôte reste entre 92,484 % et
94,451 % pendant les mesures. La pression mémoire est donc la contrainte
principale de ce mode. Le second Logstash partage les mêmes 12 CPU et la même
RAM qu'OpenSearch et la première instance ; il améliore la disponibilité mais
augmente la compétition pour les ressources.

## 5. Décision Technique

| Question | Réponse |
|---|---|
| La répartition fonctionne-t-elle ? | Oui, 22 800 / 27 200 événements |
| Le mode double perd-il des documents ? | Non, 50 000 / 50 000 indexés |
| Apporte-t-il une tolérance à la panne ? | Oui, démontrée en phase 9 |
| Augmente-t-il le débit sur cet hôte ? | Non, baisse mesurée de 12,65 % |
| OpenSearch reste-t-il sain ? | Oui, état `green` |
| La machine est-elle correctement dimensionnée pour deux JVM ? | Non, RAM proche du seuil critique |

La configuration à deux Logstash est retenue pour la résilience. Elle montre
un gain ponctuel au palier moyen, mais ne doit pas être présentée comme une
augmentation garantie de performance sur cette machine. Pour qualifier le
gain de capacité, il faut placer les instances sur des hôtes distincts ou
augmenter les ressources, puis répéter chaque palier avec un ordre d'essai
alterné.

## 6. Reproduction

```bash
./dev/tests/run-phase10-benchmark.sh phase10_$(date -u +%Y%m%d_%H%M%S)
```

Les sorties sont conservées dans :

```text
dev/tests/results/phase10/<RUN_ID>/
```

Le fichier `comparison.tsv` contient les valeurs de décision et les sous-
dossiers `single/` et `dual/` contiennent les états avant/après ainsi que les
résumés de supervision.

## 7. Conclusion

La phase 10 est validée dans le périmètre local. Les deux architectures
traitent intégralement les trois charges et OpenSearch reste sain. La deuxième
instance apporte une résilience mesurable et une répartition correcte, mais
pas de gain de débit stable sur l'hôte local actuel. Cette conclusion
constitue la condition d'entrée essentielle
avant la future étude du cluster OpenSearch : la résilience doit être évaluée
par couche et avec des ressources réellement indépendantes.

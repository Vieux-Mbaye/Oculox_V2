# Dimensionnement Oculox

Ce repertoire contient les livrables de dimensionnement et de schema
d'architecture pour un deploiement ferroviaire.

## Fichiers

| Fichier | Role |
|---|---|
| `dimensionnement_oculox_reseau_ferroviaire.xlsx` | Proposition de serveurs, roles, ressources et services |
| `prompt_architecture_oculox_astra.md` | Prompt detaille pour generer un schema d'architecture avec zones et flux |

## Hypothese D'Architecture

```text
Zone 1 : Collecteur par gare
Zone 2 : Core Oculox
Zone 3 : Cluster OpenSearch trois noeuds
```

Un collecteur est prevu par gare. Le cluster OpenSearch est separe du Core afin
d'isoler le stockage et de permettre une croissance plus propre.

## Mise A Jour

Avant d'envoyer le dimensionnement, verifier :

- debit attendu sur les ports mirroring ;
- nombre de gares ;
- retention souhaitee ;
- volumetrie journaliere estimee ;
- contraintes de sauvegarde ;
- nombre d'utilisateurs simultanes ;
- duree de conservation PCAP si Arkime stocke les paquets.

Le fichier Excel est un livrable projet. Il ne doit pas contenir de mot de passe
ni d'information sensible.

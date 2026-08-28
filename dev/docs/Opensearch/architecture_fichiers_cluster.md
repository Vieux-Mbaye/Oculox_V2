# Étape d'organisation - Organisation du depot OpenSearch

## 1. Objet

Cette étape prepare les frontieres de responsabilite du futur cluster
OpenSearch sans creer de service executable et sans deployer de secret.

Elle evite de melanger :

- l'orchestration du cluster ;
- les sources de configuration ;
- les artefacts rendus localement ;
- les scripts d'exploitation ;
- les tests ;
- la supervision.

## 2. Arborescence creee

```text
dev/
|-- compose/
|   `-- opensearch-cluster/
|       `-- README.md
|-- config/
|   `-- opensearch-cluster/
|       `-- README.md
|-- generated/
|   `-- opensearch-cluster/
|       |-- .gitignore
|       `-- README.md
|-- scripts/
|   `-- opensearch-cluster/
|       `-- README.md
|-- tests/
|   `-- opensearch-cluster/
|       `-- README.md
`-- monitoring/
    `-- opensearch-cluster/
        `-- README.md
```

Chaque README definit le contenu autorise et les invariants attendus dans son
repertoire.

## 3. Separation source et runtime

Les repertoires versionnes sont :

| Repertoire | Contenu autorise |
|---|---|
| `dev/compose/opensearch-cluster/` | orchestration Compose sans secret |
| `dev/config/opensearch-cluster/` | modeles et configuration non secrete |
| `dev/scripts/opensearch-cluster/` | operations reproductibles et idempotentes |
| `dev/tests/opensearch-cluster/` | validations statiques et fonctionnelles |
| `dev/monitoring/opensearch-cluster/` | definitions de metriques et alertes |

Le repertoire local non versionne est :

```text
dev/generated/opensearch-cluster/
```

Il recevra les configurations effectives, la PKI, les keystores et les fichiers
d'environnement locaux. Les donnees des noeuds et les snapshots resteront en
dehors du depot, dans des volumes ou stockages dedies.

## 4. Protection Git

La regle generale `dev/generated/` a ete remplacee par des regles equivalentes
qui continuent d'ignorer tous les artefacts existants tout en autorisant le seul
squelette documentaire du cluster :

```gitignore
generated/*
!generated/opensearch-cluster/
```

Le `.gitignore` interne ignore ensuite tout sauf lui-meme et son README :

```gitignore
*
!.gitignore
!README.md
```

Cette organisation permet de versionner le contrat du repertoire sans risquer
d'ajouter une cle privee ou une configuration locale.

## 5. Conventions retenues

1. Le cluster constitue un projet Compose autonome de la VM dediee.
2. Oculox Core et Hedgehog restent des clients distants.
3. L'endpoint est un parametre de deploiement ; sa valeur de developpement est
   `https://192.168.1.241:9200`.
4. Aucun noeud ne partage le volume de donnees d'un autre noeud.
5. Les fichiers sources ne contiennent ni mot de passe ni cle privee.
6. Les scripts doivent etre idempotents et verifier l'identite du cluster.
7. Les tests ne ciblent jamais implicitement le mono-noeud Oculox existant.
8. Les preuves volumineuses et donnees runtime restent ignorees.

## 6. Hors perimetre de cette étape

Cette étape ne cree pas encore :

- de fichier Compose executable ;
- de configuration `opensearch.yml` ;
- de certificat ou autorite de certification ;
- de compte ou role Security ;
- de volume Docker ;
- de conteneur ;
- de connexion entre Oculox et la VM dediee.

Ces elements appartiennent aux phases suivantes du plan directeur.

## 7. Criteres de sortie

| Critere | Resultat |
|---|---|
| Six domaines de responsabilite separes | PASS |
| Repertoire generated protege | PASS |
| Aucun secret cree | PASS |
| Aucun conteneur demarre | PASS |
| Aucun fichier Malcolm d'origine remplace | PASS |
| Responsabilites documentees | PASS |

La étape d'organisation est validee. La étape de topologie Compose peut maintenant ajouter le Compose du
cluster vide dans la frontiere prevue, sans encore initialiser la PKI ni le
plugin Security.

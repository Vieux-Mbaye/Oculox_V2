# Surcharges Docker Compose

Ce répertoire contient les changements locaux d'orchestration.

Le fichier `docker-compose.dev.yml` est un fichier de surcharge. Il ne remplace pas le `docker-compose.yml` d'origine : Docker Compose fusionne les deux fichiers.

## Seconde Instance Logstash

La phase 5 y déclare `logstash-2` avec `extends`. Cette instruction demande à
Compose de reprendre le service `logstash` du fichier officiel, notamment son
image, ses fichiers d'environnement, ses certificats, ses pipelines, son
réseau et son contrôle de santé.

Deux propriétés sont ensuite remplacées :

- `hostname` devient `logstash-2` ;
- la cible `/logstash-persistent-queue` est alimentée par le volume propre
  `logstash-persistent-queue-2`.

La cible du montage sert de clé lors de la fusion des volumes. Le nouveau
montage remplace donc la queue héritée, tandis que les autres montages en
lecture seule sont conservés.

Pour démarrer uniquement les composants nécessaires à cette phase :

```bash
./dev/scripts/platform-mode.sh dual-core
```

Pour démarrer le chemin d'ingestion sécurisé de la phase 6 :

```bash
./dev/scripts/platform-mode.sh dual-ingest
```

Ce mode prépare les certificats locaux, génère les configurations Filebeat,
puis démarre OpenSearch, Filebeat et les deux Logstash. Filebeat se connecte à
`logstash:5044` et `logstash-2:5044` avec `loadbalance: true`. Les deux côtés
vérifient leurs certificats respectifs.

## Persistance De La Phase 7

La même surcharge monte un `00_config.conf` ciblé sur chacun des sept pipelines
actifs. Les pipelines standards disposent de `512mb` et `malcolm-output` de
`1gb`. Les deux instances conservent des volumes distincts afin qu'un processus
ne puisse pas ouvrir la file de l'autre.

La configuration réellement chargée, les essais de reprise et le calcul de
capacité sont documentés dans
`dev/docs/08_phase7_persistance_reprise_certificats.md`.

Pour les arrêter sans supprimer les volumes :

```bash
./dev/scripts/platform-mode.sh dual-stop
```

Exemple futur :

```yaml
services:
  logstash:
    environment:
      LS_JAVA_OPTS: "-Xms4g -Xmx4g"
```

Dans cet exemple, seule la variable de Logstash est surchargée. Son image, ses volumes, ses réseaux et ses autres propriétés continuent de provenir du Compose d'origine.

La configuration fusionnée se vérifie avec :

```bash
./dev/scripts/validate-compose.sh
```

Le fichier n'est pas appelé `docker-compose.override.yml` à la racine afin d'éviter son chargement automatique. Son utilisation doit rester explicite avec `-f`.

En exploitation, cette utilisation explicite est assurée par `./oculox`. Les
commandes officielles Malcolm restent disponibles pour leurs assistants, mais
le démarrage et l'arrêt de la plateforme Oculox doivent passer par ce lanceur
afin de toujours charger la surcharge résiliente.

La surcharge fixe également `restart: unless-stopped` pour les services des
profils Principal et Hedgehog. Les conteneurs déjà démarrés reviennent donc
automatiquement après le redémarrage de Docker ou de l'hôte.

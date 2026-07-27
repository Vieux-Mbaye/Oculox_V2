# Surcharges Docker Compose

Ce répertoire contient les changements locaux d'orchestration.

Le fichier `docker-compose.dev.yml` est un fichier de surcharge. Il ne remplace pas le `docker-compose.yml` d'origine : Docker Compose fusionne les deux fichiers.

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


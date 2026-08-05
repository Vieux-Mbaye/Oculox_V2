# Configuration De Développement

Ce répertoire contient les modèles de configuration ajoutés par l'équipe.

## Convention

- `*.env.example` : modèle documenté et versionné, sans secret ;
- `*.env` : configuration réelle d'une machine, ignorée par Git ;
- une variable doit être expliquée avant d'être ajoutée ;
- une valeur par défaut ne doit pas contenir d'adresse client, de mot de passe ou de clé privée.

Le fichier `dev.env.example` ne modifie pas Malcolm. Il prépare seulement l'emplacement des futures variables locales.

Lorsqu'il sera nécessaire de créer la configuration locale :

```bash
cp dev/config/dev.env.example dev/config/dev.env
```

Le fichier `dev/config/dev.env` restera local grâce au `.gitignore` du répertoire `dev/`.

## Entrée Beats Renforcée

`logstash/input/01_beats_input.conf` remplace uniquement le fichier homonyme
des deux Logstash dans la surcharge de développement. Le montage porte sur un
fichier, pas sur tout le dossier `input` : `00_config.conf` reste disponible
au script de démarrage. Ce dernier copie ses paramètres dans `pipelines.yml`,
puis le supprime volontairement avant de lancer Logstash. Elle conserve TCP `5044`,
active TLS et impose `ssl_client_authentication => "required"`.

Le certificat serveur, sa clé et l'autorité de confiance sont montés depuis
`dev/generated/pki/`. Ces fichiers sont générés localement et ne doivent pas
être ajoutés au dépôt Git.

## Paramètres Des Files Persistantes

Les fichiers de `logstash/pipeline-settings/` remplacent uniquement le
`00_config.conf` de chaque pipeline actif. Ils sont lus par le script de
démarrage Malcolm pour construire la configuration effective de Logstash :

- `00_persistent_default.conf` : file de `512mb` pour les pipelines standards ;
- `00_persistent_input.conf` : même file avec le worker unique requis par
  l'entrée ;
- `00_persistent_output.conf` : file de `1gb` pour le pipeline qui écrit dans
  OpenSearch.

Chaque instance Logstash utilise son propre volume. Les réglages et leurs
preuves d'exécution sont expliqués dans
`dev/docs/08_phase7_persistance_reprise_certificats.md`.

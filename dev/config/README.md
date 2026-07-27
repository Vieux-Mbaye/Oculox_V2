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


# Identité Visuelle Oculox

Ce répertoire est la source unique des deux visuels utilisés par le déploiement Oculox.

| Fichier | Usage |
|---|---|
| `logo_Oculox.png` | Logo complet : centre du portail, écran de chargement et logo complet des interfaces |
| `icone_logo.png` | Marque compacte : barre de navigation, favicon et icône d’application |

## Remplacer Un Visuel

Conserver exactement les noms de fichiers ci-dessus et remplacer le PNG concerné :

```bash
cp /chemin/vers/le/nouveau-logo.png dev/branding/logo_Oculox.png
cp /chemin/vers/la/nouvelle-icone.png dev/branding/icone_logo.png
```

Valider ensuite les références, les volumes Docker et les empreintes des fichiers :

```bash
./dev/tests/test-branding.sh
```

Pour appliquer les changements à une plateforme déjà démarrée :

```bash
./oculox restart
```

Lors d'une installation neuve, `dev/compose/docker-compose.dev.yml` monte ces fichiers dans Nginx, OpenSearch Dashboards, l'import de fichiers, la gestion des comptes et le navigateur de fichiers extraits. Le script `install-nginx-branding.sh` crée également les alias historiques nécessaires aux images officielles.

Les noms techniques internes hérités de Malcolm, notamment les profils Docker, les variables `MALCOLM_*`, les en-têtes API et certains noms d'index, ne sont pas une identité visuelle. Ils doivent rester inchangés pour préserver la compatibilité avec les conteneurs officiels.

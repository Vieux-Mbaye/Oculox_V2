# Configuration Du Cluster OpenSearch

Ce repertoire contient les modeles versionnes du cluster OpenSearch dedie.

## Contenu

| Chemin | Role |
|---|---|
| `cluster.env.example` | Variables minimales pour valider le Compose sans secret |
| `cluster.yml.example` | Exemple de configuration declarative du cluster |
| `opensearch.yml.template` | Modele de configuration des noeuds OpenSearch |
| `haproxy.cfg.template` | Modele de l'endpoint client stable |
| `security/` | Roles, mappings, utilisateurs et configuration Security versionnes |

## Principe

Les fichiers ici sont des modeles. Ils ne doivent pas contenir :

- mot de passe ;
- hash reel d'utilisateur ;
- cle privee ;
- certificat genere ;
- IP client specifique hors exemple ;
- bundle Core ou Hedgehog.

Les valeurs reelles sont rendues dans :

```text
dev/generated/opensearch-cluster/
```

## Moindre Privilege

Les comptes techniques ne partagent pas un administrateur global. Les roles sont
separes par service :

```text
Logstash             -> ecriture ingestion
Arkime               -> index Arkime et sessions
Dashboards           -> service Dashboards
Dashboards helper    -> objets partages et templates
API / pcap-monitor   -> lecture API necessaire
Snapshot             -> operations snapshot dediees
```

Les utilisateurs humains arrivent via Keycloak/OIDC. Leurs roles Keycloak sont
vus par OpenSearch Security comme des backend roles.

## Validation

Depuis la racine :

```bash
python3 -m unittest discover -s dev/tests/opensearch-cluster -p 'test_*.py'
./oculox verify clients
```

`verify clients` doit confirmer que chaque service s'authentifie avec son propre
compte et non avec un super utilisateur partage.

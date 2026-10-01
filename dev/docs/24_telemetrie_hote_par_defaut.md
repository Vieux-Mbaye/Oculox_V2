# Telemetrie Hote Par Defaut

## Objectif

Les dashboards "Malcolm and Third-Party Logs" ne se remplissent pas uniquement
avec Zeek, Suricata et Arkime. Ils ont besoin de journaux hote supplementaires :
systemd/journald, kernel, audit, integrite fichiers, metriques CPU/RAM/disque,
temperature, reseau et logs Nginx.

Oculox active maintenant cette chaine par defaut pendant l'installation et la
preparation d'une VM neuve.

## Flux Active

| Source | Collecteur | Destination |
| --- | --- | --- |
| Logs Nginx access/error | Filebeat interne | Logstash puis OpenSearch |
| Syslog TCP externe | Filebeat syslog TCP | Logstash puis OpenSearch |
| Syslog UDP externe | Filebeat syslog UDP | Logstash puis OpenSearch |
| CPU/RAM/disque/reseau/temperature | Fluent Bit hote | Filebeat TCP `5055` |
| Journald/systemd | Fluent Bit hote | Filebeat TCP `5055` |
| Kernel messages | Fluent Bit hote | Filebeat TCP `5055` |
| Audit Linux | Fluent Bit hote | Filebeat TCP `5055` |
| AIDE/file integrity | Fluent Bit hote | Filebeat TCP `5055` |

Le port `5045` reste reserve a `logstash-2`. Les logs hote passent par
`5055` pour eviter tout conflit.

## Automatisation

`./oculox prepare principal` et `./oculox install principal` executent d'abord :

```bash
./oculox host-telemetry install-deps
```

Sur Debian/Ubuntu, cette commande installe automatiquement :

- `fluent-bit` depuis le depot officiel Fluent Bit ;
- `auditd` pour produire `/var/log/audit/audit.log` ;
- `aide` pour le controle d'integrite fichiers ;
- `jq` pour convertir le rapport AIDE en JSON compact.

Ensuite, elles executent :

```bash
./oculox host-telemetry configure
```

Cette commande copie les services Malcolm dans :

```text
~/.config/systemd/user/
```

Elle adapte automatiquement :

- le chemin du depot Oculox reel ;
- la destination TCP vers `tcp://localhost:5055` ;
- les certificats mTLS Filebeat deja generes par l'installation.

`./oculox start` et `./oculox restart` executent ensuite :

```bash
./oculox host-telemetry start
```

`./oculox stop` arrete les services avec :

```bash
./oculox host-telemetry stop
```

## Verification

Sur une VM neuve, apres installation :

```bash
./oculox status
./oculox host-telemetry verify
./oculox host-telemetry status
```

Verifier aussi que Filebeat expose les ports attendus :

```bash
docker compose --profile malcolm \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  config | grep -E '5055|5514|FILEBEAT_TCP|FILEBEAT_SYSLOG'
```

Dans OpenSearch Dashboards, les donnees arrivent dans `malcolm_beats_*` sous
des modules comme `cpu`, `mem`, `df`, `disk`, `network`, `systemd`, `kmsg`,
`auditlog`, `aide` et `nginx`.

## Dependances OS

La configuration Oculox installe les dependances automatiquement sur
Debian/Ubuntu. Sur une distribution non supportee par apt ou par le depot
officiel Fluent Bit, installez manuellement les composants suivants :

| Besoin | Dependances |
| --- | --- |
| Fluent Bit | paquet `fluent-bit` ou binaire `/opt/fluent-bit/bin/fluent-bit` |
| Audit Linux | `auditd` et lecture de `/var/log/audit/audit.log` |
| File integrity | AIDE et `/usr/local/bin/aide_integrity_check.sh` |
| Journald/systemd | systemd utilisateur actif |

Si Fluent Bit n'est pas installe, `./oculox host-telemetry start` le signale
sans casser le demarrage Docker. La plateforme continue de fonctionner, mais
les dashboards hote restent partiellement vides tant que cette dependance OS
n'est pas installee.

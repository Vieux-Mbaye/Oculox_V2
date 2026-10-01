# Audit et etat EJBCA / PKI Oculox - 2026-09-29

## Contexte

Audit demande pour comprendre ou en est le sous-projet EJBCA / PKI de Oculox.

Regle de travail initiale : audit sans modification. Ce fichier a ete cree ensuite a la demande explicite de sauvegarder les conclusions pour les prochaines sessions.

## Verdict court

Le chantier EJBCA est avance jusqu'aux phases 5, 6 et 7 fonctionnelles :

- EJBCA tourne localement dans un compose separe.
- La base MariaDB EJBCA est healthy.
- Les CA Oculox existent.
- L'acces administrateur EJBCA est durci par certificat client.
- Le manifeste PKI Oculox existe.
- L'audit PKI fonctionne.
- L'enrollment EJBCA fonctionne en staging.
- Le renew fonctionne en staging.
- L'import de bundle PKI client fonctionne.
- L'installation explicite avec backup, validation et rollback existe.
- La validation applicative web, Keycloak, Dashboards et ingestion passe.

Ce n'est pas encore une PKI production complete.

## Etat observe

Commandes observees comme OK pendant l'audit :

```text
./oculox pki status
./oculox pki audit
./oculox pki-ca status
./oculox pki-ca ca-plan
./oculox pki-ca verify-hardening
./oculox validate all
```

Etat EJBCA :

```text
oculox-ejbca      healthy
oculox-ejbca-db   healthy
```

Endpoints locaux EJBCA :

```text
127.0.0.1:18080 -> EJBCA HTTP
127.0.0.1:18443 -> EJBCA HTTPS
```

Durcissement admin observe :

```text
ADMIN CERT ROLE        OK
PUBLIC SUPERADMIN      OK
PUBLIC ACCESS ROLE     OK
ADMIN P12 EXPORT       OK
WEB WITHOUT CERT       OK
WEB WITH ADMIN CERT    OK
```

Plan EJBCA :

```text
Plan EJBCA valide: 4 CA, 9 profils
```

Validation applicative :

```text
OK    pki
OK    web
OK    keycloak
OK    dashboards
WARN  opensearch local 9200 non detecte, normal si cluster distant
OK    ingestion
```

## Fichiers structurants

- `dev/ejbca/docs/plan_developpement_integration_ejbca.md`
- `dev/ejbca/docs/phases_1_2_audit_et_manifeste.md`
- `dev/ejbca/docs/phases_3_4_installation_ejbca_et_creation_ca.md`
- `dev/ejbca/docs/phases_5_6_7_integration_installation_validation.md`
- `dev/ejbca/docs/durcissement_acces_admin_ejbca.md`
- `dev/ejbca/pki-manifest.yml`
- `dev/ejbca/profiles/ca-plan.yml`
- `dev/ejbca/compose/docker-compose.ejbca.yml`
- `dev/ejbca/config/ejbca.env.example`
- `dev/scripts/ejbca/manage-ejbca.sh`
- `dev/scripts/ejbca/pki-lifecycle.py`
- `dev/scripts/ejbca/validate-ca-plan.py`
- `dev/scripts/pki-audit.py`
- `dev/scripts/pki-validate-services.py`
- `oculox`

## Ce qui est fait

1. Phases 1 et 2 terminees :
   - audit PKI ;
   - statut PKI ;
   - expiration PKI ;
   - manifeste source de verite.

2. Phases 3 et 4 largement terminees :
   - compose EJBCA dedie ;
   - env runtime genere ;
   - MariaDB separee ;
   - CA plan valide ;
   - creation des CA Oculox ;
   - durcissement admin EJBCA.

3. Phases 5, 6 et 7 implementees :
   - `./oculox pki enroll --provider ejbca` ;
   - `./oculox pki renew --provider ejbca` ;
   - `./oculox pki import --provider customer` ;
   - staging obligatoire par defaut ;
   - installation seulement avec `--install` ;
   - redemarrage cible seulement avec `--restart` ;
   - backup avant remplacement ;
   - rollback si validation post-installation echoue ;
   - `./oculox validate web|keycloak|dashboards|opensearch|ingestion|all`.

## Point important

Les certificats actifs web, logstash et filebeat semblent deja issus d'EJBCA :

- `web_server` signe par `Oculox Web CA` ;
- `logstash_server` signe par `Oculox Internal Services CA` ;
- `filebeat_client` signe par `Oculox Internal Services CA`.

Les backups sous `dev/ejbca/generated/backups/` montrent que des installations reelles ont deja eu lieu, pas seulement du staging.

## Ce qu'il reste a faire proprement

1. Corriger les permissions des `identity.p12` generes en `0600`.

2. Creer/provisionner les vrais profils EJBCA applicatifs, pas seulement les documenter dans `ca-plan.yml`.

3. Ajouter l'enrollment EJBCA complet pour OpenSearch :
   - nodes ;
   - endpoint ;
   - admin client.

4. Implementer la revocation :
   - CRL ;
   - OCSP ou procedure minimale testee de revocation.

5. Ajouter une procedure de sauvegarde/restauration EJBCA testee, avec preuve de restore.

6. Mettre en place l'alerte d'expiration certificats.

7. Nettoyer ou archiver les anciens enrollments/backups generes.

8. Finaliser la documentation operateur :
   - installation ;
   - renouvellement ;
   - import PKI client ;
   - rollback ;
   - revocation ;
   - restauration.

9. Tester le tout sur une VM neuve de bout en bout.

10. Faire une validation finale :

```text
./oculox validate
./oculox validate all
./oculox pki audit
./oculox pki-ca verify-hardening
```

## Risques identifies

1. Les fichiers `identity.p12` dans `dev/ejbca/generated/enrollments/...` sont en `0644`.
   Ils contiennent identite et cle privee dans un P12 protege par mot de passe, mais doivent etre durcis en `0600`.

2. OpenSearch n'est pas encore integre completement au flux EJBCA.
   Le code refuse actuellement l'enrollment automatique des profils `server-client`.

3. Les profils EJBCA applicatifs sont decrits dans le plan, mais ne semblent pas encore provisionnes comme profils EJBCA custom complets.

4. Les sujets production ne sont pas termines :
   - revocation ;
   - CRL/OCSP ;
   - alerting expiration ;
   - restore test ;
   - documentation finale.

5. `dev/ejbca/generated/` est une zone sensible :
   - secrets runtime ;
   - P12 admin ;
   - backups de cles ;
   - enrollments ;
   - bundles client.

## Resume pour reprise future

Reprendre le chantier EJBCA par le durcissement des P12 generes, puis continuer avec les vrais profils EJBCA et l'integration OpenSearch. Ne pas commencer par la revocation ou la documentation finale tant que les profils et OpenSearch ne sont pas propres.

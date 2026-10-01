# Durcissement de l'acces administrateur EJBCA

## Objectif

EJBCA doit etre administre par certificat client, pas par acces public bootstrap.

L'installation locale Oculox applique donc le principe suivant :

1. EJBCA demarre une premiere fois en mode bootstrap.
2. Oculox cree un administrateur local par certificat client.
3. Le certificat admin est mappe au role EJBCA `Super Administrator Role`.
4. L'acces public bootstrap est supprime.
5. L'interface admin Web refuse l'acces sans certificat client.

## Commandes

Durcir EJBCA :

```bash
./oculox pki-ca harden
```

Verifier le durcissement :

```bash
./oculox pki-ca verify-hardening
```

Sortie attendue :

```text
ADMIN CERT ROLE        OK
PUBLIC SUPERADMIN      OK
PUBLIC ACCESS ROLE     OK
ADMIN P12 EXPORT       OK
WEB WITHOUT CERT       OK
WEB WITH ADMIN CERT    OK
```

## Fichiers generes

Certificat client administrateur :

```text
dev/ejbca/generated/admin/oculox-superadmin.p12
```

Mot de passe du P12 :

```text
dev/ejbca/generated/ejbca.env
EJBCA_ADMIN_PASSWORD=...
```

Ces fichiers sont dans `dev/ejbca/generated/`, qui est ignore par Git.
Ils ne doivent pas etre commits.

## Utilisation dans le navigateur

1. Importer `dev/ejbca/generated/admin/oculox-superadmin.p12` dans le magasin de certificats du navigateur.
2. Utiliser le mot de passe `EJBCA_ADMIN_PASSWORD`.
3. Ouvrir :

```text
https://127.0.0.1:18443/ejbca/adminweb/
```

Sans ce certificat client, EJBCA doit afficher :

```text
Authorization Denied
```

Avec ce certificat client, EJBCA doit afficher :

```text
Welcome OculoxSuperAdmin to EJBCA Administration
```

## Etat attendu des roles EJBCA

Commande de controle :

```bash
docker exec oculox-ejbca /opt/keyfactor/bin/ejbca.sh roles listadmins --role 'Super Administrator Role'
```

Etat attendu :

```text
'ManagementCA' WITH_COMMONNAME TYPE_EQUALCASE "OculoxSuperAdmin" ""
[Admin not bound to CA or provider] USERNAME TYPE_EQUALCASE "ejbca" ""
```

Le compte CLI local `ejbca` est conserve comme acces de secours local au conteneur.
Il permet de reparer EJBCA si le certificat navigateur est perdu.

Ce qui ne doit plus apparaitre :

```text
TRANSPORT_CONFIDENTIAL
PublicAccessAuthenticationToken
Public Access Role
```

## Explication du code

Le durcissement est implemente dans :

```text
dev/scripts/ejbca/manage-ejbca.sh
```

Fonctions principales :

- `generate_admin_certificate` cree l'entite EJBCA `oculox-superadmin`, genere un certificat client P12 et l'exporte dans `dev/ejbca/generated/admin/`.
- `map_admin_certificate_role` ajoute le CN `OculoxSuperAdmin` au role `Super Administrator Role`.
- `install_admin_ca_in_tls_truststore` exporte `ManagementCA` et l'ajoute dans la truststore HTTPS de WildFly/EJBCA. Cette etape est obligatoire, sinon le navigateur propose le certificat mais le serveur coupe la connexion TLS.
- `remove_public_bootstrap_access` supprime le membre public bootstrap et le role `Public Access Role`.
- `verify_hardening` controle que le role certificat existe, que l'acces public est absent, que le P12 admin est present, que l'acces sans certificat est refuse et que l'acces avec certificat admin fonctionne.

Le script charge le fichier `dev/ejbca/generated/ejbca.env` comme un fichier de configuration `.env`, pas comme un script Bash. C'est volontaire, car certains champs comme `EJBCA_ADMIN_DN` contiennent des espaces.

## Pourquoi `ManagementCA`

Le certificat administrateur Web est emis par `ManagementCA`, car cette CA est creee par le bootstrap EJBCA pour l'administration de l'application.

Les certificats des services Oculox ne doivent pas etre emis par `ManagementCA`.
Ils seront emis par les CA Oculox prevues :

- `Oculox Web CA` ;
- `Oculox Internal Services CA` ;
- `Oculox OpenSearch CA`.

## Verification reseau

EJBCA reste publie uniquement sur la machine locale :

```text
127.0.0.1:18080
127.0.0.1:18443
```

Cette limitation evite une exposition reseau directe pendant les phases de developpement.
Avant une exposition client, il faudra ajouter un filtrage reseau strict, une sauvegarde testee des volumes EJBCA et des roles EJBCA operateur moins privilegies que SuperAdmin.

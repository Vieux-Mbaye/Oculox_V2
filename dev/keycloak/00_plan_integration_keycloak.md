# Plan Directeur D'Intégration De Keycloak Dans Oculox

## 1. Objet Du Document

Ce document définit le plan de développement et de validation pour activer
l'instance Keycloak embarquée dans Oculox. L'objectif est de remplacer
l'authentification HTTP Basic actuellement utilisée par une gestion centralisée
des identités, des sessions et des autorisations.

L'intégration doit s'appuyer en priorité sur les fonctions natives de Malcolm
`26.07.1`. Elle ne doit pas créer un nouveau système d'authentification ni
modifier inutilement le code interne de Keycloak ou de Malcolm.

## 2. État Initial

La configuration actuellement générée utilise notamment :

```text
NGINX_AUTH_MODE=basic
ROLE_BASED_ACCESS=false
KEYCLOAK_AUTH_URL=
KEYCLOAK_CLIENT_ID=
```

Le dépôt contient déjà les composants natifs nécessaires :

- le service Docker `keycloak` ;
- la base PostgreSQL utilisée par Keycloak ;
- le routage Nginx vers `/keycloak` ;
- le mécanisme OpenID Connect entre Nginx et Keycloak ;
- le script officiel `scripts/auth_setup` ;
- le script d'initialisation du realm et du client OIDC ;
- les rôles RBAC natifs de Malcolm.

Keycloak est donc disponible dans l'architecture logicielle, mais il n'est pas
encore l'autorité d'authentification active d'Oculox.

## 3. Architecture Cible

L'architecture sépare le plan des identités du plan des données.

```text
Plan des identités

Utilisateur SOC
      |
      | HTTPS
      v
Nginx Oculox
      |
      | OpenID Connect
      v
Keycloak embarqué
      |-- comptes
      |-- groupes
      |-- rôles
      |-- sessions
      `-- MFA futur
      |
      v
Autorisation vers Dashboards, Arkime, NetBox, Upload et API


Plan des données

Collecteur Filebeat
      |
      | mTLS
      v
Logstash 1 / Logstash 2
      |
      v
OpenSearch
```

Keycloak ne doit pas intervenir dans le transport des événements. Le mTLS
continue d'authentifier les collecteurs et de chiffrer les communications
Filebeat vers Logstash.

## 4. Périmètre

### 4.1 Inclus

- utilisation d'une seule instance Keycloak embarquée ;
- authentification OIDC via Nginx ;
- comptes, groupes, rôles et sessions ;
- activation du RBAC natif Malcolm ;
- définition d'un modèle d'accès Oculox ;
- persistance dans PostgreSQL ;
- sauvegarde et restauration de la configuration Keycloak ;
- intégration à l'installateur `oculox` ;
- tests fonctionnels, de sécurité et de reprise ;
- documentation d'installation et d'exploitation.

### 4.2 Non Inclus Dans Cette Première Version

- cluster Keycloak ;
- PostgreSQL hautement disponible ;
- remplacement de la PKI mTLS par Keycloak ;
- authentification des collecteurs par jeton OIDC ;
- développement d'un fournisseur ou d'un plugin Keycloak spécifique ;
- fédération LDAP ou Active Directory ;
- personnalisation graphique avancée ;
- engagement de haute disponibilité pour les connexions utilisateur.

## 5. Principes Techniques

1. Utiliser les mécanismes natifs avant d'ajouter du code Oculox.
2. Ne jamais versionner les mots de passe, jetons, secrets OIDC ou clés privées.
3. Ne pas exposer directement les ports internes de Keycloak.
4. Utiliser Nginx comme point d'entrée HTTPS unique.
5. Conserver le mTLS Filebeat-Logstash indépendamment de Keycloak.
6. Utiliser les rôles RBAC natifs de Malcolm.
7. Rendre les opérations reproductibles et idempotentes.
8. Prévoir un retour temporaire vers l'authentification Basic.
9. Tester la persistance avant de considérer l'intégration comme terminée.
10. Documenter chaque décision et chaque preuve de validation.

## 6. Modèle D'Identité Initial

### 6.1 Realm Et Client

La cible fonctionnelle comprend :

- un realm dédié à Oculox, après validation de sa création avec les scripts
  natifs Malcolm ;
- un client OpenID Connect utilisé par Nginx ;
- une URL Keycloak publiée sous `https://<serveur>/keycloak` ;
- un secret de client généré à l'installation et conservé hors de Git.

Le realm `master` peut être utilisé pour le bootstrap technique. Les comptes
opérationnels ne doivent pas être administrés durablement dans `master` si un
realm Oculox dédié est retenu.

### 6.2 Groupes

| Groupe | Fonction |
|---|---|
| `/oculox-users` | Groupe commun autorisant l'accès général à Oculox |
| `/oculox-admins` | Administrateurs de la plateforme |
| `/oculox-analysts` | Analystes SOC autorisés à investiguer |
| `/oculox-readonly` | Utilisateurs limités à la consultation |

### 6.3 Rôles Natifs À Réutiliser

| Profil | Rôles de départ |
|---|---|
| Administrateur | `admin` |
| Analyste | `read_write_access` et droits Arkime nécessaires |
| Lecture seule | `read_access` et droits Dashboards en lecture |

Le groupe commun pourra être imposé avec `NGINX_REQUIRE_GROUP`. Les permissions
fonctionnelles seront attribuées par les rôles RBAC. Il faut éviter de placer
plusieurs groupes alternatifs dans `NGINX_REQUIRE_GROUP`, car les exigences
sont cumulatives.

## 7. Phases De Réalisation

## Phase K1 - Étude De L'Intégration Native

### Objectif

Comprendre le chemin d'authentification existant avant toute modification.

### Travaux

- analyser le service `keycloak` des fichiers Compose ;
- identifier sa base PostgreSQL, ses volumes et ses dépendances ;
- analyser le routage Nginx `/keycloak` ;
- étudier `scripts/auth_setup` et `keycloak/scripts/realm-setup.sh` ;
- documenter `auth-common.env` et `keycloak.env` ;
- identifier les fichiers sensibles et leur politique de permission ;
- confirmer le comportement exact du RBAC natif Malcolm.

### Livrable

```text
dev/keycloak/01_integration_native_keycloak.md
```

### Critère De Sortie

Le chemin navigateur, Nginx, OIDC, Keycloak, PostgreSQL et application est
documenté sans zone inconnue.

## Phase K2 - Conception Du Modèle IAM

### Objectif

Définir les identités, groupes, rôles et règles d'accès avant de les créer.

### Travaux

- valider le nom du realm ;
- définir le client OIDC et ses URI de redirection ;
- valider les groupes initiaux ;
- construire la matrice profils-rôles-applications ;
- définir la politique de mot de passe ;
- définir les durées de session ;
- décider si le MFA est activé immédiatement ou dans une phase ultérieure ;
- définir les comptes d'administration et d'exploitation.

### Livrables

```text
dev/keycloak/02_modele_identites_roles.md
dev/keycloak/03_matrice_autorisations.md
```

### Critère De Sortie

Chaque profil possède des droits explicites et applique le principe du moindre
privilège.

## Phase K3 - Préparation De La Configuration

### Objectif

Préparer une configuration reproductible sans enregistrer de secret dans Git.

### Travaux

- utiliser `scripts/auth_setup` comme moteur officiel ;
- sélectionner `NGINX_AUTH_MODE=keycloak` ;
- préparer l'URL publique Keycloak ;
- préparer le realm et l'identifiant du client ;
- générer le mot de passe PostgreSQL Keycloak ;
- générer le secret OIDC au moment approprié ;
- protéger les fichiers runtime en permission `600` ;
- vérifier que `.gitignore` exclut les secrets et exports sensibles ;
- préparer une sauvegarde de la configuration Basic actuelle.

### Livrable

```text
dev/keycloak/04_procedure_configuration.md
```

### Critère De Sortie

La configuration peut être préparée deux fois sans dupliquer les objets ni
corrompre les fichiers existants.

## Phase K4 - Initialisation Contrôlée

### Objectif

Démarrer Keycloak et créer les objets initiaux de manière contrôlée.

### Travaux

1. sauvegarder les fichiers de configuration et PostgreSQL ;
2. générer les secrets internes nécessaires ;
3. créer le compte administrateur bootstrap temporaire ;
4. démarrer Keycloak et PostgreSQL ;
5. créer ou valider le realm ;
6. créer le client OIDC utilisé par Nginx ;
7. créer un administrateur permanent nominatif ;
8. tester ce compte ;
9. supprimer le compte bootstrap temporaire ;
10. créer les groupes et attribuer les rôles.

### Livrable

```text
dev/keycloak/05_initialisation_controlee.md
```

### Critère De Sortie

Keycloak est sain, son client OIDC existe et aucun compte bootstrap temporaire
ne reste actif.

## Phase K5 - Activation De L'Authentification Et Du RBAC

### Objectif

Faire de Keycloak l'autorité d'identité utilisée par les interfaces Oculox.

### Travaux

- activer `NGINX_AUTH_MODE=keycloak` ;
- activer `ROLE_BASED_ACCESS=true` ;
- imposer le groupe commun si cette règle est validée ;
- vérifier les mappers de groupes et de rôles dans les jetons ;
- redémarrer uniquement les services concernés ;
- contrôler les journaux Nginx et Keycloak ;
- vérifier l'accès à chaque application.

### Livrable

```text
dev/keycloak/06_activation_oidc_rbac.md
```

### Critère De Sortie

Un utilisateur non authentifié est redirigé vers Keycloak et un utilisateur
authentifié reçoit uniquement les droits associés à ses rôles.

## Phase K6 - Intégration À L'Installateur Oculox

### Objectif

Permettre l'installation reproductible d'un Principal utilisant Keycloak.

### Cible D'Usage

```bash
./oculox install principal \
  --server-name <nom-DNS-ou-IP> \
  --auth keycloak
```

### Travaux

- ajouter une option d'authentification au lanceur Oculox ;
- appeler les outils officiels Malcolm au lieu de réimplémenter leur logique ;
- séparer paramètres publics et secrets ;
- empêcher l'installation Keycloak sur le profil Hedgehog ;
- vérifier l'idempotence ;
- produire une sortie indiquant les prochaines actions administratives ;
- conserver un mode interactif officiel pour les opérations sensibles.

### Livrables

```text
dev/keycloak/07_integration_installateur.md
dev/tests/run-keycloak-installation.sh
```

### Critère De Sortie

Une installation neuve peut activer Keycloak sans modification manuelle du
Docker Compose et sans publier de secret.

## Phase K7 - Durcissement

### Objectif

Réduire les risques liés à l'exposition du fournisseur d'identité.

### Travaux

- ne publier aucun port interne Keycloak ;
- utiliser Nginx HTTPS comme seul point d'entrée ;
- définir explicitement le hostname public ;
- valider les en-têtes de proxy ;
- utiliser des cookies sécurisés ;
- protéger le secret OIDC ;
- supprimer les comptes inutiles ;
- activer et conserver les événements d'authentification pertinents ;
- documenter la rotation du secret client ;
- définir la sauvegarde PostgreSQL ;
- vérifier que le mTLS existant reste inchangé.

### Livrable

```text
dev/keycloak/08_durcissement_sauvegarde.md
```

### Critère De Sortie

Aucun service Keycloak interne n'est directement accessible et les secrets
nécessaires sont protégés hors de Git.

## Phase K8 - Validation Fonctionnelle Et Sécurité

### Objectif

Prouver le fonctionnement et l'isolation des mécanismes de sécurité.

### Matrice Minimale

| Test | Résultat attendu |
|---|---|
| Accès sans session | Redirection vers Keycloak |
| Mauvais identifiants | Refus |
| Administrateur | Accès complet autorisé |
| Analyste | Accès conforme à ses rôles |
| Lecture seule | Modification refusée |
| Utilisateur sans groupe commun | Accès refusé |
| Jeton expiré | Nouvelle authentification demandée |
| Déconnexion | Session locale et Keycloak terminées |
| Redémarrage Keycloak | Comptes et configuration conservés |
| Arrêt Keycloak | Nouvelle connexion impossible, ingestion maintenue |
| Filebeat sans certificat | Connexion Logstash refusée |
| Keycloak arrêté et mTLS actif | Ingestion Filebeat maintenue |

### Livrables

```text
dev/tests/run-keycloak-validation.sh
dev/keycloak/09_rapport_validation.md
```

### Critère De Sortie

Tous les tests bloquants réussissent et la séparation entre identité humaine et
identité machine est démontrée.

## Phase K9 - Exploitation Et Retour Arrière

### Objectif

Permettre l'administration quotidienne et une restauration maîtrisée.

### Travaux

- documenter la création et la désactivation d'un utilisateur ;
- documenter l'attribution et le retrait d'un rôle ;
- documenter la révocation d'une session ;
- sauvegarder et restaurer PostgreSQL ;
- sauvegarder la configuration du realm sans secrets réutilisables ;
- surveiller l'état du conteneur et de la base ;
- tester le retour temporaire à `NGINX_AUTH_MODE=basic` ;
- documenter la rotation du secret du client OIDC.

### Livrables

```text
dev/keycloak/10_exploitation_keycloak.md
dev/keycloak/11_retour_arriere.md
```

### Critère De Sortie

La restauration et le retour arrière ont été exécutés au moins une fois dans
l'environnement de développement.

## Phase K10 - Livraison

### Objectif

Livrer une intégration propre, auditée et reproductible.

### Travaux

- vérifier les modifications Git ;
- exécuter les contrôles de syntaxe et Compose ;
- rechercher les secrets et artefacts runtime ;
- exécuter la validation Keycloak complète ;
- mettre à jour le guide d'installation Principal ;
- documenter les limites de l'instance unique ;
- produire des commits ciblés ;
- publier la branche de développement puis intégrer dans `main` après revue.

### Livrable

```text
dev/keycloak/12_rapport_livraison.md
```

### Critère De Sortie

Une installation neuve reproduit le même comportement et tous les contrôles
retournent `PASS`.

## 8. Stratégie De Développement Git

Le développement doit être isolé dans une branche dédiée :

```bash
git switch main
git pull --ff-only
git switch -c feature/keycloak-authentication
```

Les commits doivent rester ciblés. Exemple de découpage :

```text
Documente l'intégration native Keycloak
Ajoute le modèle de rôles Oculox
Intègre Keycloak à l'installateur Principal
Ajoute les tests OIDC et RBAC
Documente la sauvegarde et le retour arrière
```

## 9. Risques Et Mesures

| Risque | Impact | Mesure |
|---|---|---|
| Instance Keycloak unique indisponible | Nouvelles connexions impossibles | Supervision, sauvegarde et procédure de redémarrage |
| Base PostgreSQL perdue | Perte des comptes et rôles | Sauvegarde et restauration testées |
| Secret OIDC exposé | Usurpation du client | Exclusion Git, permissions et rotation |
| Mauvais rôle attribué | Accès excessif ou refus injustifié | Matrice d'accès et tests par profil |
| Compte bootstrap conservé | Compte privilégié inutile | Suppression après création de l'administrateur permanent |
| Mauvaise URL ou redirection | Boucle ou échec de connexion | Validation des URI et test HTTPS |
| Confusion Keycloak-PKI | Mauvaise architecture de confiance | Séparation explicite entre OIDC et mTLS |
| Retour arrière non testé | Indisponibilité prolongée | Test préalable du mode Basic de secours |

## 10. Critères Globaux D'Acceptation

L'intégration sera considérée comme terminée lorsque :

- Keycloak embarqué est l'autorité d'authentification active ;
- Nginx utilise correctement OpenID Connect ;
- le RBAC Malcolm est activé ;
- les profils administrateur, analyste et lecture seule sont validés ;
- le mTLS Filebeat-Logstash reste opérationnel et indépendant ;
- l'arrêt de Keycloak ne bloque pas l'ingestion ;
- les données Keycloak persistent après redémarrage ;
- la sauvegarde et la restauration sont testées ;
- aucun secret n'est suivi dans Git ;
- l'installation est reproductible depuis un serveur neuf ;
- la procédure de retour arrière est validée ;
- la documentation permet à un autre administrateur de reproduire les étapes.

## 11. Ordre D'Exécution

Les phases doivent être réalisées dans cet ordre :

```text
K1 Étude native
 -> K2 Modèle IAM
 -> K3 Préparation
 -> K4 Initialisation
 -> K5 Activation OIDC/RBAC
 -> K6 Intégration installateur
 -> K7 Durcissement
 -> K8 Validation
 -> K9 Exploitation et retour arrière
 -> K10 Livraison
```

Il ne faut pas activer Keycloak avant d'avoir défini le modèle de rôles, préparé
la sauvegarde de l'authentification actuelle et établi le retour arrière.

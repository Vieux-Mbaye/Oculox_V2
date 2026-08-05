# Documentation De Développement

Ce répertoire conserve les décisions prises pendant l'évolution locale d'Oculox.

Il doit permettre de répondre à trois questions :

1. pourquoi le changement a-t-il été décidé ?
2. comment a-t-il été implémenté ?
3. comment a-t-il été validé ?

Les études descriptives de l'existant restent dans `dev/phase1/`. Les documents de conception, procédures de modification et comptes rendus de validation sont placés ici.

## Documents Disponibles

| Document | Rôle |
|---|---|
| `00_plan_directeur_developpement_resilient.md` | Feuille de route complète du projet |
| `01_preparation_depot_developpement.md` | Organisation et règles du dépôt de développement |
| `02_architecture_cible_deux_logstash.md` | Décision d'architecture de la phase 3 |
| `03_baseline_un_logstash.md` | Mesure de référence à une instance Logstash |
| `04_mode_local_econome_et_mise_a_jour.md` | Gestion de la RAM et stratégie de migration Malcolm |
| `05_mise_a_jour_malcolm_v26_07_1.md` | Rapport de migration réel et procédure de mise à jour d'une plateforme active |
| `06_phase5_deux_instances_logstash.md` | Implémentation maîtrisée et validation de deux instances Logstash |
| `07_phase6_repartition_tls_idempotence.md` | Répartition Filebeat, TLS mutuel, basculement et maîtrise des doublons |
| `08_phase7_persistance_reprise_certificats.md` | Files persistantes, reprise après incident, dimensionnement et cycle de vie TLS |
| `09_phase8_supervision.md` | Métriques, seuils, scripts de collecte et diagnostic |
| `10_phase9_tests_resilience.md` | Basculement, réintégration et reprise après incident |
| `11_phase10_benchmark_comparatif.md` | Comparaison mesurée entre un et deux Logstash |
| `12_audit_proprete_et_perimetre_local.md` | Revue de code, hygiène Git et limites de la validation locale |
| `13_installation_resiliente_principal_hedgehog.md` | Installation neuve et exploitation intégrées des deux rôles |
| `14_comprendre_arborescence_dev_compose_filebeat.md` | Explication détaillée de l'arborescence `dev/`, des surcharges Compose et des configurations Filebeat générées |
| `15_scenario_complet_developpement_resilience_oculox.md` | Récit technique consolidé : Malcolm d'origine, onze phases, arborescence, tests, résultats et limites |
| `16_procedure_validation_avec_preuves.md` | Démarrage des services essentiels, tests reproductibles et plan de captures de preuve |
| `17_phase11_livraison_git.md` | Livraison Git expliquée : commits, contrôles, publication, exploitation et retour arrière |

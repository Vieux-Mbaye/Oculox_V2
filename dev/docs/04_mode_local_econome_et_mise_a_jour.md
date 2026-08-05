# Mode Local Économe Et Stratégie De Mise À Jour

## 1. Problème Constaté

La machine locale possède environ **30 Gio de RAM**. Lorsque la plateforme Oculox complète était active, l'état observé était le suivant :

| Mesure | Valeur observée |
|---|---:|
| RAM utilisée | environ 29 Gio |
| RAM disponible | environ 1,7 Gio |
| Swap | 511 Mio entièrement utilisés |

Les principaux consommateurs Oculox étaient :

| Service | Mémoire observée |
|---|---:|
| OpenSearch | environ 9,3 Gio |
| Logstash | environ 3,7 Gio |
| NetBox | environ 1,3 Gio |
| Strelka backend | environ 1 Gio |
| Suricata offline | environ 805 Mio |

La saturation ne provenait donc pas d'un seul processus. Elle résultait de l'exécution simultanée de la plateforme Malcolm complète, des autres applications du laboratoire ICSHUB et des outils de développement.

## 2. Action Immédiate Réalisée

Oculox a été arrêté avec le script Malcolm :

```bash
./scripts/stop --quiet
```

Cette commande arrête et supprime les conteneurs du projet, mais elle ne supprime pas les volumes ni les répertoires persistants. Les index OpenSearch, les PCAP, les journaux et les fichiers de configuration sont donc conservés.

Après cet arrêt, la machine présentait environ :

| Mesure | Valeur observée |
|---|---:|
| RAM utilisée | 12 Gio |
| RAM disponible | 18 Gio |
| Swap utilisé | 211 Mio |

La machine est ainsi redevenue utilisable sans suppression de données.

## 3. Les Trois Modes De Travail

### 3.1 Mode Arrêté : Écriture Et Validation Statique

Ce mode est le mode normal pour lire, documenter et modifier la configuration. Aucun service Oculox n'est nécessaire :

```bash
./dev/scripts/platform-mode.sh stop
./dev/scripts/platform-mode.sh check
```

La commande `check` fusionne les fichiers Compose et vérifie leur validité sans créer de conteneur.

### 3.2 Mode Core : Développement De La Couche Logstash

Ce mode démarre uniquement **OpenSearch**, destination des événements, et **Logstash**, moteur de parsing, d'enrichissement et de routage :

```bash
./dev/scripts/platform-mode.sh core
```

Il est adapté au développement de la future architecture à deux Logstash. Il ne valide pas toute la chaîne PCAP, car Zeek, Suricata, Arkime, Filebeat et les interfaces web restent arrêtés.

Le mode `core` reste relativement lourd : OpenSearch et Logstash consommaient ensemble environ 13 Gio lors de la mesure. Il faut donc l'arrêter dès que le test technique est terminé.

### 3.3 Mode Full : Validation Fonctionnelle Et Benchmark

La plateforme complète doit être démarrée seulement pour injecter un PCAP, contrôler toute la chaîne et produire une mesure comparable au baseline :

```bash
./dev/scripts/platform-mode.sh full
```

Après le test :

```bash
./dev/scripts/platform-mode.sh stop
```

## 4. Pourquoi Ne Pas Désactiver Définitivement Les Services Lourds

NetBox, Strelka, Freq, les analyseurs et les interfaces web peuvent être inutiles pendant une modification ciblée de Logstash. Ils font néanmoins partie du comportement complet de Malcolm.

Les désactiver dans la configuration changerait la nature du pipeline et rendrait les mesures difficilement comparables au baseline à un Logstash. La bonne stratégie consiste donc à les arrêter hors test, et non à altérer immédiatement leurs fonctions.

## 5. Version Locale Et Version Officielle

Le dépôt local utilisait les images **Malcolm 26.06.0** au moment de cette étude. La mise à jour vers **Malcolm 26.07.1** a ensuite été réalisée sur la branche `upgrade/v26.07.1`. Le dépôt distant interne reste configuré comme `origin` et le dépôt officiel comme `upstream`.

La version officielle **v26.07.1** apporte notamment :

- la prise en charge d'IEC 60870-5-104 ;
- trois corrections de sécurité concernant le contrôle d'accès et l'extraction d'archives ;
- des corrections de normalisation Zeek et Suricata ;
- des améliorations NetBox et PostgreSQL ;
- des versions plus récentes d'Arkime, Zeek, Filebeat et Logstash.

Cette mise à jour est pertinente pour Oculox, particulièrement pour une plateforme OT électrique. Elle ne doit toutefois pas être appliquée directement dans la branche de développement actuelle sans point de retour.

## 6. Ordre De Travail Recommandé

1. Conserver le rapport baseline `26.06.0` comme référence historique.
2. Enregistrer proprement le travail `dev/` dans Git.
3. Sauvegarder les configurations locales et les éléments d'authentification.
4. Créer une branche de mise à niveau dédiée.
5. Rattacher le dépôt interne au dépôt officiel comme source amont.
6. Examiner les différences entre `v26.06.0` et `v26.07.1`.
7. Exécuter `./scripts/status` afin de déclencher les migrations de variables prévues par Malcolm.
8. Intégrer `v26.07.1` et résoudre explicitement les conflits.
9. Exécuter la configuration Malcolm sans réinitialiser les secrets.
10. Télécharger les nouvelles images.
11. Démarrer la plateforme complète et contrôler chaque service.
12. Rejouer le baseline fonctionnel sur `v26.07.1`.
13. Commencer ensuite la création des deux instances Logstash.

Cette séquence évite de développer le cluster Logstash sur une ancienne base, puis de devoir résoudre simultanément les changements de version et les changements d'architecture.

## 7. Points De Vigilance Pour La Mise À Niveau

Les fichiers `config/*.env` réels ne sont pas versionnés par le projet officiel. Ils contiennent la configuration générée pour cette installation et doivent être sauvegardés séparément.

Les répertoires de données ne doivent pas être remplacés :

- `opensearch/` ;
- `pcap/` ;
- `zeek-logs/` ;
- `suricata-logs/` ;
- `filescan-logs/` ;
- `postgres/`.

Le dépôt contient par ailleurs des modifications et des fichiers d'exécution non enregistrés. Un nettoyage Git contrôlé est nécessaire avant de changer de version. Il ne faut ni les supprimer globalement ni utiliser une commande destructive pour obtenir artificiellement un dépôt propre.

## 8. Critères De Validation Après Mise À Niveau

La mise à niveau sera considérée valide uniquement si :

- tous les conteneurs attendus deviennent `healthy` ;
- OpenSearch est `green` ;
- l'authentification fonctionne ;
- Dashboards et Arkime sont accessibles ;
- un PCAP connu traverse la chaîne complète ;
- les événements Zeek et Suricata sont indexés ;
- les sessions Arkime sont consultables ;
- les pipelines Logstash reviennent sans pression résiduelle ;
- le volume de documents obtenu est cohérent avec le baseline ;
- la consommation RAM reste documentée.

## 9. Conclusion

La réponse au manque de RAM n'est pas de supprimer arbitrairement des composants Malcolm. La méthode correcte est d'adapter le niveau de démarrage au travail en cours : aucun service pour la documentation, le noyau OpenSearch/Logstash pour le développement ciblé, et la plateforme complète uniquement pour les validations de bout en bout.

La mise à niveau vers `v26.07.1` a été réalisée avant la duplication de Logstash comme une opération distincte, sauvegardée et réversible. Son déroulement réel est documenté dans `05_mise_a_jour_malcolm_v26_07_1.md`.

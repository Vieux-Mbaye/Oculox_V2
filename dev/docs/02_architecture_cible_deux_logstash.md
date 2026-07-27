# Architecture Cible À Deux Instances Logstash

## 1. Objet Du Document

Ce document formalise l'architecture de développement retenue pour rendre la couche d'ingestion Logstash plus disponible et plus facile à faire évoluer.

Il s'agit d'une **décision de conception**. Aucun deuxième conteneur Logstash n'est encore démarré à cette étape. L'implémentation commencera seulement après l'établissement de la baseline à un Logstash prévue en phase 4.

## 2. Besoin À Résoudre

Dans l'architecture actuelle, Filebeat envoie tous les événements vers un seul service Logstash :

```text
Filebeat → logstash:5044 → OpenSearch
```

Cette organisation présente deux limites :

- si Logstash s'arrête, l'ingestion centrale est interrompue ;
- si ses pipelines saturent, aucune seconde instance ne peut absorber une partie de la charge.

L'objectif est donc d'ajouter une deuxième instance identique et de laisser Filebeat répartir les événements entre les deux :

```text
                                   ┌──────────────────────┐
                                   │ logstash             │
                                   │ instance logique 1   │
                                   │ Beats : TCP/5044     │
                                   │ queue dédiée         │
                                   └──────────┬───────────┘
                                              │
Zeek / Suricata / Arkime                     │
           │                                  ├───────────> OpenSearch
           v                                  │
        Filebeat                              │
   répartition côté client                    │
           │                                  │
           │                       ┌──────────┴───────────┐
           └──────────────────────>│ logstash-2           │
                                   │ instance logique 2   │
                                   │ Beats : TCP/5044     │
                                   │ queue dédiée         │
                                   └──────────────────────┘
```

## 3. Ce Que Cette Architecture Améliore

Cette architecture apporte deux améliorations distinctes.

### 3.1 Tolérance À La Panne De Logstash

Si une instance devient indisponible, Filebeat peut continuer à publier vers l'instance encore accessible. À son retour, la connexion est rétablie et l'instance peut reprendre une partie du trafic.

### 3.2 Répartition Du Traitement

Lorsque les deux instances sont disponibles, Filebeat maintient des connexions vers les deux et leur transmet des lots en parallèle. Le parsing et l'enrichissement ne reposent donc plus sur un processus Logstash unique.

Cette répartition n'est toutefois pas une garantie de doublement des performances. OpenSearch, le disque, les analyseurs ou le réseau peuvent devenir le nouveau point limitant.

## 4. Périmètre De La Résilience

La phase actuelle rend uniquement la **couche Logstash** redondante.

| Élément | Nombre initial | Situation |
|---|---:|---|
| Filebeat | 1 | Point unique de collecte et de distribution |
| Logstash | 2 | Couche redondante et répartie |
| OpenSearch | 1 | Point unique de stockage et d'indexation |
| Dashboards | 1 | Point unique de consultation |

Deux Logstash ne suffisent donc pas à qualifier toute la plateforme de hautement disponible. Une indisponibilité d'OpenSearch bloque toujours l'indexation finale.

## 5. Décisions D'architecture

### 5.1 Noms Des Services

Les services retenus sont :

```text
logstash
logstash-2
```

Le service officiel `logstash` reste en place. Il représente l'instance logique 1. Cette décision évite de renommer un service déjà référencé dans la configuration Malcolm et réduit le risque de régression lors des futures mises à jour.

La deuxième instance sera ajoutée exclusivement dans :

```text
dev/compose/docker-compose.dev.yml
```

### 5.2 Image Et Pipelines

Les deux instances utiliseront :

- la même image officielle Logstash Malcolm ;
- la même version d'image ;
- les mêmes pipelines ;
- les mêmes tables de correspondance ;
- les mêmes règles de parsing et d'enrichissement ;
- la même destination OpenSearch.

Cette symétrie est indispensable. Une répartition entre deux instances configurées différemment pourrait produire des événements incohérents.

### 5.3 Réseau Et Ports

Les deux services appartiendront au réseau Docker `default` du projet.

Chaque conteneur écoutera sur son propre port interne `5044`. Il n'y a pas de conflit, car chaque conteneur possède son propre espace réseau :

```text
logstash:5044
logstash-2:5044
```

Ces ports n'ont pas besoin d'être publiés sur l'hôte pour les communications internes entre conteneurs. Une publication hôte ne sera ajoutée que si un collecteur externe doit joindre directement les deux instances.

### 5.4 Répartition Par Filebeat

La répartition sera effectuée côté client par Filebeat :

```yaml
output.logstash:
  hosts:
    - "logstash:5044"
    - "logstash-2:5044"
  loadbalance: true
  workers: 1
```

Avec `loadbalance: true`, Filebeat ouvre des connexions vers les deux hôtes et publie sur les connexions disponibles. Si une connexion échoue, il continue avec l'autre destination et tente de rétablir la connexion perdue.

Un proxy TCP supplémentaire n'est pas retenu pour cette première architecture. Filebeat fournit déjà le mécanisme nécessaire et l'ajout immédiat d'un proxy introduirait un composant supplémentaire à configurer, superviser et rendre lui-même résilient.

### 5.5 Limite De La Configuration Filebeat Actuelle

Les cinq configurations Filebeat du dépôt utilisent actuellement une destination unique :

```yaml
hosts: ["${LOGSTASH_HOST:logstash:5044}"]
```

Elles se trouvent dans :

- `filebeat/filebeat-logs.yml` ;
- `filebeat/filebeat-nginx.yml` ;
- `filebeat/filebeat-syslog-tcp.yml` ;
- `filebeat/filebeat-syslog-udp.yml` ;
- `filebeat/filebeat-tcp.yml`.

Changer uniquement la valeur de `LOGSTASH_HOST` ne suffit pas proprement, car la variable actuelle est placée à l'intérieur d'une liste contenant une seule chaîne.

La phase 6 devra fournir des configurations de développement dédiées utilisant une véritable liste, par exemple :

```yaml
output.logstash:
  hosts: '${LOGSTASH_HOSTS}'
  loadbalance: ${LOGSTASH_LOADBALANCE:true}
  workers: ${LOGSTASH_WORKERS_PER_HOST:1}
```

Avec le modèle d'environnement suivant :

```dotenv
LOGSTASH_HOSTS=logstash:5044,logstash-2:5044
LOGSTASH_LOADBALANCE=true
LOGSTASH_WORKERS_PER_HOST=1
```

Les fichiers Malcolm d'origine resteront inchangés. Les variantes seront conservées sous `dev/config/filebeat/` et montées par la surcharge Compose.

### 5.6 Files Persistantes Séparées

Chaque instance Logstash disposera de son propre volume :

```text
logstash   → logstash-pq-1
logstash-2 → logstash-pq-2
```

Les deux conteneurs ne doivent jamais écrire dans le même volume de queue. Une queue persistante appartient à un seul processus Logstash.

La queue se place entre l'entrée d'un pipeline et ses filtres :

```text
entrée → queue persistante → filtres → sortie
```

Un événement n'est acquitté par cette queue qu'après le traitement complet des filtres et des sorties du pipeline concerné. Elle permet d'absorber une interruption courte ou un pic, mais elle ne remplace ni une sauvegarde ni une réplication sur une autre machine.

La capacité initiale envisagée est de **4 Gio au maximum par instance pour le pipeline critique retenu**. Cette valeur reste un plafond de conception, pas une valeur à déployer immédiatement. Dans Logstash, `queue.max_bytes` s'applique à chaque pipeline qui active une queue ; l'espace nécessaire doit donc être calculé en additionnant toutes les queues actives.

### 5.7 TLS Et Certificats

Le transport Filebeat vers Logstash restera chiffré avec TLS.

La cible de sécurité est :

- une autorité de certification commune ;
- un certificat serveur propre à `logstash` ;
- un certificat serveur propre à `logstash-2` ;
- les noms DNS Docker présents dans les SAN des certificats ;
- une validation stricte des certificats côté Filebeat ;
- une procédure de rotation et de contrôle d'expiration.

Partager exactement la même clé privée entre les deux services faciliterait le déploiement, mais augmenterait l'impact d'une compromission. Cette solution n'est donc pas retenue comme cible.

### 5.8 Contrôles De Santé

Chaque instance aura un contrôle de santé indépendant. L'état `healthy` devra signifier au minimum que :

- le processus Logstash fonctionne ;
- ses pipelines ont démarré ;
- l'entrée Beats est disponible ;
- aucune erreur bloquante de configuration n'est présente.

Le test de résilience ne se limitera pas à `docker ps`. Les compteurs `events.in` et `events.out` devront prouver que chaque instance traite réellement des événements.

## 6. Ressources Initiales

### 6.1 Ressources Observées Sur La Machine Locale

Au moment de la conception :

| Ressource | Valeur observée |
|---|---:|
| vCPU | 12 |
| RAM totale | 30 Gio |
| RAM disponible | environ 19 Gio |
| Espace disque libre | environ 213 Gio |
| Occupation du disque | 56 % |

### 6.2 Paramètres De Départ

Pour ne pas confondre architecture et optimisation prématurée, les deux instances commenceront avec des valeurs proches des valeurs de référence du dépôt :

| Paramètre | Logstash 1 | Logstash 2 | Justification |
|---|---:|---:|---|
| Heap JVM | 3 Gio | 3 Gio | Valeur du modèle `config/logstash.env.example` |
| Workers par défaut | 2 | 2 | Point de départ conservateur |
| Taille des lots | 125 | 125 | Valeur de référence Malcolm |
| Délai des lots | 25 ms | 25 ms | Valeur de référence Malcolm |
| Queue réservée | jusqu'à 4 Gio | jusqu'à 4 Gio | À confirmer après baseline et budget disque |

La heap JVM est la zone mémoire réservée aux objets Java utilisés par Logstash. Elle ne représente pas toute la mémoire du conteneur : le processus utilise aussi de la mémoire native, les buffers réseau et le cache du système.

Les valeurs définitives ne seront pas choisies sur intuition. La phase 4 mesurera l'instance unique, puis la phase 10 comparera les mêmes charges avec deux instances.

### 6.3 Capacité Disque Disponible

Le disque local est actuellement occupé à **56 %**, avec environ **213 Gio disponibles**. La capacité est suffisante pour préparer deux queues persistantes de 4 Gio, soit 8 Gio de capacité maximale cumulée pour les deux instances.

Cette marge ne dispense pas de contrôler le stockage. Avant la phase 5, il faudra :

1. identifier ce qui occupe le disque ;
2. définir un budget pour OpenSearch, les PCAP, les logs et les queues ;
3. mesurer l'espace avant et après chaque essai ;
4. conserver une marge supérieure au cumul maximal des queues ;
5. déclencher une alerte avant d'atteindre un niveau critique.

Le risque disque n'est donc plus bloquant pour les phases suivantes. La baseline de la phase 4 reste toutefois obligatoire avant le déploiement du deuxième Logstash.

## 7. Comportement Attendu En Cas De Panne

### 7.1 Arrêt D'une Instance Logstash

```text
logstash indisponible
        ↓
Filebeat conserve logstash-2 comme destination disponible
        ↓
les événements continuent vers logstash-2
        ↓
Filebeat tente de reconnecter logstash
```

Le débit maximal peut diminuer pendant la panne, car une seule instance traite alors toute la charge.

### 7.2 Arrêt Des Deux Instances

Filebeat ne peut plus publier. Il réessaie les connexions et conserve sa position dans ses registres persistants. La reprise n'est possible que si les fichiers sources existent encore et ne sont pas supprimés par une politique de nettoyage avant leur lecture complète.

### 7.3 Ralentissement Ou Arrêt D'OpenSearch

Les sorties Logstash ralentissent, la backpressure remonte, puis les queues persistantes peuvent se remplir. Une queue pleine propage finalement la pression jusqu'à Filebeat.

Les deux Logstash ne corrigent donc pas une saturation durable d'OpenSearch.

### 7.4 Redémarrage D'une Instance

La queue propre à cette instance doit être remontée depuis son volume. Filebeat doit rétablir la connexion TLS sans modification manuelle, puis recommencer à lui transmettre des événements.

## 8. Alternatives Étudiées

| Alternative | Décision | Motif |
|---|---|---|
| Renommer le service existant en `logstash-1` | Rejetée | Modifications plus larges et risque de casser les références Malcolm |
| Ajouter HAProxy devant Logstash | Reportée | Filebeat sait déjà répartir ; le proxy ajouterait un composant et un point de panne |
| Partager une queue entre deux Logstash | Rejetée | Une queue persistante n'est pas conçue pour deux processus concurrents |
| Modifier directement tous les fichiers d'origine | Rejetée | Conflits probables lors des mises à jour Malcolm |
| Un certificat et une clé identiques pour les deux instances | Rejetée comme cible | Impact de compromission trop large |
| Deux Logstash et un seul OpenSearch | Retenue pour l'étape initiale | Permet d'isoler et de mesurer la résilience de la couche d'ingestion |

## 9. Risques À Maîtriser

| Risque | Effet | Mesure prévue |
|---|---|---|
| Disque insuffisant | Arrêt d'OpenSearch ou de Docker | Assainir le disque avant déploiement et budgéter les queues |
| Pipelines différents | Données incohérentes | Monter exactement la même configuration dans les deux instances |
| Certificat sans le bon SAN | Échec TLS | Générer les certificats pour les noms DNS Docker exacts |
| Répartition déséquilibrée | Une instance reste saturée | Mesurer `events.in/out` par instance et ajuster les connexions Filebeat |
| Deux Logstash saturent OpenSearch | Déplacement du goulot d'étranglement | Superviser la latence et les refus d'indexation OpenSearch |
| Queue pleine | Backpressure jusqu'à Filebeat | Alertes d'occupation et dimensionnement basé sur le débit réel |
| Nettoyage prématuré des logs sources | Perte lors d'une panne prolongée | Conserver les sources jusqu'à confirmation de publication |

## 10. Critères De Validation

L'architecture sera considérée comme correctement implémentée lorsque les preuves suivantes seront obtenues :

1. la fusion des fichiers Compose est valide ;
2. les deux conteneurs Logstash sont `healthy` ;
3. les deux entrées Beats écoutent sur TCP `5044` dans leur conteneur ;
4. Filebeat établit une connexion TLS vers les deux noms de service ;
5. les deux Logstash présentent une augmentation de `events.in` et `events.out` ;
6. chaque instance utilise son propre volume de queue ;
7. l'arrêt de `logstash` ne bloque pas l'ingestion par `logstash-2` ;
8. l'arrêt de `logstash-2` ne bloque pas l'ingestion par `logstash` ;
9. le retour d'une instance rétablit la répartition sans modification manuelle ;
10. les événements produits, lus, traités et indexés sont rapprochés ;
11. les pertes et doublons éventuels sont quantifiés et expliqués ;
12. OpenSearch reste `green` et sans refus d'écriture.

## 11. Ordre D'implémentation

L'architecture sera réalisée dans l'ordre suivant :

```text
Phase 4 : mesurer la configuration actuelle à un Logstash
   ↓
Phase 5 : ajouter logstash-2 et sa queue indépendante
   ↓
Phase 6 : configurer la liste Filebeat et loadbalance: true
   ↓
Phase 7 : durcir TLS et finaliser les files persistantes
   ↓
Phase 8 : ajouter les métriques et les alertes
   ↓
Phase 9 : tester les pannes et les reprises
   ↓
Phase 10 : comparer objectivement un et deux Logstash
```

## 12. Décision Finale De La Phase 3

L'architecture à deux Logstash est **retenue pour le développement local**, avec les décisions suivantes :

- conservation du service officiel `logstash` ;
- ajout d'un service `logstash-2` par surcharge Compose ;
- répartition directe par Filebeat, sans proxy supplémentaire ;
- pipelines identiques sur les deux instances ;
- volumes de queues strictement séparés ;
- certificats serveur distincts issus de la même autorité ;
- ressources initiales conservatrices, puis ajustées par mesure ;
- OpenSearch unique explicitement reconnu comme limite de résilience ;
- capacité disque validée, avec surveillance obligatoire pendant les essais.

La prochaine étape est la **phase 4 : établir une baseline mesurée avec le Logstash unique actuel**.

## 13. Références Techniques

- [Elastic - Configuration de la sortie Logstash de Filebeat](https://www.elastic.co/docs/reference/beats/filebeat/logstash-output)
- [Elastic - Variables d'environnement complexes dans Filebeat](https://www.elastic.co/docs/reference/beats/filebeat/using-environ-vars)
- [Elastic - Files persistantes Logstash](https://www.elastic.co/docs/reference/logstash/persistent-queues)
- [Elastic - Pipelines multiples Logstash](https://www.elastic.co/guide/en/logstash/8.19/multiple-pipelines.html)

# Phase 6 - Ingestion Répartie, Sécurisée Et Idempotente

## 1. Objectif

La phase 5 a créé deux instances Logstash indépendantes. La phase 6 les place
réellement dans le chemin des données et répond à quatre besoins :

1. répartir les événements Filebeat entre les deux Logstash ;
2. continuer à ingérer lorsqu'une instance Logstash devient indisponible ;
3. authentifier et chiffrer les échanges Filebeat/Logstash ;
4. empêcher qu'une réémission identique produise plusieurs documents dans
   OpenSearch.

L'architecture validée est la suivante :

```text
Fichiers Zeek / Suricata / autres sources
                    |
                    v
        Filebeat + registre persistant
                    |
        répartition côté client
          mTLS 1.2 ou 1.3
              /         \
             v           v
       logstash       logstash-2
        PQ n°1          PQ n°2
             \           /
              v         v
               OpenSearch
      event.hash -> document_id stable
```

Cette phase améliore la résilience de l'ingestion. Elle ne rend pas toute la
plateforme hautement disponible : OpenSearch fonctionne encore avec un seul
nœud et reste un point de défaillance unique.

## 2. Principes Techniques

### 2.1 Répartition Filebeat

Filebeat possède deux destinations :

```yaml
output.logstash:
  hosts:
    - logstash:5044
    - logstash-2:5044
  loadbalance: true
```

Avec `loadbalance: true`, Filebeat maintient une connexion vers chaque
destination disponible et distribue des lots d'événements entre elles. La
distribution n'est pas nécessairement égale à chaque instant. Filebeat ne
fait pas un tour de rôle ligne par ligne : la taille des lots, le nombre de
connexions et le temps de réponse de chaque Logstash influencent la part reçue.

Filebeat joue ici le rôle de répartiteur applicatif pour ses propres sorties.
Il ne remplace pas un load balancer réseau général.

### 2.2 TLS Mutuel

TLS remplit trois fonctions :

- chiffrement : le contenu n'est pas lisible en clair sur le réseau ;
- intégrité : une modification du flux est détectée ;
- authentification : chaque extrémité vérifie l'identité de l'autre.

Le TLS mutuel, ou mTLS, ajoute un certificat côté Filebeat. La vérification se
fait donc dans les deux sens :

```text
Filebeat vérifie le certificat de Logstash
Logstash vérifie le certificat de Filebeat
```

Les certificats de développement contiennent les extensions suivantes :

| Certificat | Usage | Noms vérifiés |
|---|---|---|
| Autorité locale | signe les certificats | `CA:TRUE` |
| Serveur Logstash | `serverAuth` | `logstash`, `logstash-2` |
| Client Filebeat | `clientAuth` | `filebeat` |

Les noms `logstash` et `logstash-2` sont placés dans le champ SAN du
certificat serveur. Filebeat utilise `ssl.verification_mode: full`, ce qui
vérifie à la fois la signature du certificat et la correspondance entre le
nom demandé et le SAN.

L'entrée Beats impose :

```ruby
ssl_client_authentication => "required"
```

Un client qui connaît l'adresse et le port, mais ne possède pas un certificat
valide, ne peut donc pas publier d'événements.

### 2.3 Livraison Au Moins Une Fois Et Idempotence

Filebeat utilise une livraison dite « au moins une fois ». Il conserve sa
position dans les fichiers et réessaie un lot tant qu'il n'a pas reçu sa
confirmation. Ce comportement protège contre la perte lors d'une interruption,
mais il rend possible la réémission d'un événement déjà accepté.

Malcolm calcule un `event.hash` à partir de l'événement normalisé. La sortie
OpenSearch construit ensuite un identifiant stable :

```text
document_id = date de l'index + event.hash
```

Si le même événement normalisé est réémis vers le même index, OpenSearch écrit
sur le même identifiant. Le document existant est remplacé au lieu qu'un
second document soit créé.

Il faut employer le terme **idempotence**, et non promettre une absence
mathématique de doublons dans tous les cas. Deux événements dont le contenu,
le jeu de données ou la date d'index diffèrent peuvent produire des identifiants
différents et sont alors considérés comme deux documents légitimes.

## 3. Organisation Des Fichiers

| Fichier | Responsabilité |
|---|---|
| `dev/compose/docker-compose.dev.yml` | monte les configurations et certificats sur Filebeat et les deux Logstash |
| `dev/config/logstash/input/01_beats_input.conf` | remplace uniquement l'entrée Beats et impose le certificat client sur TCP `5044` |
| `dev/scripts/render-filebeat-ha-config.py` | génère les cinq configurations Filebeat à deux destinations |
| `dev/scripts/generate-beats-pki.sh` | génère l'autorité et les certificats de développement |
| `dev/scripts/prepare-phase6.sh` | orchestre les deux générations précédentes |
| `dev/scripts/platform-mode.sh` | démarre et arrête le mode réduit `dual-ingest` |
| `dev/tests/generate-phase6-events.py` | produit des événements Zeek déterministes pour les essais |
| `dev/tests/filebeat-no-client-cert.yml` | vérifie le refus d'un client sans certificat |

Le répertoire `dev/generated/` contient les configurations rendues et les
secrets cryptographiques. Il est ignoré par Git. Les fichiers officiels de
Malcolm restent inchangés et servent toujours de source.

Cette organisation évite deux types de doublons :

- aucun second exemplaire manuel du Compose officiel n'est maintenu ;
- aucune configuration Filebeat complète n'est recopiée à la main.

Le script Python relit les fichiers officiels et ne remplace que
`output.logstash` dans les versions générées.

La surcharge Logstash monte seulement `01_beats_input.conf`, et non le dossier
`input` complet. Le fichier officiel `00_config.conf` reste donc disponible
pendant l'initialisation. `logstash-start.sh` ajoute son contenu à
`pipelines.yml`, puis le supprime volontairement avant le lancement du moteur.
Cette absence après démarrage est normale. Le montage ciblé évite de masquer
involontairement les métadonnées du pipeline en voulant modifier uniquement
son entrée TLS.

## 4. Préparation Et Démarrage

### 4.1 Générer La Configuration Locale

```bash
./dev/scripts/prepare-phase6.sh
```

Sans option, une PKI existante et valide est conservée. Pour effectuer une
rotation volontaire en développement :

```bash
./dev/scripts/generate-beats-pki.sh --force
```

Cette seconde commande change les certificats. Les services concernés doivent
ensuite être recréés de manière coordonnée.

### 4.2 Valider La Fusion Compose

```bash
./dev/scripts/validate-compose.sh
```

Cette commande détecte une erreur de syntaxe, un montage invalide ou une
référence de service incorrecte avant le démarrage.

### 4.3 Démarrer Le Mode Réduit

```bash
./dev/scripts/platform-mode.sh dual-ingest
```

Seuls les composants nécessaires à l'essai sont démarrés :

- OpenSearch ;
- Filebeat ;
- Logstash 1 ;
- Logstash 2.

Cette sélection limite la consommation de RAM sur la machine locale.

## 5. Commandes De Vérification

### 5.1 Santé Des Services

```bash
docker ps --format 'table {{.Names}}\t{{.Status}}' \
  | grep -E 'oculox-(filebeat|logstash|opensearch)'
```

### 5.2 Configuration Effective De Filebeat

```bash
docker exec oculox-filebeat-1 \
  /usr/share/filebeat/filebeat test output \
  -c /usr/share/filebeat-logs/filebeat-logs.yml \
  --strict.perms=false
```

La sortie doit montrer les deux destinations, la validation de la chaîne du
certificat, un handshake réussi et TLS 1.2 ou 1.3.

### 5.3 Entrée Beats Effective

```bash
docker exec oculox-logstash-1 \
  sed -n '1,80p' \
  /usr/share/logstash/malcolm-pipelines.available/input/01_beats_input.conf

docker exec oculox-logstash-2-1 \
  sed -n '1,80p' \
  /usr/share/logstash/malcolm-pipelines.available/input/01_beats_input.conf
```

Les deux résultats doivent contenir
`ssl_client_authentication => "required"`.

### 5.4 Compteurs Des Deux Logstash

```bash
for container in oculox-logstash-1 oculox-logstash-2-1; do
  printf '%s: ' "$container"
  docker exec "$container" \
    curl -s localhost:9600/_node/stats/pipelines/malcolm-input \
    | jq -r '.pipelines["malcolm-input"].events |
      "in=\(.in) out=\(.out)"'
done
```

`events.in` compte les événements entrés dans le pipeline et `events.out`
ceux qui en sont sortis. Une augmentation sur les deux conteneurs prouve la
répartition.

### 5.5 Santé OpenSearch

```bash
docker exec oculox-opensearch-1 \
  curl -K /var/local/curlrc/.opensearch.primary.curlrc \
  -sk 'https://localhost:9200/_cluster/health' \
  | jq '{status,number_of_nodes,active_shards_percent_as_number,unassigned_shards}'
```

## 6. Résultats Obtenus

### 6.1 Santé Initiale

Les quatre services du mode réduit étaient `healthy`. OpenSearch présentait :

| Indicateur | Résultat |
|---|---:|
| État | `green` |
| Nœuds | 1 |
| Shards actifs | 100 % |
| Shards non assignés | 0 |

### 6.2 Validation Des Deux Connexions TLS

Filebeat a validé successivement :

```text
logstash:5044   -> handshake OK, TLSv1.3
logstash-2:5044 -> handshake OK, TLSv1.3
```

La chaîne de certification et les deux noms DNS ont été vérifiés.

### 6.3 Refus D'un Client Non Authentifié

Un Filebeat de test a utilisé l'autorité de confiance, mais aucun certificat
client. La publication a échoué avec :

```text
Failed to publish events
write: connection reset by peer
```

Le processus a réessayé, mais Logstash a continué à refuser les événements.
Le contrôle démontre que connaître l'autorité serveur ne suffit pas : le
certificat client est obligatoire.

### 6.4 Répartition Des Événements

Deux fichiers de 5 000 lignes ont été présentés à Filebeat, soit 10 000
événements. Les compteurs observés étaient :

| Instance | `events.in` | `events.out` | Part reçue |
|---|---:|---:|---:|
| Logstash 1 | 3 200 | 3 200 | 32 % |
| Logstash 2 | 6 800 | 6 800 | 68 % |
| Total | 10 000 | 10 000 | 100 % |

Les deux instances ont donc participé au traitement. L'écart 32/68 ne
constitue pas une erreur : la répartition porte sur des lots et sa fonction
est d'utiliser les deux destinations disponibles, pas de garantir une égalité
instantanée parfaite.

### 6.5 Idempotence Lors D'une Réémission

Le fichier source de 5 000 événements a ensuite été présenté une seconde fois
sous la même identité logique. Le compteur cumulé de Logstash 1 est passé de
3 200 à 8 200, ce qui confirme la réception de 5 000 événements
supplémentaires.

Le nombre de documents OpenSearch correspondant au marqueur est toutefois
resté à 10 000 :

```text
événements traités par Logstash : 15 000
documents présents dans OpenSearch : 10 000
documents supplémentaires dus à la réémission : 0
```

Le `document_id` dérivé de `event.hash` a donc rendu cette réémission
idempotente.

### 6.6 Basculement Sur Une Seule Instance

Logstash 1 a été arrêté temporairement, puis 3 000 nouveaux événements ont été
créés. Logstash 2 est passé de 6 800 à 9 800 événements reçus, soit exactement
3 000 événements supplémentaires.

| Contrôle | Résultat |
|---|---:|
| Événements du test | 3 000 |
| Événements supplémentaires sur Logstash 2 | 3 000 |
| Documents OpenSearch | 3 000 |
| État Filebeat pendant la panne | `healthy` |
| Perte observée | 0 |

Après le redémarrage de Logstash 1, les deux instances sont revenues à l'état
`healthy` sans modification de la configuration Filebeat.

## 7. Critères De Validation

| Critère | Résultat |
|---|---|
| Deux destinations configurées par nom DNS Docker | Validé |
| Répartition mesurable sur les deux Logstash | Validé |
| Chiffrement TLS 1.3 observé | Validé |
| Vérification stricte des noms serveur | Validé |
| Authentification par certificat client obligatoire | Validé |
| Continuité avec un Logstash arrêté | Validé |
| Retour automatique de l'instance redémarrée | Validé |
| Files persistantes Logstash séparées | Validé en phase 5 |
| Registre Filebeat persistant | Conservé par le volume officiel |
| Réémission identique sans document supplémentaire | Validé |
| OpenSearch sain après les essais | Validé, état `green` |

## 8. Limites Et Mesures De Production

La configuration est adaptée à un laboratoire de développement, mais les
mesures suivantes restent obligatoires avant un déploiement client :

1. remplacer l'autorité locale par la PKI gérée de l'organisation ;
2. conserver la clé privée de l'autorité hors des hôtes applicatifs ;
3. définir la rotation, l'expiration et la révocation des certificats ;
4. dimensionner les files persistantes selon le débit et la durée maximale
   d'indisponibilité d'OpenSearch ;
5. superviser les erreurs Filebeat, la backpressure Logstash et la croissance
   des files ;
6. déployer un cluster OpenSearch correctement dimensionné pour supprimer le
   point de défaillance unique restant ;
7. réaliser les tests de reprise après redémarrage complet prévus en phase 7.

## 9. Références Techniques

- [Filebeat : sortie Logstash et répartition](https://www.elastic.co/guide/en/beats/filebeat/current/logstash-output.html)
- [Elastic : sécuriser Filebeat et Logstash avec TLS](https://www.elastic.co/guide/en/beats/filebeat/current/configuring-ssl-logstash.html)
- [Filebeat : livraison au moins une fois et déduplication](https://www.elastic.co/docs/reference/beats/filebeat/filebeat-deduplication)

## 10. Arrêt Propre

```bash
./dev/scripts/platform-mode.sh dual-stop
```

Cette commande arrête et retire les conteneurs sans option `-v`. Les volumes OpenSearch,
les files persistantes Logstash et le registre Filebeat ne sont pas supprimés.

## 11. Conclusion

La phase 6 est validée. Filebeat distribue les données entre deux Logstash,
le transport est chiffré et authentifié dans les deux sens, une instance peut
être retirée sans interrompre l'ingestion et les réémissions identiques sont
absorbées par un identifiant OpenSearch stable.

La couche d'ingestion Logstash est désormais plus résiliente. La prochaine
étape ne doit pas recopier cette configuration : elle doit industrialiser la
gestion des certificats, dimensionner les files et valider la reprise lors
d'une indisponibilité d'OpenSearch ou d'un redémarrage complet.

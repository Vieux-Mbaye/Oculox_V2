# Phase 7 - Persistance, Reprise Et Cycle De Vie Des Certificats

## 1. Objet Du Document

Cette phase transforme les mécanismes de résilience validés précédemment en
fonctions d'exploitation mesurables. Elle répond à quatre questions concrètes :

1. que deviennent les événements si OpenSearch est temporairement indisponible ?
2. que deviennent-ils si Logstash ou Filebeat redémarre ?
3. quelle durée d'interruption les files actuelles peuvent-elles absorber ?
4. comment contrôler et renouveler les certificats Beats/TLS sans exposer les
   clés privées ?

Les essais ont été exécutés sur la composition locale réduite comprenant
Filebeat, deux instances Logstash et OpenSearch. Chaque série utilise un marqueur
unique et un nombre connu d'événements. Le comptage final dans OpenSearch permet
donc de détecter une perte ou une duplication.

---

## 2. Résultat Exécutif

| Contrôle | Résultat mesuré | Décision |
|---|---:|---|
| Files actives avant correction | `queue.type=memory` sur 7 pipelines | Non conforme |
| Files actives après correction | `queue.type=persisted` sur 7 pipelines et 2 Logstash | Conforme |
| Indisponibilité OpenSearch | 20 000 événements retrouvés sur 20 000 | Validé |
| Redémarrage des deux Logstash | 8 000 événements retrouvés sur 8 000 | Validé |
| Redémarrage Filebeat pendant l'indisponibilité Logstash | 7 000 événements retrouvés sur 7 000 | Validé |
| Événements restant dans les files après reprise | `0` | Conforme |
| État final OpenSearch | `green`, 100 % des shards actifs | Conforme |
| Chaîne de certificats | serveur et client vérifiés par la CA | Conforme en développement |
| Expiration | 29 octobre 2028 | À superviser |

La phase 7 valide une reprise sans perte observée sur les trois incidents
contrôlés. Elle ne prouve pas qu'une panne matérielle détruisant le disque d'un
Logstash serait sans perte : une file persistante locale n'est pas répliquée.

---

## 3. Ce Qui Était Réellement Actif Avant La Correction

Le dépôt contenait déjà une configuration de file persistante dans le pipeline
`external`. Cependant, ce pipeline ne faisait pas partie des sept pipelines
chargés dans le profil testé. L'API Logstash indiquait donc `queue.type=memory`
pour les pipelines actifs :

```text
malcolm-beats
malcolm-enrichment
malcolm-filescan
malcolm-input
malcolm-output
malcolm-suricata
malcolm-zeek
```

Cette distinction est importante : la présence d'un paramètre dans un fichier
du dépôt ne prouve pas qu'il est actif. La preuve doit venir de la configuration
effective ou de l'API du processus en cours d'exécution.

Commande de preuve :

```bash
for container in oculox-logstash-1 oculox-logstash-2-1; do
  echo "=== $container ==="
  docker exec "$container" \
    curl -fsS http://127.0.0.1:9600/_node/stats/pipelines |
    python3 -c '
import json, sys
data = json.load(sys.stdin)
for name, stats in sorted(data["pipelines"].items()):
    queue = stats["queue"]
    print(name, queue["type"], queue["max_queue_size_in_bytes"])
'
done
```

---

## 4. Comprendre La File Persistante Logstash

### 4.1 Principe

Sans file persistante, les événements en attente résident principalement en
mémoire. Une interruption du processus peut alors supprimer ce qui n'a pas
encore été remis au composant suivant.

Avec `queue.type: persisted`, Logstash écrit les événements entrants sur son
disque avant leur traitement. Un événement est acquitté dans cette file quand
il a traversé les filtres et la sortie du pipeline. Si OpenSearch ne répond
plus, les événements non acquittés restent disponibles pour une reprise.

### 4.2 Paramètres Appliqués

```yaml
queue.type: persisted
queue.max_bytes: 512mb
path.queue: "/logstash-persistent-queue"
queue.checkpoint.acks: 1024
queue.checkpoint.writes: 1024
```

Le pipeline `malcolm-output`, directement exposé à une indisponibilité
d'OpenSearch, dispose de `1gb` au lieu de `512mb`.

- `queue.type` choisit une file disque plutôt qu'une file mémoire ;
- `queue.max_bytes` fixe la capacité maximale de **chaque pipeline** ;
- `path.queue` désigne le volume persistant de l'instance ;
- `queue.checkpoint.acks` et `queue.checkpoint.writes` définissent la fréquence
  des points de contrôle utilisés pour la récupération après incident.

La valeur `1024` est un compromis entre durabilité et débit. Une valeur `1`
réduit davantage la fenêtre de risque en cas de coupure brutale, mais provoque
beaucoup plus d'écritures synchrones et peut fortement diminuer les
performances.

### 4.3 Isolation Des Deux Instances

Les deux Logstash ne partagent pas leur file :

```text
oculox_logstash-persistent-queue
oculox_logstash-persistent-queue-2
```

Cette séparation évite la corruption d'une file par deux processus concurrents.
Elle signifie aussi qu'une file locale ne remplace pas une réplication de
stockage.

### 4.4 Capacité Configurée

Chaque instance possède six files de `512 MiB` et une file de sortie de
`1 GiB`, soit une limite théorique cumulée de `4 GiB` par instance et `8 GiB`
pour les deux. Ces capacités ne s'additionnent pas pour calculer la durée de
protection contre une panne OpenSearch : le point déterminant est la file
`malcolm-output` de `1 GiB` sur chaque instance.

---

## 5. Fichiers Créés Ou Modifiés

| Fichier | Rôle |
|---|---|
| `dev/compose/docker-compose.dev.yml` | Monte les paramètres de file sur les sept pipelines des deux Logstash |
| `dev/config/logstash/pipeline-settings/00_persistent_default.conf` | File persistante de `512mb` pour les pipelines standards |
| `dev/config/logstash/pipeline-settings/00_persistent_input.conf` | File persistante de l'entrée avec son worker unique d'origine |
| `dev/config/logstash/pipeline-settings/00_persistent_output.conf` | File de sortie de `1gb` pour absorber une panne OpenSearch |
| `dev/scripts/collect-phase7-state.sh` | Affiche santé, files, registres Filebeat et disque |
| `dev/scripts/check-beats-certificates.sh` | Vérifie chaîne, identité, SAN et expiration des certificats |
| `dev/tests/generate-phase6-events.py` | Génère les événements déterministes réutilisés pour les essais |
| `dev/docs/08_phase7_persistance_reprise_certificats.md` | Présent document de conception, preuve et exploitation |

Les fichiers générés dans `dev/generated/` ne sont pas versionnés. Les clés
privées et les configurations dérivées restent donc propres à la machine.

---

## 6. Vérification De La Configuration Effective

Le contrôle complet se lance avec :

```bash
./dev/scripts/collect-phase7-state.sh
```

Résultat obtenu sur chacune des deux instances :

```text
malcolm-beats:      type=persisted max=536870912
malcolm-enrichment: type=persisted max=536870912
malcolm-filescan:   type=persisted max=536870912
malcolm-input:      type=persisted max=536870912
malcolm-output:     type=persisted max=1073741824
malcolm-suricata:   type=persisted max=536870912
malcolm-zeek:       type=persisted max=536870912
```

`536870912` octets correspondent à `512 MiB` et `1073741824` octets à
`1 GiB`. Cette sortie prouve que les paramètres sont chargés par les processus,
pas seulement présents dans le dépôt.

---

## 7. Essai 1 - Indisponibilité D'OpenSearch

### 7.1 Procédure

OpenSearch a été arrêté, puis 20 000 événements Zeek déterministes portant le
marqueur `PHASE7-OS-OUTAGE-20260728` ont été produits. Les deux Logstash et
Filebeat sont restés actifs.

### 7.2 État Pendant La Panne

```text
Logstash 1, malcolm-output : 10 025 événements, 18 047 503 octets
Logstash 2, malcolm-output :  9 225 événements, 16 633 699 octets
Total inscrit sur disque   : 19 250 événements, 34 681 202 octets
```

Les 750 événements restants étaient en cours de traitement dans les workers de
sortie : deux instances × trois workers × un lot de 125 événements. Cette valeur
correspond exactement à la capacité maximale en vol des workers.

Après redémarrage d'OpenSearch, les files sont revenues à zéro et la requête
suivante a retrouvé les 20 000 événements :

```bash
docker exec oculox-opensearch-1 curl \
  -K /var/local/curlrc/.opensearch.primary.curlrc -sk \
  'https://localhost:9200/arkime_sessions3-*/_count?pretty' \
  -H 'Content-Type: application/json' \
  -d '{"query":{"query_string":{"query":"PHASE7-OS-OUTAGE-20260728*"}}}'
```

```json
{
  "count": 20000
}
```

Il n'y a donc ni perte observée ni document supplémentaire sur cet essai.

---

## 8. Essai 2 - Redémarrage Des Deux Logstash

OpenSearch a été arrêté, puis 8 000 événements identifiés par
`PHASE7-LOGSTASH-RESTART-20260728` ont été envoyés. Avant le redémarrage,
Logstash 1 conservait 7 625 événements dans `malcolm-output`; 375 événements
étaient en vol, soit trois workers × 125 événements.

Les deux Logstash ont ensuite été redémarrés pendant qu'OpenSearch était encore
indisponible. Leur démarrage complet a attendu le retour du service aval, ce qui
est un comportement normal de l'orchestration Malcolm. Après remise en ligne
d'OpenSearch :

```text
Événements retrouvés : 8 000 / 8 000
Événements en file   : 0
Logstash 1           : healthy
Logstash 2           : healthy
OpenSearch           : green
```

Commande de preuve :

```bash
docker exec oculox-opensearch-1 curl \
  -K /var/local/curlrc/.opensearch.primary.curlrc -sk \
  'https://localhost:9200/arkime_sessions3-*/_count?pretty' \
  -H 'Content-Type: application/json' \
  -d '{"query":{"query_string":{"query":"PHASE7-LOGSTASH-RESTART-20260728*"}}}'
```

Le résultat exact est `8000`. La file disque a donc survécu au redémarrage des
processus Logstash.

---

## 9. Essai 3 - Redémarrage Filebeat Et Reprise Par Registre

Les deux Logstash ont été arrêtés, puis 7 000 événements identifiés par
`PHASE7-FILEBEAT-RESTART-20260728` ont été produits. Filebeat a journalisé
l'échec de publication et ses nouvelles tentatives. Filebeat a ensuite été
redémarré avant le retour des deux destinations.

Son registre existait toujours après ce redémarrage :

```text
/usr/share/filebeat-logs/data/registry/filebeat/log.json   69 538 octets
/usr/share/filebeat-logs/data/registry/filebeat/meta.json     15 octets
```

Ce registre associe chaque fichier source à la dernière position acquittée. Il
évite de repartir volontairement du début et permet de reprendre les données
non confirmées. Après retour des deux Logstash, la requête de contrôle a donné :

```json
{
  "count": 7000
}
```

La reprise Filebeat est donc validée sur un redémarrage contrôlé, à condition
que le registre et les fichiers sources soient toujours présents.

---

## 10. Dimensionnement Des Files

### 10.1 Mesure Locale

Pendant l'indisponibilité OpenSearch, 19 250 événements occupaient
34 681 202 octets. La taille moyenne réellement observée dans la file était :

```text
34 681 202 / 19 250 = environ 1 802 octets par événement
```

Cette valeur dépend du type de logs, des enrichissements et de la version de
Logstash. Elle doit être remesurée avec un trafic représentatif du futur site.

### 10.2 Formule

```text
capacité = événements/seconde × octets/événement × durée de panne × 1,10
```

Le facteur `1,10` ajoute une marge minimale de 10 %. Avec une distribution
équilibrée entre deux Logstash, chaque instance reçoit approximativement la
moitié du débit total.

| Débit total | Débit par Logstash | Besoin pour 15 min | Autonomie d'une file de 1 GiB |
|---:|---:|---:|---:|
| 1 000 événements/s | 500 événements/s | environ 850 MiB | environ 18 min |
| 2 000 événements/s | 1 000 événements/s | environ 1 701 MiB | environ 9 min |
| 5 000 événements/s | 2 500 événements/s | environ 4 252 MiB | environ 3,6 min |

La file de sortie actuelle de `1 GiB` convient aux essais et aux interruptions
courtes. Elle ne doit pas être présentée comme un dimensionnement universel de
production. Le dimensionnement final doit partir des événements par seconde,
et non seulement du débit réseau en Mbit/s.

---

## 11. Gestion Du Cycle De Vie TLS

### 11.1 Contrôle Actuel

```bash
./dev/scripts/check-beats-certificates.sh 90
```

Le script vérifie :

- la signature des certificats serveur et client par la CA ;
- le sujet, l'émetteur et le numéro de série ;
- les dates de validité ;
- les noms DNS présents dans le SAN ;
- l'absence d'expiration dans les 90 prochains jours.

Résultat actuel :

```text
Serveur : CN=logstash, SAN=logstash et logstash-2
Client  : CN=filebeat, SAN=filebeat
Fin de validité : 29 octobre 2028
Vérification OpenSSL : OK
```

Les permissions locales ont également été contrôlées : les clés `ca.key`,
`server.key` et `client.key` sont en mode `600`, tandis que les certificats
publics sont en mode `644`. Seul le propriétaire peut donc lire ou modifier les
clés privées.

### 11.2 Rotation Dans L'Environnement De Développement

La commande suivante régénère la PKI locale :

```bash
./dev/scripts/generate-beats-pki.sh --force
```

Les trois services concernés doivent ensuite être recréés ensemble :

```bash
docker compose \
  --project-directory "$PWD" \
  -f docker-compose.yml \
  -f dev/compose/docker-compose.dev.yml \
  --profile malcolm up -d --force-recreate logstash logstash-2 filebeat
```

Cette procédure provoque une courte reconnexion et convient au laboratoire.

### 11.3 Rotation Recommandée En Production

Pour éviter une rupture lors d'un changement d'autorité :

1. créer les nouveaux certificats dans un emplacement de préparation protégé ;
2. vérifier chaîne, SAN, usages de clé et dates avant déploiement ;
3. déployer temporairement un bundle contenant l'ancienne et la nouvelle CA ;
4. remplacer les certificats serveur des deux Logstash ;
5. remplacer le certificat client Filebeat ;
6. contrôler les deux connexions TLS et l'ingestion ;
7. retirer l'ancienne CA seulement lorsque plus aucun ancien certificat ne
   l'utilise.

La clé privée de la CA de développement ne doit pas être copiée sur les hôtes de
production. Une PKI d'organisation ou un gestionnaire de secrets doit émettre
les certificats. La révocation doit être gérée par cette PKI, idéalement avec des
certificats de courte durée et une procédure documentée de remplacement
d'urgence. La PKI locale actuelle ne fournit ni CRL ni service OCSP.

---

## 12. Limites Et Précautions

- La file persistante protège une interruption de processus ou de destination,
  pas la destruction du disque qui la contient.
- Elle doit résider sur un système de fichiers local fiable ; un partage NFS
  n'est pas recommandé pour ce mécanisme.
- Une livraison Beats est de type « au moins une fois ». Une réémission est
  possible ; l'identifiant déterministe utilisé par Malcolm réduit les doublons
  documentaires dans OpenSearch.
- `events_count=0` est l'indicateur fiable d'une file vidée. Des fichiers de
  pages peuvent rester alloués jusqu'au nettoyage interne et ne signifient pas
  nécessairement que des événements attendent encore.
- Les volumes de Filebeat et des deux Logstash ne doivent pas être supprimés par
  un `docker compose down -v` pendant une reprise.
- Le chiffrement protège les données en transit entre Filebeat et Logstash. Il
  ne constitue pas, à lui seul, un chiffrement des volumes au repos.

---

## 13. Commandes D'Exploitation

Préparer puis démarrer le mode réduit :

```bash
./dev/scripts/platform-mode.sh dual-ingest
```

Contrôler la composition sans démarrage :

```bash
./dev/scripts/validate-compose.sh
```

Contrôler l'état, les files, les registres et le disque :

```bash
./dev/scripts/collect-phase7-state.sh
```

Contrôler les certificats à 90 jours :

```bash
./dev/scripts/check-beats-certificates.sh 90
```

Contrôler OpenSearch :

```bash
docker exec oculox-opensearch-1 curl \
  -K /var/local/curlrc/.opensearch.primary.curlrc -sk \
  'https://localhost:9200/_cluster/health?pretty'
```

Arrêter sans supprimer les volumes :

```bash
./dev/scripts/platform-mode.sh dual-stop
```

Ne pas ajouter `-v` à cette dernière opération : cette option supprimerait les
volumes persistants et annulerait précisément le mécanisme de reprise étudié.

---

## 14. Conclusion

La phase 7 est validée dans l'environnement local. Les sept pipelines actifs de
chaque Logstash utilisent désormais une file persistante isolée. Les essais ont
retrouvé exactement 20 000, 8 000 et 7 000 événements après trois types
d'interruption. Filebeat reprend grâce à son registre, les deux Logstash
reprennent grâce à leurs volumes distincts et OpenSearch revient dans l'état
`green` après rattrapage.

La configuration constitue une base de développement résiliente et démontrée.
Avant production, il reste à dimensionner les files avec le débit événementiel
du site, placer les volumes sur un stockage fiable, intégrer les certificats à
la PKI de l'organisation et superviser automatiquement l'expiration, le taux de
remplissage des files et les tentatives de publication.

## Références Techniques

- Elastic, *Persistent queues*: <https://www.elastic.co/guide/en/logstash/current/persistent-queues.html>
- Elastic, *Logstash settings file*: <https://www.elastic.co/docs/reference/logstash/logstash-settings-file>
- Elastic, *Deploying and scaling Logstash*: <https://www.elastic.co/guide/en/logstash/current/deploying-and-scaling.html>

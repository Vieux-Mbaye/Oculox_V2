# Verification rapide Filebeat, load balancing et mTLS

Cette procedure valide le chemin suivant :

```text
Collecteur 10.5.6.3
  -> Filebeat
  -> Logstash 1, 10.5.6.4:5044
  -> Logstash 2, 10.5.6.4:5045
  -> OpenSearch
```

## 1. Etat du collecteur

Sur le collecteur `10.5.6.3` :

```bash
cd ~/Oculox_V2
./oculox status | grep -E 'NAME|filebeat|zeek-live|suricata-live|arkime-live'
```

Les services affiches doivent etre `Up` et `healthy`.

## 2. Configuration Filebeat

Toujours sur le collecteur :

```bash
grep -R -nE 'hosts:|loadbalance:|certificate_authorities:|certificate:|key:' \
  dev/generated/filebeat/
```

Verifier la presence de :

```yaml
hosts:
  - "10.5.6.4:5044"
  - "10.5.6.4:5045"
loadbalance: true
```

## 3. Connexions Filebeat

Afficher les connexions et reconnexions recentes :

```bash
docker logs --since 30m oculox_v2-filebeat-1 2>&1 |
grep -E '5044|5045|Connection .*established|Failed to connect|connection reset'
```

Le resultat doit contenir une connexion `established` vers les deux ports. Une ancienne erreur suivie d'une reconnexion reussie n'est plus active.

Verifier les sockets dans l'espace reseau du conteneur :

```bash
PID=$(docker inspect -f '{{.State.Pid}}' oculox_v2-filebeat-1)
sudo nsenter -t "$PID" -n ss -tnp |
grep '10.5.6.4' |
grep -E ':(5044|5045)'
```

Pendant une transmission, les deux destinations doivent apparaitre en `ESTAB`. En l'absence de nouveaux logs, une connexion peut etre temporairement inactive.

## 4. Etat des deux Logstash

Sur le Core `10.5.6.4` :

```bash
cd ~/Oculox_V2
./oculox status | grep -E 'NAME|logstash'
sudo ss -lntp | grep -E ':(5044|5045)'
```

Les deux Logstash doivent etre `healthy`. Les ports `5044` et `5045` doivent ecouter.

## 5. Preuve de distribution

Sur le Core, relever les compteurs :

```bash
for C in oculox_v2-logstash-1 oculox_v2-logstash-2-1; do
  echo "=== $C ==="
  docker exec "$C" curl -s \
    http://127.0.0.1:9600/_node/stats/pipelines |
  python3 -c '
import json, sys
p = json.load(sys.stdin)["pipelines"]
for name in ("malcolm-beats", "malcolm-input", "malcolm-output"):
    events = p[name]["events"]
    print(name, "in=", events.get("in"), "out=", events.get("out"))
'
done
```

Attendre 30 secondes avec du trafic, puis relancer exactement la meme commande :

```bash
sleep 30
```

Le load balancing est valide lorsque les compteurs augmentent sur les deux instances. La repartition ne sera pas obligatoirement exactement egale, car Filebeat distribue des lots.

## 6. Verification du certificat client

Sur le collecteur :

```bash
cd ~/Oculox_V2
openssl verify \
  -CAfile dev/generated/pki/ca.crt \
  dev/generated/pki/client.crt
```

Resultat attendu :

```text
dev/generated/pki/client.crt: OK
```

## 7. Test mTLS positif

Sur le collecteur :

```bash
for PORT in 5044 5045; do
  echo "=== mTLS positif sur $PORT ==="
  timeout 8 openssl s_client \
    -connect "10.5.6.4:$PORT" \
    -CAfile dev/generated/pki/ca.crt \
    -cert dev/generated/pki/client.crt \
    -key dev/generated/pki/client.key \
    -verify_return_error </dev/null 2>&1 |
  grep -E 'subject=|issuer=|Verification|Verify return code'
done
```

Chaque port doit afficher :

```text
Verification: OK
Verify return code: 0 (ok)
```

## 8. Test mTLS negatif

Tester sans certificat client :

```bash
for PORT in 5044 5045; do
  echo "=== Sans certificat client sur $PORT ==="
  timeout 8 openssl s_client \
    -connect "10.5.6.4:$PORT" \
    -CAfile dev/generated/pki/ca.crt \
    </dev/null 2>&1 |
  grep -Ei 'certificate required|handshake failure|alert|empty client certificate'
done
```

La connexion doit etre refusee. Ce refus prouve que Logstash exige bien un certificat client.

## 9. Verification des files persistantes Logstash

Les commandes de cette section sont a executer sur le Core.

### 9.1 Verifier la configuration

```bash
cd ~/Oculox_V2

for FILE in dev/config/logstash/pipeline-settings/*.conf; do
  echo "=== $FILE ==="
  grep -E 'pipeline.workers|queue.type|queue.max_bytes|path.queue|queue.checkpoint' "$FILE"
done
```

Resultat attendu :

- `queue.type: persisted` dans les trois fichiers ;
- `512mb` pour les pipelines d'entree et de traitement ;
- `1gb` pour le pipeline de sortie ;
- `path.queue: "/logstash-persistent-queue"`.

Les sept pipelines disposent au total d'une capacite nominale de `4 Go` par instance Logstash, soit `8 Go` pour les deux instances. Cette capacite est repartie entre les pipelines et ne constitue pas une file unique de 4 Go.

### 9.2 Verifier les deux volumes independants

```bash
docker volume ls --format '{{.Name}}' |
grep 'logstash-persistent-queue'
```

Resultat attendu :

```text
oculox_v2_logstash-persistent-queue
oculox_v2_logstash-persistent-queue-2
```

Verifier le volume monte dans chaque conteneur :

```bash
for C in oculox_v2-logstash-1 oculox_v2-logstash-2-1; do
  echo "=== $C ==="
  docker inspect -f '{{range .Mounts}}{{println .Type .Name .Destination .RW}}{{end}}' "$C" |
  grep 'logstash-persistent-queue'
done
```

Chaque conteneur doit utiliser un volume different, monte en lecture/ecriture sur `/logstash-persistent-queue`.

### 9.3 Verifier le type et l'occupation de chaque file

```bash
for C in oculox_v2-logstash-1 oculox_v2-logstash-2-1; do
  echo "=== $C ==="
  docker exec "$C" curl -s \
    http://127.0.0.1:9600/_node/stats/pipelines |
  python3 -c '
import json, sys
pipelines = json.load(sys.stdin)["pipelines"]
print("pipeline|type|events_attente|octets|capacite|in|out")
for name, pipeline in sorted(pipelines.items()):
    queue = pipeline.get("queue", {})
    events = pipeline.get("events", {})
    print("%s|%s|%s|%s|%s|%s|%s" % (
        name,
        queue.get("type"),
        queue.get("events_count"),
        queue.get("queue_size_in_bytes"),
        queue.get("max_queue_size_in_bytes"),
        events.get("in"),
        events.get("out"),
    ))
'
done
```

Interpretation :

- `type=persisted` : la file du pipeline est bien persistante ;
- `events_attente=0` : la file est vide, ce qui est normal lorsque la sortie suit le rythme ;
- `events_attente>0` : des evenements attendent sur disque ;
- `capacite=536870912` : limite de 512 Mio ;
- `capacite=1073741824` : limite de 1 Gio pour `malcolm-output` ;
- `in` et `out` qui augmentent : le pipeline traite effectivement des evenements.

Une file vide ne signifie pas qu'elle ne fonctionne pas. Cela signifie que les evenements ont deja ete confirmes par l'etape suivante.

### 9.4 Verifier les fichiers physiques

```bash
for C in oculox_v2-logstash-1 oculox_v2-logstash-2-1; do
  echo "=== $C ==="
  docker exec "$C" sh -c '
    du -sh /logstash-persistent-queue
    find /logstash-persistent-queue -maxdepth 2 -type f \
      -printf "%P %s octets\n" | sort
  '
done
```

Chaque pipeline doit posseder un sous-repertoire contenant notamment :

```text
.queue-version
checkpoint.head
page.N
```

Les fichiers `checkpoint` et `page.N` constituent la preuve que Logstash utilise reellement la file persistante sur disque.

### 9.5 Test de remplissage et de relecture

Ce test arrete volontairement OpenSearch. Ne pas l'executer pendant l'exploitation ou un benchmark. Utiliser une fenetre de maintenance ou l'environnement de developpement :

```bash
RUN_ID="verification_pq_$(date -u +%Y%m%d_%H%M%S)"
./dev/tests/run-phase9-resilience.sh "$RUN_ID"
```

Les preuves attendues sont :

```text
opensearch_outage_queue  PASS
opensearch_recovery      PASS
PHASE9_RESULT=PASS
```

`opensearch_outage_queue` prouve que les evenements sont conserves sur disque pendant l'indisponibilite. `opensearch_recovery` prouve qu'ils sont relus et indexes apres le retour d'OpenSearch.

## 10. Conclusion attendue

La validation est complete si :

- Filebeat est `healthy` ;
- `loadbalance: true` et les deux destinations sont configurees ;
- Filebeat se connecte a `5044` et `5045` ;
- les compteurs progressent sur les deux Logstash ;
- le test mTLS avec certificat reussit ;
- le test sans certificat est refuse ;
- toutes les files Logstash indiquent `type=persisted` ;
- les deux instances utilisent des volumes de queue differents ;
- les checkpoints et pages de queue existent sur disque.

Ne pas executer `run-phase9-resilience.sh` sur une plateforme active sans fenetre de maintenance : ce test arrete volontairement certains services.

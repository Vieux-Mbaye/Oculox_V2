#!/bin/bash
# ════════════════════════════════════════════════════════
# Remplace toutes les images ghcr.io/idaholab/malcolm/
# par suleymane08/oculox: dans les fichiers docker-compose
# Usage : ./update_compose_images.sh [DOCKERHUB_USER]
# ════════════════════════════════════════════════════════
set -e

DOCKERHUB_USER="${1:-suleymane08}"
REPO="oculox"
OCULOS_VERSION="26.06.0"

FILES=(
    "docker-compose.yml"
    "docker-compose-dev.yml"
)

echo "════════════════════════════════════════════════"
echo "  Mise à jour des images Docker Compose"
echo "  Source  : ghcr.io/idaholab/malcolm/<IMAGE>:${OCULOS_VERSION}"
echo "  Cible   : ${DOCKERHUB_USER}/${REPO}:<IMAGE>-${OCULOS_VERSION}"
echo "════════════════════════════════════════════════"

# Liste des images à remplacer
IMAGES=(
    "api"
    "arkime"
    "dashboards-helper"
    "dashboards"
    "file-upload"
    "filebeat-oss"
    "filescan"
    "freq"
    "htadmin"
    "keycloak"
    "logstash-oss"
    "netbox"
    "nginx-proxy"
    "opensearch"
    "pcap-capture"
    "pcap-monitor"
    "postgresql"
    "strelka-backend"
    "strelka-frontend"
    "strelka-manager"
    "suricata"
    "valkey"
    "zeek"
)

for FILE in "${FILES[@]}"; do
    if [ ! -f "$FILE" ]; then
        echo ""
        echo "⚠️  Fichier introuvable : $FILE — ignoré"
        continue
    fi

    echo ""
    echo "▶ Traitement de $FILE"

    # Sauvegarde
    cp "$FILE" "${FILE}.bak"
    echo "  💾 Sauvegarde : ${FILE}.bak"

    COUNT=0
    for IMG in "${IMAGES[@]}"; do
        SOURCE="ghcr.io/idaholab/malcolm/${IMG}:${OCULOS_VERSION}"
        TARGET="${DOCKERHUB_USER}/${REPO}:${IMG}-${OCULOS_VERSION}"

        if grep -q "$SOURCE" "$FILE"; then
            sed -i "s|${SOURCE}|${TARGET}|g" "$FILE"
            echo "  ✅ $IMG"
            COUNT=$((COUNT + 1))
        fi
    done

    echo "  → $COUNT image(s) remplacée(s) dans $FILE"
done

echo ""
echo "════════════════════════════════════════════════"
echo "RÉSUMÉ"
echo "════════════════════════════════════════════════"
for FILE in "${FILES[@]}"; do
    if [ -f "$FILE" ]; then
        echo "  ✅ $FILE mis à jour (sauvegarde : ${FILE}.bak)"
    fi
done
echo ""
echo "Pour annuler :"
for FILE in "${FILES[@]}"; do
    echo "  cp ${FILE}.bak ${FILE}"
done
echo "════════════════════════════════════════════════"

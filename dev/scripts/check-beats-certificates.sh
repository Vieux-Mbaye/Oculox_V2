#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd -- "${SCRIPT_DIR}/../.." && pwd)"
PKI_DIR="${PROJECT_DIR}/dev/generated/pki"
WARN_DAYS="${1:-60}"

if ! [[ "$WARN_DAYS" =~ ^[0-9]+$ ]]; then
    echo "Usage: $0 [nombre_de_jours_d_alerte]" >&2
    exit 2
fi

for required_file in ca.crt server.crt client.crt; do
    if [[ ! -r "${PKI_DIR}/${required_file}" ]]; then
        echo "Fichier absent ou illisible : ${PKI_DIR}/${required_file}" >&2
        exit 1
    fi
done

echo "Vérification de la chaîne de confiance"
openssl verify \
    -CAfile "${PKI_DIR}/ca.crt" \
    "${PKI_DIR}/server.crt" \
    "${PKI_DIR}/client.crt"

for certificate in server client; do
    cert_path="${PKI_DIR}/${certificate}.crt"
    echo
    echo "Certificat ${certificate}"
    openssl x509 -in "$cert_path" -noout \
        -subject -issuer -serial -dates -ext subjectAltName

    if ! openssl x509 -in "$cert_path" -noout \
        -checkend "$((WARN_DAYS * 86400))"; then
        echo "ALERTE : expiration dans moins de ${WARN_DAYS} jours" >&2
        exit 1
    fi
done

echo
echo "Résultat : chaîne valide et certificats valides au-delà de ${WARN_DAYS} jours."

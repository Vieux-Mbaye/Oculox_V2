#!/usr/bin/env bash

set -euo pipefail

# determine the location of the cacerts file we're adding to

JDK_DIR="$(find /usr -type d -name jdk -print -quit)"

CACERTS_FILE="$(realpath "$JDK_DIR/lib/security/cacerts")"
KEYTOOL_BIN="$JDK_DIR"/bin/keytool

if [[ ! -f "$CACERTS_FILE" ]] || [[ ! -x "$KEYTOOL_BIN" ]]; then
  echo "Unable to locate cacerts and/or keytool " >&2
  exit 1
fi

unset TRUSTED_CA_DIR
TRUSTED_CA_DIRNAME=${CA_DIR:-"ca-trust"}
CA_DIR_PARENTS=(
  "$JDK_DIR"/../"$TRUSTED_CA_DIRNAME"
  /etc/"$TRUSTED_CA_DIRNAME"
  /opt/"$TRUSTED_CA_DIRNAME"
  /var/local/"$TRUSTED_CA_DIRNAME"
  /"$TRUSTED_CA_DIRNAME"
)
for i in "${CA_DIR_PARENTS[@]}"; do
  if [[ -d "$i" ]]; then
    TRUSTED_CA_DIR="$i"
    break;
  fi
done

if [[ -z ${TRUSTED_CA_DIR:-} ]] || [[ ! -d "$TRUSTED_CA_DIR" ]]; then
  echo "Unable to locate directory containing trusted CA certificates" >&2
  exit 1
fi

echo
find "$TRUSTED_CA_DIR" -type f -print0 | while read -d $'\0' CRT_FILE; do
  CRT_FILE_BASE="$(basename "$CRT_FILE" | sed 's/\.[^.]*$//')"
  if [[ -n $CRT_FILE_BASE ]] && [[ "$CRT_FILE_BASE" != \.* ]] ; then
    echo "Importing \"$CRT_FILE_BASE\"... "
    # A trust bundle can contain several PEM certificates during CA rotation.
    PEM_DIR="$(mktemp -d)"
    WORK_STORE="$(mktemp "${CACERTS_FILE}.rotation.XXXXXX")"
    trap 'rm -rf "$PEM_DIR"; rm -f "$WORK_STORE"' EXIT
    cp --preserve=mode "$CACERTS_FILE" "$WORK_STORE"
    awk -v directory="$PEM_DIR" '
      /^-----BEGIN CERTIFICATE-----$/ { number++; file=sprintf("%s/%04d.crt", directory, number) }
      number && file != "" { print > file }
      /^-----END CERTIFICATE-----$/ { close(file); file="" }
    ' "$CRT_FILE"
    shopt -s nullglob
    CERTIFICATES=("$PEM_DIR"/*.crt)
    shopt -u nullglob
    ((${#CERTIFICATES[@]} > 0)) || { echo "No PEM certificates in $CRT_FILE" >&2; exit 1; }
    while IFS= read -r ALIAS; do
      if [[ "$ALIAS" == "$CRT_FILE_BASE" || "$ALIAS" == "$CRT_FILE_BASE"-* ]]; then
        "$KEYTOOL_BIN" -delete -keystore "$WORK_STORE" -alias "$ALIAS" -storepass changeit
      fi
    done < <("$KEYTOOL_BIN" -list -keystore "$WORK_STORE" -storepass changeit 2>/dev/null | awk -F, 'NF > 1 {print $1}')
    INDEX=0
    for CERTIFICATE in "${CERTIFICATES[@]}"; do
      openssl x509 -in "$CERTIFICATE" -noout >/dev/null
      INDEX=$((INDEX + 1))
      "$KEYTOOL_BIN" -importcert -keystore "$WORK_STORE" -trustcacerts -file "$CERTIFICATE" \
        -alias "${CRT_FILE_BASE}-${INDEX}" -storepass changeit -noprompt
    done
    mv -f "$WORK_STORE" "$CACERTS_FILE"
    rm -rf "$PEM_DIR"
    trap - EXIT
    echo
  fi
done

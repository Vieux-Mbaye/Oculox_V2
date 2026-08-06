#!/bin/sh

set -eu

SOURCE_DIR=/opt/oculox-branding
HTML_DIR=/usr/share/nginx/html

# The upstream entrypoint replaces runtime URLs in these writable copies.
install -m 0644 "$SOURCE_DIR/landingpage/index.html" "$HTML_DIR/index.html"
install -m 0644 "$SOURCE_DIR/landingpage/401.html" "$HTML_DIR/401.html"
install -m 0644 "$SOURCE_DIR/landingpage/404.html" "$HTML_DIR/404.html"
install -m 0644 "$SOURCE_DIR/landingpage/502.html" "$HTML_DIR/502.html"

install -d -m 0755 "$HTML_DIR/assets/img"
install -m 0644 "$SOURCE_DIR/Oculox_logo.png" "$HTML_DIR/assets/img/Oculox_logo.png"
install -m 0644 "$SOURCE_DIR/oculox-icon.png" "$HTML_DIR/oculox-icon.png"
install -m 0644 "$SOURCE_DIR/oculox-icon.png" "$HTML_DIR/assets/oculox-icon.png"

exec /usr/local/bin/docker_entrypoint.sh "$@"

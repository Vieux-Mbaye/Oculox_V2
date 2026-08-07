#!/bin/sh

set -eu

SOURCE_DIR=/opt/oculox-branding
LANDINGPAGE_DIR=/opt/oculox-landingpage
HTML_DIR=/usr/share/nginx/html

# The upstream entrypoint replaces runtime URLs in these writable copies.
install -m 0644 "$LANDINGPAGE_DIR/index.html" "$HTML_DIR/index.html"
install -m 0644 "$LANDINGPAGE_DIR/401.html" "$HTML_DIR/401.html"
install -m 0644 "$LANDINGPAGE_DIR/404.html" "$HTML_DIR/404.html"
install -m 0644 "$LANDINGPAGE_DIR/502.html" "$HTML_DIR/502.html"

install -d -m 0755 "$HTML_DIR/assets" "$HTML_DIR/assets/img"

# A single pair of tracked assets drives every Oculox surface. Compatibility
# aliases remain available for upstream pages that still expect older paths.
install -m 0644 "$SOURCE_DIR/logo_Oculox.png" "$HTML_DIR/assets/img/logo_Oculox.png"
install -m 0644 "$SOURCE_DIR/logo_Oculox.png" "$HTML_DIR/assets/img/Oculox_logo.png"
install -m 0644 "$SOURCE_DIR/icone_logo.png" "$HTML_DIR/assets/img/icone_logo.png"
install -m 0644 "$SOURCE_DIR/icone_logo.png" "$HTML_DIR/assets/oculox-icon.png"
install -m 0644 "$SOURCE_DIR/icone_logo.png" "$HTML_DIR/oculox-icon.png"
install -m 0644 "$SOURCE_DIR/icone_logo.png" "$HTML_DIR/favicon.ico"

exec /usr/local/bin/docker_entrypoint.sh "$@"

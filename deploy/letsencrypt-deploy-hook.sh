#!/bin/sh
# certbot deploy hook: install the renewed certificate for the relay (SMTP)
# and nginx (admin UI), then reload both.
#   certbot certonly --standalone -d relay.example.com \
#     --deploy-hook /opt/smtp-relay/deploy/letsencrypt-deploy-hook.sh
set -eu
RELAY_DIR="${RELAY_DIR:-/opt/smtp-relay}"
TLS="$RELAY_DIR/smtp-tls"
mkdir -p "$TLS/nginx"
# relay runs as uid 1000, nginx as uid 101 — each gets its own readable copy.
install -m 644 -o 1000 -g 1000 "$RENEWED_LINEAGE/fullchain.pem" "$TLS/cert.pem"
install -m 600 -o 1000 -g 1000 "$RENEWED_LINEAGE/privkey.pem" "$TLS/key.pem"
install -m 644 -o 101 -g 101 "$RENEWED_LINEAGE/fullchain.pem" "$TLS/nginx/fullchain.pem"
install -m 600 -o 101 -g 101 "$RENEWED_LINEAGE/privkey.pem" "$TLS/nginx/privkey.pem"
cd "$RELAY_DIR"
# On first issuance the stack may not run yet; it picks the files up on start.
if [ -n "$(docker compose ps -q relay 2>/dev/null)" ]; then
  docker compose restart relay nginx
fi

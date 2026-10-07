#!/bin/sh
# certbot deploy hook: copy the renewed certificate for the relay and reload it.
#   certbot certonly --standalone --http-01-address <public-ip> -d relay.example.com \
#     --deploy-hook /opt/smtp-relay/deploy/letsencrypt-deploy-hook.sh
set -eu
RELAY_DIR="${RELAY_DIR:-/opt/smtp-relay}"
mkdir -p "$RELAY_DIR/smtp-tls"
install -m 644 -o 1000 -g 1000 "$RENEWED_LINEAGE/fullchain.pem" "$RELAY_DIR/smtp-tls/cert.pem"
install -m 600 -o 1000 -g 1000 "$RENEWED_LINEAGE/privkey.pem" "$RELAY_DIR/smtp-tls/key.pem"
cd "$RELAY_DIR"
# On first issuance the stack may not run yet; it picks the files up on start.
if [ -n "$(docker compose ps -q relay 2>/dev/null)" ]; then
  docker compose restart relay
fi

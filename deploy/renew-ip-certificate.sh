#!/bin/sh
set -eu
cd /opt/research-explorer

/usr/bin/docker run --rm \
  -v /opt/research-explorer/certbot/conf:/etc/letsencrypt \
  -v /opt/research-explorer/certbot/www:/var/www/certbot \
  certbot/certbot:v5.4.0 \
  renew --cert-name research-ip --non-interactive

/usr/bin/docker compose \
  -f compose.yaml \
  -f compose.https.yaml \
  -f compose.ip.yaml \
  exec -T proxy \
  caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile --force


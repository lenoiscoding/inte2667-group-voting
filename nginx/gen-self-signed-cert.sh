#!/bin/sh
# Req 6 - on first start, create a self-signed certificate so the demo runs
# over HTTPS with no manual steps. It is kept in the "certs" volume, so it
# survives restarts. Use a CA-issued certificate (e.g. Let's Encrypt) in
# production.
set -eu

dir=/etc/nginx/certs
if [ ! -s "$dir/server.crt" ]; then
    mkdir -p "$dir"
    openssl req -x509 -nodes -newkey rsa:2048 -days 365 \
        -subj "/CN=localhost" \
        -addext "subjectAltName=DNS:localhost,IP:127.0.0.1" \
        -keyout "$dir/server.key" -out "$dir/server.crt"
    chmod 600 "$dir/server.key"
fi

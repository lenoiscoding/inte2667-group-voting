FROM nginx:1.27-alpine

RUN apk add --no-cache openssl

COPY default.conf /etc/nginx/conf.d/default.conf
# Scripts in /docker-entrypoint.d/ run before nginx starts.
COPY --chmod=755 gen-self-signed-cert.sh /docker-entrypoint.d/40-gen-self-signed-cert.sh

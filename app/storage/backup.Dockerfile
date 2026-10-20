# Req 11: pg_dump from the same PostgreSQL version as the db service,
# plus Python to encrypt the dump with storage.py.
FROM postgres:16-alpine
RUN apk add --no-cache python3 py3-cryptography
WORKDIR /backup
COPY app/storage/storage.py app/storage/backup.py ./
ENTRYPOINT ["python3", "backup.py"]

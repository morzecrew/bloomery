#!/bin/sh
# Bootstrap Lakekeeper and create the warehouse Trino's catalog points at.
# Runs as a one-shot compose service once Lakekeeper reports healthy; both
# calls are idempotent, so `compose up` twice is not an error.
set -eu

LAKEKEEPER="${LAKEKEEPER_URL:-http://lakekeeper:8181}"

# 204 the first time, 409 ("already bootstrapped") every time after.
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  "$LAKEKEEPER/management/v1/bootstrap" \
  -H 'Content-Type: application/json' \
  -d '{"accept-terms-of-use": true}')
echo "bootstrap: HTTP $code"
case "$code" in 2*|409) ;; *) echo "bootstrap failed"; exit 1 ;; esac

# The warehouse is what `trino/iceberg.properties` names as
# `iceberg.rest-catalog.warehouse`. Its storage profile points at MinIO; the
# credential is what Lakekeeper writes metadata with, and Trino reaches the
# data files itself using the same key from its own config.
code=$(curl -sS -o /dev/null -w '%{http_code}' -X POST \
  "$LAKEKEEPER/management/v1/warehouse" \
  -H 'Content-Type: application/json' \
  -d '{
        "warehouse-name": "demo",
        "project-id": "00000000-0000-0000-0000-000000000000",
        "storage-profile": {
          "type": "s3",
          "bucket": "warehouse",
          "key-prefix": "demo",
          "endpoint": "http://minio:9000",
          "region": "local-01",
          "path-style-access": true,
          "flavor": "s3-compat",
          "sts-enabled": false
        },
        "storage-credential": {
          "type": "s3",
          "credential-type": "access-key",
          "aws-access-key-id": "minio-admin",
          "aws-secret-access-key": "minio-admin-password"
        }
      }')
echo "warehouse: HTTP $code"
case "$code" in 2*|409) ;; *) echo "warehouse creation failed"; exit 1 ;; esac

echo "lakehouse ready"

#!/usr/bin/env bash

set -euo pipefail

now() {
    date "+%Y-%m-%d %H:%M:%S"
}

tear_down() {
    docker image rm npg-irods-python-app >/dev/null 2>&1 || true
}

trap tear_down EXIT

echo "[$(now)] Testing..."

mkdir -p coverage
docker compose run --build --quiet --remove-orphans --rm \
    --volume ./coverage:/coverage \
    app \
    pytest --it "$@"

# Debug using `docker compose exec app bash`

echo "[$(now)] ...testing complete."
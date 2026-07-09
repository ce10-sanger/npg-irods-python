# Development test loop

The default `./test.sh` path is still the full Docker rebuild path. For a faster
inner loop, use one of these prototype paths.

## Start services

```bash
./scripts/dev-test-up
```

This starts MySQL, iRODS, a reusable iRODS client container, and a reusable app
container. It also creates `.dev/bin` symlinks for iRODS commands used by the
host test loop.

## Run pytest on the host

```bash
./scripts/dev-test-host tests/test_diff.py
```

Python and pytest run from `.venv` on the host. iRODS commands are resolved via
`.dev/bin` into the long-lived `irods-clients` container. MySQL is reached on
`127.0.0.1:3306`.

Set `NPG_IRODS_DEV_SYNC=1` to reinstall Python dependencies into `.venv`.

## Run pytest in the app container

```bash
./scripts/dev-test-container tests/test_diff.py
```

Pytest runs inside the long-lived `app-dev` container. The `src`, `tests`, and
`scripts` directories are bind-mounted, so source edits are visible without
rebuilding the image.

## Stop services

```bash
./scripts/dev-test-down
```

This stops containers and removes the compose network, but leaves images in
place for the next run.

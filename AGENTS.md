# Repository Guidance

## Project overview

- This is a Python 3.12+ project for managing NPG data and metadata in iRODS.
- Application code is under `src/npg_irods/`, tests are under `tests/`, and CLI
  entry points are declared in `pyproject.toml`.

## Testing

- Tests expect configured iRODS clients, an iRODS server, and MySQL. Do not use
  host `pytest` as canonical validation unless that environment is already
  available.
- Use Docker Compose for the full test suite:

  ```shell
  docker compose run --build --rm app pytest --it
  ```

- Add a test path or pytest arguments after `--it` for focused validation:

  ```shell
  docker compose run --build --rm app pytest --it tests/test_diff.py
  ```

- Keep `--build` after source changes because the application source is copied
  into the image rather than bind-mounted.
- See `README.md`, under **Building and testing**, for host and container setup
  details.

## Formatting

Run the same Black check as CI:

```shell
docker compose run --build --rm --no-deps app \
    black --check --diff ./src ./tests ./scripts
```

## Completion criteria

- Add or update tests for behavior changes.
- Run focused tests while iterating and the full suite for broad or shared
  changes.
- Report any validation command that could not run and the exact failure.

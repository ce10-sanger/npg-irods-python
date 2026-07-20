# npg-irods-python

[![Unit tests](https://github.com/wtsi-npg/npg-irods-python/actions/workflows/run-tests.yml/badge.svg)](https://github.com/wtsi-npg/npg-irods-python/actions/workflows/run-tests.yml)

## Overview

This repository is the home of application code used by NPG to manage data and
metadata in WSI [iRODS](https://irods.org).

It includes:

- iRODS CLI utilities
    - Metadata verification and repair.
    - Checksum verification and repair.
    - Replica verification and repair.
    - Safe bulk copy.
    - Safe bulk deletion.

- General purpose API
    - Managing standard WSI iRODS metadata.

- Analysis platform-specific API and CLI utilities
    - Managing Oxford Nanopore metadata and permissions.

## Installing

The easiest way to get the CLI scripts is to use the pre-built Docker image (the image
includes the necessary iRODS clients):

```shell
# Latest release
docker pull ghcr.io/wtsi-npg/npg-irods-python:latest

# Specific version
docker pull ghcr.io/wtsi-npg/npg-irods-python:1.1.0
```

## Building and testing

### Running tests

#### Running directly in a configured environment

To run the tests directly, you will need to have the `irods` clients installed
(`icommands` and `baton`). The environment must either be Linux or provide
containerised clients through proxy wrappers with the same command names.

You will also need working iRODS and MySQL servers with the test configuration
expected by the repository.

With this in place, you can run the tests with the following command:

    pytest --it

#### Running in a container

Docker Compose is the recommended option when the host does not already have the
test infrastructure. It runs the tests in Linux and starts the required iRODS and
MySQL services.

To run the tests in a container, you will need to have Docker installed.

Run the full test suite with:

    docker compose run --build --rm app pytest --it

To run a focused test file or pass other pytest arguments, append them after
`--it`. For example:

    docker compose run --build --rm app pytest --it tests/test_diff.py

The first run will take longer while Docker builds the application image and pulls
the service images. Keep `--build` after source changes because the source tree is
copied into the application image rather than bind-mounted.

## Creating a release

Releases are created automatically by GitHub Actions when a new tag is pushed to the
master branch. In a local clone of the repository:

1. Run `git checkout devel ` to check out the `devel` branch
2. Run `git pull` to update the `devel` branch
3. Run `git checkout master` to check out the `master` branch
4. Run `git merge devel ` to merge the `devel` branch into the `master` branch
5. Run `git tag -a X.Y.Z -m X.Y.Z` to create a new tag
6. Push the branch and tag with `git push --tags origin master`

## Logging

### Structured logging

Most of the scripts have a CLI option `--json` to enable structured logging in JSON.
This is preferred when the scripts are run as a service, particularly when forwarding
logs to an aggregator (such as ELK) because it allows more effective filtering than
unstructured messages.

### Logging configuration

This package uses the standard Python logging library to deliver log messages. When a
script has the option `--log-config`, the user can specify a configuration file
to modify logging behaviour e.g. to set log levels and add new log destinations.

The configuration file must be JSON, in the form of a standard logging [configuration
dictionary](https://docs.python.org/3/library/logging.config.html#configuration-dictionary-schema).

An example configuration is provided in the file `logging.json`:

```json
{
  "version": 1,
  "disable_existing_loggers": false,
  "formatters": {
    "stderr": {
      "format": "%(message)s"
    },
    "syslog": {
      "format": "%(message)s"
    }
  },
  "handlers": {
    "stderr": {
      "class": "logging.StreamHandler",
      "level": "INFO",
      "formatter": "stderr",
      "stream": "ext://sys.stderr"
    },
    "syslog": {
      "class": "logging.handlers.SysLogHandler",
      "level": "ERROR",
      "formatter": "syslog",
      "address": "/dev/log"
    }
  },
  "root": {
    "level": "ERROR",
    "handlers": [
      "stderr",
      "syslog"
    ]
  }
}
```

In the `stderr` handler, the `level` option refers to the starting priority to consider.
Its priority of INFO means that it will log all messages to STDERR starting from INFO,
including WARNING, ERROR and FATAL. Whereas the `syslog` handler will log ERROR and
FATAL to the syslog.

A formatter can be specified for each handler with different variable. However, as we
rely on `structlog` to pre-format the messages, we simply forward the pre-formatted
string.

## Architecture

- `publish-directory` removes public permissions unless explicitly specified by `--group public` to be able to publish privately whilst having iRODS inheritance enabled on sequencing runs collections ([ADR 1](/docs/decisions/adr-01-publish-directory-removes-public-permissions-by-default.md))

# -*- coding: utf-8 -*-
#
# Copyright © 2026 Genome Research Ltd. All rights reserved.
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import argparse
import json
import sys
from pathlib import Path, PurePath

import structlog
from npg.cli import add_logging_arguments
from npg.log import configure_structlog

from npg_irods import add_appinfo_structlog_processor, version
from npg_irods.diff import (
    DIFFERENCE_STATUSES,
    KIND_DIRECTORY,
    STATUS_ERROR,
    STATUS_SYMBOLS,
    iter_diff_directory,
)
from npg_irods.utilities import make_get_checksum, read_md5_file, sanitise_path
from npg_irods.xenium import iter_output_directories, xenium_irods_partial_path

description = """
Find Xenium result directories below a local root and compare each with its expected
iRODS collection.
"""


def logger():
    return structlog.get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_logging_arguments(parser)
    parser.add_argument(
        "root",
        help="Root directory to search for Xenium result directories.",
        type=str,
    )
    parser.add_argument(
        "collection",
        help="The iRODS root collection containing Xenium results.",
        type=str,
    )
    checksums_group = parser.add_mutually_exclusive_group(required=False)
    checksums_group.add_argument(
        "--use-checksum-files",
        help="Read local MD5 checksums from files alongside the data files with "
        "the same name as the data file but with an additional '.md5' extension.",
        action="store_true",
    )
    checksums_group.add_argument(
        "--use-checksums-file",
        help="Read local MD5 checksums from the specified GNU md5sum-format file.",
        type=str,
        default=None,
    )
    parser.add_argument(
        "--json", help="Output in JSON Lines format.", action="store_true"
    )
    parser.add_argument(
        "--version",
        help="Print the version and exit.",
        action="version",
        version=version(),
    )

    args = parser.parse_args()
    configure_structlog(
        config_file=args.log_config,
        debug=args.debug,
        verbose=args.verbose,
        colour=args.colour,
        json=args.log_json,
    )
    add_appinfo_structlog_processor()

    local_root = Path(sanitise_path(args.root))
    irods_root = PurePath(sanitise_path(args.collection))

    checksum_fn = None
    if args.use_checksum_files:
        checksum_fn = read_md5_file
    elif args.use_checksums_file:
        try:
            checksum_fn = make_get_checksum(Path(args.use_checksums_file))
        except Exception as e:
            logger().error(
                "Failed to read checksums file",
                path=args.use_checksums_file,
                error=str(e),
            )
            sys.exit(1)

    has_error = False
    has_difference = False

    for experiment in iter_output_directories(local_root):
        try:
            collection = irods_root / xenium_irods_partial_path(experiment)
        except Exception as e:
            has_error = True
            logger().error(
                "Failed to map Xenium result directory",
                experiment=experiment.as_posix(),
                error=str(e),
            )
            continue

        if not args.json:
            print(f"# {experiment.as_posix()} {collection.as_posix()}", flush=True)

        try:
            for row in iter_diff_directory(
                experiment, collection, local_checksum=checksum_fn
            ):
                if args.json:
                    print(
                        json.dumps(
                            {
                                "experiment": experiment.as_posix(),
                                "collection": collection.as_posix(),
                                "status": row.status,
                                "path": row.path,
                                "kind": row.kind,
                            }
                        ),
                        flush=True,
                    )
                else:
                    print(
                        f"{STATUS_SYMBOLS[row.status]} {_display_path(row)}",
                        flush=True,
                    )

                if row.status == STATUS_ERROR:
                    has_error = True
                elif row.status in DIFFERENCE_STATUSES:
                    has_difference = True
        except Exception as e:
            has_error = True
            logger().error(
                "Failed to diff Xenium result directory",
                experiment=experiment.as_posix(),
                collection=collection.as_posix(),
                error=str(e),
            )

    if has_error or has_difference:
        sys.exit(1)


def _display_path(row):
    if row.kind == KIND_DIRECTORY:
        return f"{row.path}/"

    return row.path


if __name__ == "__main__":
    main()

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
from pathlib import Path

import structlog
from npg.cli import add_logging_arguments, integer_in_range
from npg.log import configure_structlog

from npg_irods import add_appinfo_structlog_processor, version
from npg_irods.diff import diff_directory, has_errors
from npg_irods.utilities import make_get_checksum, read_md5_file

description = """
Compare a local directory with an iRODS collection.

The output contains one row for each relative path below the two roots. Status values
are:

    =  path exists on both sides and matches
    >  path exists only in the local directory
    <  path exists only in the iRODS collection
    *  path exists on both sides but differs
    !  path could not be compared because of an error
"""


def logger():
    return structlog.get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    add_logging_arguments(parser)
    parser.add_argument(
        "directory",
        help="The local directory to compare.",
        type=str,
    )
    parser.add_argument(
        "collection",
        help="The iRODS collection to compare.",
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
        "--num-clients",
        help="Number of iRODS clients to use for the operation, maximum 24. "
        "Optional, defaults to 4.",
        type=integer_in_range(1, 24),
        default=4,
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
            raise e

    try:
        rows = diff_directory(
            args.directory,
            args.collection,
            local_checksum=checksum_fn,
            num_clients=args.num_clients,
        )
    except Exception as e:
        logger().error(
            "Failed to diff directory",
            directory=args.directory,
            collection=args.collection,
            error=str(e),
        )
        sys.exit(1)

    for row in rows:
        if args.json:
            print(json.dumps({"status": row.status, "path": row.path}))
        else:
            print(f"{row.status} {row.path}")

    if has_errors(rows):
        sys.exit(1)


if __name__ == "__main__":
    main()

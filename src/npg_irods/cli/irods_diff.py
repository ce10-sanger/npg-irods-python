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
from npg_irods.diff import (
    DIFFERENCE_STATUSES,
    EXIT_DIFFERENCE,
    EXIT_ERROR,
    KIND_DIRECTORY,
    STATUS_ERROR,
    STATUS_SYMBOLS,
    diff_row_to_dict,
    format_diff_details,
    iter_diff_paths,
    make_diff_filter,
)
from npg_irods.utilities import make_get_checksum, read_md5_file

description = """
Compare a local filesystem path with an iRODS path.

The supported path pairs are a local directory and iRODS collection, or a local
file and iRODS data object.

The output contains one row for each relative path below the two roots. Plain text
status symbols are:

    =  path exists on both sides and matches
    >  path exists only in the local filesystem
    <  path exists only in iRODS
    *  path exists on both sides but differs
    !  path could not be compared because of an error

With --json, status values are same, local_only, irods_only, different, or error.
For a file and data object comparison, path is the local file basename.
File differences include either the local and iRODS sizes or MD5 checksums.

Exit status is 0 when all compared paths are the same, 1 when differences are
found, and 2 when an error is encountered.

Examples:

Compare a file with a data object:

    irods-diff FILE DATA_OBJECT

Exclude macOS Finder metadata files at any depth:

    irods-diff --exclude '(^|/)\\.DS_Store$' DIRECTORY COLLECTION
"""

epilog = """
notes:
  Replicas: irods-diff works with iRODS at the abstraction level of a virtual
    filesystem and does not verify the health or consistency of replicas.
    If your use case requires this, consider running check-checksums on the
    output of irods-diff.
"""


def logger():
    return structlog.get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_logging_arguments(parser)
    parser.add_argument(
        "local_path",
        metavar="LOCAL_PATH",
        help="The local directory or file to compare.",
        type=str,
    )
    parser.add_argument(
        "irods_path",
        metavar="IRODS_PATH",
        help="The iRODS collection or data object to compare.",
        type=str,
    )
    parser.add_argument(
        "--exclude",
        help="Exclude paths matching the given regular expression. May be used "
        "multiple times to filter on additional regular expressions. Exclude "
        "regular expressions are applied after any include regular expressions. "
        "Paths are relative to the compared directory and collection roots. "
        "Only valid for directory and collection comparisons. Optional, "
        "defaults to none.",
        type=str,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--include",
        help="Include paths matching the given regular expression. Only matching "
        "paths will be compared, all others will be ignored. If more than one "
        "regex is supplied, the matches for all of them are aggregated. "
        "Paths are relative to the compared directory and collection roots. "
        "Only valid for directory and collection comparisons. Optional, "
        "defaults to all.",
        type=str,
        action="append",
        default=[],
    )
    parser.add_argument(
        "--include-top-level-files",
        help="Include top level files and data objects. Composes with other filters. "
        "Only valid for directory and collection comparisons.",
        action="store_true",
    )
    parser.add_argument(
        "--exclude-md5",
        help="Exclude md5 files and data objects. Composes with other filters. "
        "Only valid for directory and collection comparisons.",
        action="store_true",
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
        "--no-recurse-missing-dirs",
        help="Report directories that exist only on one side, but do not recurse "
        "into them. Only valid for directory and collection comparisons.",
        action="store_true",
    )
    parser.add_argument(
        "--exit-on-difference",
        help="Exit with status 1 after printing the first difference.",
        action="store_true",
    )
    parser.add_argument(
        "--exit-on-error",
        help="Exit with status 2 after printing the first error.",
        action="store_true",
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
            sys.exit(EXIT_ERROR)

    filter_fn = (
        make_diff_filter(
            include_patterns=args.include,
            exclude_patterns=args.exclude,
            include_top_level_files=args.include_top_level_files,
            exclude_md5=args.exclude_md5,
        )
        if args.exclude
        or args.include
        or args.include_top_level_files
        or args.exclude_md5
        else None
    )

    has_error = False
    has_difference = False
    try:
        for row in iter_diff_paths(
            args.local_path,
            args.irods_path,
            local_checksum=checksum_fn,
            filter_fn=filter_fn,
            num_clients=args.num_clients,
            no_recurse_missing_dirs=args.no_recurse_missing_dirs,
        ):
            if args.json:
                print(json.dumps(diff_row_to_dict(row)), flush=True)
            else:
                fields = [STATUS_SYMBOLS[row.status], _display_path(row)]
                fields.extend(format_diff_details(row))
                print(" ".join(fields), flush=True)

            if row.status == STATUS_ERROR:
                has_error = True
                if args.exit_on_error:
                    sys.exit(EXIT_ERROR)
            elif row.status in DIFFERENCE_STATUSES:
                has_difference = True
                if args.exit_on_difference:
                    sys.exit(EXIT_DIFFERENCE)
    except Exception as e:
        logger().error(
            "Failed to diff paths",
            local_path=args.local_path,
            irods_path=args.irods_path,
            error=str(e),
        )
        sys.exit(EXIT_ERROR)

    if has_error:
        sys.exit(EXIT_ERROR)
    if has_difference:
        sys.exit(EXIT_DIFFERENCE)


def _display_path(row):
    if row.kind == KIND_DIRECTORY:
        return f"{row.path}/"

    return row.path


if __name__ == "__main__":
    main()

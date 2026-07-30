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
from pathlib import Path

from typing import Callable

import argparse
import sys

import structlog
from npg.cli import add_io_arguments, add_logging_arguments, open_input, open_output
from npg.log import configure_structlog

from npg_irods import add_appinfo_structlog_processor, version
from npg_irods.cli import register_term_handling
from npg_irods.utilities import sanitise_path, read_md5_file, make_get_checksum
from npg_irods.xenium import publish_result_dirs

description = """Publishes each Xenium result directory in its input to its own iRODS
collection, maintaining the directory's structural organisation and adding metadata
taken from the experiment.xenium file in the that directory.

A single Xenium run may have multiple associated result directories. In iRODS, these
are grouped by instrument name and then run name, under a common root collection:

    <iRODS root path>/<instrument name>/<run name>/<result directory name>/<result directory content>

A subset of the keys and values from the experiment.xenium file are added as metadata
to the iRODS collection. The metadata includes information such as the instrument name,
run name, and other relevant details from the Xenium experiment.

This script is not responsible for adding LIMS-related tracking metadata.
"""


def logger():
    return structlog.get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser = add_logging_arguments(parser)
    parser = add_io_arguments(parser)

    parser.add_argument(
        "collection",
        help="The iRODS collection to publish the local directory to.",
        type=str,
    )
    parser.add_argument(
        "--print-success",
        help="Print to output those paths that were successfully processed.",
        action="store_true",
    )
    parser.add_argument(
        "--print-fail",
        help="Print to output those paths that were not successfully processed.",
        action="store_true",
    )
    checksums_group = parser.add_mutually_exclusive_group(required=False)
    checksums_group.add_argument(
        "--use-checksum-files",
        help="Expect checksum files to be present alongside the data files with "
        "the same name as the data file but with an additional '.md5' extension"
        "e.g. 'data.txt' and 'data.txt.md5'. Each checksum file should contain only "
        "the single MD5 checksum of the corresponding data file. This avoids having "
        "to calculate the checksums during the publish process. If this option is "
        "enabled and a checksum file cannot be read, an error will be raised for "
        "that file. Optional, defaults to false.",
        action="store_true",
    )
    checksums_group.add_argument(
        "--use-checksums-file",
        help="Expect checksums to be present in a checksums file at path specified "
        "following GNU coreutils md5sum format. This avoids having to calculate the "
        "checksums during the publish process. If this option is enabled and a "
        "checksum is missing or stale, an error will be raised for that file. "
        "Optional, defaults to none.",
        type=str,
        default=None,
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

    register_term_handling()

    input_path = sanitise_path(args.input)
    output_path = sanitise_path(args.output)

    checksum_fn: Callable[[Path | str], str] | None
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
    else:
        checksum_fn = None

    with open_input(input_path, encoding="utf-8") as reader:
        with open_output(output_path, encoding="utf-8") as writer:

            num_dirs, num_published, num_failed = publish_result_dirs(
                reader,
                writer,
                remote_root=args.collection,
                print_success=args.print_success,
                print_fail=args.print_fail,
                local_checksum=checksum_fn,
            )

            if num_failed:
                logger().error(
                    "Some result directories could not be published cleanly",
                    num_dirs=num_dirs,
                    num_published=num_published,
                    num_failed=num_failed,
                )
                sys.exit(1)

            logger().info(
                "All result directories published",
                num_dirs=num_dirs,
                num_published=num_published,
                num_failed=num_failed,
            )

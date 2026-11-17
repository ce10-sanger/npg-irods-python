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
# @author Calum Eadie <ce10@sanger.ac.uk>

import sys
from pathlib import Path
import argparse

import structlog
from npg.cli import add_logging_arguments, open_output
from npg.log import configure_structlog
from npg_irods import add_appinfo_structlog_processor, version
from npg_irods.utilities import sanitise_path
from npg_irods.xenium import get_xenium_output_directories

description = """
Lists Xenium output directories, identified by the presence of an experiment file.
"""

epilog = """
notes:
  Error Handling: Continues on error.
"""


def logger():
    return structlog.get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser = add_logging_arguments(parser)

    parser.add_argument(
        "--output",
        help="Output file",
        type=str,
        default="-",
    )

    parser.add_argument("root", help="Root directory to search for Xenium directories")

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

    root_path = Path(sanitise_path(args.root))
    output_path = sanitise_path(args.output)

    logger().info("Searching for Xenium output directories")

    with open_output(output_path, encoding="utf-8") as writer:
        num_dirs, num_errors, num_experiments = get_xenium_output_directories(
            root_path, writer
        )

    if num_errors:
        logger().error(
            "Some parts of tree could not be searched",
            num_dirs=num_dirs,
            num_experiments=num_experiments,
            num_errors=num_errors,
        )
        sys.exit(1)

    logger().info(
        "Search completed",
        num_dirs=num_dirs,
        num_experiments=num_experiments,
        num_errors=num_errors,
    )


if __name__ == "__main__":
    main()

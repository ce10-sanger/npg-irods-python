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
from datetime import datetime, timedelta

import operator

import sys
from npg_irods.system_calls import get_now, get_ctime, get_mtime

from pathlib import Path
import argparse
import structlog
from npg.cli import add_logging_arguments, open_output, open_input, add_io_arguments
from npg.log import configure_structlog
from npg_irods import add_appinfo_structlog_processor, version
from npg_irods.utilities import sanitise_path

# TODO: Docs
# TODO: Where should this live?
# TODO: Expected runtime
# TODO: Structure into a utility
# TODO: Timezones

description = """
Filters a list of directories to those recently created.

Reads directory paths from a file or STDIN, one per line, filters and writes
directory paths to a file or STDOUT, one per line.

Considers all files at any depth below directory.

Compares by ctime. Tool is only applicable to filesystems where
ctime a creation time (i.e. some NFS filesystems depending on configuration) and
not last metadata change (i.e. a typical Unix filesystem).   

Directories with "too recent" changes can be excluded. For example, to
heuristically guard against in progress transfers. 

Directories with "late" changes can be excluded. For example, for Xenium
publishing, we need to find directories recently copied from instrument to a
team NFS area. We need to be aware of any later modifications to those directories
and exclude from automatic publishing.
"""

epilog = """
notes:
  Error Handling: TODO
  Symbolic Links: Follows file links. Does not follow directory links (to avoid filesystem loops).
  Exclusions: Excludes checksums (.md5) and macOS Finder metadata (.DS_Store) files
  
history:
"""

# TODO: Document ctime, birthtime etc

def logger():
    return structlog.get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )

    add_io_arguments(parser)

    add_logging_arguments(parser)

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

    input_path = sanitise_path(args.input)
    output_path = sanitise_path(args.output)

    logger().info("Getting recently created directories")

    begin = get_now() - timedelta(days=7)
    # Safety against in progress uploads
    end = get_now() - timedelta(hours=1)

    logger().debug("Filtering", begin=begin, end=end)

    with open_input(input_path, encoding="utf-8") as reader:
        with open_output(output_path, encoding="utf-8") as writer:
            num_dirs, num_filtered, num_recent, num_failed = 0, 0, 0, 0

            for line in reader:
                directory_path = Path(sanitise_path(line))

                num_dirs += 1

                ctimes: dict[Path, datetime] = {}

                for file_path in directory_path.rglob("*"):
                    if not file_path.is_file():
                        continue

                    # TODO: exclude_patterns?
                    # TODO: Share common
                    if (
                        file_path.suffix.lower() == ".md5"
                        or file_path.name == ".DS_Store"
                    ):
                        continue

                    ctimes[file_path] = datetime.fromtimestamp(get_ctime(file_path))

                # TODO: Expect n files
                # TODO: mtimes

                if not ctimes:
                    num_failed += 1
                    logger().warning(
                        "No matching files.",
                        directory=directory_path,
                    )
                    continue

                earliest_ctime_path, earliest_ctime_date = min(
                    ctimes.items(), key=operator.itemgetter(1)
                )
                latest_ctime_path, latest_ctime_date = max(
                    ctimes.items(), key=operator.itemgetter(1)
                )

                too_old = latest_ctime_date < begin
                if too_old:
                    num_filtered += 1
                    logger().debug(
                        "Filtered out: too old. Latest ctime before beginning of recent creation window.",
                        directory=directory_path,
                        begin=begin,
                        latest_ctime_path=latest_ctime_path,
                        latest_ctime_date=latest_ctime_date,
                    )
                    continue

                too_new = latest_ctime_date > end
                if too_new:
                    num_filtered += 1
                    logger().info(
                        "Filtered out: too new (avoid in progress). Latest ctime after end of recent creation window.",
                        directory=directory_path,
                        begin=begin,
                        latest_ctime_path=latest_ctime_path,
                        latest_ctime_date=latest_ctime_date,
                    )
                    continue

                creation_period = latest_ctime_date - earliest_ctime_date
                if creation_period > timedelta(days=7):  # TODO: LATE_CHANGE_DAYS
                    logger().warning(
                        "Unexpected later change to file",
                        directory=directory_path,
                        creation_period=creation_period,
                        earliest_ctime_path=earliest_ctime_path,
                        earliest_ctime_date=earliest_ctime_date,
                        latest_ctime_path=latest_ctime_path,
                        latest_ctime_date=latest_ctime_date,
                    )
                    num_failed += 1
                    continue

                num_filtered += 1
                num_recent += 1
                try:
                    print(directory_path, file=writer)
                except BrokenPipeError:
                    # Support being used in a pipeline with filtering
                    # e.g. get-recently-created-directories | head -n 1
                    sys.exit(0)
                logger().debug(
                    "Filtered in.",
                    directory=directory_path,
                    begin=begin,
                    end=end,
                    creation_period=creation_period,
                    latest_ctime_path=latest_ctime_path,
                    latest_ctime_date=latest_ctime_date,
                )

    logger().info(
        "Got recently created directories",
        num_dirs=num_dirs,
        num_filtered=num_filtered,
        num_recent=num_recent,
        num_failed=num_failed,
    )
    # TODO: Error handling


if __name__ == "__main__":
    main()

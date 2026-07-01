#!/usr/bin/env python3
from datetime import datetime, timedelta

import operator

import sys

from pathlib import Path
import argparse
import structlog
from npg.cli import add_logging_arguments, open_output, open_input
from npg.log import configure_structlog
from npg_irods import add_appinfo_structlog_processor, version
from npg_irods.utilities import sanitise_path

# TODO: Copyright
# TODO: Docs
# TODO: Where should this live?
# TODO: Expected runtime
# TODO: add_input_argument, add_output_argument to python lib
# TODO: Structure into a utility
# TODO: Timezones

description = """TODO"""

def logger():
    return structlog.get_logger(__name__)

def main():
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser = add_logging_arguments(parser)

    inputs = parser.add_mutually_exclusive_group(required=True)

    inputs.add_argument(
        "--input",
        help="Input file",
        type=str,
        default="-",
    )
    # TODO: Root

    parser.add_argument(
        "--output",
        help="Output file",
        type=str,
        default="-",
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

    if not args.input:
        sys.exit("Error: Only input method supported at the moment")

    input_path = sanitise_path(args.input)
    output_path = sanitise_path(args.output)

    logger().info("Getting recently changed directories")

    begin = datetime.now() - timedelta(days=7)
    # Safety against in progress uploads
    end = datetime.now() - timedelta(hours=1)

    with open_input(input_path, encoding="utf-8") as reader:
        with open_output(output_path, encoding="utf-8") as writer:

            for line in reader:
                directory_path = Path(sanitise_path(line))

                mtimes: dict[Path, datetime] = {}
                ctimes: dict[Path, datetime] = {}

                for file_path in sorted(directory_path.glob("*")):
                    if not file_path.is_file():
                        continue

                    # TODO: exclude_patterns?
                    # TODO: Share common
                    if file_path.suffix.lower() != ".md5" or file_path.name == ".DS_Store":
                        continue

                    mtimes[file_path] = datetime.fromtimestamp(file_path.stat().st_mtime)
                    ctimes[file_path] = datetime.fromtimestamp(file_path.stat().st_ctime)

                # TODO: Expect n files
                # TODO: mtimes

                earliest_ctime_path, earliest_ctime_date = min(ctimes.items(), key=operator.itemgetter(1))
                latest_ctime_path, latest_ctime_date = max(ctimes.items(), key=operator.itemgetter(1))

                if begin < latest_ctime_date < end:
                    if latest_ctime_date - earliest_ctime_date > timedelta(days=7): # TODO: LATE_CHANGE_DAYS
                        logger().warning("Unexpected later change to file",
                             directory=directory_path,
                             earliest_ctime_path=earliest_ctime_path,
                                         earliest_ctime_date=earliest_ctime_date,
                             latest_ctime_path=latest_ctime_path,
                                         latest_ctime_date=latest_ctime_date,
                        )
                        continue

                    print(directory_path, file=writer)

    logger().info("Got recently changed directories")

if __name__ == "__main__":
    main()
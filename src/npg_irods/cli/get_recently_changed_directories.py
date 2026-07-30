#!/usr/bin/env python3
import signal
from datetime import datetime, timedelta

import operator

import sys

from npg_irods.cli import register_term_handling
from npg_irods.system_calls import get_now, get_ctime, get_mtime

from pathlib import Path
import argparse
from structlog.stdlib import get_logger, BoundLogger
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


def logger() -> BoundLogger:
    return get_logger(__name__)


def main():
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser = add_logging_arguments(parser)

    inputs = parser.add_mutually_exclusive_group()

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

    register_term_handling()

    if not args.input:
        sys.exit("Error: Only input method supported at the moment")

    input_path = sanitise_path(args.input)
    output_path = sanitise_path(args.output)

    logger().info("Getting recently changed directories")

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

                mtimes: dict[Path, datetime] = {}
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

                    mtimes[file_path] = datetime.fromtimestamp(get_mtime(file_path))
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
                        "Filtered out: too old. Latest ctime before beginning of recent change window.",
                        directory=directory_path,
                        begin=begin,
                        latest_ctime_path=latest_ctime_path,
                        latest_ctime_date=latest_ctime_date,
                    )
                    continue

                too_new = latest_ctime_date > end
                if too_new:
                    num_filtered += 1
                    logger().debug(
                        "Filtered out: too new (avoid in progress). Latest ctime after end of recent change window.",
                        directory=directory_path,
                        begin=begin,
                        latest_ctime_path=latest_ctime_path,
                        latest_ctime_date=latest_ctime_date,
                    )
                    continue

                change_period = latest_ctime_date - earliest_ctime_date
                if change_period > timedelta(days=7):  # TODO: LATE_CHANGE_DAYS
                    logger().warning(
                        "Unexpected later change to file",
                        directory=directory_path,
                        change_period=change_period,
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
                    # e.g. get-recently-changed-directories | head -n 1
                    sys.exit(0)
                logger().debug(
                    "Filtered in.",
                    directory=directory_path,
                    begin=begin,
                    end=end,
                    change_period=change_period,
                    latest_ctime_path=latest_ctime_path,
                    latest_ctime_date=latest_ctime_date,
                )

    logger().info(
        "Got recently changed directories",
        num_dirs=num_dirs,
        num_filtered=num_filtered,
        num_recent=num_recent,
        num_failed=num_failed,
    )
    # TODO: Error handling


if __name__ == "__main__":
    main()

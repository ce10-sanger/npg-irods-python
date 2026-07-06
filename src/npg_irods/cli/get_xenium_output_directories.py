#!/usr/bin/env python3
from pathlib import Path
import argparse
import structlog
from npg.cli import add_logging_arguments, open_output
from npg.log import configure_structlog
from npg_irods import add_appinfo_structlog_processor, version
from npg_irods.metadata.xenium import EXPERIMENT_FILENAME
from npg_irods.utilities import sanitise_path

# TODO: Copyright
# TODO: Docs
# TODO: Where should this live?
# TODO: Expected runtime

description = """TODO"""


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

    def on_error(error: OSError):
        logger().error("Could not scan directory", error=error, filename=error.filename)

    logger().info("Getting Xenium output directories")

    with open_output(output_path, encoding="utf-8") as writer:
        for dirpath, dirnames, filenames in root_path.walk(
            on_error=on_error, follow_symlinks=False
        ):
            logger().debug("Considering dirpath", dirpath=dirpath)

            if EXPERIMENT_FILENAME in filenames:
                print(dirpath, file=writer)

    logger().info("Got Xenium output directories")


if __name__ == "__main__":
    main()

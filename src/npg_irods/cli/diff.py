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
from typing import Callable

from abc import abstractmethod
from os import PathLike

import argparse
from npg_irods.cli.publish_directory import make_get_checksum
from npg_irods.utilities import read_md5_file
from partisan.irods import Collection, DataObject
from pathlib import Path, PurePath

import structlog
from npg.cli import add_logging_arguments
from npg.log import configure_structlog

from npg_irods import add_appinfo_structlog_processor, version
from npg_irods.checksum import checksum_directory

description = """
TODO
"""

epilog = """
TODO
"""


def logger():
    return structlog.get_logger(__name__)

class DiffItem(PathLike):

    @abstractmethod
    def relative_path(self) -> PurePath:
        pass

    def __fspath__(self):
        return self.relative_path()

# TODO: Directories vs files vs links vs others
# TODO: Where to implement comparison?

class DiffDirectoryLike(DiffItem):

    def __eq__(self, other):
        if not isinstance(other, DiffDirectoryLike):
            return False

        return (
            self.relative_path == other.relative_path()
        )


class DiffFileLike(DiffItem):

    def __eq__(self, other):
        if not isinstance(other, DiffFileLike):
            return False

        return (
            self.relative_path == other.relative_path()
            and self.size() == other.size()
            and self.checksum() == other.checksum()
        )

    @abstractmethod
    def size(self) -> int:
        pass

    @abstractmethod
    def checksum(self) -> str:
        pass

class DiffDirectory(DiffDirectoryLike):
    def __init__(self, root: PurePath, path: Path):
        self.root = root
        self.path = path

    def relative_path(self):
        return self.path.relative_to(self.root)

class DiffFile(DiffFileLike):
    def __init__(self, root: PurePath, path: Path, get_checksum):
        self.root = root
        self.path = path
        self.get_checksum = lambda: get_checksum(path)

    def relative_path(self):
        return self.path.relative_to(self.root)

    def size(self):
        return self.path.stat(follow_symlinks=True).st_size

    def checksum(self):
        return self.get_checksum()

# TODO: Symbolic links

class DiffCollection(DiffDirectoryLike):
    def __init__(self, root: PurePath, collection: Collection):
        self.root = root
        self.collection = collection

    def relative_path(self):
        return self.collection.path.relative_to(self.root)

class DiffDataObject(DiffFileLike):
    def __init__(self, root: PurePath, data_object: DataObject):
        self.root = root
        self.data_object = data_object

    def relative_path(self):
        return (self.data_object.path / self.data_object.name).relative_to(self.root)

    def size(self):
        self.data_object.size()

    def checksum(self):
        self.data_object.checksum()

def make_diff_item(root: PurePath, item: Path | Collection | DataObject, get_checksum) -> DiffItem:
    match item:
        case Path():
            if item.is_dir(follow_symlinks=True):
                return DiffDirectory(root, item)
            elif item.is_file(follow_symlinks=True):
                return DiffFile(root, item, get_checksum)
            else:
                raise ValueError()
        case Collection():
            return DiffCollection(root, item)
        case DataObject():
            return DiffDataObject(root, item)

# TODO: Local or iRODS
def diff(
    left: Path,
    right: Collection,
    get_checksum: Callable[[Path | str], str]
):
    left_items = [make_diff_item(left, x, get_checksum) for x in left.rglob("*")]
    right_items = [make_diff_item(right.path, x, get_checksum) for x in right.iter_contents(recurse=False)]

    left_items = {x.relative_path: x for x in left_items}
    right_items = {x.relative_path: x for x in right_items}

    left_only = left_items.keys() - right_items.keys()
    right_only = right_items.keys() - left_items.keys()

    common = left_items.keys() & right_items.keys()

    same = set(x for x in common if left_items[x] == right_items[x])
    different = common - same

    print("same", same)
    print("different", different)
    print("left_only", left_only)
    print("right_only", right_only)

    return (
        same,
        different,
        left_only,
        right_only,
    )

def main():
    parser = argparse.ArgumentParser(
        description=description,
        epilog=epilog,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_logging_arguments(parser)

    # local or irods
    parser.add_argument(
        "left",
        help="TODO",
        type=str,
    )

    # local or irods
    parser.add_argument(
        "right",
        help="TODO",
        type=str,
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

    left = Path(args.left) # TODO: Local or iRODS
    right = Collection(args.right) # TODO: Local or iRODS

    get_checksum: Callable[[Path], str]
    if args.use_checksum_files:
        get_checksum = read_md5_file
    elif args.use_checksums_file:
        try:
            # TODO: Share
            get_checksum = make_get_checksum(Path(args.use_checksums_file))
        except Exception as e:
            logger().error(
                "Failed to read checksums file",
                path=args.use_checksums_file,
                error=str(e),
            )
            raise e
    else:
        raise ValueError()

    diff(
        left,
        right,
        get_checksum
    )


if __name__ == "__main__":
    main()
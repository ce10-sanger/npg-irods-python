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

"""Compare local directories with iRODS collections."""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import file_digest
from pathlib import Path, PurePath

from partisan.irods import Collection, DataObject, client_pool, rods_path_type
from structlog import get_logger

log = get_logger(__name__)

STATUS_SAME = "="
STATUS_LOCAL = ">"
STATUS_IRODS = "<"
STATUS_DIFFERENT = "*"
STATUS_ERROR = "!"

KIND_FILE = "file"
KIND_DIRECTORY = "directory"
KIND_ERROR = "error"


@dataclass(frozen=True)
class DiffEntry:
    """A local filesystem or iRODS item to compare."""

    path: str
    kind: str
    size: int | Callable[[], int] | None = None
    checksum: Callable[[], str | None] | None = None

    def get_size(self) -> int:
        size = self.size() if callable(self.size) else self.size
        if size is None:
            raise ValueError(f"No size available for {self.path}")
        return size

    def get_checksum(self) -> str:
        if self.checksum is None:
            raise ValueError(f"No checksum available for {self.path}")

        checksum = self.checksum()
        if not checksum:
            raise ValueError(f"No checksum available for {self.path}")

        return str(checksum).lower()


@dataclass(frozen=True)
class DiffRow:
    """A single diff output row."""

    status: str
    path: str


def calculate_md5(path: Path) -> str:
    """Calculate the MD5 checksum of a local file."""
    with path.open("rb") as f:
        return file_digest(f, "md5").hexdigest()


def scan_local_directory(
    root: Path | str,
    local_checksum: Callable[[Path | str], str] | None = None,
) -> dict[str, DiffEntry]:
    """Return entries below a local directory, keyed by relative POSIX path."""
    root = Path(root)
    entries: dict[str, DiffEntry] = {}

    if not root.exists():
        return entries
    if not root.is_dir():
        raise NotADirectoryError(f"Local path is not a directory: {root}")

    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root).as_posix()

        try:
            if path.is_dir():
                entries[rel] = DiffEntry(path=rel, kind=KIND_DIRECTORY)
            elif path.is_file():
                entries[rel] = DiffEntry(
                    path=rel,
                    kind=KIND_FILE,
                    size=lambda path=path: path.stat().st_size,
                    checksum=_local_checksum_fn(path, local_checksum),
                )
            else:
                entries[rel] = DiffEntry(path=rel, kind=KIND_ERROR)
                log.error("Unsupported local path type", path=path)
        except Exception as e:
            entries[rel] = DiffEntry(path=rel, kind=KIND_ERROR)
            log.error("Error scanning local path", path=path, error=str(e))

    return entries


def scan_irods_collection(
    root: PurePath | str,
    pool=None,
) -> dict[str, DiffEntry]:
    """Return entries below an iRODS collection, keyed by relative POSIX path."""
    root = PurePath(root)
    entries: dict[str, DiffEntry] = {}

    root_type = rods_path_type(root.as_posix())
    if root_type is None:
        return entries
    if root_type != Collection:
        raise ValueError(f"iRODS path is not a collection: {root}")

    coll = Collection(root, pool=pool)
    for item in coll.iter_contents(recurse=True):
        rel = item.path.relative_to(root).as_posix()
        if rel == ".":
            continue

        try:
            if item.rods_type == Collection:
                entries[rel] = DiffEntry(path=rel, kind=KIND_DIRECTORY)
            elif item.rods_type == DataObject:
                entries[rel] = DiffEntry(
                    path=rel,
                    kind=KIND_FILE,
                    size=lambda item=item: item.size(),
                    checksum=lambda item=item: item.checksum(),
                )
            else:
                entries[rel] = DiffEntry(path=rel, kind=KIND_ERROR)
                log.error("Unsupported iRODS item type", path=item)
        except Exception as e:
            entries[rel] = DiffEntry(path=rel, kind=KIND_ERROR)
            log.error("Error scanning iRODS item", path=item, error=str(e))

    return entries


def diff_entries(
    local_entries: Mapping[str, DiffEntry],
    irods_entries: Mapping[str, DiffEntry],
) -> list[DiffRow]:
    """Compare two entry maps and return sorted diff rows."""
    rows: list[DiffRow] = []

    for path in sorted(set(local_entries) | set(irods_entries)):
        local = local_entries.get(path)
        irods = irods_entries.get(path)

        if local is None:
            rows.append(_side_only_row(irods, STATUS_IRODS))
        elif irods is None:
            rows.append(_side_only_row(local, STATUS_LOCAL))
        elif local.kind == KIND_ERROR or irods.kind == KIND_ERROR:
            rows.append(DiffRow(STATUS_ERROR, path))
        elif local.kind != irods.kind:
            rows.append(DiffRow(STATUS_LOCAL, path))
            rows.append(DiffRow(STATUS_IRODS, path))
        elif local.kind == KIND_DIRECTORY:
            rows.append(DiffRow(STATUS_SAME, path))
        elif local.kind == KIND_FILE:
            rows.append(_compare_files(local, irods))
        else:
            rows.append(DiffRow(STATUS_ERROR, path))

    return rows


def diff_directory(
    local_root: Path | str,
    irods_root: PurePath | str,
    local_checksum: Callable[[Path | str], str] | None = None,
    num_clients: int = 1,
) -> list[DiffRow]:
    """Compare a local directory with an iRODS collection."""
    local_entries = scan_local_directory(local_root, local_checksum=local_checksum)

    with client_pool(maxsize=num_clients) as pool:
        irods_entries = scan_irods_collection(irods_root, pool=pool)

    if not local_entries and not irods_entries:
        local_exists = Path(local_root).exists()
        irods_exists = rods_path_type(PurePath(irods_root).as_posix()) is not None
        if not local_exists and not irods_exists:
            raise FileNotFoundError(
                f"Neither local directory nor iRODS collection exists: {local_root}, {irods_root}"
            )

    return diff_entries(local_entries, irods_entries)


def has_errors(rows: list[DiffRow]) -> bool:
    """Return True if any diff row is an error."""
    return any(row.status == STATUS_ERROR for row in rows)


def _local_checksum_fn(
    path: Path,
    local_checksum: Callable[[Path | str], str] | None,
) -> Callable[[], str | None]:
    if local_checksum is None:
        return lambda path=path: calculate_md5(path)

    return lambda path=path: local_checksum(path)


def _side_only_row(entry: DiffEntry | None, status: str) -> DiffRow:
    if entry is None:
        return DiffRow(STATUS_ERROR, "")
    if entry.kind == KIND_ERROR:
        return DiffRow(STATUS_ERROR, entry.path)
    return DiffRow(status, entry.path)


def _compare_files(local: DiffEntry, irods: DiffEntry) -> DiffRow:
    try:
        if local.get_size() != irods.get_size():
            return DiffRow(STATUS_DIFFERENT, local.path)

        if local.get_checksum() != irods.get_checksum():
            return DiffRow(STATUS_DIFFERENT, local.path)

        return DiffRow(STATUS_SAME, local.path)
    except Exception as e:
        log.error("Error comparing path", path=local.path, error=str(e))
        return DiffRow(STATUS_ERROR, local.path)

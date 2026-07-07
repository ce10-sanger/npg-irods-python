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

from collections.abc import Callable, Iterator, Mapping
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
    source_path: Path | PurePath | None = None

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
    no_recurse_missing_dirs: bool = False,
) -> list[DiffRow]:
    """Compare a local directory with an iRODS collection."""
    return list(
        iter_diff_directory(
            local_root,
            irods_root,
            local_checksum=local_checksum,
            num_clients=num_clients,
            no_recurse_missing_dirs=no_recurse_missing_dirs,
        )
    )


def iter_diff_directory(
    local_root: Path | str,
    irods_root: PurePath | str,
    local_checksum: Callable[[Path | str], str] | None = None,
    num_clients: int = 1,
    no_recurse_missing_dirs: bool = False,
) -> Iterator[DiffRow]:
    """Yield comparison rows for a local directory and iRODS collection."""
    local_root = Path(local_root)
    irods_root = PurePath(irods_root)

    local_exists = local_root.exists()
    irods_type = rods_path_type(irods_root.as_posix())

    if not local_exists and irods_type is None:
        raise FileNotFoundError(
            f"Neither local directory nor iRODS collection exists: {local_root}, {irods_root}"
        )
    if local_exists and not local_root.is_dir():
        raise NotADirectoryError(f"Local path is not a directory: {local_root}")
    if irods_type is not None and irods_type != Collection:
        raise ValueError(f"iRODS path is not a collection: {irods_root}")

    local_dir = local_root if local_exists else None

    if irods_type is None:
        yield from _iter_compare_dirs(
            local_root,
            irods_root,
            local_dir,
            None,
            local_checksum,
            no_recurse_missing_dirs,
            None,
            None,
        )
        return

    with client_pool(maxsize=num_clients) as pool:
        yield from _iter_compare_dirs(
            local_root,
            irods_root,
            local_dir,
            Collection(irods_root, pool=pool),
            local_checksum,
            no_recurse_missing_dirs,
            pool,
            None,
        )


def has_errors(rows: list[DiffRow]) -> bool:
    """Return True if any diff row is an error."""
    return any(row.status == STATUS_ERROR for row in rows)


def _iter_compare_dirs(
    local_root: Path,
    irods_root: PurePath,
    local_dir: Path | None,
    irods_coll: Collection | None,
    local_checksum: Callable[[Path | str], str] | None,
    no_recurse_missing_dirs: bool,
    pool,
    rel_path: str | None,
):
    try:
        local_entries = (
            _local_child_entries(local_dir, local_root, local_checksum)
            if local_dir is not None
            else {}
        )
        irods_entries = (
            _irods_child_entries(irods_coll, irods_root)
            if irods_coll is not None
            else {}
        )
    except Exception as e:
        if rel_path is None:
            raise
        log.error("Error listing path", path=rel_path, error=str(e))
        yield DiffRow(STATUS_ERROR, rel_path)
        return

    for name in sorted(set(local_entries) | set(irods_entries)):
        local = local_entries.get(name)
        irods = irods_entries.get(name)

        if local is None:
            yield from _iter_side_only(
                irods,
                STATUS_IRODS,
                local_root,
                irods_root,
                local_checksum,
                no_recurse_missing_dirs,
                pool,
            )
        elif irods is None:
            yield from _iter_side_only(
                local,
                STATUS_LOCAL,
                local_root,
                irods_root,
                local_checksum,
                no_recurse_missing_dirs,
                pool,
            )
        elif local.kind == KIND_ERROR or irods.kind == KIND_ERROR:
            yield DiffRow(STATUS_ERROR, local.path)
        elif local.kind != irods.kind:
            yield DiffRow(STATUS_LOCAL, local.path)
            yield DiffRow(STATUS_IRODS, local.path)
            if not no_recurse_missing_dirs:
                if local.kind == KIND_DIRECTORY:
                    yield from _iter_local_only_dir(
                        local,
                        local_root,
                        irods_root,
                        local_checksum,
                        no_recurse_missing_dirs,
                        pool,
                    )
                if irods.kind == KIND_DIRECTORY:
                    yield from _iter_irods_only_collection(
                        irods,
                        local_root,
                        irods_root,
                        local_checksum,
                        no_recurse_missing_dirs,
                        pool,
                    )
        elif local.kind == KIND_DIRECTORY:
            yield DiffRow(STATUS_SAME, local.path)
            yield from _iter_compare_dirs(
                local_root,
                irods_root,
                local.source_path,
                Collection(irods.source_path, pool=pool),
                local_checksum,
                no_recurse_missing_dirs,
                pool,
                local.path,
            )
        elif local.kind == KIND_FILE:
            yield _compare_files(local, irods)
        else:
            yield DiffRow(STATUS_ERROR, local.path)


def _iter_side_only(
    entry: DiffEntry | None,
    status: str,
    local_root: Path,
    irods_root: PurePath,
    local_checksum: Callable[[Path | str], str] | None,
    no_recurse_missing_dirs: bool,
    pool,
):
    row = _side_only_row(entry, status)
    yield row

    if (
        entry is None
        or entry.kind != KIND_DIRECTORY
        or no_recurse_missing_dirs
        or row.status == STATUS_ERROR
    ):
        return

    if status == STATUS_LOCAL:
        yield from _iter_local_only_dir(
            entry,
            local_root,
            irods_root,
            local_checksum,
            no_recurse_missing_dirs,
            pool,
        )
    else:
        yield from _iter_irods_only_collection(
            entry,
            local_root,
            irods_root,
            local_checksum,
            no_recurse_missing_dirs,
            pool,
        )


def _iter_local_only_dir(
    entry: DiffEntry,
    local_root: Path,
    irods_root: PurePath,
    local_checksum: Callable[[Path | str], str] | None,
    no_recurse_missing_dirs: bool,
    pool,
):
    try:
        children = _local_child_entries(entry.source_path, local_root, local_checksum)
    except Exception as e:
        log.error("Error listing local path", path=entry.path, error=str(e))
        yield DiffRow(STATUS_ERROR, entry.path)
        return

    for name in sorted(children):
        child = children[name]
        yield from _iter_side_only(
            child,
            STATUS_LOCAL,
            local_root,
            irods_root,
            local_checksum,
            no_recurse_missing_dirs,
            pool,
        )


def _iter_irods_only_collection(
    entry: DiffEntry,
    local_root: Path,
    irods_root: PurePath,
    local_checksum: Callable[[Path | str], str] | None,
    no_recurse_missing_dirs: bool,
    pool,
):
    try:
        children = _irods_child_entries(
            Collection(entry.source_path, pool=pool), irods_root
        )
    except Exception as e:
        log.error("Error listing iRODS path", path=entry.path, error=str(e))
        yield DiffRow(STATUS_ERROR, entry.path)
        return

    for name in sorted(children):
        child = children[name]
        yield from _iter_side_only(
            child,
            STATUS_IRODS,
            local_root,
            irods_root,
            local_checksum,
            no_recurse_missing_dirs,
            pool,
        )


def _local_child_entries(
    local_dir: Path,
    local_root: Path,
    local_checksum: Callable[[Path | str], str] | None,
) -> dict[str, DiffEntry]:
    entries = {}
    for path in local_dir.iterdir():
        rel = path.relative_to(local_root).as_posix()
        if path.is_dir():
            entries[path.name] = DiffEntry(
                path=rel, kind=KIND_DIRECTORY, source_path=path
            )
        elif path.is_file():
            entries[path.name] = DiffEntry(
                path=rel,
                kind=KIND_FILE,
                size=lambda path=path: path.stat().st_size,
                checksum=_local_checksum_fn(path, local_checksum),
                source_path=path,
            )
        else:
            entries[path.name] = DiffEntry(path=rel, kind=KIND_ERROR, source_path=path)
            log.error("Unsupported local path type", path=path)

    return entries


def _irods_child_entries(
    irods_coll: Collection,
    irods_root: PurePath,
) -> dict[str, DiffEntry]:
    entries = {}
    for item in irods_coll.iter_contents(recurse=False):
        rel = item.path.relative_to(irods_root).as_posix()
        if item.rods_type == Collection:
            entries[item.path.name] = DiffEntry(
                path=rel, kind=KIND_DIRECTORY, source_path=item.path
            )
        elif item.rods_type == DataObject:
            entries[item.path.name] = DiffEntry(
                path=rel,
                kind=KIND_FILE,
                size=lambda item=item: item.size(),
                checksum=lambda item=item: item.checksum(),
                source_path=item.path,
            )
        else:
            entries[item.path.name] = DiffEntry(
                path=rel, kind=KIND_ERROR, source_path=item.path
            )
            log.error("Unsupported iRODS item type", path=item)

    return entries


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

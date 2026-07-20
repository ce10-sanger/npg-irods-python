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

import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path, PurePath

from partisan.irods import Collection, DataObject, client_pool, rods_path_type
from structlog import get_logger

from npg_irods.checksum import calculate_file_checksum

log = get_logger(__name__)

STATUS_SAME = "same"
STATUS_LOCAL = "local_only"
STATUS_IRODS = "irods_only"
STATUS_DIFFERENT = "different"
STATUS_ERROR = "error"
STATUS_SYMBOLS = {
    STATUS_SAME: "=",
    STATUS_LOCAL: ">",
    STATUS_IRODS: "<",
    STATUS_DIFFERENT: "*",
    STATUS_ERROR: "!",
}

EXIT_SAME = 0
EXIT_DIFFERENCE = 1
EXIT_ERROR = 2

KIND_FILE = "file"
KIND_DIRECTORY = "directory"
KIND_ERROR = "error"

DIFFERENCE_STATUSES = frozenset((STATUS_LOCAL, STATUS_IRODS, STATUS_DIFFERENT))


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

    @property
    def name(self):
        # TODO: Clean up
        return PurePath(self.path).name

@dataclass(frozen=True)
class DiffRow:
    """A single diff output row."""

    status: str
    path: str
    kind: str


def make_diff_filter(
    include_patterns: list[str] = None,
    exclude_patterns: list[str] = None,
    include_top_level_files: bool = False,
    exclude_md5: bool = False,
    flags: int | re.RegexFlag = 0,
) -> Callable[[DiffEntry], bool]:
    """Return a filter function for diff entries.

    The returned function follows publish-directory convention: it returns True
    when an entry should be skipped, and False when it should be included.
    """
    include_patterns = include_patterns or []
    exclude_patterns = exclude_patterns or []

    include_regexes = [re.compile(p, flags=flags) for p in include_patterns]
    exclude_regexes = [re.compile(p, flags=flags) for p in exclude_patterns]

    if exclude_md5:
        exclude_regexes.append(re.compile(".md5"))

    def entry_filter(entry: DiffEntry) -> bool:
        path = PurePath(entry.path)
        path_posix = path.as_posix()

        if include_regexes or include_top_level_files:
            include = any(r.search(path_posix) for r in include_regexes)

            if include_top_level_files and _is_top_level_file(entry):
                include = True

            if not include:
                return True

        return any(r.search(path_posix) for r in exclude_regexes)

    return entry_filter


def _is_top_level_file(entry: DiffEntry) -> bool:
    return entry.kind == KIND_FILE and "/" not in PurePath(entry.path).as_posix()


def diff_directory(
    local_root: Path | str,
    irods_root: PurePath | str,
    local_checksum: Callable[[Path | str], str] | None = None,
    filter_fn: Callable[[DiffEntry], bool] | None = None,
    num_clients: int = 1,
    no_recurse_missing_dirs: bool = False,
) -> list[DiffRow]:
    """Compare a local directory with an iRODS collection."""
    return list(
        iter_diff_directory(
            local_root,
            irods_root,
            local_checksum=local_checksum,
            filter_fn=filter_fn,
            num_clients=num_clients,
            no_recurse_missing_dirs=no_recurse_missing_dirs,
        )
    )


def iter_diff_directory(
    local_root: Path | str,
    irods_root: PurePath | str,
    local_checksum: Callable[[Path | str], str] | None = None,
    filter_fn: Callable[[DiffEntry], bool] | None = None,
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
            filter_fn,
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
            filter_fn,
            no_recurse_missing_dirs,
            pool,
            None,
        )


def _iter_compare_dirs(
    local_root: Path,
    irods_root: PurePath,
    local_dir: Path | None,
    irods_coll: Collection | None,
    local_checksum: Callable[[Path | str], str] | None,
    filter_fn: Callable[[DiffEntry], bool] | None,
    no_recurse_missing_dirs: bool,
    pool,
    rel_path: str | None,
):
    try:
        local_entries = (
            _local_child_entries(local_dir, local_root, local_checksum, filter_fn)
            if local_dir is not None
            else {}
        )
        irods_entries = (
            _irods_child_entries(irods_coll, irods_root, filter_fn)
            if irods_coll is not None
            else {}
        )
    except Exception as e:
        if rel_path is None:
            raise
        log.error("Error listing path", path=rel_path, error=str(e))
        yield DiffRow(STATUS_ERROR, rel_path, KIND_ERROR)
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
                filter_fn,
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
                filter_fn,
                no_recurse_missing_dirs,
                pool,
            )
        elif local.kind == KIND_ERROR or irods.kind == KIND_ERROR:
            yield DiffRow(STATUS_ERROR, local.path, KIND_ERROR)
        elif local.kind != irods.kind:
            yield DiffRow(STATUS_LOCAL, local.path, local.kind)
            yield DiffRow(STATUS_IRODS, irods.path, irods.kind)
            if not no_recurse_missing_dirs:
                if local.kind == KIND_DIRECTORY:
                    yield from _iter_local_only_dir(
                        local,
                        local_root,
                        irods_root,
                        local_checksum,
                        filter_fn,
                        no_recurse_missing_dirs,
                        pool,
                    )
                if irods.kind == KIND_DIRECTORY:
                    yield from _iter_irods_only_collection(
                        irods,
                        local_root,
                        irods_root,
                        local_checksum,
                        filter_fn,
                        no_recurse_missing_dirs,
                        pool,
                    )
        elif local.kind == KIND_DIRECTORY:
            yield DiffRow(STATUS_SAME, local.path, KIND_DIRECTORY)
            yield from _iter_compare_dirs(
                local_root,
                irods_root,
                local.source_path,
                Collection(irods.source_path, pool=pool),
                local_checksum,
                filter_fn,
                no_recurse_missing_dirs,
                pool,
                local.path,
            )
        elif local.kind == KIND_FILE:
            yield _compare_files(local, irods)
        else:
            yield DiffRow(STATUS_ERROR, local.path, KIND_ERROR)


def _iter_side_only(
    entry: DiffEntry | None,
    status: str,
    local_root: Path,
    irods_root: PurePath,
    local_checksum: Callable[[Path | str], str] | None,
    filter_fn: Callable[[DiffEntry], bool] | None,
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
            filter_fn,
            no_recurse_missing_dirs,
            pool,
        )
    else:
        yield from _iter_irods_only_collection(
            entry,
            local_root,
            irods_root,
            local_checksum,
            filter_fn,
            no_recurse_missing_dirs,
            pool,
        )


def _iter_local_only_dir(
    entry: DiffEntry,
    local_root: Path,
    irods_root: PurePath,
    local_checksum: Callable[[Path | str], str] | None,
    filter_fn: Callable[[DiffEntry], bool] | None,
    no_recurse_missing_dirs: bool,
    pool,
):
    try:
        children = _local_child_entries(
            entry.source_path, local_root, local_checksum, filter_fn
        )
    except Exception as e:
        log.error("Error listing local path", path=entry.path, error=str(e))
        yield DiffRow(STATUS_ERROR, entry.path, KIND_ERROR)
        return

    for name in sorted(children):
        child = children[name]
        yield from _iter_side_only(
            child,
            STATUS_LOCAL,
            local_root,
            irods_root,
            local_checksum,
            filter_fn,
            no_recurse_missing_dirs,
            pool,
        )


def _iter_irods_only_collection(
    entry: DiffEntry,
    local_root: Path,
    irods_root: PurePath,
    local_checksum: Callable[[Path | str], str] | None,
    filter_fn: Callable[[DiffEntry], bool] | None,
    no_recurse_missing_dirs: bool,
    pool,
):
    try:
        children = _irods_child_entries(
            Collection(entry.source_path, pool=pool), irods_root, filter_fn
        )
    except Exception as e:
        log.error("Error listing iRODS path", path=entry.path, error=str(e))
        yield DiffRow(STATUS_ERROR, entry.path, KIND_ERROR)
        return

    for name in sorted(children):
        child = children[name]
        yield from _iter_side_only(
            child,
            STATUS_IRODS,
            local_root,
            irods_root,
            local_checksum,
            filter_fn,
            no_recurse_missing_dirs,
            pool,
        )


def _local_child_entries(
    local_dir: Path,
    local_root: Path,
    local_checksum: Callable[[Path | str], str] | None,
    filter_fn: Callable[[DiffEntry], bool] | None = None,
) -> dict[str, DiffEntry]:
    entries = {}
    for path in local_dir.iterdir():
        rel = path.relative_to(local_root).as_posix()
        if path.is_dir():
            entry = DiffEntry(path=rel, kind=KIND_DIRECTORY, source_path=path)
        elif path.is_file():
            entry = DiffEntry(
                path=rel,
                kind=KIND_FILE,
                size=lambda path=path: path.stat().st_size,
                checksum=_local_checksum_fn(path, local_checksum),
                source_path=path,
            )
        else:
            entry = DiffEntry(path=rel, kind=KIND_ERROR, source_path=path)
            log.error("Unsupported local path type", path=path)

        if filter_fn is None or not filter_fn(entry):
            entries[path.name] = entry

    return entries


def _irods_child_entries(
    irods_coll: Collection,
    irods_root: PurePath,
    filter_fn: Callable[[DiffEntry], bool] | None = None,
) -> dict[str, DiffEntry]:
    entries = {}
    for item in irods_coll.iter_contents(recurse=False):
        if item.rods_type == Collection:
            full_path = item.path
            rel = full_path.relative_to(irods_root).as_posix()
            key = item.path.name
            entry = DiffEntry(path=rel, kind=KIND_DIRECTORY, source_path=full_path)
        elif item.rods_type == DataObject:
            full_path = item.path / item.name
            rel = full_path.relative_to(irods_root).as_posix()
            key = item.name
            entry = DiffEntry(
                path=rel,
                kind=KIND_FILE,
                size=lambda item=item: item.size(),
                checksum=lambda item=item: item.checksum(),
                source_path=full_path,
            )
        else:
            full_path = item.path
            rel = full_path.relative_to(irods_root).as_posix()
            key = item.path.name
            entry = DiffEntry(path=rel, kind=KIND_ERROR, source_path=full_path)
            log.error("Unsupported iRODS item type", path=item)

        if filter_fn is None or not filter_fn(entry):
            entries[key] = entry

    return entries


def _local_checksum_fn(
    path: Path,
    local_checksum: Callable[[Path | str], str] | None,
) -> Callable[[], str | None]:
    if local_checksum is None:
        return lambda path=path: _calculate_local_checksum(path)

    return lambda path=path: local_checksum(path)


def _calculate_local_checksum(path: Path) -> str:
    log.debug("Calculating local checksum on the fly", path=path)
    return calculate_file_checksum(path)


def _side_only_row(entry: DiffEntry | None, status: str) -> DiffRow:
    if entry is None:
        return DiffRow(STATUS_ERROR, "", KIND_ERROR)
    if entry.kind == KIND_ERROR:
        return DiffRow(STATUS_ERROR, entry.path, KIND_ERROR)
    return DiffRow(status, entry.path, entry.kind)


def _compare_files(local: DiffEntry, irods: DiffEntry) -> DiffRow:
    try:
        if local.get_size() != irods.get_size():
            return DiffRow(STATUS_DIFFERENT, local.path, KIND_FILE)

        if local.get_checksum() != irods.get_checksum():
            return DiffRow(STATUS_DIFFERENT, local.path, KIND_FILE)

        return DiffRow(STATUS_SAME, local.path, KIND_FILE)
    except Exception as e:
        log.error("Error comparing path", path=local.path, error=str(e))
        return DiffRow(STATUS_ERROR, local.path, KIND_FILE)

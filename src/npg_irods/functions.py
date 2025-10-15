# -*- coding: utf-8 -*-
#
# Copyright © 2025 Genome Research Ltd. All rights reserved.
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

"""This module provides free functions that are general purpose and don't fit in
other categories (such as the instrument-specific modules or metadata)."""

import re
from pathlib import Path
from typing import Callable, TypeVar

from structlog.stdlib import get_logger

log = get_logger(__name__)

T = TypeVar("T")
Predicate = Callable[[T], bool]
PathPredicate = Predicate[Path]

def is_true(_: Path) -> bool:
    """Always returns true."""
    return True

def is_false(_: Path) -> bool:
    """Always returns false."""
    return False

# def and(*preds: Predicate[T]) -> Predicate[T]:
#     return lambda x: all(p(x) for p in preds)
#
# def Or(*preds: Predicate[T]) -> Predicate[T]:
#     return lambda x: any(p(x) for p in preds)

# def Not(pred: Predicate[T]) -> Predicate[T]:
#     return lambda x: not pred(x)

def _is_top_level_file(path: Path, parent: Path):
    if not path.is_file():
        return False

    path_absolute = path.resolve()
    parent_absolute = parent.resolve()

    return path_absolute.parent == parent_absolute

def _make_match_pattern(pattern: str, flags: int | re.RegexFlag = 0) -> PathPredicate:
    r = re.compile(pattern, flags=flags)
    def f(path: Path) -> bool:
        return bool(r.search(path.as_posix()))
    return f

def _make_match_patterns(patterns: list[str], flags: int | re.RegexFlag = 0) -> PathPredicate:
    regexes = [re.compile(p, flags=flags) for p in patterns]
    def f(path: Path) -> bool:
        return any(r.search(path.as_posix()) for r in regexes)
    return f

def match_patterns(path: Path, patterns: list[str], flags: int | re.RegexFlag = 0) -> bool:
    regexes = [re.compile(p, flags=flags) for p in patterns]
    return any(r.search(path.as_posix()) for r in regexes)

is_md5 = _make_match_pattern(".md5")

def make_path_filter(
    include_patterns: list[str] = None,
    exclude_patterns: list[str] = None,
    include_top_level_files: bool = False,
    exclude_md5: bool = False,
    src: Path | None = None,
    flags: int | re.RegexFlag = 0,
) -> PathPredicate:
    """Return a function that filters paths based on the given filters.

    Args:
        include_patterns: Include paths matching the given regular expressions.
        exclude_patterns: Exclude paths matching the given regular expressions.
            Exclude applied after include.
        include_top_level_files: Include files immediately below top level directory.
        exclude_md5: Exclude md5 files.
        src: Top level directory to compare against for include_top_level_files. Required if include_top_level_files=True.
        flags: Optional regex flags to use when compiling the patterns.

    Returns:
        A function that accepts a Path and returns True if the path doesn't
        match any of the include filters or matches any of the exclude
        filters, False otherwise.
    """
    if include_top_level_files and not src:
        raise ValueError("`src` is required if when `include_top_level_files` is True")

    include_patterns = include_patterns or []
    exclude_patterns = exclude_patterns or []

    # include_regexes = [re.compile(p, flags=flags) for p in include_patterns]
    # exclude_regexes = [re.compile(p, flags=flags) for p in exclude_patterns]
    #
    # match_include_patterns = _make_match_patterns(include_patterns, flags) if include_patterns else is_true
    # match_exclude_patterns = _make_match_patterns(exclude_patterns, flags) if exclude_patterns else is_true

    def path_filter(path: Path) -> bool:
        if include_patterns or include_top_level_files:
            include = False

            if match_patterns(path, include_patterns, flags):
                include = True

            if include_top_level_files:
                if _is_top_level_file(path, src):
                    include = True

            if not include:
                return True

        if match_patterns(path, exclude_patterns, flags):
            return True

        if exclude_md5:
            if is_md5(path):
                return True

        return False

    return path_filter

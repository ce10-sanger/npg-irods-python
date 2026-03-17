#!/usr/bin/env python3
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

from __future__ import annotations

import argparse
import json
import sys

try:
    import language_tool_python
except ImportError:  # pragma: no cover - exercised through the shell script
    language_tool_python = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check extracted prose for grammar issues using LanguageTool."
    )
    parser.add_argument("--language", default="en-GB")
    parser.add_argument("--min-length", type=int, default=10)
    return parser.parse_args()


def iter_entries() -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    for line in sys.stdin:
        stripped = line.strip()
        if stripped:
            entries.append(json.loads(stripped))
    return entries


def should_check(text: str, min_length: int) -> bool:
    if len(text) < min_length:
        return False
    return any(char.isalpha() for char in text)


def format_match(entry: dict[str, object], match: object) -> str:
    replacements = ", ".join(getattr(match, "replacements", [])[:3])
    detail = f"{entry['path']}:{entry['line']}:{entry['column']}: {entry['kind']}: "
    detail += f"{getattr(match, 'message', 'Issue detected')} [{getattr(match, 'ruleId', 'unknown')}]"
    if replacements:
        detail += f" Suggestions: {replacements}"
    detail += f"\n    {entry['text']}"
    return detail


def main() -> int:
    args = parse_args()
    if language_tool_python is None:
        print(
            "language_tool_python is not installed. Install it with "
            f"`{sys.executable} -m pip install language-tool-python`.",
            file=sys.stderr,
        )
        return 2

    entries = iter_entries()
    if not entries:
        return 0

    tool = language_tool_python.LanguageTool(args.language)
    problems = 0
    for entry in entries:
        text = str(entry["text"])
        if not should_check(text, args.min_length):
            continue
        matches = tool.check(text)
        for match in matches:
            print(format_match(entry, match))
            problems += 1

    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())

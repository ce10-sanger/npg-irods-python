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
import ast
import json
import token
import tokenize
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_PATHS = ("src", "tests", "scripts")
PYTEST_IT_NAMES = {"describe", "context", "it"}
IGNORED_COMMENTS = (
    "-*- coding:",
    "Copyright",
    "This program is free software:",
    "it under the terms of the GNU General Public License",
    "the Free Software Foundation, either version 3 of the License, or",
    "(at your option) any later version.",
    "This program is distributed in the hope that it will be useful,",
    "but WITHOUT ANY WARRANTY;",
    "MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.",
    "GNU General Public License for more details.",
    "You should have received a copy of the GNU General Public License",
    "along with this program.",
    "@author",
)


@dataclass(frozen=True, order=True)
class ProseItem:
    path: str
    line: int
    column: int
    kind: str
    text: str

    def to_json(self) -> str:
        return json.dumps(
            {
                "path": self.path,
                "line": self.line,
                "column": self.column,
                "kind": self.kind,
                "text": self.text,
            },
            ensure_ascii=True,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract prose from Python comments, docstrings and pytest-it text."
    )
    parser.add_argument("paths", nargs="*", default=list(DEFAULT_PATHS))
    return parser.parse_args()


def iter_python_files(paths: Iterable[str]) -> Iterable[Path]:
    for raw_path in paths:
        path = Path(raw_path)
        if path.is_file() and path.suffix == ".py":
            yield path
        elif path.is_dir():
            yield from sorted(p for p in path.rglob("*.py") if p.is_file())


def should_ignore_comment(text: str) -> bool:
    if not text:
        return True
    return any(text.startswith(prefix) for prefix in IGNORED_COMMENTS)


def extract_comments(path: Path, source: str) -> list[ProseItem]:
    items: list[ProseItem] = []
    for tok in tokenize.generate_tokens(
        iter(source.splitlines(keepends=True)).__next__
    ):
        if tok.type != token.COMMENT:
            continue
        text = tok.string.lstrip("#").strip()
        if should_ignore_comment(text):
            continue
        items.append(
            ProseItem(
                path=str(path),
                line=tok.start[0],
                column=tok.start[1] + 1,
                kind="comment",
                text=text,
            )
        )
    return items


def iter_docstring_nodes(tree: ast.AST) -> Iterable[ast.AST]:
    if isinstance(tree, ast.Module):
        yield tree
    for node in ast.walk(tree):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def extract_docstrings(path: Path, tree: ast.AST) -> list[ProseItem]:
    items: list[ProseItem] = []
    for node in iter_docstring_nodes(tree):
        body = getattr(node, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            text = first.value.value.strip()
            if text:
                items.append(
                    ProseItem(
                        path=str(path),
                        line=first.lineno,
                        column=first.col_offset + 1,
                        kind="docstring",
                        text=text,
                    )
                )
    return items


def get_call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def extract_pytest_it_text(path: Path, tree: ast.AST) -> list[ProseItem]:
    items: list[ProseItem] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = get_call_name(node)
        if name not in PYTEST_IT_NAMES or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Constant) or not isinstance(first.value, str):
            continue
        text = first.value.strip()
        if not text:
            continue
        items.append(
            ProseItem(
                path=str(path),
                line=first.lineno,
                column=first.col_offset + 1,
                kind=f"pytest-{name}",
                text=text,
            )
        )
    return items


def extract_from_file(path: Path) -> list[ProseItem]:
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    items = [
        *extract_comments(path, source),
        *extract_docstrings(path, tree),
        *extract_pytest_it_text(path, tree),
    ]
    return sorted(set(items))


def main() -> int:
    args = parse_args()
    for path in iter_python_files(args.paths):
        for item in extract_from_file(path):
            print(item.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

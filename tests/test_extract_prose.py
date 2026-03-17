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

import json
import subprocess
import sys
from pathlib import Path


def run_extract_prose(path: Path) -> list[dict[str, str]]:
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, str(repo_root / "scripts" / "extract_prose.py"), str(path)],
        check=True,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def test_extracts_comments_docstrings_and_pytest_it_text(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "\n".join(
            [
                '"""Module docstring."""',
                "",
                "from pytest import mark as m",
                "",
                "# Useful comment",
                "@m.describe('Widget checks')",
                "class TestWidget:",
                '    """Class docstring."""',
                '    @m.context("When widgets are loaded")',
                '    @m.it("Returns a widget")',
                "    def test_widget(self):",
                "        pass",
            ]
        ),
        encoding="utf-8",
    )

    items = run_extract_prose(sample)

    assert {"kind": "comment", "text": "Useful comment"} in [
        {"kind": item["kind"], "text": item["text"]} for item in items
    ]
    assert {"kind": "docstring", "text": "Module docstring."} in [
        {"kind": item["kind"], "text": item["text"]} for item in items
    ]
    assert {"kind": "pytest-describe", "text": "Widget checks"} in [
        {"kind": item["kind"], "text": item["text"]} for item in items
    ]
    assert {"kind": "pytest-context", "text": "When widgets are loaded"} in [
        {"kind": item["kind"], "text": item["text"]} for item in items
    ]
    assert {"kind": "pytest-it", "text": "Returns a widget"} in [
        {"kind": item["kind"], "text": item["text"]} for item in items
    ]


def test_ignores_license_boilerplate_comments(tmp_path: Path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "\n".join(
            [
                "# -*- coding: utf-8 -*-",
                "# Copyright © 2026 Genome Research Ltd. All rights reserved.",
                "# Useful comment",
            ]
        ),
        encoding="utf-8",
    )

    items = run_extract_prose(sample)

    assert len(items) == 1
    assert items[0]["kind"] == "comment"
    assert items[0]["text"] == "Useful comment"

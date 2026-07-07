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

import json
from unittest.mock import MagicMock, patch

import pytest
from pytest import mark as m

from npg_irods import diff
from npg_irods.cli import diff_directory as diff_directory_script


def file_entry(path, size=1, checksum="a" * 32):
    return diff.DiffEntry(
        path=path,
        kind=diff.KIND_FILE,
        size=size,
        checksum=lambda checksum=checksum: checksum,
    )


def dir_entry(path):
    return diff.DiffEntry(path=path, kind=diff.KIND_DIRECTORY)


def rows_as_tuples(rows):
    return [(row.status, row.path) for row in rows]


@m.describe("Directory diff")
class TestDirectoryDiff:
    @m.context("When entries differ in all supported ways")
    @m.it("Returns sorted diff rows")
    def test_diff_entries(self):
        local = {
            "a.txt": file_entry("a.txt", checksum="a" * 32),
            "b.txt": file_entry("b.txt"),
            "d.txt": file_entry("d.txt", size=1),
            "e.txt": file_entry("e.txt", checksum="e" * 32),
            "same_dir": dir_entry("same_dir"),
            "type_mismatch": dir_entry("type_mismatch"),
        }
        irods = {
            "a.txt": file_entry("a.txt", checksum="a" * 32),
            "c.txt": file_entry("c.txt"),
            "d.txt": file_entry("d.txt", size=2),
            "e.txt": file_entry("e.txt", checksum="f" * 32),
            "same_dir": dir_entry("same_dir"),
            "type_mismatch": file_entry("type_mismatch"),
        }

        rows = diff.diff_entries(local, irods)

        assert rows_as_tuples(rows) == [
            ("=", "a.txt"),
            (">", "b.txt"),
            ("<", "c.txt"),
            ("*", "d.txt"),
            ("*", "e.txt"),
            ("=", "same_dir"),
            (">", "type_mismatch"),
            ("<", "type_mismatch"),
        ]

    @m.context("When file comparison raises an exception")
    @m.it("Returns an error row")
    def test_file_comparison_error(self):
        local = {"a.txt": file_entry("a.txt")}
        irods = {
            "a.txt": diff.DiffEntry(
                path="a.txt",
                kind=diff.KIND_FILE,
                size=1,
                checksum=lambda: (_ for _ in ()).throw(ValueError("bad checksum")),
            )
        }

        rows = diff.diff_entries(local, irods)

        assert rows_as_tuples(rows) == [("!", "a.txt")]
        assert diff.has_errors(rows)

    @m.context("When a local directory is scanned")
    @m.it("Returns POSIX relative file and directory entries")
    def test_scan_local_directory(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "b.txt").write_text("test")

        entries = diff.scan_local_directory(tmp_path)

        assert entries["a"].kind == diff.KIND_DIRECTORY
        assert entries["a/b.txt"].kind == diff.KIND_FILE
        assert entries["a/b.txt"].get_size() == 4

    @m.context("When the iRODS collection is absent")
    @m.it("Reports all local entries as local-only")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    @patch("npg_irods.diff.client_pool")
    def test_diff_directory_irods_missing(
        self, mock_client_pool: MagicMock, _mock_rods_path_type: MagicMock, tmp_path
    ):
        mock_client_pool.return_value.__enter__.return_value = object()
        (tmp_path / "a.txt").write_text("test")

        rows = diff.diff_directory(tmp_path, "/missing")

        assert rows_as_tuples(rows) == [(">", "a.txt")]

    @m.context("When both roots are absent")
    @m.it("Raises an error")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    @patch("npg_irods.diff.client_pool")
    def test_diff_directory_both_missing(
        self, mock_client_pool: MagicMock, _mock_rods_path_type: MagicMock, tmp_path
    ):
        mock_client_pool.return_value.__enter__.return_value = object()

        with pytest.raises(FileNotFoundError):
            diff.diff_directory(tmp_path / "missing", "/missing")


@m.describe("Diff directory script")
class TestDiffDirectoryScript:
    @m.context("When run with default parameters")
    @m.it("Prints plain text diff rows")
    @patch("npg_irods.cli.diff_directory.diff_directory", autospec=True)
    def test_main_plain_text(self, mock_diff_directory: MagicMock, capsys):
        mock_diff_directory.return_value = [
            diff.DiffRow("=", "a.txt"),
            diff.DiffRow(">", "b.txt"),
        ]

        self._main(["directory", "/collection"])

        mock_diff_directory.assert_called_once_with(
            "directory",
            "/collection",
            local_checksum=None,
            num_clients=4,
        )
        assert capsys.readouterr().out == "= a.txt\n> b.txt\n"

    @m.context("When run with JSON output")
    @m.it("Prints JSON Lines")
    @patch("npg_irods.cli.diff_directory.diff_directory", autospec=True)
    def test_main_json(self, mock_diff_directory: MagicMock, capsys):
        mock_diff_directory.return_value = [diff.DiffRow("*", "a.txt")]

        self._main(["--json", "directory", "/collection"])

        assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
            {"status": "*", "path": "a.txt"}
        ]

    @m.context("When any error rows are produced")
    @m.it("Exits non-zero after printing output")
    @patch("npg_irods.cli.diff_directory.diff_directory", autospec=True)
    def test_main_error_status(self, mock_diff_directory: MagicMock, capsys):
        mock_diff_directory.return_value = [diff.DiffRow("!", "a.txt")]

        with pytest.raises(SystemExit):
            self._main(["directory", "/collection"])

        assert capsys.readouterr().out == "! a.txt\n"

    @staticmethod
    def _main(args: list[str]):
        with patch("sys.argv", ["diff-directory"] + args):
            diff_directory_script.main()

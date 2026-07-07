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


def rows_as_tuples(rows):
    return [(row.status, row.path) for row in rows]


@m.describe("Directory diff")
class TestDirectoryDiff:
    @m.context("When streaming file comparisons")
    @m.it("Yields same, different and error rows")
    @patch("npg_irods.diff._irods_child_entries")
    @patch("npg_irods.diff._local_child_entries")
    @patch("npg_irods.diff.client_pool")
    @patch("npg_irods.diff.rods_path_type", return_value=diff.Collection)
    def test_iter_diff_directory_file_comparison_rows(
        self,
        _mock_rods_path_type: MagicMock,
        mock_client_pool: MagicMock,
        mock_local_child_entries: MagicMock,
        mock_irods_child_entries: MagicMock,
        tmp_path,
    ):
        mock_client_pool.return_value.__enter__.return_value = object()
        mock_local_child_entries.return_value = {
            "a.txt": file_entry("a.txt", size=1, checksum="a" * 32),
            "b.txt": file_entry("b.txt", size=1, checksum="b" * 32),
            "c.txt": file_entry("c.txt", size=1, checksum="c" * 32),
            "d.txt": file_entry("d.txt", size=1, checksum="d" * 32),
        }
        mock_irods_child_entries.return_value = {
            "a.txt": file_entry("a.txt", size=1, checksum="a" * 32),
            "b.txt": file_entry("b.txt", size=2, checksum="b" * 32),
            "c.txt": file_entry("c.txt", size=1, checksum="e" * 32),
            "d.txt": diff.DiffEntry(
                path="d.txt",
                kind=diff.KIND_FILE,
                size=1,
                checksum=lambda: (_ for _ in ()).throw(ValueError("bad checksum")),
            ),
        }

        rows = diff.diff_directory(tmp_path, "/collection")

        assert rows_as_tuples(rows) == [
            ("=", "a.txt"),
            ("*", "b.txt"),
            ("*", "c.txt"),
            ("!", "d.txt"),
        ]

    @m.context("When streaming a local-only tree")
    @m.it("Yields rows in sorted depth-first order")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_iter_diff_directory_depth_first(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "z.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")

        rows = diff.diff_directory(tmp_path, "/missing")

        assert rows_as_tuples(rows) == [
            (">", "a"),
            (">", "a/z.txt"),
            (">", "b.txt"),
        ]

    @m.context("When streaming starts before recursing")
    @m.it("Yields a one-sided directory before listing its children")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    @patch("npg_irods.diff._local_child_entries")
    def test_iter_diff_directory_yields_before_recursing(
        self,
        mock_local_child_entries: MagicMock,
        _mock_rods_path_type: MagicMock,
        tmp_path,
    ):
        child_path = tmp_path / "a"
        mock_local_child_entries.return_value = {
            "a": diff.DiffEntry(
                path="a",
                kind=diff.KIND_DIRECTORY,
                source_path=child_path,
            )
        }

        iterator = diff.iter_diff_directory(tmp_path, "/missing")

        assert next(iterator) == diff.DiffRow(">", "a")
        mock_local_child_entries.assert_called_once()

    @m.context("When one-sided directories are not recursed")
    @m.it("Reports the directory but skips descendants")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_diff_directory_no_recurse_missing_dirs(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "z.txt").write_text("a")
        (tmp_path / "b.txt").write_text("b")

        rows = diff.diff_directory(tmp_path, "/missing", no_recurse_missing_dirs=True)

        assert rows_as_tuples(rows) == [
            (">", "a"),
            (">", "b.txt"),
        ]

    @m.context("When a type mismatch is pruned")
    @m.it("Reports both sides without recursing into the directory side")
    @patch("npg_irods.diff._irods_child_entries")
    @patch("npg_irods.diff._local_child_entries")
    @patch("npg_irods.diff.client_pool")
    @patch("npg_irods.diff.rods_path_type", return_value=diff.Collection)
    def test_diff_directory_type_mismatch_no_recurse_missing_dirs(
        self,
        _mock_rods_path_type: MagicMock,
        mock_client_pool: MagicMock,
        mock_local_child_entries: MagicMock,
        mock_irods_child_entries: MagicMock,
        tmp_path,
    ):
        mock_client_pool.return_value.__enter__.return_value = object()
        mock_local_child_entries.return_value = {
            "a": diff.DiffEntry(
                path="a",
                kind=diff.KIND_DIRECTORY,
                source_path=tmp_path / "a",
            )
        }
        mock_irods_child_entries.return_value = {"a": file_entry("a")}

        rows = diff.diff_directory(
            tmp_path,
            "/collection",
            no_recurse_missing_dirs=True,
        )

        assert rows_as_tuples(rows) == [
            (">", "a"),
            ("<", "a"),
        ]
        mock_local_child_entries.assert_called_once()

    @m.context("When the iRODS collection is absent")
    @m.it("Reports all local entries as local-only")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_diff_directory_irods_missing(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        (tmp_path / "a.txt").write_text("test")

        rows = diff.diff_directory(tmp_path, "/missing")

        assert rows_as_tuples(rows) == [(">", "a.txt")]

    @m.context("When both roots are absent")
    @m.it("Raises an error")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_diff_directory_both_missing(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        with pytest.raises(FileNotFoundError):
            diff.diff_directory(tmp_path / "missing", "/missing")


@m.describe("Diff directory script")
class TestDiffDirectoryScript:
    @m.context("When run with default parameters")
    @m.it("Prints plain text diff rows")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_plain_text(self, mock_iter_diff_directory: MagicMock, capsys):
        mock_iter_diff_directory.return_value = [
            diff.DiffRow("=", "a.txt"),
            diff.DiffRow(">", "b.txt"),
        ]

        self._main(["directory", "/collection"])

        mock_iter_diff_directory.assert_called_once_with(
            "directory",
            "/collection",
            local_checksum=None,
            num_clients=4,
            no_recurse_missing_dirs=False,
        )
        assert capsys.readouterr().out == "= a.txt\n> b.txt\n"

    @m.context("When run with JSON output")
    @m.it("Prints JSON Lines")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_json(self, mock_iter_diff_directory: MagicMock, capsys):
        mock_iter_diff_directory.return_value = [diff.DiffRow("*", "a.txt")]

        self._main(["--json", "directory", "/collection"])

        assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
            {"status": "*", "path": "a.txt"}
        ]

    @m.context("When missing directory recursion is disabled")
    @m.it("Passes the option to the diff iterator")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_no_recurse_missing_dirs(self, mock_iter_diff_directory: MagicMock):
        mock_iter_diff_directory.return_value = []

        self._main(["--no-recurse-missing-dirs", "directory", "/collection"])

        assert (
            mock_iter_diff_directory.call_args.kwargs["no_recurse_missing_dirs"] is True
        )

    @m.context("When any error rows are produced")
    @m.it("Exits non-zero after printing output")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_error_status(self, mock_iter_diff_directory: MagicMock, capsys):
        mock_iter_diff_directory.return_value = [diff.DiffRow("!", "a.txt")]

        with pytest.raises(SystemExit):
            self._main(["directory", "/collection"])

        assert capsys.readouterr().out == "! a.txt\n"

    @staticmethod
    def _main(args: list[str]):
        with patch("sys.argv", ["diff-directory"] + args):
            diff_directory_script.main()

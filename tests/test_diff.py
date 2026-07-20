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
from pathlib import PurePath
from types import SimpleNamespace
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


def rows_as_triples(rows):
    return [(row.status, row.path, row.kind) for row in rows]


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

        assert rows_as_triples(rows) == [
            (diff.STATUS_SAME, "a.txt", diff.KIND_FILE),
            (diff.STATUS_DIFFERENT, "b.txt", diff.KIND_FILE),
            (diff.STATUS_DIFFERENT, "c.txt", diff.KIND_FILE),
            (diff.STATUS_ERROR, "d.txt", diff.KIND_FILE),
        ]

    @m.context("When iRODS data objects are listed")
    @m.it("Builds relative paths from parent path and data object name")
    def test_irods_child_entries_data_object_path(self):
        obj = SimpleNamespace(
            rods_type=diff.DataObject,
            path=PurePath("/root/sub"),
            name="file.txt",
            size=lambda: 1,
            checksum=lambda: "a" * 32,
        )
        coll = SimpleNamespace(iter_contents=lambda recurse=False: [obj])

        entries = diff._irods_child_entries(coll, PurePath("/root"))

        assert set(entries) == {"file.txt"}
        assert entries["file.txt"].path == "sub/file.txt"
        assert entries["file.txt"].source_path == PurePath("/root/sub/file.txt")

    @m.context("When no local checksum function is provided")
    @m.it("Calculates the local checksum on the fly")
    @patch("npg_irods.diff.calculate_file_checksum", autospec=True)
    def test_local_checksum_fn_calculates_checksum_on_the_fly(
        self, mock_calculate_file_checksum: MagicMock, tmp_path, caplog
    ):
        path = tmp_path / "a.txt"
        path.write_text("test")
        mock_calculate_file_checksum.return_value = "a" * 32

        checksum_fn = diff._local_checksum_fn(path, None)

        with caplog.at_level("DEBUG"):
            checksum = checksum_fn()

        assert checksum == "a" * 32
        mock_calculate_file_checksum.assert_called_once_with(path)
        assert "Calculating local checksum on the fly" in caplog.text

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
            (diff.STATUS_LOCAL, "a"),
            (diff.STATUS_LOCAL, "a/z.txt"),
            (diff.STATUS_LOCAL, "b.txt"),
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

        assert next(iterator) == diff.DiffRow(
            diff.STATUS_LOCAL, "a", diff.KIND_DIRECTORY
        )
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
            (diff.STATUS_LOCAL, "a"),
            (diff.STATUS_LOCAL, "b.txt"),
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

        assert rows_as_triples(rows) == [
            (diff.STATUS_LOCAL, "a", diff.KIND_DIRECTORY),
            (diff.STATUS_IRODS, "a", diff.KIND_FILE),
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

        assert rows_as_tuples(rows) == [(diff.STATUS_LOCAL, "a.txt")]

    @m.context("With an include filter")
    @m.it("Only compares matching paths")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_diff_directory_include_filter(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        (tmp_path / "keep.txt").write_text("test")
        (tmp_path / "skip.txt").write_text("test")

        rows = diff.diff_directory(
            tmp_path,
            "/missing",
            filter_fn=diff.make_diff_filter(include_patterns=["keep"]),
        )

        assert rows_as_tuples(rows) == [(diff.STATUS_LOCAL, "keep.txt")]

    @m.context("With an exclude filter")
    @m.it("Skips matching paths")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_diff_directory_exclude_filter(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        (tmp_path / "keep.txt").write_text("test")
        (tmp_path / "skip.txt").write_text("test")

        rows = diff.diff_directory(
            tmp_path,
            "/missing",
            filter_fn=diff.make_diff_filter(exclude_patterns=["skip"]),
        )

        assert rows_as_tuples(rows) == [(diff.STATUS_LOCAL, "keep.txt")]

    @m.context("With the documented macOS metadata exclude filter")
    @m.it("Skips exact DS_Store filenames at any depth")
    def test_diff_directory_ds_store_exclude_filter(self):
        filter_fn = diff.make_diff_filter(exclude_patterns=[r"(^|/)\.DS_Store$"])

        assert filter_fn(file_entry(".DS_Store")) is True
        assert filter_fn(file_entry("nested/.DS_Store")) is True
        assert filter_fn(file_entry(".DS_Store.backup")) is False
        assert filter_fn(file_entry("my.DS_Store")) is False

    @m.context("With include and exclude filters")
    @m.it("Applies exclude filters after include filters")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_diff_directory_include_exclude_filter(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        (tmp_path / "a_keep.txt").write_text("test")
        (tmp_path / "a_skip.txt").write_text("test")
        (tmp_path / "b.txt").write_text("test")

        rows = diff.diff_directory(
            tmp_path,
            "/missing",
            filter_fn=diff.make_diff_filter(
                include_patterns=["a_"], exclude_patterns=["skip"]
            ),
        )

        assert rows_as_tuples(rows) == [(diff.STATUS_LOCAL, "a_keep.txt")]

    @m.context("With include-top-level-files")
    @m.it("Includes only files directly below the root")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_diff_directory_include_top_level_files(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "nested.txt").write_text("test")
        (tmp_path / "root.txt").write_text("test")

        rows = diff.diff_directory(
            tmp_path,
            "/missing",
            filter_fn=diff.make_diff_filter(include_top_level_files=True),
        )

        assert rows_as_tuples(rows) == [(diff.STATUS_LOCAL, "root.txt")]

    @m.context("With exclude-md5")
    @m.it("Skips matching local and iRODS md5 paths")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_diff_directory_exclude_md5_filter(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        (tmp_path / "a.txt").write_text("test")
        (tmp_path / "a.txt.md5").write_text("test")
        (tmp_path / "dir").mkdir()
        (tmp_path / "dir" / "b.txt").write_text("test")
        (tmp_path / "dir" / "b.txt.md5").write_text("test")

        rows = diff.diff_directory(
            tmp_path,
            "/missing",
            filter_fn=diff.make_diff_filter(exclude_md5=True),
        )

        assert rows_as_tuples(rows) == [
            (diff.STATUS_LOCAL, "a.txt"),
            (diff.STATUS_LOCAL, "dir"),
            (diff.STATUS_LOCAL, "dir/b.txt"),
        ]

        obj = SimpleNamespace(
            rods_type=diff.DataObject,
            path=PurePath("/root"),
            name="c.txt.md5",
            size=lambda: 1,
            checksum=lambda: "a" * 32,
        )
        coll = SimpleNamespace(iter_contents=lambda recurse=False: [obj])

        assert (
            diff._irods_child_entries(
                coll, PurePath("/root"), diff.make_diff_filter(exclude_md5=True)
            )
            == {}
        )

    @m.context("When a filtered directory has matching descendants")
    @m.it("Prunes the directory and does not recurse")
    @patch("npg_irods.diff.rods_path_type", return_value=None)
    def test_diff_directory_filter_prunes_directory(
        self, _mock_rods_path_type: MagicMock, tmp_path
    ):
        (tmp_path / "a").mkdir()
        (tmp_path / "a" / "z.txt").write_text("test")

        rows = diff.diff_directory(
            tmp_path,
            "/missing",
            filter_fn=diff.make_diff_filter(include_patterns=["z.txt"]),
        )

        assert rows == []

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
    @m.context("When help is requested")
    @m.it("Shows how to exclude macOS Finder metadata")
    def test_main_help_ds_store_example(self, capsys):
        with pytest.raises(SystemExit) as exit_info:
            self._main(["--help"])

        assert exit_info.value.code == 0
        assert (
            "diff-directory --exclude '(^|/)\\.DS_Store$' DIRECTORY COLLECTION"
            in capsys.readouterr().out
        )

    @m.context("When run with default parameters")
    @m.it("Prints plain text diff rows")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_plain_text(self, mock_iter_diff_directory: MagicMock, capsys):
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_SAME, "a", diff.KIND_DIRECTORY),
        ]

        self._main(["directory", "/collection"])

        mock_iter_diff_directory.assert_called_once_with(
            "directory",
            "/collection",
            local_checksum=None,
            filter_fn=None,
            num_clients=4,
            no_recurse_missing_dirs=False,
        )
        assert capsys.readouterr().out == "= a/\n"

    @m.context("When run with JSON output")
    @m.it("Prints JSON Lines")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_json(self, mock_iter_diff_directory: MagicMock, capsys):
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_SAME, "a", diff.KIND_DIRECTORY)
        ]

        self._main(["--json", "directory", "/collection"])

        assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
            {"status": "same", "path": "a", "kind": diff.KIND_DIRECTORY}
        ]

    @m.context("When filtering options are supplied")
    @m.it("Builds and passes a diff filter")
    @patch("npg_irods.cli.diff_directory.make_diff_filter", autospec=True)
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_filter_options(
        self,
        mock_iter_diff_directory: MagicMock,
        mock_make_diff_filter: MagicMock,
    ):
        filter_fn = lambda entry: False
        mock_make_diff_filter.return_value = filter_fn
        mock_iter_diff_directory.return_value = []

        self._main(
            [
                "--include",
                "include1",
                "--include",
                "include2",
                "--exclude",
                "exclude1",
                "--include-top-level-files",
                "--exclude-md5",
                "directory",
                "/collection",
            ]
        )

        mock_make_diff_filter.assert_called_once_with(
            include_patterns=["include1", "include2"],
            exclude_patterns=["exclude1"],
            include_top_level_files=True,
            exclude_md5=True,
        )
        assert mock_iter_diff_directory.call_args.kwargs["filter_fn"] is filter_fn

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
    @m.it("Exits with error status after printing all output")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_error_status(self, mock_iter_diff_directory: MagicMock, capsys):
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_ERROR, "a.txt", diff.KIND_FILE),
            diff.DiffRow(diff.STATUS_SAME, "b.txt", diff.KIND_FILE),
        ]

        with pytest.raises(SystemExit) as exit_info:
            self._main(["directory", "/collection"])

        assert exit_info.value.code == diff.EXIT_ERROR
        assert capsys.readouterr().out == "! a.txt\n= b.txt\n"

    @m.context("When any difference rows are produced")
    @m.it("Exits with difference status after printing all output")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_difference_status(self, mock_iter_diff_directory: MagicMock, capsys):
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_LOCAL, "a.txt", diff.KIND_FILE),
            diff.DiffRow(diff.STATUS_SAME, "b.txt", diff.KIND_FILE),
        ]

        with pytest.raises(SystemExit) as exit_info:
            self._main(["directory", "/collection"])

        assert exit_info.value.code == diff.EXIT_DIFFERENCE
        assert capsys.readouterr().out == "> a.txt\n= b.txt\n"

    @m.context("When both differences and errors are produced")
    @m.it("Exits with error status after printing all output")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_error_takes_precedence(
        self, mock_iter_diff_directory: MagicMock, capsys
    ):
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_LOCAL, "a.txt", diff.KIND_FILE),
            diff.DiffRow(diff.STATUS_ERROR, "b.txt", diff.KIND_FILE),
        ]

        with pytest.raises(SystemExit) as exit_info:
            self._main(["directory", "/collection"])

        assert exit_info.value.code == diff.EXIT_ERROR
        assert capsys.readouterr().out == "> a.txt\n! b.txt\n"

    @m.context("When exit-on-difference is set")
    @m.it("Exits with difference status after printing the first difference")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_exit_on_difference(self, mock_iter_diff_directory: MagicMock, capsys):
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_LOCAL, "a.txt", diff.KIND_FILE),
            diff.DiffRow(diff.STATUS_SAME, "b.txt", diff.KIND_FILE),
        ]

        with pytest.raises(SystemExit) as exit_info:
            self._main(["--exit-on-difference", "directory", "/collection"])

        assert exit_info.value.code == diff.EXIT_DIFFERENCE
        assert capsys.readouterr().out == "> a.txt\n"

    @m.context("When exit-on-error is set")
    @m.it("Exits with error status after printing the first error")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_exit_on_error(self, mock_iter_diff_directory: MagicMock, capsys):
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_ERROR, "a.txt", diff.KIND_FILE),
            diff.DiffRow(diff.STATUS_SAME, "b.txt", diff.KIND_FILE),
        ]

        with pytest.raises(SystemExit) as exit_info:
            self._main(["--exit-on-error", "directory", "/collection"])

        assert exit_info.value.code == diff.EXIT_ERROR
        assert capsys.readouterr().out == "! a.txt\n"

    @m.context("When diffing raises an exception")
    @m.it("Exits with error status")
    @patch("npg_irods.cli.diff_directory.iter_diff_directory", autospec=True)
    def test_main_diff_exception(self, mock_iter_diff_directory: MagicMock):
        mock_iter_diff_directory.side_effect = ValueError("bad diff")

        with pytest.raises(SystemExit) as exit_info:
            self._main(["directory", "/collection"])

        assert exit_info.value.code == diff.EXIT_ERROR

    @m.context("When checksums file cannot be read")
    @m.it("Exits with error status")
    @patch("npg_irods.cli.diff_directory.make_get_checksum", autospec=True)
    def test_main_checksums_file_exception(self, mock_make_get_checksum: MagicMock):
        mock_make_get_checksum.side_effect = ValueError("bad checksums")

        with pytest.raises(SystemExit) as exit_info:
            self._main(
                ["--use-checksums-file", "checksums.md5", "directory", "/collection"]
            )

        assert exit_info.value.code == diff.EXIT_ERROR

    @staticmethod
    def _main(args: list[str]):
        with patch("sys.argv", ["diff-directory"] + args):
            diff_directory_script.main()

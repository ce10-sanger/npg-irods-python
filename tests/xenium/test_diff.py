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
from pathlib import Path, PurePath
from unittest.mock import ANY, MagicMock, patch

import pytest
from pytest import mark as m

from npg_irods import diff
from npg_irods.cli import diff_xenium as diff_xenium_script
from npg_irods.metadata.xenium import EXPERIMENT_FILENAME
from npg_irods.xenium import iter_output_directories, xenium_irods_partial_path


def write_experiment(path: Path, instrument="XETG00000", slide="0000000"):
    path.write_text(
        json.dumps(
            {
                "instrument_sn": instrument,
                "slide_id": slide,
            }
        )
    )


@m.describe("Xenium output directory discovery")
class TestXeniumOutputDirectoryDiscovery:

    @m.context("When a root contains Xenium output directories")
    @m.it("Finds directories containing experiment.xenium")
    def test_iter_output_directories(self, tmp_path):
        result_dir = tmp_path / "a" / "result"
        result_dir.mkdir(parents=True)
        write_experiment(result_dir / EXPERIMENT_FILENAME)
        (tmp_path / "not_xenium").mkdir()

        assert list(iter_output_directories(tmp_path)) == [result_dir]

    @m.context("When a symlink points to a Xenium output directory")
    @m.it("Does not follow the symlink")
    def test_iter_output_directories_no_symlinks(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        target = tmp_path / "target"
        target.mkdir()
        write_experiment(target / EXPERIMENT_FILENAME)
        (root / "link").symlink_to(target, target_is_directory=True)

        assert list(iter_output_directories(root)) == []

    @m.context("When mapping a Xenium output directory to iRODS")
    @m.it("Uses instrument, slide and directory name")
    def test_xenium_irods_partial_path(self, tmp_path):
        result_dir = tmp_path / "result"
        result_dir.mkdir()
        write_experiment(result_dir / EXPERIMENT_FILENAME)

        assert xenium_irods_partial_path(result_dir) == PurePath(
            "XETG00000", "0000000", "result"
        )


@m.describe("Diff Xenium script")
class TestDiffXeniumScript:

    @m.context("When run with default parameters")
    @m.it("Prints one text row per output directory")
    @patch("npg_irods.cli.diff_xenium.iter_diff_directory", autospec=True)
    @patch("npg_irods.cli.diff_xenium.xenium_irods_partial_path", autospec=True)
    @patch("npg_irods.cli.diff_xenium.iter_output_directories", autospec=True)
    def test_main_plain_text(
        self,
        mock_iter_output_directories: MagicMock,
        mock_xenium_irods_partial_path: MagicMock,
        mock_iter_diff_directory: MagicMock,
        capsys,
    ):
        experiment = Path("experiment")
        collection = PurePath("XETG00000", "0000000", "experiment")
        mock_iter_output_directories.return_value = [experiment]
        mock_xenium_irods_partial_path.return_value = collection
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_SAME, "a", diff.KIND_DIRECTORY),
            diff.DiffRow(diff.STATUS_SAME, "a/b.txt", diff.KIND_FILE),
        ]

        self._main(["root", "/irods/xenium"])

        mock_iter_output_directories.assert_called_once_with(Path("root"))
        mock_xenium_irods_partial_path.assert_called_once_with(experiment)
        mock_iter_diff_directory.assert_called_once_with(
            experiment,
            PurePath("/irods/xenium/XETG00000/0000000/experiment"),
            local_checksum=None,
            filter_fn=ANY,
        )
        filter_fn = mock_iter_diff_directory.call_args.kwargs["filter_fn"]
        assert filter_fn(diff.DiffEntry(".DS_Store", diff.KIND_FILE)) is True
        assert filter_fn(diff.DiffEntry("nested/.DS_Store", diff.KIND_FILE)) is True
        assert filter_fn(diff.DiffEntry(".DS_Store.backup", diff.KIND_FILE)) is False
        assert filter_fn(diff.DiffEntry("my.DS_Store", diff.KIND_FILE)) is False
        assert (
            capsys.readouterr().out
            == "= experiment /irods/xenium/XETG00000/0000000/experiment\n"
        )

    @m.context("When run with JSON output")
    @m.it("Prints one JSON Line per output directory")
    @patch("npg_irods.cli.diff_xenium.iter_diff_directory", autospec=True)
    @patch("npg_irods.cli.diff_xenium.xenium_irods_partial_path", autospec=True)
    @patch("npg_irods.cli.diff_xenium.iter_output_directories", autospec=True)
    def test_main_json(
        self,
        mock_iter_output_directories: MagicMock,
        mock_xenium_irods_partial_path: MagicMock,
        mock_iter_diff_directory: MagicMock,
        capsys,
    ):
        experiment = Path("experiment")
        mock_iter_output_directories.return_value = [experiment]
        mock_xenium_irods_partial_path.return_value = PurePath(
            "XETG00000", "0000000", "experiment"
        )
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_SAME, "a.txt", diff.KIND_FILE)
        ]

        self._main(["--json", "root", "/irods/xenium"])

        assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
            {
                "experiment": "experiment",
                "collection": "/irods/xenium/XETG00000/0000000/experiment",
                "status": "same",
                "trigger": None,
            }
        ]

    @m.context("When an output directory has a non-same diff row")
    @m.it("Uses the first non-same row as trigger details")
    @patch("npg_irods.cli.diff_xenium.iter_diff_directory", autospec=True)
    @patch("npg_irods.cli.diff_xenium.xenium_irods_partial_path", autospec=True)
    @patch("npg_irods.cli.diff_xenium.iter_output_directories", autospec=True)
    def test_main_json_difference_trigger(
        self,
        mock_iter_output_directories: MagicMock,
        mock_xenium_irods_partial_path: MagicMock,
        mock_iter_diff_directory: MagicMock,
        capsys,
    ):
        experiment = Path("experiment")
        mock_iter_output_directories.return_value = [experiment]
        mock_xenium_irods_partial_path.return_value = PurePath(
            "XETG00000", "0000000", "experiment"
        )
        mock_iter_diff_directory.return_value = [
            diff.DiffRow(diff.STATUS_SAME, "a.txt", diff.KIND_FILE),
            diff.DiffRow(diff.STATUS_DIFFERENT, "b.txt", diff.KIND_FILE),
        ]

        with pytest.raises(SystemExit) as exit_info:
            self._main(["--json", "root", "/irods/xenium"])

        assert exit_info.value.code == 1
        assert [json.loads(line) for line in capsys.readouterr().out.splitlines()] == [
            {
                "experiment": "experiment",
                "collection": "/irods/xenium/XETG00000/0000000/experiment",
                "status": "different",
                "trigger": {
                    "status": "different",
                    "path": "b.txt",
                    "kind": diff.KIND_FILE,
                },
            }
        ]

    @m.context("When run with checksum files")
    @m.it("Passes the md5 file reader to the diff iterator")
    @patch("npg_irods.cli.diff_xenium.iter_diff_directory", autospec=True)
    @patch("npg_irods.cli.diff_xenium.xenium_irods_partial_path", autospec=True)
    @patch("npg_irods.cli.diff_xenium.iter_output_directories", autospec=True)
    def test_main_use_checksum_files(
        self,
        mock_iter_output_directories: MagicMock,
        mock_xenium_irods_partial_path: MagicMock,
        mock_iter_diff_directory: MagicMock,
    ):
        experiment = Path("experiment")
        mock_iter_output_directories.return_value = [experiment]
        mock_xenium_irods_partial_path.return_value = PurePath(
            "XETG00000", "0000000", "experiment"
        )
        mock_iter_diff_directory.return_value = []

        self._main(["--use-checksum-files", "root", "/irods/xenium"])

        assert (
            mock_iter_diff_directory.call_args.kwargs["local_checksum"]
            is diff_xenium_script.read_md5_file
        )

    @m.context("When run with a checksums file")
    @m.it("Builds and passes a checksum function")
    @patch("npg_irods.cli.diff_xenium.make_get_checksum", autospec=True)
    @patch("npg_irods.cli.diff_xenium.iter_diff_directory", autospec=True)
    @patch("npg_irods.cli.diff_xenium.xenium_irods_partial_path", autospec=True)
    @patch("npg_irods.cli.diff_xenium.iter_output_directories", autospec=True)
    def test_main_use_checksums_file(
        self,
        mock_iter_output_directories: MagicMock,
        mock_xenium_irods_partial_path: MagicMock,
        mock_iter_diff_directory: MagicMock,
        mock_make_get_checksum: MagicMock,
    ):
        checksum_fn = lambda path: "a" * 32
        experiment = Path("experiment")
        mock_iter_output_directories.return_value = [experiment]
        mock_xenium_irods_partial_path.return_value = PurePath(
            "XETG00000", "0000000", "experiment"
        )
        mock_iter_diff_directory.return_value = []
        mock_make_get_checksum.return_value = checksum_fn

        self._main(["--use-checksums-file", "checksums.md5", "root", "/irods/xenium"])

        mock_make_get_checksum.assert_called_once_with(Path("checksums.md5"))
        assert (
            mock_iter_diff_directory.call_args.kwargs["local_checksum"] is checksum_fn
        )

    @m.context("When a checksums file cannot be read")
    @m.it("Logs and exits non-zero")
    @patch("npg_irods.cli.diff_xenium.make_get_checksum", autospec=True)
    def test_main_use_checksums_file_error(
        self, mock_make_get_checksum: MagicMock, caplog
    ):
        mock_make_get_checksum.side_effect = ValueError("bad checksums file")

        with caplog.at_level("ERROR"):
            with pytest.raises(SystemExit) as exit_info:
                self._main(
                    ["--use-checksums-file", "checksums.md5", "root", "/irods/xenium"]
                )

        assert exit_info.value.code == 1
        assert "Failed to read checksums file" in caplog.text

    @m.context("When any difference rows are produced")
    @m.it("Exits non-zero after printing one aggregate row")
    @patch("npg_irods.cli.diff_xenium.iter_diff_directory", autospec=True)
    @patch("npg_irods.cli.diff_xenium.xenium_irods_partial_path", autospec=True)
    @patch("npg_irods.cli.diff_xenium.iter_output_directories", autospec=True)
    def test_main_difference_status(
        self,
        mock_iter_output_directories: MagicMock,
        mock_xenium_irods_partial_path: MagicMock,
        mock_iter_diff_directory: MagicMock,
        capsys,
    ):
        experiment = Path("experiment")
        mock_iter_output_directories.return_value = [experiment]
        mock_xenium_irods_partial_path.return_value = PurePath(
            "XETG00000", "0000000", "experiment"
        )

        def diff_rows():
            yield diff.DiffRow(diff.STATUS_SAME, "a.txt", diff.KIND_FILE)
            yield diff.DiffRow(diff.STATUS_LOCAL, "a", diff.KIND_DIRECTORY)
            raise AssertionError("Rows after the first non-same row should not be read")

        mock_iter_diff_directory.return_value = diff_rows()

        with pytest.raises(SystemExit) as exit_info:
            self._main(["root", "/irods/xenium"])

        assert exit_info.value.code == 1
        assert (
            capsys.readouterr().out
            == "> experiment /irods/xenium/XETG00000/0000000/experiment > a/\n"
        )

    @m.context("When one experiment cannot be mapped")
    @m.it("Logs and continues with later experiments")
    @patch("npg_irods.cli.diff_xenium.iter_diff_directory", autospec=True)
    @patch("npg_irods.cli.diff_xenium.xenium_irods_partial_path", autospec=True)
    @patch("npg_irods.cli.diff_xenium.iter_output_directories", autospec=True)
    def test_main_mapping_failure(
        self,
        mock_iter_output_directories: MagicMock,
        mock_xenium_irods_partial_path: MagicMock,
        mock_iter_diff_directory: MagicMock,
        caplog,
        capsys,
    ):
        bad = Path("bad")
        good = Path("good")
        mock_iter_output_directories.return_value = [bad, good]
        mock_xenium_irods_partial_path.side_effect = [
            ValueError("bad metadata"),
            PurePath("XETG00000", "0000000", "good"),
        ]
        mock_iter_diff_directory.return_value = []

        with caplog.at_level("ERROR"):
            with pytest.raises(SystemExit) as exit_info:
                self._main(["root", "/irods/xenium"])

        assert exit_info.value.code == 1
        mock_iter_diff_directory.assert_called_once_with(
            good,
            PurePath("/irods/xenium/XETG00000/0000000/good"),
            local_checksum=None,
            filter_fn=ANY,
        )
        assert "Failed to map Xenium result directory" in caplog.text
        assert (
            capsys.readouterr().out
            == "! bad - ! bad metadata\n= good /irods/xenium/XETG00000/0000000/good\n"
        )

    @m.context("When diffing an output directory raises an error")
    @m.it("Prints one aggregate error row")
    @patch("npg_irods.cli.diff_xenium.iter_diff_directory", autospec=True)
    @patch("npg_irods.cli.diff_xenium.xenium_irods_partial_path", autospec=True)
    @patch("npg_irods.cli.diff_xenium.iter_output_directories", autospec=True)
    def test_main_diff_failure(
        self,
        mock_iter_output_directories: MagicMock,
        mock_xenium_irods_partial_path: MagicMock,
        mock_iter_diff_directory: MagicMock,
        capsys,
    ):
        experiment = Path("experiment")
        mock_iter_output_directories.return_value = [experiment]
        mock_xenium_irods_partial_path.return_value = PurePath(
            "XETG00000", "0000000", "experiment"
        )
        mock_iter_diff_directory.side_effect = ValueError("bad diff")

        with pytest.raises(SystemExit) as exit_info:
            self._main(["root", "/irods/xenium"])

        assert exit_info.value.code == 1
        assert (
            capsys.readouterr().out
            == "! experiment /irods/xenium/XETG00000/0000000/experiment ! bad diff\n"
        )

    @staticmethod
    def _main(args: list[str]):
        with patch("sys.argv", ["diff-xenium"] + args):
            diff_xenium_script.main()

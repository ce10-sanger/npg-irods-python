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

from datetime import datetime, UTC
from os import PathLike

from pathlib import Path
from typing import AnyStr

from unittest.mock import patch, Mock
import pytest
from pytest import LogCaptureFixture, CaptureFixture
from pytest import mark as m

from npg_irods.cli import get_recently_created_directories


class FakeFilesystem:

    def __init__(self, root: Path, mock_get_ctime):
        self.root = root
        mock_get_ctime.side_effect = lambda path: self._get_ctime(path)
        self.ctimes = {}

    def create_directory(self, path: AnyStr | PathLike, ctime: datetime | None = None):
        directory_path = self.root / path

        # if not directory_path.exists():
        #     self.create_directory(directory_path.parent)
        #
        # directory_path.mkdir(parents=False, exist_ok=True)

        directory_path.mkdir(parents=False, exist_ok=False)

        if ctime:
            self.ctimes[directory_path] = ctime.timestamp()

    def create_file(self, path: AnyStr | PathLike, ctime: datetime | None = None):
        file_path = self.root / path

        # if not file_path.parent.exists():
        #     self.create_directory(file_path.parent)
        #
        # file_path.touch(exist_ok=False)

        file_path.touch(exist_ok=False)

        if ctime:
            self.ctimes[file_path] = ctime.timestamp()

    def _get_ctime(self, path):
        ctime = self.ctimes.get(path)
        if not ctime:
            raise Exception("Test error")
        return ctime


# TODO: Constants/uppercase?
first_monday_3am = datetime(2024, 1, 1, 3, 0, 0, tzinfo=UTC)
second_monday_3am = datetime(2024, 1, 8, 3, 0, 0, tzinfo=UTC)
second_sunday_3am = datetime(2024, 1, 14, 3, 0, 0, tzinfo=UTC)


class TestGetRecentlyCreatedDirectoriesScript:

    @patch("npg_irods.cli.get_recently_created_directories.get_ctime")
    @patch("npg_irods.cli.get_recently_created_directories.get_now_utc")
    def test_main_normal_case_defaults(
        self,
        mock_get_now_utc: Mock,
        mock_get_ctime: Mock,
        tmp_path: Path,
        caplog: LogCaptureFixture,
        capsys: CaptureFixture,
    ):
        # Arrange
        fs = FakeFilesystem(tmp_path, mock_get_ctime)

        mock_get_now_utc.return_value = second_sunday_3am

        # Directory case 1: Created recently
        recent = tmp_path / "recent"
        fs.create_directory(recent)
        fs.create_file(recent / "recent.txt", ctime=second_monday_3am)

        # Directory case 2: Not created recently
        not_recent = tmp_path / "not_recent"
        fs.create_directory(not_recent)
        fs.create_file(not_recent / "not_recent.txt", ctime=first_monday_3am)

        directories = [recent, not_recent]

        input_path = tmp_path / "input.txt"
        input_path.write_text("\n".join(str(x) for x in directories))

        # Act
        with caplog.at_level("DEBUG"):
            self._main(["--input", str(input_path)])

        # Assert
        stdout_lines = [line for line in capsys.readouterr().out.split("\n") if line]
        expected = [
            str(recent),
        ]
        assert stdout_lines == expected

        assert "Got recently created directories" in caplog.text
        assert "num_dirs=2" in caplog.text
        assert "num_filtered=2" in caplog.text
        assert "num_recent=1" in caplog.text
        assert "num_errors=0" in caplog.text

    @patch("get_recently_created_directories.system_calls.get_ctime")
    @patch("get_recently_created_directories.system_calls.get_now_utc")
    def test_get_recently_created_directories(
        self, mock_get_now_utc, mock_get_ctime, tmp_path: Path
    ):
        # Arrange

        fs = FakeFilesystem(tmp_path, mock_get_ctime)

        first_monday_3am = datetime(2024, 1, 1, 3, 0, 0)
        second_monday_3am = datetime(2024, 1, 8, 3, 0, 0)
        second_sunday_3am = datetime(2024, 1, 14, 3, 0, 0)

        mock_get_now_utc.return_value = second_sunday_3am

        ctimes = {}

        # Directory case 1: Created recently
        recent = tmp_path / "recent"
        # recent.mkdir()
        # (recent / "recent.txt").touch()
        # ctimes[(recent / "recent.txt")] = second_monday_3am.timestamp()
        fs.create_directory(recent)
        fs.create_file(recent / "recent.txt", ctime=second_monday_3am)

        # Directory case 2: Not created recently
        not_recent = tmp_path / "not_recent"
        not_recent.mkdir()
        (not_recent / "not_recent.txt").touch()
        ctimes[(recent / "recent.txt")] = first_monday_3am.timestamp()

        # Directory case 3: Creation currently happening

        # Directory case 4: Change after initial creation

        # Directory case 5: Empty
        empty = tmp_path / "empty"
        empty.mkdir()

        directories = [recent, not_recent, empty]

        input_path = tmp_path / "input.txt"
        input_path.write_text("\n".join(str(x) for x in directories))

        # Act
        self._main(["--debug", "--input", input_path])

        # Assert

    @staticmethod
    def _main(args: list[str]):
        with patch("sys.argv", ["get-recently-created-directories"] + args):
            get_recently_created_directories.main()

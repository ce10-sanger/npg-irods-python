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

from datetime import datetime
from os import PathLike

from pathlib import Path
from typing import AnyStr

from unittest.mock import patch

from npg_irods.cli import get_recently_changed_directories

class FakeFilesystem:

    def __init__(self, root: Path, mock_get_ctime):
        self.root = root
        mock_get_ctime.side_effect = mock_get_ctime
        self.times = {}

    def create_directory(self, path: AnyStr | PathLike, mtime: datetime | None = None, ctime: datetime | None = None):
        directory_path = self.root / path

        # if not directory_path.exists():
        #     self.create_directory(directory_path.parent)
        #
        # directory_path.mkdir(parents=False, exist_ok=True)

        directory_path.mkdir(parents=False, exist_ok=False)

        self.times[directory_path] = {
            "mtime": mtime,
            "ctime": ctime,
        } # TODO: Clean up

    def create_file(self, path: AnyStr | PathLike, mtime: datetime | None = None, ctime: datetime | None = None):
        file_path = self.root / path

        # if not file_path.parent.exists():
        #     self.create_directory(file_path.parent)
        #
        # file_path.touch(exist_ok=False)

        file_path.touch(exist_ok=False)

        self.times[file_path] = {
            "mtime": mtime,
            "ctime": ctime,
        } # TODO: Clean up

    def _get_ctime(self, path):
        ctime =  self.times[path]["ctime"]
        if not ctime:
            raise Exception("Test error")
        return ctime


class TestGetRecentlyChangedDirectoriesScript:

    @patch("get_recently_changed_directories.system_calls.get_ctime")
    @patch("get_recently_changed_directories.system_calls.get_now")
    def test_get_recently_changed_directories(
        self, mock_get_now, mock_get_ctime, tmp_path: Path
    ):
        # Arrange

        fs = FakeFilesystem(tmp_path, mock_get_ctime)

        first_monday_3am = datetime(2024, 1, 1, 3, 0, 0)
        second_monday_3am = datetime(2024, 1, 8, 3, 0, 0)
        second_sunday_3am = datetime(2024, 1, 14, 3, 0, 0)

        mock_get_now.return_value = second_sunday_3am

        ctimes = {}

        # Directory case 1: Changed recently
        recent = tmp_path / "recent"
        # recent.mkdir()
        # (recent / "recent.txt").touch()
        # ctimes[(recent / "recent.txt")] = second_monday_3am.timestamp()
        fs.create_directory(recent)
        fs.create_file(recent / "recent.txt", mtime=None, ctime=second_monday_3am)

        # Directory case 2: Not changed recently
        not_recent = tmp_path / "not_recent"
        not_recent.mkdir()
        (not_recent / "not_recent.txt").touch()
        ctimes[(recent / "recent.txt")] = first_monday_3am.timestamp()

        # Directory case 3: Changes currently happening

        # Directory case 4: Change after initial change

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
        with patch("sys.argv", ["get-recently-changed-directories"] + args):
            get_recently_changed_directories.main()

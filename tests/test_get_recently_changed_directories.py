from datetime import datetime

from pathlib import Path

from unittest.mock import patch

from npg_irods.cli import get_recently_changed_directories


class TestGetRecentlyChangedDirectoriesScript:

    @patch("get_recently_changed_directories.system_calls.get_ctime")
    @patch("get_recently_changed_directories.system_calls.get_now")
    def test_get_recently_changed_directories(
        self, mock_get_now, mock_get_ctime, tmp_path: Path
    ):
        # Arrange

        first_monday_3am = datetime(2024, 1, 1, 3, 0, 0)
        second_monday_3am = datetime(2024, 1, 8, 3, 0, 0)
        second_sunday_3am = datetime(2024, 1, 14, 3, 0, 0)

        mock_get_now.return_value = second_sunday_3am

        ctimes = {}

        # Directory case 1: Changed recently
        recent = tmp_path / "recent"
        recent.mkdir()
        (recent / "recent.txt").touch()
        ctimes[(recent / "recent.txt")] = second_monday_3am.timestamp()

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

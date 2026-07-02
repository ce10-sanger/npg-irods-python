import shutil

from npg_irods.checksum import calculate_file_checksum
from npg_irods.cli.diff import diff
from partisan.irods import Collection, DataObject

from helpers import consume


class TestDiff:

    def test_diff(self, tmp_path, tmp_irods_collection_path):
        # Arrange
        left = tmp_path / "collection"
        shutil.copytree("./tests/data/simple/collection", left)

        right = Collection(tmp_irods_collection_path / "right")
        consume(right.put(left, recurse=True))

        (left / "a.txt").write_text("modified")
        (left / "left.txt").write_text("left")
        (tmp_path / "right.txt").write_text("right")
        DataObject(right.path / "right.txt").put(tmp_path / "right.txt")

        # Act
        result = diff(left, right, calculate_file_checksum)
        breakpoint()

        # Assert
        assert len(result.same) == 4
        assert len(result.diff) == 1
        assert len(result.left_only) == 1
        assert len(result.right_only) == 1
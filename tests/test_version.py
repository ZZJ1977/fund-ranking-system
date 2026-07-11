import pathlib
import unittest

import fund_ranking_system


class VersionTest(unittest.TestCase):
    def test_package_version_matches_pyproject(self):
        root = pathlib.Path(__file__).resolve().parents[1]
        version_line = next(
            line
            for line in (root / "pyproject.toml").read_text(encoding="utf-8").splitlines()
            if line.startswith("version = ")
        )
        pyproject_version = version_line.split("=", 1)[1].strip().strip('"')

        self.assertEqual(pyproject_version, fund_ranking_system.__version__)


if __name__ == "__main__":
    unittest.main()

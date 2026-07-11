import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fund_ranking_system.research import build_research_enhancement


class ResearchTest(unittest.TestCase):
    def test_build_research_enhancement_outputs_files(self):
        scored = pd.DataFrame(
            {
                "fund_name": ["成长基金", "债券基金"],
                "annual_return": [0.1, 0.02],
                "annual_volatility": [0.2, 0.05],
                "max_drawdown": [-0.3, -0.05],
                "sharpe": [0.4, 0.2],
                "calmar": [0.3, 0.4],
                "rolling_positive_ratio": [0.6, 0.55],
            },
            index=["000001", "000002"],
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path, md_path = build_research_enhancement(scored, Path(tmpdir))

            self.assertTrue(csv_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIn("研究附录", md_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

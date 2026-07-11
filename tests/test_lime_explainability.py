import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fund_ranking_system.lime_explainability import (
    generate_lime_explanations,
    save_lime_outputs,
)
from fund_ranking_system.scoring import DEFAULT_PROFILES, SCORE_METRICS, score_funds


class LimeExplainabilityTest(unittest.TestCase):
    def test_generate_lime_explanations_outputs_local_weights(self):
        scored = score_funds(_sample_metrics(), DEFAULT_PROFILES["balanced"])

        explanations = generate_lime_explanations(
            scored,
            DEFAULT_PROFILES["balanced"],
            top_n=2,
            n_samples=80,
            random_state=7,
        )

        self.assertEqual(len(explanations), 2 * len(SCORE_METRICS))
        self.assertEqual(set(explanations["feature"]), set(SCORE_METRICS))
        self.assertIn("local_weight", explanations.columns)
        self.assertIn("surrogate_r2", explanations.columns)
        self.assertTrue(explanations["local_weight"].notna().all())
        self.assertTrue(explanations["surrogate_r2"].notna().all())

    def test_save_lime_outputs_writes_csv_and_markdown(self):
        scored = score_funds(_sample_metrics(), DEFAULT_PROFILES["balanced"])

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path, md_path = save_lime_outputs(
                scored,
                DEFAULT_PROFILES["balanced"],
                Path(tmpdir),
                top_n=2,
                n_samples=80,
            )

            self.assertTrue(csv_path.exists())
            self.assertTrue(md_path.exists())
            self.assertIn("LIME 局部解释", md_path.read_text(encoding="utf-8"))


def _sample_metrics() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fund_name": ["稳健成长A", "价值精选A", "平衡混合A", "债券优选A"],
            "annual_return": [0.05, 0.12, 0.08, 0.03],
            "annual_volatility": [0.10, 0.22, 0.15, 0.05],
            "max_drawdown": [-0.08, -0.30, -0.18, -0.04],
            "sharpe": [0.45, 0.55, 0.50, 0.30],
            "calmar": [0.62, 0.40, 0.44, 0.75],
            "rolling_positive_ratio": [0.62, 0.58, 0.55, 0.66],
        },
        index=["000001", "000002", "000003", "000004"],
    )


if __name__ == "__main__":
    unittest.main()

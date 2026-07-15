import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fund_ranking_system.adaptive_weights import (
    save_adaptive_weight_outputs,
    score_funds_with_adaptive_weights,
)
from fund_ranking_system.scoring import DEFAULT_PROFILES, SCORE_METRICS, score_funds


class AdaptiveWeightsTest(unittest.TestCase):
    def test_score_funds_with_adaptive_weights_varies_by_fund(self):
        metrics = _sample_metrics()

        scored, weights = score_funds_with_adaptive_weights(
            metrics,
            DEFAULT_PROFILES["balanced"],
        )

        self.assertIn("dynamic_score", scored.columns)
        self.assertIn("dynamic_rank", scored.columns)
        self.assertEqual(set(weights["feature"]), set(SCORE_METRICS))
        sums = weights.groupby("fund")["dynamic_weight"].sum().round(8)
        self.assertTrue((sums == 1.0).all())
        wide = weights.pivot(index="fund", columns="feature", values="dynamic_weight")
        self.assertGreater(wide.drop_duplicates().shape[0], 1)

    def test_save_adaptive_weight_outputs_writes_files(self):
        metrics = _sample_metrics()
        base_scored = score_funds(metrics, DEFAULT_PROFILES["balanced"])

        with tempfile.TemporaryDirectory() as tmpdir:
            ranking_path, weights_path, report_path, adaptive_scored, weight_table = save_adaptive_weight_outputs(
                metrics,
                DEFAULT_PROFILES["balanced"],
                Path(tmpdir),
                profile="balanced",
                top_n=3,
                base_scored=base_scored,
            )

            self.assertTrue(ranking_path.exists())
            self.assertTrue(weights_path.exists())
            self.assertTrue(report_path.exists())
            self.assertFalse(adaptive_scored.empty)
            self.assertFalse(weight_table.empty)
            self.assertIn("基金级动态权重报告", report_path.read_text(encoding="utf-8"))


def _sample_metrics() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fund_name": ["收益强", "稳健型", "高波动"],
            "fund_type": ["混合型", "债券型", "股票型"],
            "observations": [300, 300, 300],
            "annual_return": [0.18, 0.08, 0.22],
            "annual_volatility": [0.16, 0.06, 0.34],
            "max_drawdown": [-0.22, -0.05, -0.48],
            "sharpe": [0.9, 1.0, 0.45],
            "calmar": [0.82, 1.6, 0.46],
            "rolling_positive_ratio": [0.62, 0.76, 0.54],
        },
        index=pd.Index(["A", "B", "C"], name="fund"),
    )


if __name__ == "__main__":
    unittest.main()

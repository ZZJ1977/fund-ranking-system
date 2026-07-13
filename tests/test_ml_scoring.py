import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fund_ranking_system.ml_scoring import (
    build_ml_training_samples,
    fit_ml_factor_weights,
    save_ml_outputs,
)
from fund_ranking_system.metrics import calculate_metrics
from fund_ranking_system.scoring import DEFAULT_PROFILES, SCORE_METRICS


class MLScoringTest(unittest.TestCase):
    def test_build_training_samples_and_fit_weights(self):
        nav = _sample_nav()
        samples = build_ml_training_samples(
            nav,
            lookback_days=80,
            holding_days=20,
            step_days=20,
        )

        self.assertFalse(samples.empty)
        self.assertIn("future_return_rank", samples.columns)
        self.assertTrue(set(SCORE_METRICS).issubset(samples.columns))

        result = fit_ml_factor_weights(samples, DEFAULT_PROFILES["balanced"], min_samples=6)

        self.assertAlmostEqual(sum(result.weights.values()), 1.0)
        self.assertEqual(set(result.weights), set(SCORE_METRICS))
        self.assertIn("final_weight", result.coefficient_table.columns)
        self.assertIn(result.diagnostics["status"], {"trained", "fallback_no_positive_signal"})

    def test_save_ml_outputs_writes_report_and_csvs(self):
        nav = _sample_nav()
        metrics = calculate_metrics(nav)

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = save_ml_outputs(
                nav,
                metrics,
                DEFAULT_PROFILES["balanced"],
                Path(tmpdir),
                profile="balanced",
                top_n=3,
                lookback_days=80,
                holding_days=20,
                step_days=20,
            )

            self.assertTrue(all(path.exists() for path in paths))
            self.assertIn("机器学习辅助评分报告", paths[3].read_text(encoding="utf-8"))
            self.assertIn("原始排名 vs ML 排名对比", paths[-1].read_text(encoding="utf-8"))


def _sample_nav() -> pd.DataFrame:
    dates = pd.date_range("2022-01-01", periods=220)
    returns = pd.DataFrame(
        {
            "A": np.full(len(dates), 1.0009),
            "B": np.full(len(dates), 1.0004),
            "C": np.full(len(dates), 1.0001),
            "D": np.full(len(dates), 0.9999),
        },
        index=dates,
    )
    returns.iloc[::17, 1] = 0.997
    returns.iloc[::23, 2] = 1.004
    return returns.cumprod()


if __name__ == "__main__":
    unittest.main()

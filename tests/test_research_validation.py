import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fund_ranking_system.diagnostics import factor_correlation
from fund_ranking_system.explainability import calculate_factor_contributions
from fund_ranking_system.fund_universe import build_fund_universe, share_class_group, strategy_name_group
from fund_ranking_system.sensitivity import monte_carlo_weight_perturbation
from fund_ranking_system.benchmark import build_benchmark_comparison, build_peer_comparison
from fund_ranking_system.scoring import score_funds
from fund_ranking_system.validation import (
    adaptive_walk_forward_backtest,
    save_adaptive_walk_forward_outputs,
    save_walk_forward_outputs,
    walk_forward_backtest,
)


class ResearchValidationTest(unittest.TestCase):
    def test_universe_filters_excluded_types_and_share_classes(self):
        dates = pd.date_range("2021-01-01", periods=760)
        nav = pd.DataFrame(
            {
                "A": np.linspace(1.0, 1.5, len(dates)),
                "C": np.linspace(1.0, 1.4, len(dates)),
                "B": np.linspace(1.0, 1.1, len(dates)),
            },
            index=dates,
        )
        metrics = pd.DataFrame(
            {
                "fund_name": ["成长基金A", "成长基金C", "债券基金A"],
                "fund_type": ["混合型", "混合型", "债券型"],
                "observations": [759, 759, 759],
            },
            index=["A", "C", "B"],
        )

        filtered, audit = build_fund_universe(metrics, nav)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(share_class_group("成长基金C"), "成长基金")
        self.assertEqual(strategy_name_group("成长基金混合A"), "成长基金")
        self.assertIn("quality_score", audit.columns)
        self.assertIn("quality_flags", audit.columns)
        self.assertFalse(audit.loc["B", "universe_eligible"])

    def test_factor_contributions_sum_to_score(self):
        metrics = _sample_metrics()
        weights = {"annual_return": 0.5, "sharpe": 0.5}

        contributions = calculate_factor_contributions(metrics, weights)
        summed = contributions.groupby("fund")["contribution"].sum()

        self.assertEqual(set(summed.index), {"A", "B", "C"})
        self.assertGreater(summed.loc["C"], summed.loc["A"])

    def test_monte_carlo_weight_perturbation_outputs_rank_stats(self):
        robustness = monte_carlo_weight_perturbation(
            _sample_metrics(),
            {"annual_return": 0.5, "sharpe": 0.5},
            n_simulations=20,
            top_k=2,
        )

        self.assertIn("top_k_frequency", robustness.columns)
        self.assertIn("rank_iqr", robustness.columns)

    def test_walk_forward_backtest_outputs_summary(self):
        dates = pd.date_range("2020-01-01", periods=420)
        nav = pd.DataFrame(
            {
                "A": np.cumprod(np.full(len(dates), 1.0008)),
                "B": np.cumprod(np.full(len(dates), 1.0002)),
                "C": np.cumprod(np.full(len(dates), 0.9999)),
            },
            index=dates,
        )
        weights = {
            "annual_return": 0.5,
            "sharpe": 0.2,
            "max_drawdown": 0.1,
            "calmar": 0.1,
            "annual_volatility": 0.05,
            "rolling_positive_ratio": 0.05,
        }

        summary, periods = walk_forward_backtest(
            nav,
            weights,
            lookback_days=120,
            holding_days=30,
            step_days=30,
            top_n=1,
            min_funds=2,
        )

        self.assertFalse(summary.empty)
        self.assertFalse(periods.empty)
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = save_walk_forward_outputs(
                nav,
                weights,
                Path(tmpdir),
                lookback_days=120,
                holding_days=30,
                step_days=30,
                top_n=1,
            )
            self.assertTrue(all(path.exists() for path in paths))

    def test_adaptive_walk_forward_backtest_outputs_summary(self):
        dates = pd.date_range("2020-01-01", periods=420)
        nav = pd.DataFrame(
            {
                "A": np.cumprod(np.full(len(dates), 1.0008)),
                "B": np.cumprod(np.full(len(dates), 1.0002)),
                "C": np.cumprod(np.full(len(dates), 0.9999)),
            },
            index=dates,
        )
        weights = {
            "annual_return": 0.5,
            "sharpe": 0.2,
            "max_drawdown": 0.1,
            "calmar": 0.1,
            "annual_volatility": 0.05,
            "rolling_positive_ratio": 0.05,
        }

        summary, periods = adaptive_walk_forward_backtest(
            nav,
            weights,
            lookback_days=120,
            holding_days=30,
            step_days=30,
            top_n=1,
            min_funds=2,
        )

        self.assertIn("Adaptive TopN", summary.index)
        self.assertFalse(periods.empty)
        with tempfile.TemporaryDirectory() as tmpdir:
            paths = save_adaptive_walk_forward_outputs(
                nav,
                weights,
                Path(tmpdir),
                lookback_days=120,
                holding_days=30,
                step_days=30,
                top_n=1,
            )
            self.assertTrue(all(path.exists() for path in paths))

    def test_benchmark_and_peer_comparison(self):
        dates = pd.date_range("2020-01-01", periods=180)
        nav = pd.DataFrame(
            {
                "A": np.cumprod(np.full(len(dates), 1.0008)),
                "B": np.cumprod(np.full(len(dates), 1.0002)),
                "C": np.cumprod(np.full(len(dates), 0.9999)),
            },
            index=dates,
        )
        metrics = _sample_metrics()
        metrics["fund_type"] = ["混合型", "混合型", "债券型"]
        scored = score_funds(metrics, {"annual_return": 0.5, "sharpe": 0.5})
        scored["type_rank"] = [2, 1, 1]

        external = pd.DataFrame({"沪深300": np.cumprod(np.full(len(dates), 1.0001))}, index=dates)
        benchmark = build_benchmark_comparison(nav, scored, None, None, top_n=1, external_benchmark=external)
        peers = build_peer_comparison(scored, None, None)

        self.assertIn("基金池等权基准", set(benchmark["portfolio"]))
        self.assertIn("外部基准：沪深300", set(benchmark["portfolio"]))
        self.assertIn("type_percentile", peers.columns)

    def test_factor_correlation(self):
        corr = factor_correlation(_sample_metrics())

        self.assertIn("annual_return", corr.columns)
        self.assertEqual(corr.loc["annual_return", "annual_return"], 1.0)


def _sample_metrics() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "fund_name": ["A", "B", "C"],
            "annual_return": [0.05, 0.10, 0.20],
            "annual_volatility": [0.12, 0.15, 0.18],
            "max_drawdown": [-0.10, -0.20, -0.25],
            "sharpe": [0.2, 0.6, 1.0],
            "calmar": [0.5, 0.5, 0.8],
            "rolling_positive_ratio": [0.45, 0.55, 0.65],
            "observations": [300, 300, 300],
        },
        index=["A", "B", "C"],
    )


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from fund_ranking_system.data_quality import build_data_quality_diagnostics, save_data_quality_outputs
from fund_ranking_system.strategy_benchmark import build_strategy_benchmark, save_strategy_benchmark_outputs


class ProductReadinessTest(unittest.TestCase):
    def test_data_quality_outputs_rank_low_quality_first(self):
        dates = pd.date_range("2024-01-01", periods=10)
        nav = pd.DataFrame(
            {
                "000001": [1, 1.01, 1.02, 1.03, 1.04, 1.05, 1.06, 1.07, 1.08, 1.09],
                "000002": [1, None, None, 1.5, None, None, 1.52, None, None, 1.53],
            },
            index=dates,
        )
        metrics = pd.DataFrame(
            [
                {"fund": "000001", "fund_name": "A", "fund_type": "混合型"},
                {"fund": "000002", "fund_name": "B", "fund_type": "混合型"},
            ]
        ).set_index("fund")

        diagnostics = build_data_quality_diagnostics(nav, metrics)

        self.assertEqual(diagnostics.iloc[0]["fund"], "000002")
        self.assertIn("质量分", save_data_quality_outputs(nav, metrics, pd.DataFrame(), Path(tempfile.mkdtemp()))[1].read_text(encoding="utf-8"))

    def test_strategy_benchmark_compares_against_all_funds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reports_dir = Path(tmpdir)
            pd.DataFrame(
                [
                    {"portfolio": "Top 10", "annual_return": 0.1, "annual_volatility": 0.12, "max_drawdown": -0.1, "sharpe": 0.8, "win_rate": 0.55},
                    {"portfolio": "All Funds", "annual_return": 0.05, "annual_volatility": 0.1, "max_drawdown": -0.12, "sharpe": 0.4, "win_rate": 0.5},
                ]
            ).to_csv(reports_dir / "walk_forward_results.csv", index=False)

            benchmark = build_strategy_benchmark(reports_dir)
            _, report_path = save_strategy_benchmark_outputs(reports_dir)

            self.assertIn("excess_annual_return", benchmark.columns)
            self.assertIn("策略回测基准对比", report_path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()

import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from fund_ranking_system.portfolio import (
    PortfolioConstraints,
    build_portfolio_recommendations,
    build_portfolio_risk_controls,
    build_portfolios,
    optimize_constrained_portfolio,
    portfolio_summary,
    save_portfolio_outputs,
)
from fund_ranking_system.portfolio_backtest import rebalance_backtest, save_portfolio_backtest_outputs


class PortfolioTest(unittest.TestCase):
    def test_build_portfolios_and_summary(self):
        nav = _sample_nav()
        base, adaptive, ml = _sample_scored()

        weights = build_portfolios(nav, base, adaptive, ml, top_n=2)
        summary = portfolio_summary(nav, weights)

        self.assertIn("风险平价组合", set(weights["portfolio"]))
        self.assertIn("动态权重TopN等权", set(weights["portfolio"]))
        self.assertIn("约束优化组合", set(weights["portfolio"]))
        self.assertTrue((weights.groupby("portfolio")["weight"].sum().round(6) == 1.0).all())
        self.assertIn("annual_return", summary.columns)
        self.assertFalse(summary.empty)

    def test_constrained_optimizer_respects_basic_constraints(self):
        nav = _sample_nav()
        _, adaptive, _ = _sample_scored()
        constraints = PortfolioConstraints(
            objective="defensive",
            min_funds=2,
            max_funds=3,
            max_position_weight=0.55,
            max_type_weight=0.7,
            max_pair_correlation=0.95,
            max_drawdown_floor=-0.35,
            min_sharpe=0.0,
        )

        optimized = optimize_constrained_portfolio(nav, adaptive, constraints)

        self.assertEqual(set(optimized["portfolio"]), {"约束优化组合"})
        self.assertLessEqual(optimized["weight"].max(), 0.55 + 1e-9)
        self.assertNotIn("C", set(optimized["fund"]))

        recommendations = build_portfolio_recommendations(nav, adaptive, optimized, constraints)
        risk_controls = build_portfolio_risk_controls(nav, optimized, constraints)
        self.assertIn("selection_reason", recommendations.columns)
        self.assertIn("type_exposure", set(risk_controls["control_type"]))
        self.assertIn("correlation", set(risk_controls["control_type"]))

    def test_save_portfolio_outputs_creates_files(self):
        nav = _sample_nav()
        base, adaptive, ml = _sample_scored()

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = save_portfolio_outputs(nav, base, adaptive, ml, Path(tmpdir), profile="balanced", top_n=2)

            self.assertTrue(all(path.exists() for path in paths))
            self.assertIn("组合构建报告", paths[2].read_text(encoding="utf-8"))
            self.assertIn("组合目标", paths[3].read_text(encoding="utf-8"))
            self.assertIn("组合建议说明书", paths[5].read_text(encoding="utf-8"))

    def test_rebalance_backtest_and_outputs(self):
        nav = _sample_nav(periods=420)
        weights = {
            "annual_return": 0.4,
            "sharpe": 0.25,
            "max_drawdown": 0.15,
            "calmar": 0.1,
            "annual_volatility": 0.05,
            "rolling_positive_ratio": 0.05,
        }

        summary, periods, returns = rebalance_backtest(
            nav,
            weights,
            lookback_days=120,
            holding_days=30,
            step_days=30,
            top_n=2,
            min_funds=3,
        )

        self.assertIn("Adaptive Rebalance", summary.index)
        self.assertFalse(periods.empty)
        self.assertFalse(returns.empty)

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = save_portfolio_backtest_outputs(
                nav,
                weights,
                Path(tmpdir),
                constraints=PortfolioConstraints(rebalance_days=30, transaction_cost_bps=5),
                lookback_days=120,
                top_n=2,
            )
            self.assertTrue(all(path.exists() for path in paths))


def _sample_nav(periods: int = 260) -> pd.DataFrame:
    dates = pd.date_range("2021-01-01", periods=periods)
    return pd.DataFrame(
        {
            "A": np.cumprod(np.full(periods, 1.0008)),
            "B": np.cumprod(np.full(periods, 1.0004)),
            "C": np.cumprod(np.full(periods, 0.9999)),
            "D": np.cumprod(np.full(periods, 1.0002)),
        },
        index=dates,
    )


def _sample_scored() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    base = pd.DataFrame(
        {
            "fund_name": ["Alpha", "Beta", "Gamma", "Delta"],
            "fund_type": ["混合型", "股票型", "混合型", "债券型"],
            "rank": [1, 2, 3, 4],
            "composite_score": [90, 80, 70, 60],
            "max_drawdown": [-0.1, -0.2, -0.5, -0.3],
            "risk_level": ["低风险", "中风险", "高风险", "中风险"],
            "decision_label": ["重点观察", "可观察", "暂不优先", "可观察"],
        },
        index=["A", "B", "C", "D"],
    )
    adaptive = base.copy()
    adaptive["dynamic_rank"] = [2, 1, 3, 4]
    ml = base.copy()
    ml["ml_rank"] = [1, 3, 2, 4]
    return base, adaptive, ml


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import run_pipeline
from .portfolio import PORTFOLIO_OBJECTIVES, normalize_portfolio_constraints
from .scoring import DEFAULT_PROFILES


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rank mutual funds with a risk-return multi-factor model."
    )
    parser.add_argument("--input", type=Path, help="CSV file containing fund NAV data.")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Generate demo NAV data and run the full pipeline.",
    )
    parser.add_argument(
        "--profile",
        choices=sorted(DEFAULT_PROFILES),
        default="balanced",
        help="Investor profile used for the main report.",
    )
    parser.add_argument("--top-n", type=int, default=10, help="Number of top funds.")
    parser.add_argument(
        "--min-observations",
        type=int,
        default=252,
        help="Minimum daily return observations for sufficient data quality.",
    )
    parser.add_argument(
        "--max-drawdown-limit",
        type=float,
        default=-0.6,
        help="Drawdown threshold for high drawdown warning, for example -0.6.",
    )
    parser.add_argument(
        "--risk-free-rate",
        type=float,
        default=0.02,
        help="Annual risk-free rate used in Sharpe ratio.",
    )
    parser.add_argument("--reports-dir", type=Path, default=Path("reports"))
    parser.add_argument("--processed-dir", type=Path, default=Path("data/processed"))
    parser.add_argument(
        "--benchmark",
        type=Path,
        help="Optional benchmark NAV CSV. Columns after Date are treated as external benchmark series.",
    )
    parser.add_argument(
        "--portfolio-objective",
        choices=sorted(PORTFOLIO_OBJECTIVES),
        default="balanced",
        help="Objective used by constrained portfolio optimization.",
    )
    parser.add_argument("--portfolio-min-funds", type=int, default=3, help="Minimum fund count for constrained portfolio.")
    parser.add_argument("--portfolio-max-funds", type=int, default=8, help="Maximum fund count for constrained portfolio.")
    parser.add_argument("--max-position-weight", type=float, default=0.35, help="Maximum single-fund portfolio weight.")
    parser.add_argument("--max-type-weight", type=float, default=0.65, help="Maximum total weight for one inferred fund type.")
    parser.add_argument("--max-pair-correlation", type=float, default=0.9, help="Maximum allowed pairwise return correlation between selected funds.")
    parser.add_argument("--portfolio-max-drawdown", type=float, default=-0.45, help="Per-fund max drawdown floor, for example -0.45.")
    parser.add_argument("--portfolio-min-sharpe", type=float, default=0.0, help="Minimum Sharpe for constrained candidates.")
    parser.add_argument("--rebalance-days", type=int, default=63, help="Holding/rebalance interval used by portfolio backtest.")
    parser.add_argument("--max-turnover", type=float, default=0.6, help="Maximum turnover per constrained rebalance window.")
    parser.add_argument("--transaction-cost-bps", type=float, default=0.0, help="Transaction cost assumption in basis points.")
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data/raw/fund_metadata.csv"),
        help="CSV file containing fund_code and fund_name columns.",
    )
    parser.add_argument(
        "--demo-output",
        type=Path,
        default=Path("data/raw/demo_fund_nav.csv"),
        help="Where to save generated demo NAV data.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    portfolio_constraints = normalize_portfolio_constraints(
        objective=args.portfolio_objective,
        min_funds=args.portfolio_min_funds,
        max_funds=args.portfolio_max_funds,
        max_position_weight=args.max_position_weight,
        max_type_weight=args.max_type_weight,
        max_pair_correlation=args.max_pair_correlation,
        max_drawdown_floor=args.portfolio_max_drawdown,
        min_sharpe=args.portfolio_min_sharpe,
        rebalance_days=args.rebalance_days,
        max_turnover=args.max_turnover,
        transaction_cost_bps=args.transaction_cost_bps,
    )
    result = run_pipeline(
        input_path=args.input,
        metadata_path=args.metadata,
        benchmark_path=args.benchmark,
        profile=args.profile,
        top_n=args.top_n,
        risk_free_rate=args.risk_free_rate,
        reports_dir=args.reports_dir,
        processed_dir=args.processed_dir,
        demo=args.demo or not args.input,
        demo_output=args.demo_output,
        min_observations=args.min_observations,
        max_drawdown_limit=args.max_drawdown_limit,
        portfolio_constraints=portfolio_constraints,
    )

    print("Fund ranking pipeline finished.")
    print(f"Data source: {result.data_source}")
    print(f"Metrics: {result.metrics_path}")
    print(f"All profiles: {result.all_profiles_path}")
    print(f"Weight sensitivity: {result.sensitivity_csv_path}")
    print(f"Sensitivity report: {result.sensitivity_report_path}")
    print(f"Main report: {result.report_path}")
    print(f"Data quality diagnostics: {result.data_quality_report_path}")
    print(f"Walk-forward report: {result.backtest_report_path}")
    print(f"Adaptive walk-forward report: {result.adaptive_backtest_report_path}")
    print(f"Strategy benchmark report: {result.strategy_benchmark_report_path}")
    print(f"Benchmark comparison report: {result.benchmark_report_path}")
    print(f"Portfolio construction report: {result.portfolio_report_path}")
    print(f"Portfolio recommendation report: {result.portfolio_recommendation_path}")
    print(f"Portfolio constraints: {result.portfolio_constraints_path}")
    print(f"Portfolio weight figure: {result.portfolio_figure_path}")
    print(f"Portfolio rebalance report: {result.portfolio_backtest_report_path}")
    print(f"Factor contribution report: {result.factor_contribution_report_path}")
    print(f"LIME local explanation report: {result.lime_report_path}")
    print(f"Adaptive weight report: {result.adaptive_report_path}")
    print(f"Adaptive weight table: {result.adaptive_weights_path}")
    print(f"ML-assisted scoring report: {result.ml_report_path}")
    print(f"ML evaluation report: {result.ml_evaluation_report_path}")
    print(f"Dynamic weight figure: {result.dynamic_weight_figure_path}")
    print(f"LIME local weight figure: {result.lime_weight_figure_path}")
    print(f"Rank comparison figure: {result.rank_comparison_figure_path}")
    print(f"Word report bundle: {result.word_report_path}")
    print(f"PDF report bundle: {result.pdf_report_path}")
    print(f"Excel data workbook: {result.excel_workbook_path}")
    print(f"Research appendix: {result.research_report_path}")


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
from pathlib import Path

from .pipeline import run_pipeline
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
    result = run_pipeline(
        input_path=args.input,
        metadata_path=args.metadata,
        profile=args.profile,
        top_n=args.top_n,
        risk_free_rate=args.risk_free_rate,
        reports_dir=args.reports_dir,
        processed_dir=args.processed_dir,
        demo=args.demo or not args.input,
        demo_output=args.demo_output,
        min_observations=args.min_observations,
        max_drawdown_limit=args.max_drawdown_limit,
    )

    print("Fund ranking pipeline finished.")
    print(f"Data source: {result.data_source}")
    print(f"Metrics: {result.metrics_path}")
    print(f"All profiles: {result.all_profiles_path}")
    print(f"Weight sensitivity: {result.sensitivity_csv_path}")
    print(f"Sensitivity report: {result.sensitivity_report_path}")
    print(f"Main report: {result.report_path}")
    print(f"Walk-forward report: {result.backtest_report_path}")
    print(f"Factor contribution report: {result.factor_contribution_report_path}")
    print(f"LIME local explanation report: {result.lime_report_path}")
    print(f"Research appendix: {result.research_report_path}")


if __name__ == "__main__":
    main()

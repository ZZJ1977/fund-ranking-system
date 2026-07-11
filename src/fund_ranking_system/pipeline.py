from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .advisory import add_decision_labels
from .data import generate_demo_nav, load_nav_csv, save_nav_csv
from .diagnostics import save_factor_diagnostics
from .explainability import save_explainability_outputs
from .fund_universe import build_fund_universe, save_universe_outputs
from .metadata import attach_fund_metadata, load_fund_metadata
from .metrics import calculate_metrics
from .report import build_report, save_report
from .research import build_research_enhancement
from .scoring import DEFAULT_PROFILES, score_all_profiles, score_funds
from .sensitivity import (
    build_sensitivity_table,
    monte_carlo_weight_perturbation,
    save_monte_carlo_outputs,
    save_sensitivity_outputs,
)
from .validation import save_walk_forward_outputs
from .visualization import plot_drawdown, plot_nav, plot_risk_return, plot_top_scores


@dataclass(frozen=True)
class PipelineResult:
    data_source: Path
    metrics_path: Path
    all_profiles_path: Path
    sensitivity_csv_path: Path
    sensitivity_report_path: Path
    report_path: Path
    research_csv_path: Path
    research_report_path: Path
    universe_csv_path: Path
    universe_report_path: Path
    factor_correlation_path: Path
    factor_diagnostics_path: Path
    factor_contribution_path: Path
    ranking_explanation_path: Path
    factor_contribution_report_path: Path
    robustness_csv_path: Path
    robustness_report_path: Path
    backtest_summary_path: Path
    backtest_periods_path: Path
    backtest_report_path: Path
    backtest_figure_path: Path
    ranking_paths: dict[str, Path]


def run_pipeline(
    input_path: Path | None = None,
    metadata_path: Path = Path("data/raw/fund_metadata.csv"),
    profile: str = "balanced",
    top_n: int = 10,
    risk_free_rate: float = 0.02,
    reports_dir: Path = Path("reports"),
    processed_dir: Path = Path("data/processed"),
    demo: bool = False,
    demo_output: Path = Path("data/raw/demo_fund_nav.csv"),
    min_observations: int = 252,
    max_drawdown_limit: float = -0.6,
) -> PipelineResult:
    reports_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    if demo or input_path is None:
        nav = generate_demo_nav()
        data_source = save_nav_csv(nav, demo_output)
    else:
        nav = load_nav_csv(input_path)
        data_source = input_path

    metrics = calculate_metrics(nav, risk_free_rate=risk_free_rate)
    metadata = load_fund_metadata(metadata_path)
    metrics = attach_fund_metadata(metrics, metadata)
    universe_metrics, universe_audit = build_fund_universe(metrics, nav)
    if len(universe_metrics) >= 3:
        metrics_for_scoring = universe_metrics
    else:
        metrics_for_scoring = metrics
    universe_csv_path, universe_report_path = save_universe_outputs(
        universe_audit,
        reports_dir / "fund_universe.csv",
        reports_dir / "fund_universe.md",
    )
    metrics_path = processed_dir / "fund_metrics.csv"
    metrics_for_scoring.to_csv(metrics_path)

    factor_correlation_path, factor_diagnostics_path = save_factor_diagnostics(
        metrics_for_scoring,
        reports_dir / "factor_correlation.csv",
        reports_dir / "factor_diagnostics.md",
    )

    all_profiles = score_all_profiles(metrics_for_scoring)
    all_profiles_path = processed_dir / "ranking_all_profiles.csv"
    all_profiles.to_csv(all_profiles_path)

    sensitivity = build_sensitivity_table(all_profiles)
    sensitivity_csv_path, sensitivity_report_path = save_sensitivity_outputs(
        sensitivity,
        reports_dir / "weight_sensitivity.csv",
        reports_dir / "weight_sensitivity.md",
        top_n=top_n,
    )

    selected_scored = None
    ranking_paths: dict[str, Path] = {}
    for profile_name, weights in DEFAULT_PROFILES.items():
        scored = score_funds(metrics_for_scoring, weights)
        if "fund_type" in scored.columns:
            scored["type_rank"] = scored.groupby("fund_type")["composite_score"].rank(
                ascending=False,
                method="min",
            ).astype(int)
        scored = add_decision_labels(
            scored,
            min_observations=min_observations,
            max_drawdown_limit=max_drawdown_limit,
        )
        ranking_path = reports_dir / f"ranking_{profile_name}.csv"
        scored.to_csv(ranking_path)
        ranking_paths[profile_name] = ranking_path

        if profile_name == profile:
            selected_scored = scored

    if selected_scored is None:
        raise RuntimeError(f"Profile not scored: {profile}")

    top_funds = selected_scored.head(top_n).index.tolist()
    top_for_lines = top_funds[: min(5, len(top_funds))]
    figure_paths = [
        plot_top_scores(
            selected_scored,
            reports_dir / f"top_scores_{profile}.png",
            top_n=top_n,
        ),
        plot_risk_return(
            selected_scored,
            reports_dir / f"risk_return_{profile}.png",
            top_n=top_n,
        ),
        plot_nav(nav, top_for_lines, reports_dir / f"nav_top_{profile}.png"),
        plot_drawdown(nav, top_for_lines, reports_dir / f"drawdown_top_{profile}.png"),
    ]

    report = build_report(
        selected_scored,
        DEFAULT_PROFILES[profile],
        profile=profile,
        top_n=top_n,
        figures=[str(path) for path in figure_paths],
    )
    report_path = save_report(report, reports_dir / "fund_analysis_report.md")
    research_csv_path, research_report_path = build_research_enhancement(selected_scored, reports_dir)
    (
        factor_contribution_path,
        ranking_explanation_path,
        factor_contribution_report_path,
    ) = save_explainability_outputs(
        selected_scored,
        DEFAULT_PROFILES[profile],
        reports_dir,
        top_n=top_n,
    )
    robustness = monte_carlo_weight_perturbation(
        metrics_for_scoring,
        DEFAULT_PROFILES[profile],
        top_k=min(top_n, len(metrics_for_scoring)),
        n_simulations=300,
    )
    robustness_csv_path, robustness_report_path = save_monte_carlo_outputs(
        robustness,
        reports_dir / "weight_robustness.csv",
        reports_dir / "weight_robustness.md",
        top_n=top_n,
        top_k=min(top_n, len(metrics_for_scoring)),
    )
    (
        backtest_summary_path,
        backtest_periods_path,
        backtest_report_path,
        backtest_figure_path,
    ) = save_walk_forward_outputs(
        nav[metrics_for_scoring.index.intersection(nav.columns)],
        DEFAULT_PROFILES[profile],
        reports_dir,
        top_n=top_n,
    )

    return PipelineResult(
        data_source=Path(data_source),
        metrics_path=metrics_path,
        all_profiles_path=all_profiles_path,
        sensitivity_csv_path=sensitivity_csv_path,
        sensitivity_report_path=sensitivity_report_path,
        report_path=report_path,
        research_csv_path=research_csv_path,
        research_report_path=research_report_path,
        universe_csv_path=universe_csv_path,
        universe_report_path=universe_report_path,
        factor_correlation_path=factor_correlation_path,
        factor_diagnostics_path=factor_diagnostics_path,
        factor_contribution_path=factor_contribution_path,
        ranking_explanation_path=ranking_explanation_path,
        factor_contribution_report_path=factor_contribution_report_path,
        robustness_csv_path=robustness_csv_path,
        robustness_report_path=robustness_report_path,
        backtest_summary_path=backtest_summary_path,
        backtest_periods_path=backtest_periods_path,
        backtest_report_path=backtest_report_path,
        backtest_figure_path=backtest_figure_path,
        ranking_paths=ranking_paths,
    )

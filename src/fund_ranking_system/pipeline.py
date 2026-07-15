from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .adaptive_weights import save_adaptive_weight_outputs
from .advisory import add_decision_labels
from .benchmark import save_benchmark_outputs
from .data import generate_demo_nav, load_nav_csv, save_nav_csv
from .data_quality import save_data_quality_outputs
from .diagnostics import save_factor_diagnostics
from .explainability import save_explainability_outputs
from .explanation_visuals import save_explanation_visuals
from .friendly_exports import save_friendly_exports
from .fund_universe import build_fund_universe, save_universe_outputs
from .lime_explainability import save_lime_outputs
from .metadata import attach_fund_metadata, load_fund_metadata
from .metrics import calculate_metrics
from .ml_scoring import save_ml_outputs
from .portfolio import PortfolioConstraints, normalize_portfolio_constraints, save_portfolio_outputs
from .portfolio_backtest import save_portfolio_backtest_outputs
from .report import build_report, save_report
from .research import build_research_enhancement
from .scoring import DEFAULT_PROFILES, SCORE_METRICS, score_all_profiles, score_funds
from .strategy_benchmark import save_strategy_benchmark_outputs
from .sensitivity import (
    build_sensitivity_table,
    monte_carlo_weight_perturbation,
    save_monte_carlo_outputs,
    save_sensitivity_outputs,
)
from .validation import save_adaptive_walk_forward_outputs, save_walk_forward_outputs
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
    data_quality_csv_path: Path
    data_quality_report_path: Path
    factor_correlation_path: Path
    factor_diagnostics_path: Path
    factor_contribution_path: Path
    ranking_explanation_path: Path
    factor_contribution_report_path: Path
    lime_explanation_path: Path
    lime_report_path: Path
    ml_training_samples_path: Path
    ml_weights_path: Path
    ml_ranking_path: Path
    ml_report_path: Path
    ml_comparison_path: Path
    ml_comparison_report_path: Path
    ml_evaluation_path: Path
    ml_evaluation_report_path: Path
    adaptive_ranking_path: Path
    adaptive_weights_path: Path
    adaptive_report_path: Path
    benchmark_comparison_path: Path
    peer_comparison_path: Path
    benchmark_report_path: Path
    portfolio_weights_path: Path
    portfolio_summary_path: Path
    portfolio_report_path: Path
    portfolio_constraints_path: Path
    portfolio_figure_path: Path
    portfolio_recommendation_path: Path
    portfolio_recommendation_csv_path: Path
    portfolio_risk_controls_path: Path
    portfolio_backtest_summary_path: Path
    portfolio_backtest_periods_path: Path
    portfolio_backtest_report_path: Path
    portfolio_backtest_figure_path: Path
    strategy_benchmark_path: Path
    strategy_benchmark_report_path: Path
    dynamic_weight_figure_path: Path
    lime_weight_figure_path: Path
    rank_comparison_figure_path: Path
    word_report_path: Path
    pdf_report_path: Path
    excel_workbook_path: Path
    robustness_csv_path: Path
    robustness_report_path: Path
    backtest_summary_path: Path
    backtest_periods_path: Path
    backtest_report_path: Path
    backtest_figure_path: Path
    adaptive_backtest_summary_path: Path
    adaptive_backtest_periods_path: Path
    adaptive_backtest_report_path: Path
    adaptive_backtest_figure_path: Path
    ranking_paths: dict[str, Path]


def run_pipeline(
    input_path: Path | None = None,
    metadata_path: Path = Path("data/raw/fund_metadata.csv"),
    benchmark_path: Path | None = None,
    profile: str = "balanced",
    top_n: int = 10,
    risk_free_rate: float = 0.02,
    reports_dir: Path = Path("reports"),
    processed_dir: Path = Path("data/processed"),
    demo: bool = False,
    demo_output: Path = Path("data/raw/demo_fund_nav.csv"),
    min_observations: int = 252,
    max_drawdown_limit: float = -0.6,
    portfolio_constraints: PortfolioConstraints | dict[str, object] | None = None,
    custom_weights: dict[str, float] | None = None,
) -> PipelineResult:
    portfolio_constraints = normalize_portfolio_constraints(portfolio_constraints)
    profile_weight_map = _profile_weight_map(profile, custom_weights)
    selected_weights = profile_weight_map[profile]
    reports_dir.mkdir(parents=True, exist_ok=True)
    processed_dir.mkdir(parents=True, exist_ok=True)

    if demo or input_path is None:
        nav = generate_demo_nav()
        data_source = save_nav_csv(nav, demo_output)
    else:
        nav = load_nav_csv(input_path)
        data_source = input_path
    benchmark_nav = load_nav_csv(benchmark_path) if benchmark_path is not None and benchmark_path.exists() else None

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
    data_quality_csv_path, data_quality_report_path = save_data_quality_outputs(
        nav,
        metrics,
        universe_audit,
        reports_dir,
    )
    metrics_path = processed_dir / "fund_metrics.csv"
    metrics_for_scoring.to_csv(metrics_path)

    factor_correlation_path, factor_diagnostics_path = save_factor_diagnostics(
        metrics_for_scoring,
        reports_dir / "factor_correlation.csv",
        reports_dir / "factor_diagnostics.md",
    )

    all_profiles = score_all_profiles(metrics_for_scoring, profile_weight_map)
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
    for profile_name, weights in profile_weight_map.items():
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

    (
        ml_training_samples_path,
        ml_weights_path,
        ml_ranking_path,
        ml_report_path,
        ml_comparison_path,
        ml_comparison_report_path,
        ml_evaluation_path,
        ml_evaluation_report_path,
    ) = save_ml_outputs(
        nav[metrics_for_scoring.index.intersection(nav.columns)],
        metrics_for_scoring,
        selected_weights,
        reports_dir,
        profile=profile,
        top_n=top_n,
        risk_free_rate=risk_free_rate,
        base_scored=selected_scored,
    )
    ml_reference_weights = _load_ml_reference_weights(ml_weights_path, selected_weights)
    (
        adaptive_ranking_path,
        adaptive_weights_path,
        adaptive_report_path,
        adaptive_scored,
        adaptive_weight_table,
    ) = save_adaptive_weight_outputs(
        metrics_for_scoring,
        selected_weights,
        reports_dir,
        profile=profile,
        top_n=top_n,
        reference_weights=ml_reference_weights,
        base_scored=selected_scored,
    )
    ml_scored_for_comparison = _read_indexed_csv(ml_ranking_path)
    (
        benchmark_comparison_path,
        peer_comparison_path,
        benchmark_report_path,
    ) = save_benchmark_outputs(
        nav[metrics_for_scoring.index.intersection(nav.columns)],
        selected_scored,
        adaptive_scored,
        ml_scored_for_comparison,
        reports_dir,
        profile=profile,
        top_n=top_n,
        external_benchmark=benchmark_nav,
    )
    (
        portfolio_weights_path,
        portfolio_summary_path,
        portfolio_report_path,
        portfolio_constraints_path,
        portfolio_figure_path,
        portfolio_recommendation_path,
        portfolio_recommendation_csv_path,
        portfolio_risk_controls_path,
    ) = save_portfolio_outputs(
        nav[metrics_for_scoring.index.intersection(nav.columns)],
        selected_scored,
        adaptive_scored,
        ml_scored_for_comparison,
        reports_dir,
        profile=profile,
        top_n=top_n,
        constraints=portfolio_constraints,
    )
    report = build_report(
        selected_scored,
        selected_weights,
        profile=profile,
        top_n=top_n,
        figures=[str(path) for path in figure_paths],
        adaptive_scored=adaptive_scored,
        adaptive_weights=adaptive_weight_table,
    )
    report_path = save_report(report, reports_dir / "fund_analysis_report.md")
    research_csv_path, research_report_path = build_research_enhancement(selected_scored, reports_dir)
    (
        factor_contribution_path,
        ranking_explanation_path,
        factor_contribution_report_path,
    ) = save_explainability_outputs(
        selected_scored,
        selected_weights,
        reports_dir,
        top_n=top_n,
    )
    lime_explanation_path, lime_report_path = save_lime_outputs(
        selected_scored,
        selected_weights,
        reports_dir,
        top_n=top_n,
    )
    (
        dynamic_weight_figure_path,
        lime_weight_figure_path,
        rank_comparison_figure_path,
    ) = save_explanation_visuals(
        adaptive_scored,
        adaptive_weight_table,
        pd.read_csv(lime_explanation_path, dtype={"fund": str}) if lime_explanation_path.exists() else pd.DataFrame(),
        pd.read_csv(ml_comparison_path, dtype={"fund": str}) if ml_comparison_path.exists() else pd.DataFrame(),
        reports_dir,
        top_n=top_n,
    )
    robustness = monte_carlo_weight_perturbation(
        metrics_for_scoring,
        selected_weights,
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
        selected_weights,
        reports_dir,
        top_n=top_n,
    )
    (
        adaptive_backtest_summary_path,
        adaptive_backtest_periods_path,
        adaptive_backtest_report_path,
        adaptive_backtest_figure_path,
    ) = save_adaptive_walk_forward_outputs(
        nav[metrics_for_scoring.index.intersection(nav.columns)],
        selected_weights,
        reports_dir,
        reference_weights=ml_reference_weights,
        top_n=top_n,
    )
    (
        portfolio_backtest_summary_path,
        portfolio_backtest_periods_path,
        portfolio_backtest_report_path,
        portfolio_backtest_figure_path,
    ) = save_portfolio_backtest_outputs(
        nav[metrics_for_scoring.index.intersection(nav.columns)],
        selected_weights,
        reports_dir,
        reference_weights=ml_reference_weights,
        constraints=portfolio_constraints,
        top_n=top_n,
    )
    strategy_benchmark_path, strategy_benchmark_report_path = save_strategy_benchmark_outputs(reports_dir)
    word_report_path, pdf_report_path, excel_workbook_path = save_friendly_exports(
        reports_dir,
        processed_dir,
        profile,
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
        data_quality_csv_path=data_quality_csv_path,
        data_quality_report_path=data_quality_report_path,
        factor_correlation_path=factor_correlation_path,
        factor_diagnostics_path=factor_diagnostics_path,
        factor_contribution_path=factor_contribution_path,
        ranking_explanation_path=ranking_explanation_path,
        factor_contribution_report_path=factor_contribution_report_path,
        lime_explanation_path=lime_explanation_path,
        lime_report_path=lime_report_path,
        ml_training_samples_path=ml_training_samples_path,
        ml_weights_path=ml_weights_path,
        ml_ranking_path=ml_ranking_path,
        ml_report_path=ml_report_path,
        ml_comparison_path=ml_comparison_path,
        ml_comparison_report_path=ml_comparison_report_path,
        ml_evaluation_path=ml_evaluation_path,
        ml_evaluation_report_path=ml_evaluation_report_path,
        adaptive_ranking_path=adaptive_ranking_path,
        adaptive_weights_path=adaptive_weights_path,
        adaptive_report_path=adaptive_report_path,
        benchmark_comparison_path=benchmark_comparison_path,
        peer_comparison_path=peer_comparison_path,
        benchmark_report_path=benchmark_report_path,
        portfolio_weights_path=portfolio_weights_path,
        portfolio_summary_path=portfolio_summary_path,
        portfolio_report_path=portfolio_report_path,
        portfolio_constraints_path=portfolio_constraints_path,
        portfolio_figure_path=portfolio_figure_path,
        portfolio_recommendation_path=portfolio_recommendation_path,
        portfolio_recommendation_csv_path=portfolio_recommendation_csv_path,
        portfolio_risk_controls_path=portfolio_risk_controls_path,
        portfolio_backtest_summary_path=portfolio_backtest_summary_path,
        portfolio_backtest_periods_path=portfolio_backtest_periods_path,
        portfolio_backtest_report_path=portfolio_backtest_report_path,
        portfolio_backtest_figure_path=portfolio_backtest_figure_path,
        strategy_benchmark_path=strategy_benchmark_path,
        strategy_benchmark_report_path=strategy_benchmark_report_path,
        dynamic_weight_figure_path=dynamic_weight_figure_path,
        lime_weight_figure_path=lime_weight_figure_path,
        rank_comparison_figure_path=rank_comparison_figure_path,
        word_report_path=word_report_path,
        pdf_report_path=pdf_report_path,
        excel_workbook_path=excel_workbook_path,
        robustness_csv_path=robustness_csv_path,
        robustness_report_path=robustness_report_path,
        backtest_summary_path=backtest_summary_path,
        backtest_periods_path=backtest_periods_path,
        backtest_report_path=backtest_report_path,
        backtest_figure_path=backtest_figure_path,
        adaptive_backtest_summary_path=adaptive_backtest_summary_path,
        adaptive_backtest_periods_path=adaptive_backtest_periods_path,
        adaptive_backtest_report_path=adaptive_backtest_report_path,
        adaptive_backtest_figure_path=adaptive_backtest_figure_path,
        ranking_paths=ranking_paths,
    )


def _load_ml_reference_weights(path: Path, fallback: dict[str, float]) -> dict[str, float]:
    if not path.exists():
        return fallback
    try:
        frame = pd.read_csv(path)
    except Exception:
        return fallback
    if not {"feature", "final_weight"}.issubset(frame.columns):
        return fallback
    weights = {
        str(row.feature): float(row.final_weight)
        for row in frame.itertuples(index=False)
        if pd.notna(row.final_weight)
    }
    return weights or fallback


def _profile_weight_map(profile: str, custom_weights: dict[str, float] | None) -> dict[str, dict[str, float]]:
    profiles = {name: weights.copy() for name, weights in DEFAULT_PROFILES.items()}
    if custom_weights is not None:
        profiles[profile] = _normalize_score_weights(custom_weights, fallback=profiles.get(profile, DEFAULT_PROFILES["balanced"]))
    elif profile not in profiles:
        profiles[profile] = profiles["balanced"].copy()
    return profiles


def _normalize_score_weights(
    weights: dict[str, float],
    fallback: dict[str, float],
) -> dict[str, float]:
    normalized = {
        metric: max(float(weights.get(metric, 0.0)), 0.0)
        for metric in SCORE_METRICS
    }
    total = sum(normalized.values())
    if total <= 0:
        normalized = {metric: max(float(fallback.get(metric, 0.0)), 0.0) for metric in SCORE_METRICS}
        total = sum(normalized.values())
    if total <= 0:
        return {metric: 1 / len(SCORE_METRICS) for metric in SCORE_METRICS}
    return {metric: value / total for metric, value in normalized.items()}


def _read_indexed_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"fund": str})
    if "fund" in frame.columns:
        return frame.set_index("fund")
    return pd.read_csv(path, index_col=0)

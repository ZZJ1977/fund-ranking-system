from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .advisory import add_decision_labels
from .data import generate_demo_nav, load_nav_csv, save_nav_csv
from .metadata import attach_fund_metadata, load_fund_metadata
from .metrics import calculate_metrics
from .report import build_report, save_report
from .research import build_research_enhancement
from .scoring import DEFAULT_PROFILES, score_all_profiles, score_funds
from .sensitivity import build_sensitivity_table, save_sensitivity_outputs
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
    metrics_path = processed_dir / "fund_metrics.csv"
    metrics.to_csv(metrics_path)

    all_profiles = score_all_profiles(metrics)
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
        scored = score_funds(metrics, weights)
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

    return PipelineResult(
        data_source=Path(data_source),
        metrics_path=metrics_path,
        all_profiles_path=all_profiles_path,
        sensitivity_csv_path=sensitivity_csv_path,
        sensitivity_report_path=sensitivity_report_path,
        report_path=report_path,
        research_csv_path=research_csv_path,
        research_report_path=research_report_path,
        ranking_paths=ranking_paths,
    )

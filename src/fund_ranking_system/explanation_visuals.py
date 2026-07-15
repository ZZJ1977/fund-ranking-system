from __future__ import annotations

from pathlib import Path

import pandas as pd

from .chart_style import (
    ACCENT,
    GREEN,
    GRID,
    MUTED,
    PALETTE,
    RED,
    TEXT,
    annotate_barh,
    empty_plot,
    figure_axes,
    finish_figure,
    polish_axes,
)


PLOT_FACTOR_LABELS = {
    "annual_return": "Annual Return",
    "年化收益": "Annual Return",
    "sharpe": "Sharpe",
    "max_drawdown": "Max Drawdown",
    "最大回撤": "Max Drawdown",
    "calmar": "Calmar",
    "annual_volatility": "Annual Volatility",
    "年化波动": "Annual Volatility",
    "rolling_positive_ratio": "Rolling Positive Ratio",
    "滚动正收益比例": "Rolling Positive Ratio",
}


def save_explanation_visuals(
    adaptive_scored: pd.DataFrame,
    adaptive_weights: pd.DataFrame,
    lime_explanations: pd.DataFrame,
    comparison: pd.DataFrame,
    reports_dir: str | Path,
    top_n: int,
) -> tuple[Path, Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    dynamic_path = reports_dir / "dynamic_weight_top_factors.png"
    lime_path = reports_dir / "lime_local_weight_bars.png"
    rank_path = reports_dir / "rank_comparison_changes.png"
    plot_dynamic_weight_bars(adaptive_scored, adaptive_weights, dynamic_path, top_n=top_n)
    plot_lime_weight_bars(lime_explanations, lime_path, top_n=top_n)
    plot_rank_comparison(comparison, rank_path, top_n=top_n)
    return dynamic_path, lime_path, rank_path


def plot_dynamic_weight_bars(
    adaptive_scored: pd.DataFrame,
    adaptive_weights: pd.DataFrame,
    path: str | Path,
    top_n: int,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if adaptive_scored.empty or adaptive_weights.empty:
        return _empty_plot(path, "No dynamic weight data")

    funds = [str(fund) for fund in adaptive_scored.head(min(top_n, 6)).index]
    frame = adaptive_weights[adaptive_weights["fund"].astype(str).isin(funds)].copy()
    if frame.empty:
        return _empty_plot(path, "No dynamic weight data")
    feature_column = "feature" if "feature" in frame.columns else "feature_label"
    pivot = frame.pivot_table(index="fund", columns=feature_column, values="dynamic_weight", aggfunc="sum").fillna(0)
    pivot = pivot.rename(columns=lambda value: PLOT_FACTOR_LABELS.get(str(value), str(value)))
    pivot = pivot.reindex(funds)
    fig, ax = figure_axes((11, 6.2))
    pivot.plot(kind="bar", stacked=True, ax=ax, color=PALETTE[: len(pivot.columns)], width=0.72, edgecolor="white", linewidth=0.5)
    polish_axes(
        ax,
        "Top 基金动态因子权重",
        "基金",
        "权重",
        grid_axis="y",
        subtitle="每根堆叠柱展示该基金在动态评分中的因子侧重点。",
    )
    ax.set_ylim(0, 1.02)
    ax.legend(fontsize=8, loc="upper center", bbox_to_anchor=(0.5, -0.16), ncols=3)
    ax.tick_params(axis="x", rotation=20)
    finish_figure(fig, path)
    return path


def plot_lime_weight_bars(lime_explanations: pd.DataFrame, path: str | Path, top_n: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if lime_explanations.empty:
        return _empty_plot(path, "No LIME data")
    funds = lime_explanations["fund"].astype(str).drop_duplicates().head(min(top_n, 5)).tolist()
    frame = lime_explanations[lime_explanations["fund"].astype(str).isin(funds)].copy()
    frame["label"] = frame["fund"].astype(str) + " / " + frame["feature"].map(lambda value: PLOT_FACTOR_LABELS.get(str(value), str(value)))
    frame = frame.sort_values("abs_weight", ascending=False).head(18).sort_values("local_weight")
    colors = [RED if value < 0 else GREEN for value in frame["local_weight"]]
    fig, ax = figure_axes((11, 7.2))
    ax.barh(frame["label"], frame["local_weight"], color=colors, edgecolor="white", linewidth=1.0, height=0.72)
    ax.axvline(0, color=GRID, linewidth=1.2)
    annotate_barh(ax, frame["local_weight"].astype(float), fmt="{:+.2f}")
    polish_axes(
        ax,
        "LIME 局部因子权重",
        "局部代理模型权重",
        "",
        grid_axis="x",
        subtitle="绿色因子推高局部评分，红色因子拉低局部评分。",
    )
    finish_figure(fig, path)
    return path


def plot_rank_comparison(comparison: pd.DataFrame, path: str | Path, top_n: int) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if comparison.empty:
        return _empty_plot(path, "No rank comparison data")
    frame = comparison.head(min(top_n, 12)).copy()
    labels = frame["fund"].astype(str)
    x = range(len(frame))
    fig, ax = figure_axes((11, 6.2))
    ax.plot(x, frame["original_rank"], marker="o", markersize=6, linewidth=2.2, label="原始排名", color=MUTED)
    ax.plot(x, frame["ml_rank"], marker="o", markersize=6, linewidth=2.2, label="ML 排名", color=ACCENT)
    for index, row in enumerate(frame.itertuples(index=False)):
        ax.plot([index, index], [row.original_rank, row.ml_rank], color=GRID, linewidth=1.2, zorder=0)
        change = int(row.rank_change) if hasattr(row, "rank_change") and pd.notna(row.rank_change) else int(row.original_rank - row.ml_rank)
        ax.text(index, min(row.original_rank, row.ml_rank) - 0.25, f"{change:+d}", ha="center", va="bottom", fontsize=8, color=GREEN if change > 0 else RED if change < 0 else MUTED, fontweight="bold")
    ax.invert_yaxis()
    ax.set_xticks(list(x), labels, rotation=22, ha="right")
    polish_axes(
        ax,
        "原始排名与 ML 排名变化",
        "",
        "排名",
        grid_axis="y",
        subtitle="正数表示基金在 ML 辅助排名中上升。",
    )
    ax.legend(fontsize=9, loc="upper right")
    finish_figure(fig, path)
    return path


def _empty_plot(path: Path, message: str) -> Path:
    return empty_plot(path, message)

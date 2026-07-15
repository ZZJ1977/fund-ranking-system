from __future__ import annotations

from pathlib import Path

import pandas as pd

from .chart_style import (
    AMBER,
    GRID,
    MUTED,
    PALETTE,
    SCORE_CMAP,
    TEXT,
    annotate_barh,
    figure_axes,
    finish_figure,
    format_percent_axis,
    polish_axes,
)
from .metadata import display_fund
from .metrics import drawdown_series

def plot_top_scores(scored: pd.DataFrame, path: str | Path, top_n: int = 10) -> Path:
    top = scored.head(top_n).sort_values("composite_score")
    fig, ax = figure_axes((10.5, 6.2))
    labels = [_short_label(str(fund), row) for fund, row in top.iterrows()]
    scores = top["composite_score"].astype(float).tolist()
    colors = SCORE_CMAP(top["composite_score"].rank(pct=True).to_numpy())
    ax.barh(labels, scores, color=colors, edgecolor="white", linewidth=1.2, height=0.72)
    annotate_barh(ax, scores, fmt="{:.1f}")
    ax.set_xlim(0, max(max(scores) * 1.12, 100 if max(scores) > 88 else 1))
    polish_axes(
        ax,
        f"Top {min(top_n, len(top))} 基金多因子评分",
        "综合评分",
        "",
        grid_axis="x",
        subtitle="分数越高，代表越符合当前画像下的风险收益偏好。",
    )
    return finish_figure(fig, path)


def plot_risk_return(scored: pd.DataFrame, path: str | Path, top_n: int = 10) -> Path:
    fig, ax = figure_axes((10.2, 6.4))
    size = 70 + scored["composite_score"].rank(pct=True).fillna(0.5) * 90
    scatter = ax.scatter(
        scored["annual_volatility"],
        scored["annual_return"],
        c=scored["composite_score"],
        cmap=SCORE_CMAP,
        s=size,
        alpha=0.90,
        edgecolor="white",
        linewidth=1.1,
    )
    colorbar = fig.colorbar(scatter, ax=ax, pad=0.025)
    colorbar.set_label("综合评分", color=TEXT)
    colorbar.outline.set_edgecolor(GRID)
    ax.axvline(scored["annual_volatility"].median(), color=GRID, linestyle="--", linewidth=1)
    ax.axhline(scored["annual_return"].median(), color=GRID, linestyle="--", linewidth=1)
    ax.margins(x=0.08, y=0.16)
    polish_axes(ax, "风险收益分布", "年化波动率", "年化收益率", grid_axis="both")
    format_percent_axis(ax, "both")
    ax.text(0.01, 0.98, "左上角更优：收益更高、波动更低。", transform=ax.transAxes, va="top", color=MUTED, fontsize=9)

    offsets = [(12, -14), (14, 16), (-12, 20), (14, -22), (-12, 16), (-14, -18)]
    for index, (fund, row) in enumerate(scored.head(top_n).iterrows()):
        offset = offsets[index % len(offsets)]
        ax.annotate(
            _short_label(str(fund), row, max_len=13),
            (row["annual_volatility"], row["annual_return"]),
            fontsize=8,
            color=TEXT,
            fontweight="bold",
            xytext=offset,
            textcoords="offset points",
            ha="right" if offset[0] < 0 else "left",
            va="top" if offset[1] < 0 else "bottom",
            bbox={"boxstyle": "round,pad=0.22", "fc": "white", "ec": GRID, "lw": 0.6, "alpha": 0.88},
            arrowprops={"arrowstyle": "-", "color": GRID, "lw": 0.7, "shrinkA": 0, "shrinkB": 4},
        )

    return finish_figure(fig, path)


def plot_nav(nav: pd.DataFrame, funds: list[str], path: str | Path) -> Path:
    fig, ax = figure_axes((10.5, 6.2))
    normalized = nav[funds] / nav[funds].iloc[0]
    for index, fund in enumerate(funds):
        series = normalized[fund].dropna()
        color = PALETTE[index % len(PALETTE)]
        ax.plot(series.index, series, label=str(fund), linewidth=2.2, color=color)
        if not series.empty:
            ax.scatter(series.index[-1], series.iloc[-1], s=28, color=color, zorder=3, edgecolor="white", linewidth=0.8)
            ax.annotate(f"{series.iloc[-1]:.2f}x", (series.index[-1], series.iloc[-1]), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8, color=color)
    polish_axes(ax, "Top 基金净值走势", "", "单位净值增长倍数", grid_axis="y")
    ax.legend(fontsize=8, ncols=2, loc="upper left")
    return finish_figure(fig, path)


def plot_drawdown(nav: pd.DataFrame, funds: list[str], path: str | Path) -> Path:
    fig, ax = figure_axes((10.5, 6.2))
    drawdowns = drawdown_series(nav, funds)
    for index, fund in enumerate(funds):
        series = drawdowns[fund].dropna()
        color = PALETTE[index % len(PALETTE)]
        ax.plot(series.index, series, label=str(fund), linewidth=2.0, color=color)
        if not series.empty:
            trough = series.idxmin()
            ax.scatter(trough, series.loc[trough], s=30, color=AMBER, zorder=3, edgecolor="white", linewidth=0.8)
    ax.axhline(0, color=GRID, linewidth=1)
    polish_axes(ax, "Top 基金回撤走势", "", "回撤", grid_axis="y")
    format_percent_axis(ax, "y")
    ax.legend(fontsize=8, ncols=2, loc="lower left")
    return finish_figure(fig, path)


def _short_label(fund: str, row: pd.Series, max_len: int = 18) -> str:
    label = display_fund(fund, row).replace("Fund_", "F")
    if len(label) <= max_len:
        return label
    return label[: max_len - 1] + "…"

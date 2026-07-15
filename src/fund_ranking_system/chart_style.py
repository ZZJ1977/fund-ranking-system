from __future__ import annotations

from pathlib import Path
from typing import Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import ticker
from matplotlib.colors import LinearSegmentedColormap


BACKGROUND = "#F6F7F9"
PANEL = "#FFFFFF"
TEXT = "#17202A"
MUTED = "#667085"
GRID = "#D9DEE7"
ACCENT = "#176B87"
GREEN = "#027A48"
RED = "#B42318"
AMBER = "#A94F19"
PALETTE = ["#176B87", "#35A7A0", "#6B8E23", "#D89B00", "#7A5C99", "#B85C38", "#3E6EA8", "#5C8374"]
SCORE_CMAP = LinearSegmentedColormap.from_list("fund_score", ["#DDEAF0", "#35A7A0", "#176B87"])


def apply_chart_theme() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": BACKGROUND,
            "axes.facecolor": PANEL,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT,
            "axes.titlecolor": TEXT,
            "xtick.color": "#344054",
            "ytick.color": "#344054",
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "font.family": [
                "PingFang SC",
                "Hiragino Sans GB",
                "Heiti SC",
                "Arial Unicode MS",
                "Microsoft YaHei",
                "SimHei",
                "Noto Sans CJK SC",
                "DejaVu Sans",
            ],
            "font.size": 10,
            "axes.unicode_minus": False,
            "axes.titlesize": 14,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "legend.frameon": True,
            "legend.facecolor": PANEL,
            "legend.edgecolor": GRID,
            "savefig.facecolor": BACKGROUND,
        }
    )


def figure_axes(figsize: tuple[float, float] = (10, 6)):
    apply_chart_theme()
    fig, ax = plt.subplots(figsize=figsize)
    return fig, ax


def polish_axes(
    ax,
    title: str,
    xlabel: str = "",
    ylabel: str = "",
    grid_axis: str = "y",
    subtitle: str = "",
) -> None:
    ax.set_title(title, loc="left", pad=30 if subtitle else 14)
    if subtitle:
        ax.text(0, 1.012, subtitle, transform=ax.transAxes, color=MUTED, fontsize=9, va="bottom", clip_on=False)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    if grid_axis:
        ax.grid(True, axis=grid_axis, alpha=0.65)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    ax.spines["left"].set_color(GRID)
    ax.spines["bottom"].set_color(GRID)


def format_percent_axis(ax, axis: str = "x") -> None:
    formatter = ticker.PercentFormatter(xmax=1.0, decimals=0)
    if axis == "x":
        ax.xaxis.set_major_formatter(formatter)
    elif axis == "y":
        ax.yaxis.set_major_formatter(formatter)
    else:
        ax.xaxis.set_major_formatter(formatter)
        ax.yaxis.set_major_formatter(formatter)


def annotate_barh(ax, values: Iterable[float], fmt: str = "{:.1f}", color: str = TEXT) -> None:
    values = list(values)
    if not values:
        return
    max_value = max(abs(value) for value in values) or 1.0
    offset = max_value * 0.015
    for index, value in enumerate(values):
        ha = "left" if value >= 0 else "right"
        x = value + offset if value >= 0 else value - offset
        ax.text(x, index, fmt.format(value), va="center", ha=ha, color=color, fontsize=9, fontweight="bold")


def finish_figure(fig, path: str | Path, dpi: int = 190) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(pad=2.0)
    fig.savefig(path, dpi=dpi, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return path


def empty_plot(path: str | Path, message: str) -> Path:
    fig, ax = figure_axes((8, 4))
    ax.text(0.5, 0.54, message, ha="center", va="center", color=MUTED, fontsize=12, fontweight="bold")
    ax.text(0.5, 0.42, "The report will populate this chart when enough data is available.", ha="center", va="center", color=MUTED, fontsize=9)
    ax.axis("off")
    return finish_figure(fig, path)

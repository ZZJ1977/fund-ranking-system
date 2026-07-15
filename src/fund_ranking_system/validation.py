from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .adaptive_weights import score_funds_with_adaptive_weights
from .chart_style import GRID, PALETTE, empty_plot, figure_axes, finish_figure, polish_axes
from .metrics import calculate_metrics, daily_returns, max_drawdown
from .scoring import score_funds


def walk_forward_backtest(
    nav: pd.DataFrame,
    weights: dict[str, float],
    lookback_days: int = 252,
    holding_days: int = 63,
    step_days: int = 63,
    top_n: int = 10,
    top_pct: float = 0.2,
    min_funds: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run a walk-forward out-of-sample validation on NAV data."""
    nav = nav.sort_index().dropna(how="all").ffill()
    if len(nav) < lookback_days + holding_days:
        return pd.DataFrame(), pd.DataFrame()

    portfolio_returns: list[pd.Series] = []
    period_rows: list[dict[str, object]] = []
    start = 0
    while start + lookback_days + holding_days <= len(nav):
        train = nav.iloc[start : start + lookback_days]
        hold = nav.iloc[start + lookback_days : start + lookback_days + holding_days]
        available = train.columns[train.notna().sum() >= max(60, int(lookback_days * 0.8))]
        available = [fund for fund in available if hold[fund].notna().sum() >= max(20, int(holding_days * 0.5))]
        if len(available) >= min_funds:
            train_metrics = calculate_metrics(train[available])
            scored = score_funds(train_metrics, weights)
            top_n_funds = scored.head(min(top_n, len(scored))).index.tolist()
            top_pct_count = max(1, int(np.ceil(len(scored) * top_pct)))
            top_pct_funds = scored.head(top_pct_count).index.tolist()
            period_returns = daily_returns(hold[available]).dropna(how="all")
            portfolios = {
                "Top 10": _equal_weight_return(period_returns, top_n_funds),
                "Top 20%": _equal_weight_return(period_returns, top_pct_funds),
                "All Funds": _equal_weight_return(period_returns, available),
            }
            period_frame = pd.DataFrame(portfolios).dropna(how="all")
            portfolio_returns.append(period_frame)
            for name, series in portfolios.items():
                period_rows.append(
                    {
                        "train_start": train.index[0].date().isoformat(),
                        "train_end": train.index[-1].date().isoformat(),
                        "hold_start": hold.index[0].date().isoformat(),
                        "hold_end": hold.index[-1].date().isoformat(),
                        "portfolio": name,
                        "fund_count": len(top_n_funds if name == "Top 10" else top_pct_funds if name == "Top 20%" else available),
                        "holding_return": float((1 + series.dropna()).prod() - 1),
                    }
                )
        start += step_days

    if not portfolio_returns:
        return pd.DataFrame(), pd.DataFrame(period_rows)
    returns = pd.concat(portfolio_returns).sort_index()
    returns = returns[~returns.index.duplicated(keep="first")]
    summary = _performance_summary(returns)
    return summary, pd.DataFrame(period_rows)


def save_walk_forward_outputs(
    nav: pd.DataFrame,
    weights: dict[str, float],
    reports_dir: str | Path,
    lookback_days: int = 252,
    holding_days: int = 63,
    step_days: int = 63,
    top_n: int = 10,
) -> tuple[Path, Path, Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary, periods = walk_forward_backtest(
        nav,
        weights,
        lookback_days=lookback_days,
        holding_days=holding_days,
        step_days=step_days,
        top_n=top_n,
    )
    summary_path = reports_dir / "walk_forward_results.csv"
    periods_path = reports_dir / "walk_forward_periods.csv"
    markdown_path = reports_dir / "backtest_summary.md"
    figure_path = reports_dir / "walk_forward_cumulative_return.png"
    summary.to_csv(summary_path)
    periods.to_csv(periods_path, index=False)
    _plot_cumulative_returns(nav, weights, figure_path, lookback_days, holding_days, step_days, top_n)
    markdown_path.write_text(build_backtest_markdown(summary, periods, figure_path), encoding="utf-8")
    return summary_path, periods_path, markdown_path, figure_path


def adaptive_walk_forward_backtest(
    nav: pd.DataFrame,
    base_weights: dict[str, float],
    reference_weights: dict[str, float] | None = None,
    lookback_days: int = 252,
    holding_days: int = 63,
    step_days: int = 63,
    top_n: int = 10,
    min_funds: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Validate whether fund-level dynamic weights improve Top-N selection."""
    nav = nav.sort_index().dropna(how="all").ffill()
    if len(nav) < lookback_days + holding_days:
        return pd.DataFrame(), pd.DataFrame()

    portfolio_returns: list[pd.DataFrame] = []
    period_rows: list[dict[str, object]] = []
    start = 0
    while start + lookback_days + holding_days <= len(nav):
        train = nav.iloc[start : start + lookback_days]
        hold = nav.iloc[start + lookback_days : start + lookback_days + holding_days]
        available = train.columns[train.notna().sum() >= max(60, int(lookback_days * 0.8))]
        available = [fund for fund in available if hold[fund].notna().sum() >= max(20, int(holding_days * 0.5))]
        if len(available) >= min_funds:
            train_metrics = calculate_metrics(train[available])
            fixed_scored = score_funds(train_metrics, base_weights)
            adaptive_scored, _ = score_funds_with_adaptive_weights(
                train_metrics,
                base_weights,
                reference_weights=reference_weights,
            )
            fixed_top = fixed_scored.head(min(top_n, len(fixed_scored))).index.tolist()
            adaptive_top = adaptive_scored.head(min(top_n, len(adaptive_scored))).index.tolist()
            period_returns = daily_returns(hold[available]).dropna(how="all")
            portfolios = {
                "Fixed TopN": _equal_weight_return(period_returns, fixed_top),
                "Adaptive TopN": _equal_weight_return(period_returns, adaptive_top),
                "All Funds": _equal_weight_return(period_returns, available),
            }
            portfolio_returns.append(pd.DataFrame(portfolios).dropna(how="all"))
            for name, series in portfolios.items():
                selected = adaptive_top if name == "Adaptive TopN" else fixed_top if name == "Fixed TopN" else available
                period_rows.append(
                    {
                        "train_start": train.index[0].date().isoformat(),
                        "train_end": train.index[-1].date().isoformat(),
                        "hold_start": hold.index[0].date().isoformat(),
                        "hold_end": hold.index[-1].date().isoformat(),
                        "portfolio": name,
                        "fund_count": len(selected),
                        "selected_funds": " ".join(str(fund) for fund in selected),
                        "holding_return": float((1 + series.dropna()).prod() - 1),
                    }
                )
        start += step_days

    if not portfolio_returns:
        return pd.DataFrame(), pd.DataFrame(period_rows)
    returns = pd.concat(portfolio_returns).sort_index()
    returns = returns[~returns.index.duplicated(keep="first")]
    return _performance_summary(returns), pd.DataFrame(period_rows)


def save_adaptive_walk_forward_outputs(
    nav: pd.DataFrame,
    base_weights: dict[str, float],
    reports_dir: str | Path,
    reference_weights: dict[str, float] | None = None,
    lookback_days: int = 252,
    holding_days: int = 63,
    step_days: int = 63,
    top_n: int = 10,
) -> tuple[Path, Path, Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary, periods = adaptive_walk_forward_backtest(
        nav,
        base_weights,
        reference_weights=reference_weights,
        lookback_days=lookback_days,
        holding_days=holding_days,
        step_days=step_days,
        top_n=top_n,
    )
    summary_path = reports_dir / "adaptive_walk_forward_results.csv"
    periods_path = reports_dir / "adaptive_walk_forward_periods.csv"
    markdown_path = reports_dir / "adaptive_backtest_summary.md"
    figure_path = reports_dir / "adaptive_walk_forward_cumulative_return.png"
    summary.to_csv(summary_path)
    periods.to_csv(periods_path, index=False)
    _plot_adaptive_cumulative_returns(periods, figure_path)
    markdown_path.write_text(
        build_adaptive_backtest_markdown(summary, periods, figure_path),
        encoding="utf-8",
    )
    return summary_path, periods_path, markdown_path, figure_path


def build_backtest_markdown(summary: pd.DataFrame, periods: pd.DataFrame, figure_path: Path) -> str:
    if summary.empty:
        return """# Walk-Forward 样本外验证

当前数据长度不足，无法完成滚动样本外验证。建议至少提供覆盖训练窗口和持有窗口的连续净值数据。
"""
    rows = [
        "| Portfolio | Annual Return | Sharpe | Volatility | Max Drawdown | Win Rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for portfolio, row in summary.iterrows():
        rows.append(
            f"| {portfolio} | {row['annual_return']:.2%} | {row['sharpe']:.2f} | {row['annual_volatility']:.2%} | {row['max_drawdown']:.2%} | {row['win_rate']:.1%} |"
        )
    return f"""# Walk-Forward 样本外验证

本验证用于回答：历史多因子评分较高的基金，在后续持有期是否表现出一定区分能力。

验证方式：

- 使用滚动历史窗口计算指标并进行评分。
- 选择 Top 10 与 Top 20% 基金构建等权组合。
- 与全基金等权组合进行比较。
- 观察后续持有期的真实表现。

## 结果汇总

{chr(10).join(rows)}

## 样本窗口

- 有效滚动窗口数量：{periods['hold_start'].nunique() if not periods.empty else 0}
- 累计收益图：`{figure_path}`

## 表述边界

该验证不证明模型可以预测基金未来收益，只检验历史评价指标是否对后续表现具有一定区分能力。
"""


def build_adaptive_backtest_markdown(summary: pd.DataFrame, periods: pd.DataFrame, figure_path: Path) -> str:
    if summary.empty:
        return """# 动态权重 Walk-Forward 验证

当前数据长度不足，无法完成动态权重滚动样本外验证。
"""

    rows = [
        "| Portfolio | Annual Return | Sharpe | Volatility | Max Drawdown | Win Rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for portfolio, row in summary.iterrows():
        rows.append(
            f"| {portfolio} | {row['annual_return']:.2%} | {row['sharpe']:.2f} | {row['annual_volatility']:.2%} | {row['max_drawdown']:.2%} | {row['win_rate']:.1%} |"
        )

    adaptive_return = _summary_value(summary, "Adaptive TopN", "annual_return")
    fixed_return = _summary_value(summary, "Fixed TopN", "annual_return")
    return_gap = adaptive_return - fixed_return if pd.notna(adaptive_return) and pd.notna(fixed_return) else np.nan

    return f"""# 动态权重 Walk-Forward 验证

本验证用于回答：基金级动态权重是否只是解释层，还是能在滚动样本外选择中带来更好的区分能力。

验证方式：

- 每个训练窗口先计算基金指标。
- 固定权重模型选择 `Fixed TopN`。
- 动态权重模型根据每只基金局部特征生成权重并选择 `Adaptive TopN`。
- 后续持有期用真实净值计算等权组合收益。
- 与本次基金池全基金等权组合比较。

## 结果汇总

{chr(10).join(rows)}

## 动态权重相对固定权重

- 年化收益差：{return_gap:.2%}
- 有效滚动窗口数量：{periods['hold_start'].nunique() if not periods.empty else 0}
- 累计收益图：`{figure_path}`

## 使用边界

动态权重验证仍基于历史滚动窗口，不能保证未来有效。它适合判断“动态权重是否比固定权重更有研究价值”，不应被理解为收益承诺或交易信号。
"""


def _equal_weight_return(returns: pd.DataFrame, funds: list[str]) -> pd.Series:
    selected = [fund for fund in funds if fund in returns.columns]
    if not selected:
        return pd.Series(dtype=float)
    return returns[selected].mean(axis=1)


def _performance_summary(returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in returns.columns:
        series = returns[column].dropna()
        if series.empty:
            continue
        cumulative = (1 + series).cumprod()
        ann_return = cumulative.iloc[-1] ** (252 / len(series)) - 1
        ann_vol = series.std(ddof=1) * np.sqrt(252)
        sharpe = ann_return / ann_vol if ann_vol > 0 else np.nan
        rows.append(
            {
                "portfolio": column,
                "annual_return": ann_return,
                "annual_volatility": ann_vol,
                "max_drawdown": max_drawdown(cumulative),
                "sharpe": sharpe,
                "win_rate": float((series > 0).mean()),
            }
        )
    return pd.DataFrame(rows).set_index("portfolio")


def _plot_cumulative_returns(
    nav: pd.DataFrame,
    weights: dict[str, float],
    path: Path,
    lookback_days: int,
    holding_days: int,
    step_days: int,
    top_n: int,
) -> None:
    summary, periods = walk_forward_backtest(
        nav,
        weights,
        lookback_days=lookback_days,
        holding_days=holding_days,
        step_days=step_days,
        top_n=top_n,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    if summary.empty or periods.empty:
        empty_plot(path, "Not enough data for walk-forward validation")
        return
    # Rebuild daily return path once for plotting.
    # Use period holding returns for a compact cumulative view.
    pivot = periods.pivot_table(index="hold_end", columns="portfolio", values="holding_return", aggfunc="mean")
    cumulative = (1 + pivot.fillna(0)).cumprod()
    fig, ax = figure_axes((10, 5.8))
    for index, column in enumerate(cumulative.columns):
        series = cumulative[column].dropna()
        color = PALETTE[index % len(PALETTE)]
        ax.plot(pd.to_datetime(series.index), series, label=column, linewidth=2.2, color=color)
        if not series.empty:
            ax.scatter(pd.to_datetime(series.index[-1]), series.iloc[-1], s=30, color=color, edgecolor="white", linewidth=0.8, zorder=3)
            ax.annotate(f"{series.iloc[-1]:.2f}x", (pd.to_datetime(series.index[-1]), series.iloc[-1]), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8, color=color)
    ax.axhline(1.0, color=GRID, linestyle="--", linewidth=1)
    polish_axes(
        ax,
        "Walk-Forward 累计收益",
        "持有期结束日",
        "单位净值增长倍数",
        grid_axis="y",
        subtitle="滚动样本外检验排名组合相对全基金基准的表现。",
    )
    ax.legend(fontsize=8, loc="upper left")
    finish_figure(fig, path)


def _plot_adaptive_cumulative_returns(periods: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if periods.empty:
        empty_plot(path, "Not enough data for adaptive validation")
        return
    pivot = periods.pivot_table(index="hold_end", columns="portfolio", values="holding_return", aggfunc="mean")
    cumulative = (1 + pivot.fillna(0)).cumprod()
    fig, ax = figure_axes((10, 5.8))
    for index, column in enumerate(cumulative.columns):
        series = cumulative[column].dropna()
        color = PALETTE[index % len(PALETTE)]
        ax.plot(pd.to_datetime(series.index), series, label=column, linewidth=2.2, color=color)
        if not series.empty:
            ax.scatter(pd.to_datetime(series.index[-1]), series.iloc[-1], s=30, color=color, edgecolor="white", linewidth=0.8, zorder=3)
            ax.annotate(f"{series.iloc[-1]:.2f}x", (pd.to_datetime(series.index[-1]), series.iloc[-1]), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8, color=color)
    ax.axhline(1.0, color=GRID, linestyle="--", linewidth=1)
    polish_axes(
        ax,
        "动态权重 Walk-Forward 累计收益",
        "持有期结束日",
        "单位净值增长倍数",
        grid_axis="y",
        subtitle="比较基金级动态权重、固定 TopN 与全基金基准的收益路径。",
    )
    ax.legend(fontsize=8, loc="upper left")
    finish_figure(fig, path)


def _summary_value(summary: pd.DataFrame, portfolio: str, column: str) -> float:
    if portfolio not in summary.index or column not in summary.columns:
        return float("nan")
    return float(summary.loc[portfolio, column])

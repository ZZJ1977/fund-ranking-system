from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .adaptive_weights import score_funds_with_adaptive_weights
from .chart_style import GRID, PALETTE, empty_plot, figure_axes, finish_figure, polish_axes
from .metrics import calculate_metrics, daily_returns, max_drawdown
from .portfolio import PortfolioConstraints, normalize_portfolio_constraints, optimize_constrained_portfolio, portfolio_turnover, _risk_parity_weights
from .scoring import score_funds

SUMMARY_COLUMNS = [
    "annual_return",
    "annual_volatility",
    "max_drawdown",
    "sharpe",
    "win_rate",
    "avg_turnover",
]
PERIOD_COLUMNS = [
    "train_start",
    "train_end",
    "hold_start",
    "hold_end",
    "portfolio",
    "fund_count",
    "turnover",
    "transaction_cost",
    "selected_funds",
    "holding_return",
]


def save_portfolio_backtest_outputs(
    nav: pd.DataFrame,
    base_weights: dict[str, float],
    reports_dir: str | Path,
    reference_weights: dict[str, float] | None = None,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
    lookback_days: int = 252,
    holding_days: int | None = None,
    step_days: int | None = None,
    top_n: int = 10,
) -> tuple[Path, Path, Path, Path]:
    constraints = normalize_portfolio_constraints(constraints)
    holding_days = holding_days or constraints.rebalance_days
    step_days = step_days or constraints.rebalance_days
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    summary, periods, returns = rebalance_backtest(
        nav,
        base_weights,
        reference_weights=reference_weights,
        constraints=constraints,
        lookback_days=lookback_days,
        holding_days=holding_days,
        step_days=step_days,
        top_n=top_n,
    )
    summary_path = reports_dir / "portfolio_rebalance_results.csv"
    periods_path = reports_dir / "portfolio_rebalance_periods.csv"
    report_path = reports_dir / "portfolio_rebalance_report.md"
    figure_path = reports_dir / "portfolio_rebalance_cumulative_return.png"
    summary.to_csv(summary_path)
    periods.to_csv(periods_path, index=False)
    _plot_cumulative(returns, figure_path)
    report_path.write_text(build_rebalance_report(summary, periods, figure_path, constraints), encoding="utf-8")
    return summary_path, periods_path, report_path, figure_path


def rebalance_backtest(
    nav: pd.DataFrame,
    base_weights: dict[str, float],
    reference_weights: dict[str, float] | None = None,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
    lookback_days: int = 252,
    holding_days: int = 63,
    step_days: int = 63,
    top_n: int = 10,
    min_funds: int = 3,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    constraints = normalize_portfolio_constraints(constraints)
    nav = nav.sort_index().dropna(how="all").ffill()
    if len(nav) < lookback_days + holding_days:
        return _empty_summary(), _empty_periods(), pd.DataFrame()

    return_frames: list[pd.DataFrame] = []
    period_rows: list[dict[str, object]] = []
    previous_weights: dict[str, dict[str, float]] = {}
    start = 0
    while start + lookback_days + holding_days <= len(nav):
        train = nav.iloc[start : start + lookback_days]
        hold = nav.iloc[start + lookback_days : start + lookback_days + holding_days]
        available = train.columns[train.notna().sum() >= max(60, int(lookback_days * 0.8))]
        available = [fund for fund in available if hold[fund].notna().sum() >= max(20, int(holding_days * 0.5))]
        if len(available) >= min_funds:
            train_metrics = calculate_metrics(train[available])
            fixed_scored = score_funds(train_metrics, base_weights)
            adaptive_scored, _ = score_funds_with_adaptive_weights(train_metrics, base_weights, reference_weights=reference_weights)
            period_returns = daily_returns(hold[available]).dropna(how="all")

            fixed_top = [str(fund) for fund in fixed_scored.head(min(top_n, len(fixed_scored))).index]
            adaptive_top = [str(fund) for fund in adaptive_scored.head(min(top_n, len(adaptive_scored))).index]
            risk_parity = _risk_parity_weights(period_returns[[fund for fund in adaptive_top if fund in period_returns.columns]])
            constrained_frame = optimize_constrained_portfolio(
                train[available],
                adaptive_scored,
                constraints,
                previous_weights=previous_weights.get("Constrained Optimized Rebalance"),
                portfolio_name="Constrained Optimized Rebalance",
            )
            constrained_weights = dict(zip(constrained_frame["fund"], constrained_frame["weight"], strict=False)) if not constrained_frame.empty else {}
            portfolios = {
                "Fixed Rebalance": {fund: 1 / len(fixed_top) for fund in fixed_top} if fixed_top else {},
                "Adaptive Rebalance": {fund: 1 / len(adaptive_top) for fund in adaptive_top} if adaptive_top else {},
                "Constrained Optimized Rebalance": constrained_weights,
                "Risk Parity Rebalance": risk_parity,
                "All Funds": {fund: 1 / len(available) for fund in available},
            }
            period_series = {
                name: _apply_transaction_cost(
                    _weighted_return(period_returns, weights),
                    portfolio_turnover(previous_weights.get(name, {}), weights),
                    constraints.transaction_cost_bps,
                )
                for name, weights in portfolios.items()
                if weights
            }
            frame = pd.DataFrame(
                period_series
            ).dropna(how="all")
            return_frames.append(frame)
            for name, weights in portfolios.items():
                holdings = set(weights)
                turnover = portfolio_turnover(previous_weights.get(name, {}), weights)
                transaction_cost = turnover * constraints.transaction_cost_bps / 10000.0
                period_rows.append(
                    {
                        "train_start": train.index[0].date().isoformat(),
                        "train_end": train.index[-1].date().isoformat(),
                        "hold_start": hold.index[0].date().isoformat(),
                        "hold_end": hold.index[-1].date().isoformat(),
                        "portfolio": name,
                        "fund_count": len(holdings),
                        "turnover": turnover,
                        "transaction_cost": transaction_cost,
                        "selected_funds": " ".join(sorted(holdings)),
                        "holding_return": float((1 + frame[name].dropna()).prod() - 1) if name in frame else np.nan,
                    }
                )
                previous_weights[name] = weights
        start += step_days

    if not return_frames:
        return _empty_summary(), _period_frame(period_rows), pd.DataFrame()
    returns = pd.concat(return_frames).sort_index()
    returns = returns[~returns.index.duplicated(keep="first")]
    summary = _performance_summary(returns)
    if period_rows:
        turnover = pd.DataFrame(period_rows).groupby("portfolio")["turnover"].mean()
        summary["avg_turnover"] = turnover
    return summary, _period_frame(period_rows), returns


def build_rebalance_report(
    summary: pd.DataFrame,
    periods: pd.DataFrame,
    figure_path: Path,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
) -> str:
    constraints = normalize_portfolio_constraints(constraints)
    if summary.empty:
        return "# 组合再平衡回测\n\n当前数据长度不足，无法完成组合再平衡回测。"
    rows = [
        "| 组合 | 年化收益 | Sharpe | 年化波动 | 最大回撤 | 胜率 | 平均换手率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for portfolio, row in summary.iterrows():
        rows.append(
            "| {portfolio} | {ret:.2%} | {sharpe:.2f} | {vol:.2%} | {drawdown:.2%} | {win:.1%} | {turnover:.1%} |".format(
                portfolio=portfolio,
                ret=float(row["annual_return"]),
                sharpe=float(row["sharpe"]) if pd.notna(row["sharpe"]) else float("nan"),
                vol=float(row["annual_volatility"]),
                drawdown=float(row["max_drawdown"]),
                win=float(row["win_rate"]),
                turnover=float(row.get("avg_turnover", 0.0)),
            )
        )
    return f"""# 组合再平衡回测

## 定位

本报告把基金排名转化为可重复执行的组合回测：每个滚动窗口用历史数据重新排名，构建组合并持有到下一个窗口，记录收益、回撤和换手率。

## 结果汇总

{chr(10).join(rows)}

## 回测设置

- 有效再平衡窗口：{periods['hold_start'].nunique() if not periods.empty else 0}
- 再平衡间隔：{constraints.rebalance_days} 天
- 单期最大换手率：{constraints.max_turnover:.1%}
- 交易成本假设：{constraints.transaction_cost_bps:.1f} bps
- 累计收益图：`{figure_path}`

## 使用边界

当前回测未计入申赎费、赎回限制、税费和实际成交摩擦。它用于比较不同组合构建方法的历史表现，不构成未来收益承诺。
"""


def _weighted_return(returns: pd.DataFrame, weights: dict[str, float]) -> pd.Series:
    series = pd.Series(0.0, index=returns.index)
    total = 0.0
    for fund, weight in weights.items():
        if fund not in returns.columns:
            continue
        series = series.add(returns[fund].fillna(0.0) * weight, fill_value=0.0)
        total += weight
    if total <= 0:
        return pd.Series(dtype=float)
    return series / total


def _apply_transaction_cost(series: pd.Series, turnover: float, transaction_cost_bps: float) -> pd.Series:
    if series.empty or transaction_cost_bps <= 0:
        return series
    adjusted = series.copy()
    adjusted.iloc[0] = adjusted.iloc[0] - turnover * transaction_cost_bps / 10000.0
    return adjusted


def _performance_summary(returns: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for column in returns.columns:
        series = returns[column].dropna()
        if series.empty:
            continue
        cumulative = (1 + series).cumprod()
        annual_return = cumulative.iloc[-1] ** (252 / len(series)) - 1
        annual_volatility = series.std(ddof=1) * np.sqrt(252)
        rows.append(
            {
                "portfolio": column,
                "annual_return": float(annual_return),
                "annual_volatility": float(annual_volatility),
                "max_drawdown": float(max_drawdown(cumulative)),
                "sharpe": float(annual_return / annual_volatility) if annual_volatility > 0 else float("nan"),
                "win_rate": float((series > 0).mean()),
            }
        )
    if not rows:
        return _empty_summary()
    return pd.DataFrame(rows).set_index("portfolio").rename_axis("portfolio")


def _empty_summary() -> pd.DataFrame:
    return pd.DataFrame(columns=SUMMARY_COLUMNS).rename_axis("portfolio")


def _empty_periods() -> pd.DataFrame:
    return pd.DataFrame(columns=PERIOD_COLUMNS)


def _period_frame(rows: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=PERIOD_COLUMNS)


def _plot_cumulative(returns: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if returns.empty:
        empty_plot(path, "Not enough data for portfolio rebalance backtest")
        return
    cumulative = (1 + returns.fillna(0)).cumprod()
    fig, ax = figure_axes((10, 5.8))
    for index, column in enumerate(cumulative.columns):
        series = cumulative[column].dropna()
        color = PALETTE[index % len(PALETTE)]
        ax.plot(series.index, series, label=column, linewidth=2.1, color=color)
        if not series.empty:
            ax.scatter(series.index[-1], series.iloc[-1], s=30, color=color, edgecolor="white", linewidth=0.8, zorder=3)
            ax.annotate(f"{series.iloc[-1]:.2f}x", (series.index[-1], series.iloc[-1]), xytext=(6, 0), textcoords="offset points", va="center", fontsize=8, color=color)
    ax.axhline(1.0, color=GRID, linestyle="--", linewidth=1)
    polish_axes(
        ax,
        "组合再平衡累计收益",
        "日期",
        "单位净值增长倍数",
        grid_axis="y",
        subtitle="再平衡路径已纳入换手率与交易成本假设。",
    )
    ax.legend(fontsize=8, loc="upper left", ncols=2)
    finish_figure(fig, path)

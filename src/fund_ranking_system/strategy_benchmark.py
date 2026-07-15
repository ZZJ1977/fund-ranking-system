from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


def save_strategy_benchmark_outputs(
    reports_dir: str | Path,
) -> tuple[Path, Path]:
    reports_dir = Path(reports_dir)
    benchmark = build_strategy_benchmark(reports_dir)
    csv_path = reports_dir / "strategy_benchmark.csv"
    report_path = reports_dir / "strategy_benchmark.md"
    benchmark.to_csv(csv_path, index=False)
    report_path.write_text(build_strategy_benchmark_report(benchmark), encoding="utf-8")
    return csv_path, report_path


def build_strategy_benchmark(reports_dir: str | Path) -> pd.DataFrame:
    reports_dir = Path(reports_dir)
    frames = [
        _load_scope(reports_dir / "benchmark_comparison.csv", "静态基准对比", baseline="基金池等权基准"),
        _load_scope(reports_dir / "walk_forward_results.csv", "Walk-Forward", baseline="All Funds"),
        _load_scope(reports_dir / "adaptive_walk_forward_results.csv", "动态权重 Walk-Forward", baseline="All Funds"),
        _load_scope(reports_dir / "portfolio_rebalance_results.csv", "组合再平衡回测", baseline="All Funds"),
    ]
    rows = [row for frame in frames for row in frame]
    return pd.DataFrame(rows, columns=_columns())


def build_strategy_benchmark_report(benchmark: pd.DataFrame) -> str:
    if benchmark.empty:
        return "# 策略回测基准对比\n\n当前没有可汇总的策略回测结果。"

    ranked = benchmark.sort_values(["risk_adjusted_label", "sharpe"], ascending=[True, False])
    best = ranked.iloc[0]
    rows = [
        "| 模块 | 策略 | 基准 | 年化收益差 | Sharpe差 | 最大回撤差 | 结论 |",
        "|---|---|---|---:|---:|---:|---|",
    ]
    for row in benchmark.itertuples(index=False):
        rows.append(
            "| {scope} | {strategy} | {baseline} | {ret:+.2%} | {sharpe:+.2f} | {dd:+.2%} | {label} |".format(
                scope=row.scope,
                strategy=row.strategy,
                baseline=row.baseline_strategy,
                ret=float(row.excess_annual_return) if pd.notna(row.excess_annual_return) else 0.0,
                sharpe=float(row.excess_sharpe) if pd.notna(row.excess_sharpe) else 0.0,
                dd=float(row.drawdown_improvement) if pd.notna(row.drawdown_improvement) else 0.0,
                label=row.risk_adjusted_label,
            )
        )

    return f"""# 策略回测基准对比

## 定位

本报告把静态基准、Walk-Forward、动态权重验证和组合再平衡回测放在同一张表中，帮助判断当前策略是否真的优于简单基准。

## 最优风险调整策略

- 模块：{best['scope']}
- 策略：{best['strategy']}
- 对比基准：{best['baseline_strategy']}
- 年化收益差：{float(best['excess_annual_return']):+.2%}
- Sharpe 差：{float(best['excess_sharpe']) if pd.notna(best['excess_sharpe']) else float('nan'):+.2f}
- 最大回撤改善：{float(best['drawdown_improvement']):+.2%}

## 全部策略对比

{chr(10).join(rows)}

## 使用边界

策略回测用于比较模型选择、动态权重和组合约束是否优于基金池等权或 All Funds 基准。它仍是历史回测，不代表未来收益，也未完整覆盖申购赎回限制、税费和真实交易冲击。
"""


def _load_scope(path: Path, scope: str, baseline: str) -> list[dict[str, object]]:
    if not path.exists():
        return []
    frame = pd.read_csv(path)
    if frame.empty:
        return []
    if "portfolio" in frame.columns:
        strategy_col = "portfolio"
    elif "strategy" in frame.columns:
        strategy_col = "strategy"
    else:
        return []
    baseline_row = _baseline_row(frame, strategy_col, baseline)
    rows = []
    for row in frame.to_dict(orient="records"):
        strategy = str(row.get(strategy_col, ""))
        annual_return = _num(row.get("annual_return"))
        sharpe = _num(row.get("sharpe"))
        drawdown = _num(row.get("max_drawdown"))
        rows.append(
            {
                "scope": scope,
                "strategy": strategy,
                "baseline_strategy": str(baseline_row.get(strategy_col, "")) if baseline_row else "",
                "annual_return": annual_return,
                "annual_volatility": _num(row.get("annual_volatility")),
                "max_drawdown": drawdown,
                "sharpe": sharpe,
                "win_rate": _num(row.get("win_rate")),
                "excess_annual_return": annual_return - _num(baseline_row.get("annual_return")) if baseline_row else np.nan,
                "excess_sharpe": sharpe - _num(baseline_row.get("sharpe")) if baseline_row else np.nan,
                "drawdown_improvement": drawdown - _num(baseline_row.get("max_drawdown")) if baseline_row else np.nan,
                "risk_adjusted_label": _label(
                    annual_return - _num(baseline_row.get("annual_return")) if baseline_row else np.nan,
                    sharpe - _num(baseline_row.get("sharpe")) if baseline_row else np.nan,
                    drawdown - _num(baseline_row.get("max_drawdown")) if baseline_row else np.nan,
                ),
            }
        )
    return rows


def _baseline_row(frame: pd.DataFrame, strategy_col: str, baseline: str) -> dict[str, object] | None:
    exact = frame[frame[strategy_col].astype(str) == baseline]
    if not exact.empty:
        return exact.iloc[0].to_dict()
    all_funds = frame[frame[strategy_col].astype(str).str.contains("All Funds|基金池等权", regex=True, na=False)]
    if not all_funds.empty:
        return all_funds.iloc[0].to_dict()
    return frame.iloc[-1].to_dict() if not frame.empty else None


def _label(excess_return: float, excess_sharpe: float, drawdown_improvement: float) -> str:
    if pd.isna(excess_return) or pd.isna(excess_sharpe):
        return "缺少基准"
    if excess_return > 0 and excess_sharpe > 0 and drawdown_improvement >= 0:
        return "优于基准"
    if excess_return > 0 and excess_sharpe > 0:
        return "收益/Sharpe改善"
    if excess_return < 0 and excess_sharpe < 0:
        return "弱于基准"
    return "结果分化"


def _num(value: object) -> float:
    return float(value) if value is not None and pd.notna(value) else float("nan")


def _columns() -> list[str]:
    return [
        "scope",
        "strategy",
        "baseline_strategy",
        "annual_return",
        "annual_volatility",
        "max_drawdown",
        "sharpe",
        "win_rate",
        "excess_annual_return",
        "excess_sharpe",
        "drawdown_improvement",
        "risk_adjusted_label",
    ]

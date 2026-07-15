from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .metadata import display_fund
from .metrics import daily_returns, max_drawdown


def save_benchmark_outputs(
    nav: pd.DataFrame,
    base_scored: pd.DataFrame,
    adaptive_scored: pd.DataFrame | None,
    ml_scored: pd.DataFrame | None,
    reports_dir: str | Path,
    profile: str,
    top_n: int,
    external_benchmark: pd.DataFrame | None = None,
) -> tuple[Path, Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)

    benchmark = build_benchmark_comparison(
        nav,
        base_scored,
        adaptive_scored,
        ml_scored,
        top_n=top_n,
        external_benchmark=external_benchmark,
    )
    peers = build_peer_comparison(base_scored, adaptive_scored, ml_scored)

    benchmark_path = reports_dir / "benchmark_comparison.csv"
    peer_path = reports_dir / f"peer_comparison_{profile}.csv"
    report_path = reports_dir / "benchmark_comparison.md"
    benchmark.to_csv(benchmark_path, index=False)
    peers.to_csv(peer_path, index=False)
    report_path.write_text(
        build_benchmark_report(benchmark, peers, profile=profile, top_n=top_n),
        encoding="utf-8",
    )
    return benchmark_path, peer_path, report_path


def build_benchmark_comparison(
    nav: pd.DataFrame,
    base_scored: pd.DataFrame,
    adaptive_scored: pd.DataFrame | None,
    ml_scored: pd.DataFrame | None,
    top_n: int,
    external_benchmark: pd.DataFrame | None = None,
) -> pd.DataFrame:
    returns = daily_returns(nav.sort_index().dropna(how="all").ffill()).dropna(how="all")
    if returns.empty:
        return pd.DataFrame(
            columns=[
                "portfolio",
                "fund_count",
                "annual_return",
                "annual_volatility",
                "max_drawdown",
                "sharpe",
                "win_rate",
                "description",
            ]
        )

    portfolios: list[tuple[str, list[str], str]] = [
        ("原始TopN等权", _top_funds(base_scored, "rank", top_n), "固定画像权重选出的 Top N 基金等权组合"),
        ("基金池等权基准", list(returns.columns), "本次输入基金池的全体基金等权组合"),
    ]
    if adaptive_scored is not None and not adaptive_scored.empty:
        portfolios.insert(
            1,
            ("动态权重TopN等权", _top_funds(adaptive_scored, "dynamic_rank", top_n), "基金级动态权重选出的 Top N 基金等权组合"),
        )
    if ml_scored is not None and not ml_scored.empty:
        portfolios.insert(
            2,
            ("ML TopN等权", _top_funds(ml_scored, "ml_rank", top_n), "ML 融合权重选出的 Top N 基金等权组合"),
        )

    rows: list[dict[str, object]] = []
    for name, funds, description in portfolios:
        series = _equal_weight_return(returns, funds)
        rows.append({"portfolio": name, "fund_count": len([fund for fund in funds if fund in returns.columns]), **_summary(series), "description": description})
    if external_benchmark is not None and not external_benchmark.empty:
        rows.extend(_external_benchmark_rows(external_benchmark))
    return pd.DataFrame(rows)


def build_peer_comparison(
    base_scored: pd.DataFrame,
    adaptive_scored: pd.DataFrame | None,
    ml_scored: pd.DataFrame | None,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    total = max(len(base_scored), 1)
    adaptive_lookup = adaptive_scored if adaptive_scored is not None else pd.DataFrame()
    ml_lookup = ml_scored if ml_scored is not None else pd.DataFrame()

    for fund, row in base_scored.iterrows():
        fund_type = row.get("fund_type", "未分类")
        type_count = int((base_scored.get("fund_type", pd.Series(dtype=object)) == fund_type).sum()) if "fund_type" in base_scored.columns else total
        rank = int(row.get("rank", 0))
        type_rank = int(row.get("type_rank", rank)) if pd.notna(row.get("type_rank", rank)) else rank
        adaptive_rank = _lookup_number(adaptive_lookup, fund, "dynamic_rank")
        ml_rank = _lookup_number(ml_lookup, fund, "ml_rank")
        rows.append(
            {
                "fund": fund,
                "fund_name": row.get("fund_name", fund),
                "fund_type": fund_type,
                "pool_rank": rank,
                "pool_percentile": _rank_percentile(rank, total),
                "type_rank": type_rank,
                "type_count": type_count,
                "type_percentile": _rank_percentile(type_rank, max(type_count, 1)),
                "dynamic_rank": adaptive_rank,
                "ml_rank": ml_rank,
                "composite_score": float(row.get("composite_score", 0.0)),
                "dynamic_score": _lookup_number(adaptive_lookup, fund, "dynamic_score"),
                "ml_score": _lookup_number(ml_lookup, fund, "ml_score"),
                "risk_level": row.get("risk_level", ""),
                "decision_label": row.get("decision_label", ""),
            }
        )
    return pd.DataFrame(rows).sort_values(["pool_rank", "fund"])


def build_benchmark_report(
    benchmark: pd.DataFrame,
    peers: pd.DataFrame,
    profile: str,
    top_n: int,
) -> str:
    if benchmark.empty:
        benchmark_rows = ["| 组合 | 基金数 | 年化收益 | 年化波动 | 最大回撤 | Sharpe | 胜率 |", "|---|---:|---:|---:|---:|---:|---:|"]
    else:
        benchmark_rows = [
            "| 组合 | 基金数 | 年化收益 | 年化波动 | 最大回撤 | Sharpe | 胜率 |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
        for row in benchmark.itertuples(index=False):
            benchmark_rows.append(
                "| {portfolio} | {count} | {ret:.2%} | {vol:.2%} | {drawdown:.2%} | {sharpe:.2f} | {win:.1%} |".format(
                    portfolio=row.portfolio,
                    count=int(row.fund_count),
                    ret=float(row.annual_return),
                    vol=float(row.annual_volatility),
                    drawdown=float(row.max_drawdown),
                    sharpe=float(row.sharpe) if pd.notna(row.sharpe) else float("nan"),
                    win=float(row.win_rate),
                )
            )

    peer_rows = [
        "| 基金 | 基金池排名 | 基金池百分位 | 同类排名 | 同类百分位 | 动态排名 | ML排名 | 风险等级 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in peers.head(top_n).itertuples(index=False):
        peer_rows.append(
            "| {fund} | {pool_rank} | {pool_pct:.1%} | {type_rank}/{type_count} | {type_pct:.1%} | {dynamic_rank} | {ml_rank} | {risk} |".format(
                fund=display_fund(str(row.fund), pd.Series({"fund_name": row.fund_name})),
                pool_rank=int(row.pool_rank),
                pool_pct=float(row.pool_percentile),
                type_rank=int(row.type_rank),
                type_count=int(row.type_count),
                type_pct=float(row.type_percentile),
                dynamic_rank=_format_optional(row.dynamic_rank),
                ml_rank=_format_optional(row.ml_rank),
                risk=row.risk_level,
            )
        )

    return f"""# 基准与同类对比报告

## 定位

本报告用于把 `{profile}` 排名结果放到更实用的参照系里：一方面比较原始 Top N、动态权重 Top N、ML Top N 与基金池等权基准；另一方面给出每只基金在本次基金池和同类基金中的相对位置。

## 组合基准对比

{chr(10).join(benchmark_rows)}

## Top {top_n} 同类/基金池位置

{chr(10).join(peer_rows)}

## 使用边界

默认基准为本次输入基金池的等权组合。如果运行时提供外部基准净值 CSV，本报告也会纳入外部基准行。外部基准适合用于比较沪深300、中证偏股基金指数、中债综合指数等市场参照。
"""


def _top_funds(scored: pd.DataFrame, rank_column: str, top_n: int) -> list[str]:
    if scored.empty:
        return []
    if rank_column in scored.columns:
        ordered = scored.sort_values(rank_column, ascending=True)
    else:
        ordered = scored
    return [str(fund) for fund in ordered.head(min(top_n, len(ordered))).index]


def _equal_weight_return(returns: pd.DataFrame, funds: list[str]) -> pd.Series:
    columns = {str(column): column for column in returns.columns}
    selected = [columns[str(fund)] for fund in funds if str(fund) in columns]
    if not selected:
        return pd.Series(dtype=float)
    return returns[selected].mean(axis=1)


def _summary(series: pd.Series) -> dict[str, float]:
    series = series.dropna()
    if series.empty:
        return {
            "annual_return": 0.0,
            "annual_volatility": 0.0,
            "max_drawdown": 0.0,
            "sharpe": float("nan"),
            "win_rate": 0.0,
        }
    cumulative = (1 + series).cumprod()
    annual_return = cumulative.iloc[-1] ** (252 / len(series)) - 1
    annual_volatility = series.std(ddof=1) * (252 ** 0.5)
    return {
        "annual_return": float(annual_return),
        "annual_volatility": float(annual_volatility),
        "max_drawdown": float(max_drawdown(cumulative)),
        "sharpe": float(annual_return / annual_volatility) if annual_volatility > 0 else float("nan"),
        "win_rate": float((series > 0).mean()),
    }


def _external_benchmark_rows(benchmark_nav: pd.DataFrame) -> list[dict[str, object]]:
    frame = benchmark_nav.sort_index().dropna(how="all").ffill()
    returns = frame.pct_change().replace([np.inf, -np.inf], np.nan).dropna(how="all")
    rows = []
    for column in returns.columns:
        series = returns[column].dropna()
        rows.append(
            {
                "portfolio": f"外部基准：{column}",
                "fund_count": 1,
                **_summary(series),
                "description": "用户提供的外部基准净值序列",
            }
        )
    return rows


def _lookup_number(frame: pd.DataFrame, fund: object, column: str) -> float:
    if frame.empty or column not in frame.columns or fund not in frame.index:
        return float("nan")
    value = frame.loc[fund, column]
    return float(value) if pd.notna(value) else float("nan")


def _rank_percentile(rank: int, count: int) -> float:
    if count <= 1:
        return 1.0
    return 1.0 - (rank - 1) / count


def _format_optional(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(int(float(value)))

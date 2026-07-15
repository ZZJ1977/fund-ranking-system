from __future__ import annotations

from dataclasses import asdict, dataclass
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .chart_style import SCORE_CMAP, annotate_barh, empty_plot, figure_axes, finish_figure, format_percent_axis, polish_axes
from .metadata import display_fund
from .metrics import daily_returns, max_drawdown


PORTFOLIO_OBJECTIVES = {
    "balanced": "平衡组合",
    "stable": "稳健组合",
    "growth": "进取组合",
    "defensive": "防守组合",
}


@dataclass(frozen=True)
class PortfolioConstraints:
    objective: str = "balanced"
    min_funds: int = 3
    max_funds: int = 8
    max_position_weight: float = 0.35
    max_type_weight: float = 0.65
    max_pair_correlation: float = 0.9
    max_drawdown_floor: float = -0.45
    min_sharpe: float = 0.0
    rebalance_days: int = 63
    max_turnover: float = 0.6
    transaction_cost_bps: float = 0.0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def normalize_portfolio_constraints(
    constraints: PortfolioConstraints | dict[str, object] | None = None,
    **overrides: object,
) -> PortfolioConstraints:
    data: dict[str, object] = {}
    if isinstance(constraints, PortfolioConstraints):
        data.update(constraints.to_dict())
    elif isinstance(constraints, dict):
        data.update(constraints)
    data.update({key: value for key, value in overrides.items() if value is not None})

    objective = str(data.get("objective", "balanced"))
    if objective not in PORTFOLIO_OBJECTIVES:
        objective = "balanced"
    min_funds = _bounded_int(data.get("min_funds", 3), 1, 50)
    max_funds = _bounded_int(data.get("max_funds", 8), min_funds, 80)
    return PortfolioConstraints(
        objective=objective,
        min_funds=min_funds,
        max_funds=max_funds,
        max_position_weight=_bounded_float(data.get("max_position_weight", 0.35), 0.05, 1.0),
        max_type_weight=_bounded_float(data.get("max_type_weight", 0.65), 0.1, 1.0),
        max_pair_correlation=_bounded_float(data.get("max_pair_correlation", 0.9), 0.0, 1.0),
        max_drawdown_floor=_bounded_float(data.get("max_drawdown_floor", -0.45), -0.95, 0.0),
        min_sharpe=_bounded_float(data.get("min_sharpe", 0.0), -5.0, 10.0),
        rebalance_days=_bounded_int(data.get("rebalance_days", 63), 21, 252),
        max_turnover=_bounded_float(data.get("max_turnover", 0.6), 0.0, 1.0),
        transaction_cost_bps=_bounded_float(data.get("transaction_cost_bps", 0.0), 0.0, 500.0),
    )


def save_portfolio_outputs(
    nav: pd.DataFrame,
    base_scored: pd.DataFrame,
    adaptive_scored: pd.DataFrame,
    ml_scored: pd.DataFrame,
    reports_dir: str | Path,
    profile: str,
    top_n: int,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
) -> tuple[Path, Path, Path, Path, Path, Path, Path, Path]:
    constraints = normalize_portfolio_constraints(constraints)
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    weights = build_portfolios(nav, base_scored, adaptive_scored, ml_scored, top_n=top_n, constraints=constraints)
    summary = portfolio_summary(nav, weights)
    weights_path = reports_dir / f"portfolio_weights_{profile}.csv"
    summary_path = reports_dir / "portfolio_summary.csv"
    report_path = reports_dir / "portfolio_construction.md"
    constraints_path = reports_dir / "portfolio_constraints.csv"
    figure_path = reports_dir / "portfolio_optimized_weights.png"
    recommendation_path = reports_dir / "portfolio_recommendation.md"
    recommendation_csv_path = reports_dir / "portfolio_recommendations.csv"
    risk_controls_path = reports_dir / "portfolio_risk_controls.csv"
    recommendations = build_portfolio_recommendations(nav, adaptive_scored, weights, constraints)
    risk_controls = build_portfolio_risk_controls(nav, weights, constraints)
    weights.to_csv(weights_path, index=False)
    summary.to_csv(summary_path, index=False)
    constraints_to_frame(constraints).to_csv(constraints_path, index=False)
    recommendations.to_csv(recommendation_csv_path, index=False)
    risk_controls.to_csv(risk_controls_path, index=False)
    plot_optimized_portfolio_weights(weights, figure_path)
    report_path.write_text(build_portfolio_report(weights, summary, top_n=top_n, constraints=constraints), encoding="utf-8")
    recommendation_path.write_text(
        build_portfolio_recommendation_report(recommendations, risk_controls, constraints),
        encoding="utf-8",
    )
    return (
        weights_path,
        summary_path,
        report_path,
        constraints_path,
        figure_path,
        recommendation_path,
        recommendation_csv_path,
        risk_controls_path,
    )


def build_portfolios(
    nav: pd.DataFrame,
    base_scored: pd.DataFrame,
    adaptive_scored: pd.DataFrame,
    ml_scored: pd.DataFrame,
    top_n: int,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
) -> pd.DataFrame:
    constraints = normalize_portfolio_constraints(constraints)
    returns = daily_returns(nav.sort_index().dropna(how="all").ffill()).dropna(how="all")
    rows: list[dict[str, object]] = []
    candidates = {
        "原始TopN等权": _top_funds(base_scored, "rank", top_n),
        "动态权重TopN等权": _top_funds(adaptive_scored, "dynamic_rank", top_n),
        "ML TopN等权": _top_funds(ml_scored, "ml_rank", top_n),
        "风险平价组合": _top_funds(adaptive_scored, "dynamic_rank", top_n),
        "回撤约束组合": _drawdown_constrained_funds(base_scored, top_n),
    }
    for portfolio, funds in candidates.items():
        selected = [fund for fund in funds if fund in returns.columns]
        if not selected:
            continue
        if portfolio == "风险平价组合":
            weights = _risk_parity_weights(returns[selected])
        else:
            equal = 1.0 / len(selected)
            weights = {fund: equal for fund in selected}
        for fund, weight in weights.items():
            meta_row = _lookup_row(base_scored, fund)
            rows.append(
                {
                    "portfolio": portfolio,
                    "fund": fund,
                    "fund_name": meta_row.get("fund_name", fund),
                    "fund_type": meta_row.get("fund_type", "未分类"),
                    "weight": float(weight),
                    "risk_level": meta_row.get("risk_level", ""),
                    "decision_label": meta_row.get("decision_label", ""),
                }
            )
    optimized = optimize_constrained_portfolio(nav, adaptive_scored, constraints)
    rows.extend(optimized.to_dict(orient="records"))
    columns = [
        "portfolio",
        "fund",
        "fund_name",
        "fund_type",
        "weight",
        "risk_level",
        "decision_label",
        "selected_by",
        "constraint_status",
    ]
    return pd.DataFrame(rows, columns=columns)


def portfolio_summary(nav: pd.DataFrame, weights: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "portfolio",
        "fund_count",
        "annual_return",
        "annual_volatility",
        "max_drawdown",
        "sharpe",
        "win_rate",
    ]
    if weights.empty or "portfolio" not in weights.columns:
        return pd.DataFrame(columns=columns)
    returns = daily_returns(nav.sort_index().dropna(how="all").ffill()).dropna(how="all")
    rows: list[dict[str, object]] = []
    for portfolio, group in weights.groupby("portfolio"):
        series = _portfolio_return(returns, group)
        rows.append({"portfolio": portfolio, "fund_count": group["fund"].nunique(), **_summary(series)})
    return pd.DataFrame(rows, columns=columns)


def optimize_constrained_portfolio(
    nav: pd.DataFrame,
    scored: pd.DataFrame,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
    previous_weights: dict[str, float] | None = None,
    portfolio_name: str = "约束优化组合",
) -> pd.DataFrame:
    constraints = normalize_portfolio_constraints(constraints)
    columns = [
        "portfolio",
        "fund",
        "fund_name",
        "fund_type",
        "weight",
        "risk_level",
        "decision_label",
        "selected_by",
        "constraint_status",
    ]
    if scored is None or scored.empty or nav.empty:
        return pd.DataFrame(columns=columns)
    scored = scored.copy()
    scored.index = scored.index.astype(str)

    returns = daily_returns(nav.sort_index().dropna(how="all").ffill()).dropna(how="all")
    available = [fund for fund in scored.index.astype(str) if fund in returns.columns]
    if not available:
        return pd.DataFrame(columns=columns)

    frame = scored.loc[available].copy()
    if "fund_type" not in frame.columns:
        frame["fund_type"] = "未分类"
    frame["_objective_score"] = _objective_signal(frame, constraints.objective)
    filtered = _apply_metric_constraints(frame, constraints)
    relaxed = False
    if len(filtered) < constraints.min_funds:
        filtered = frame
        relaxed = True

    desired_count = min(constraints.max_funds, len(filtered))
    min_count_for_cap = math.ceil(1.0 / constraints.max_position_weight) if constraints.max_position_weight > 0 else desired_count
    desired_count = max(min(desired_count, len(filtered)), min(constraints.min_funds, len(filtered)))
    desired_count = min(max(desired_count, min_count_for_cap), len(filtered), constraints.max_funds)
    if desired_count <= 0:
        return pd.DataFrame(columns=columns)

    selected, selection_status = _select_diversified_candidates(filtered, returns, constraints, desired_count)
    raw = selected["_objective_score"].clip(lower=0.0)
    if float(raw.sum()) <= 0:
        raw = pd.Series(1.0, index=selected.index)
    weights = _cap_weight_series(raw / raw.sum(), constraints.max_position_weight)
    weights = _cap_group_weight_series(weights, selected["fund_type"].fillna("未分类").astype(str), constraints.max_type_weight)
    weights = _cap_weight_series(weights, constraints.max_position_weight)
    weights = _apply_turnover_limit(weights.to_dict(), previous_weights or {}, constraints.max_turnover)

    status_parts = []
    status_parts.extend(selection_status)
    if relaxed:
        status_parts.append("筛选条件已放宽")
    if len(selected) < constraints.min_funds:
        status_parts.append("候选基金少于最低持仓数")
    effective_cap = max(float(weights.max()) if not weights.empty else 0.0, 0.0)
    if effective_cap > constraints.max_position_weight + 1e-6:
        status_parts.append("单只上限因候选数量不足而放宽")
    type_weights = selected.assign(_weight=weights.reindex(selected.index).fillna(0.0)).groupby("fund_type")["_weight"].sum()
    if not type_weights.empty and float(type_weights.max()) > constraints.max_type_weight + 1e-6:
        status_parts.append("同类占比上限因候选不足而放宽")
    status = "；".join(status_parts) if status_parts else "满足约束"

    rows: list[dict[str, object]] = []
    for fund, weight in weights.items():
        row = selected.loc[fund] if fund in selected.index else frame.loc[fund]
        rows.append(
            {
                "portfolio": portfolio_name,
                "fund": str(fund),
                "fund_name": row.get("fund_name", fund),
                "fund_type": row.get("fund_type", "未分类"),
                "weight": float(weight),
                "risk_level": row.get("risk_level", ""),
                "decision_label": row.get("decision_label", ""),
                "selected_by": PORTFOLIO_OBJECTIVES.get(constraints.objective, constraints.objective),
                "constraint_status": status,
            }
        )
    return pd.DataFrame(rows, columns=columns)


def constraints_to_frame(constraints: PortfolioConstraints | dict[str, object] | None = None) -> pd.DataFrame:
    constraints = normalize_portfolio_constraints(constraints)
    rows = [
        ("组合目标", constraints.objective, PORTFOLIO_OBJECTIVES.get(constraints.objective, constraints.objective)),
        ("最少持仓数", constraints.min_funds, ""),
        ("最多持仓数", constraints.max_funds, ""),
        ("单只基金最大权重", constraints.max_position_weight, f"{constraints.max_position_weight:.1%}"),
        ("同类型最大占比", constraints.max_type_weight, f"{constraints.max_type_weight:.1%}"),
        ("基金间最高相关阈值", constraints.max_pair_correlation, f"{constraints.max_pair_correlation:.2f}"),
        ("基金最大回撤下限", constraints.max_drawdown_floor, f"{constraints.max_drawdown_floor:.1%}"),
        ("最低 Sharpe", constraints.min_sharpe, f"{constraints.min_sharpe:.2f}"),
        ("再平衡间隔天数", constraints.rebalance_days, ""),
        ("单期最大换手率", constraints.max_turnover, f"{constraints.max_turnover:.1%}"),
        ("交易成本 bps", constraints.transaction_cost_bps, f"{constraints.transaction_cost_bps:.1f} bps"),
    ]
    return pd.DataFrame(rows, columns=["constraint", "value", "display_value"])


def plot_optimized_portfolio_weights(weights: pd.DataFrame, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    optimized = weights[weights["portfolio"] == "约束优化组合"].copy() if "portfolio" in weights.columns else pd.DataFrame()
    if optimized.empty:
        return empty_plot(path, "No constrained portfolio weights")

    optimized = optimized.sort_values("weight", ascending=True)
    labels = [
        display_fund(str(row.fund), pd.Series({"fund_name": row.fund_name if hasattr(row, "fund_name") else ""}))
        for row in optimized.itertuples(index=False)
    ]
    fig, ax = figure_axes((9.5, 5.6))
    colors = SCORE_CMAP(optimized["weight"].rank(pct=True).to_numpy())
    ax.barh(labels, optimized["weight"], color=colors, edgecolor="white", linewidth=1.1, height=0.72)
    annotate_barh(ax, optimized["weight"].astype(float), fmt="{:.1%}")
    ax.set_xlim(0, max(float(optimized["weight"].max()) * 1.22, 0.1))
    polish_axes(
        ax,
        "约束优化组合权重",
        "组合权重",
        "",
        grid_axis="x",
        subtitle="权重已综合组合目标、单只上限、回撤、换手率与分散化约束。",
    )
    format_percent_axis(ax, "x")
    finish_figure(fig, path)
    return path


def build_portfolio_recommendations(
    nav: pd.DataFrame,
    scored: pd.DataFrame,
    weights: pd.DataFrame,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
) -> pd.DataFrame:
    constraints = normalize_portfolio_constraints(constraints)
    optimized = _optimized_weights(weights)
    columns = [
        "portfolio",
        "fund",
        "fund_name",
        "fund_type",
        "weight",
        "objective",
        "selection_reason",
        "weight_reason",
        "risk_note",
        "diversification_note",
    ]
    if optimized.empty:
        return pd.DataFrame(columns=columns)
    scored = scored.copy() if scored is not None else pd.DataFrame()
    scored.index = scored.index.astype(str) if not scored.empty else scored.index
    returns = daily_returns(nav.sort_index().dropna(how="all").ffill()).dropna(how="all")
    corr = returns[[fund for fund in optimized["fund"].astype(str) if fund in returns.columns]].corr().abs() if not returns.empty else pd.DataFrame()
    type_weights = optimized.groupby("fund_type")["weight"].sum().to_dict()

    rows: list[dict[str, object]] = []
    for row in optimized.sort_values("weight", ascending=False).itertuples(index=False):
        fund = str(row.fund)
        metric_row = scored.loc[fund] if fund in scored.index else pd.Series(dtype=object)
        max_peer_corr = _max_peer_correlation(corr, fund)
        rows.append(
            {
                "portfolio": row.portfolio,
                "fund": fund,
                "fund_name": row.fund_name,
                "fund_type": row.fund_type,
                "weight": float(row.weight),
                "objective": PORTFOLIO_OBJECTIVES.get(constraints.objective, constraints.objective),
                "selection_reason": _selection_reason(metric_row, constraints),
                "weight_reason": _weight_reason(float(row.weight), constraints),
                "risk_note": _risk_note(metric_row, constraints),
                "diversification_note": _diversification_note(
                    str(row.fund_type),
                    float(type_weights.get(row.fund_type, 0.0)),
                    max_peer_corr,
                    constraints,
                ),
            }
        )
    return pd.DataFrame(rows, columns=columns)


def build_portfolio_risk_controls(
    nav: pd.DataFrame,
    weights: pd.DataFrame,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
) -> pd.DataFrame:
    constraints = normalize_portfolio_constraints(constraints)
    optimized = _optimized_weights(weights)
    columns = ["control_type", "item", "value", "limit", "status", "note"]
    if optimized.empty:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    for fund_type, weight in optimized.groupby("fund_type")["weight"].sum().sort_values(ascending=False).items():
        rows.append(
            {
                "control_type": "type_exposure",
                "item": fund_type,
                "value": float(weight),
                "limit": constraints.max_type_weight,
                "status": "pass" if float(weight) <= constraints.max_type_weight + 1e-9 else "warn",
                "note": f"{fund_type} 占比 {float(weight):.1%}",
            }
        )

    max_position = float(optimized["weight"].max()) if not optimized.empty else 0.0
    rows.append(
        {
            "control_type": "position_cap",
            "item": "single_fund_max",
            "value": max_position,
            "limit": constraints.max_position_weight,
            "status": "pass" if max_position <= constraints.max_position_weight + 1e-9 else "warn",
            "note": f"最大单只权重 {max_position:.1%}",
        }
    )

    returns = daily_returns(nav.sort_index().dropna(how="all").ffill()).dropna(how="all")
    selected = [fund for fund in optimized["fund"].astype(str) if fund in returns.columns]
    corr_rows = _correlation_control_rows(returns[selected] if selected else pd.DataFrame(), constraints)
    rows.extend(corr_rows)
    return pd.DataFrame(rows, columns=columns)


def build_portfolio_recommendation_report(
    recommendations: pd.DataFrame,
    risk_controls: pd.DataFrame,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
) -> str:
    constraints = normalize_portfolio_constraints(constraints)
    if recommendations.empty:
        return "# 组合建议说明书\n\n当前没有可解释的约束优化组合。"

    recommendation_rows = [
        "| 基金 | 权重 | 入选原因 | 权重说明 | 风险提示 | 分散化说明 |",
        "|---|---:|---|---|---|---|",
    ]
    for row in recommendations.itertuples(index=False):
        recommendation_rows.append(
            "| {fund} | {weight:.1%} | {selection} | {weight_reason} | {risk_note} | {diversification} |".format(
                fund=display_fund(str(row.fund), pd.Series({"fund_name": row.fund_name})),
                weight=float(row.weight),
                selection=row.selection_reason,
                weight_reason=row.weight_reason,
                risk_note=row.risk_note,
                diversification=row.diversification_note,
            )
        )

    control_rows = [
        "| 控制项 | 对象 | 当前值 | 阈值 | 状态 | 说明 |",
        "|---|---|---:|---:|---|---|",
    ]
    for row in risk_controls.itertuples(index=False):
        control_rows.append(
            "| {control} | {item} | {value} | {limit} | {status} | {note} |".format(
                control=row.control_type,
                item=row.item,
                value=_format_control_value(row.value),
                limit=_format_control_value(row.limit),
                status=row.status,
                note=row.note,
            )
        )

    return f"""# 组合建议说明书

## 定位

本报告解释约束优化组合为什么选择这些基金、为什么给出当前权重，以及组合在同类集中度和基金间相关性上的控制情况。

## 当前约束

- 组合目标：{PORTFOLIO_OBJECTIVES.get(constraints.objective, constraints.objective)}
- 持仓数量：{constraints.min_funds} - {constraints.max_funds} 只
- 单只基金最大权重：{constraints.max_position_weight:.1%}
- 同类型基金最大占比：{constraints.max_type_weight:.1%}
- 基金间最高相关阈值：{constraints.max_pair_correlation:.2f}
- 基金最大回撤下限：{constraints.max_drawdown_floor:.1%}
- 最低 Sharpe：{constraints.min_sharpe:.2f}

## 持仓建议解释

{chr(10).join(recommendation_rows)}

## 集中度与相关性控制

{chr(10).join(control_rows)}

## 使用边界

建议说明书用于解释历史数据下的组合构建逻辑，不构成个性化投资建议。相关性和集中度会随市场环境变化，需要定期复核。
"""


def build_portfolio_report(
    weights: pd.DataFrame,
    summary: pd.DataFrame,
    top_n: int,
    constraints: PortfolioConstraints | dict[str, object] | None = None,
) -> str:
    constraints = normalize_portfolio_constraints(constraints)
    if weights.empty:
        return "# 组合构建报告\n\n当前数据不足，无法构建组合。"

    summary_rows = [
        "| 组合 | 基金数 | 年化收益 | 年化波动 | 最大回撤 | Sharpe | 胜率 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.itertuples(index=False):
        summary_rows.append(
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

    weight_rows = [
        "| 组合 | 基金 | 权重 | 风险等级 | 标签 |",
        "|---|---|---:|---|---|",
    ]
    for row in weights.sort_values(["portfolio", "weight"], ascending=[True, False]).itertuples(index=False):
        weight_rows.append(
            "| {portfolio} | {fund} | {weight:.1%} | {risk} | {label} |".format(
                portfolio=row.portfolio,
                fund=display_fund(str(row.fund), pd.Series({"fund_name": row.fund_name})),
                weight=float(row.weight),
                risk=row.risk_level,
                label=row.decision_label,
            )
        )

    return f"""# 组合构建报告

## 定位

本报告把基金筛选结果进一步转化为可观察组合。当前版本默认生成 Top {top_n} 等权组合、动态权重 Top {top_n} 组合、ML Top {top_n} 组合、风险平价组合和回撤约束组合，便于从“选基金”过渡到“组合观察池”。

## 组合表现摘要

{chr(10).join(summary_rows)}

## 用户组合约束

- 组合目标：{PORTFOLIO_OBJECTIVES.get(constraints.objective, constraints.objective)}
- 持仓数量：{constraints.min_funds} - {constraints.max_funds} 只
- 单只基金最大权重：{constraints.max_position_weight:.1%}
- 同类型基金最大占比：{constraints.max_type_weight:.1%}
- 基金间最高相关阈值：{constraints.max_pair_correlation:.2f}
- 基金最大回撤下限：{constraints.max_drawdown_floor:.1%}
- 最低 Sharpe：{constraints.min_sharpe:.2f}
- 再平衡间隔：{constraints.rebalance_days} 天
- 单期最大换手率：{constraints.max_turnover:.1%}
- 交易成本假设：{constraints.transaction_cost_bps:.1f} bps

## 组合持仓权重

{chr(10).join(weight_rows)}

## 使用边界

组合构建结果仅用于历史研究和观察池管理，不构成个性化资产配置建议。真实投资还需要考虑申赎费率、持有期、税务、流动性、个人风险承受能力和合规要求。
"""


def _select_diversified_candidates(
    frame: pd.DataFrame,
    returns: pd.DataFrame,
    constraints: PortfolioConstraints,
    desired_count: int,
) -> tuple[pd.DataFrame, list[str]]:
    ordered = frame.sort_values("_objective_score", ascending=False)
    selected: list[str] = []
    skipped_by_corr: list[str] = []
    skipped_by_type: list[str] = []
    available_returns = returns[[fund for fund in ordered.index.astype(str) if fund in returns.columns]]
    corr = available_returns.corr().abs() if not available_returns.empty else pd.DataFrame()
    max_type_count = max(1, math.ceil(desired_count * constraints.max_type_weight))

    for fund, row in ordered.iterrows():
        fund = str(fund)
        if len(selected) >= desired_count:
            break
        fund_type = str(row.get("fund_type", "未分类"))
        current_type_count = sum(str(ordered.loc[item].get("fund_type", "未分类")) == fund_type for item in selected)
        if current_type_count >= max_type_count and len(ordered) - len(selected) > desired_count - len(selected):
            skipped_by_type.append(fund)
            continue
        if selected and not corr.empty and fund in corr.index:
            max_corr = float(corr.loc[fund, [item for item in selected if item in corr.columns]].max())
            if pd.notna(max_corr) and max_corr > constraints.max_pair_correlation:
                skipped_by_corr.append(fund)
                continue
        selected.append(fund)

    if len(selected) < min(constraints.min_funds, len(ordered)):
        for fund in ordered.index.astype(str):
            if fund not in selected:
                selected.append(fund)
            if len(selected) >= min(desired_count, len(ordered)):
                break

    status: list[str] = []
    if skipped_by_corr and len(selected) < desired_count:
        status.append("相关性限制已放宽")
    if skipped_by_type and len(selected) < desired_count:
        status.append("同类集中度限制已放宽")
    return ordered.loc[selected], status


def _top_funds(scored: pd.DataFrame, rank_column: str, top_n: int) -> list[str]:
    if scored is None or scored.empty:
        return []
    ordered = scored.sort_values(rank_column, ascending=True) if rank_column in scored.columns else scored
    return [str(fund) for fund in ordered.head(min(top_n, len(ordered))).index]


def _apply_metric_constraints(scored: pd.DataFrame, constraints: PortfolioConstraints) -> pd.DataFrame:
    filtered = scored.copy()
    if "max_drawdown" in filtered.columns:
        filtered = filtered[pd.to_numeric(filtered["max_drawdown"], errors="coerce") >= constraints.max_drawdown_floor]
    if "sharpe" in filtered.columns:
        filtered = filtered[pd.to_numeric(filtered["sharpe"], errors="coerce") >= constraints.min_sharpe]
    return filtered


def _objective_signal(scored: pd.DataFrame, objective: str) -> pd.Series:
    annual_return = _scaled_column(scored, "annual_return", higher_is_better=True)
    sharpe = _scaled_column(scored, "sharpe", higher_is_better=True)
    drawdown = _scaled_column(scored, "max_drawdown", higher_is_better=True)
    calmar = _scaled_column(scored, "calmar", higher_is_better=True)
    volatility = _scaled_column(scored, "annual_volatility", higher_is_better=False)
    stability = _scaled_column(scored, "rolling_positive_ratio", higher_is_better=True)
    dynamic_column = "dynamic_score" if "dynamic_score" in scored.columns else "composite_score"
    dynamic = _scaled_column(scored, dynamic_column, higher_is_better=True)

    if objective == "stable":
        signal = 0.35 * volatility + 0.25 * drawdown + 0.20 * sharpe + 0.10 * stability + 0.10 * dynamic
    elif objective == "growth":
        signal = 0.38 * annual_return + 0.22 * dynamic + 0.18 * sharpe + 0.12 * calmar + 0.10 * stability
    elif objective == "defensive":
        signal = 0.36 * drawdown + 0.30 * volatility + 0.14 * stability + 0.12 * sharpe + 0.08 * dynamic
    else:
        signal = 0.24 * dynamic + 0.20 * sharpe + 0.18 * drawdown + 0.16 * annual_return + 0.12 * volatility + 0.10 * stability
    return signal.fillna(0.0).clip(lower=0.0) + 0.01


def _scaled_column(frame: pd.DataFrame, column: str, higher_is_better: bool) -> pd.Series:
    if column not in frame.columns:
        return pd.Series(0.5, index=frame.index)
    return _scaled(frame[column], higher_is_better=higher_is_better).reindex(frame.index, fill_value=0.5)


def _scaled(values: pd.Series | None, higher_is_better: bool) -> pd.Series:
    if values is None:
        return pd.Series(dtype=float)
    series = pd.to_numeric(values, errors="coerce")
    if series.empty:
        return pd.Series(dtype=float)
    if not higher_is_better:
        series = -series
    minimum = float(series.min(skipna=True)) if series.notna().any() else 0.0
    maximum = float(series.max(skipna=True)) if series.notna().any() else 0.0
    if np.isclose(maximum, minimum):
        return pd.Series(0.5, index=series.index)
    return ((series - minimum) / (maximum - minimum)).fillna(0.0)


def _cap_weight_series(weights: pd.Series, max_weight: float) -> pd.Series:
    weights = pd.to_numeric(weights, errors="coerce").fillna(0.0).clip(lower=0.0)
    weights = weights[weights > 0]
    if weights.empty:
        return weights
    weights = weights / weights.sum()
    effective_cap = max(float(max_weight), 1.0 / len(weights))
    for _ in range(len(weights) + 2):
        over = weights > effective_cap
        if not over.any():
            break
        excess = float((weights[over] - effective_cap).sum())
        weights.loc[over] = effective_cap
        under = ~over
        if not under.any() or float(weights[under].sum()) <= 0:
            break
        weights.loc[under] += excess * weights.loc[under] / float(weights.loc[under].sum())
    return weights / weights.sum()


def _cap_group_weight_series(weights: pd.Series, groups: pd.Series, max_group_weight: float) -> pd.Series:
    weights = weights.copy()
    groups = groups.reindex(weights.index).fillna("未分类").astype(str)
    if weights.empty or max_group_weight >= 1.0:
        return weights
    group_count = max(groups.nunique(), 1)
    effective_cap = max(float(max_group_weight), 1.0 / group_count)
    for _ in range(group_count + 2):
        group_weights = weights.groupby(groups).sum()
        over_groups = group_weights[group_weights > effective_cap]
        if over_groups.empty:
            break
        excess_total = 0.0
        for group, group_weight in over_groups.items():
            members = groups[groups == group].index
            if float(group_weight) <= 0:
                continue
            scale = effective_cap / float(group_weight)
            old_sum = float(weights.loc[members].sum())
            weights.loc[members] = weights.loc[members] * scale
            excess_total += old_sum - float(weights.loc[members].sum())
        if excess_total <= 0:
            break
        group_weights = weights.groupby(groups).sum()
        under_groups = group_weights[group_weights < effective_cap].index
        under_members = groups[groups.isin(under_groups)].index
        if len(under_members) == 0 or float(weights.loc[under_members].sum()) <= 0:
            break
        weights.loc[under_members] += excess_total * weights.loc[under_members] / float(weights.loc[under_members].sum())
    return weights / weights.sum()


def _apply_turnover_limit(
    new_weights: dict[str, float],
    previous_weights: dict[str, float],
    max_turnover: float,
) -> pd.Series:
    new = pd.Series(new_weights, dtype=float).clip(lower=0.0)
    new = new[new > 0]
    if new.empty:
        return new
    new = new / new.sum()
    if not previous_weights:
        return new

    previous = pd.Series(previous_weights, dtype=float).clip(lower=0.0)
    previous = previous[previous > 0]
    if previous.empty:
        return new
    previous = previous / previous.sum()

    funds = sorted(set(new.index.astype(str)) | set(previous.index.astype(str)))
    new = new.rename(index=str).reindex(funds, fill_value=0.0)
    previous = previous.rename(index=str).reindex(funds, fill_value=0.0)
    turnover = portfolio_turnover(previous.to_dict(), new.to_dict())
    if turnover <= max_turnover or turnover <= 0:
        limited = new
    else:
        blend = max(min(max_turnover / turnover, 1.0), 0.0)
        limited = previous + blend * (new - previous)
    limited = limited[limited > 1e-8]
    return limited / limited.sum()


def portfolio_turnover(previous_weights: dict[str, float], current_weights: dict[str, float]) -> float:
    if not previous_weights:
        return 0.0
    previous = pd.Series(previous_weights, dtype=float).rename(index=str)
    current = pd.Series(current_weights, dtype=float).rename(index=str)
    funds = sorted(set(previous.index) | set(current.index))
    previous = previous.reindex(funds, fill_value=0.0)
    current = current.reindex(funds, fill_value=0.0)
    if float(previous.sum()) > 0:
        previous = previous / previous.sum()
    if float(current.sum()) > 0:
        current = current / current.sum()
    return float((current - previous).abs().sum() / 2.0)


def _optimized_weights(weights: pd.DataFrame) -> pd.DataFrame:
    if weights.empty or "portfolio" not in weights.columns:
        return pd.DataFrame()
    optimized = weights[weights["portfolio"] == "约束优化组合"].copy()
    if optimized.empty:
        return optimized
    optimized["fund"] = optimized["fund"].astype(str)
    optimized["fund_type"] = optimized["fund_type"].fillna("未分类").astype(str)
    optimized["weight"] = pd.to_numeric(optimized["weight"], errors="coerce").fillna(0.0)
    return optimized


def _selection_reason(row: pd.Series, constraints: PortfolioConstraints) -> str:
    objective = PORTFOLIO_OBJECTIVES.get(constraints.objective, constraints.objective)
    score = row.get("dynamic_score", row.get("composite_score"))
    parts = [f"符合{objective}目标"]
    if pd.notna(score):
        parts.append(f"综合/动态评分为 {float(score):.2f}")
    if pd.notna(row.get("sharpe")) and float(row.get("sharpe")) >= constraints.min_sharpe:
        parts.append("Sharpe 达到约束")
    if pd.notna(row.get("max_drawdown")) and float(row.get("max_drawdown")) >= constraints.max_drawdown_floor:
        parts.append("回撤低于限制")
    return "；".join(parts)


def _weight_reason(weight: float, constraints: PortfolioConstraints) -> str:
    if weight >= constraints.max_position_weight - 1e-6:
        return "权重接近单只基金上限，已受集中度约束控制"
    if weight >= 1.0 / max(constraints.min_funds, 1):
        return "权重高于最低持仓等权水平，说明目标评分相对更优"
    return "权重低于等权水平，用于分散风险和控制集中度"


def _risk_note(row: pd.Series, constraints: PortfolioConstraints) -> str:
    notes: list[str] = []
    if pd.notna(row.get("max_drawdown")):
        drawdown = float(row.get("max_drawdown"))
        notes.append(f"最大回撤 {drawdown:.1%}")
        if drawdown < constraints.max_drawdown_floor:
            notes.append("低于回撤约束，因候选不足被保留")
    if pd.notna(row.get("annual_volatility")):
        notes.append(f"年化波动 {float(row.get('annual_volatility')):.1%}")
    if pd.notna(row.get("risk_level")):
        notes.append(str(row.get("risk_level")))
    return "；".join(notes) if notes else "风险指标可用性有限"


def _diversification_note(
    fund_type: str,
    type_weight: float,
    max_peer_corr: float | None,
    constraints: PortfolioConstraints,
) -> str:
    notes = [f"{fund_type} 合计占比 {type_weight:.1%}"]
    if type_weight > constraints.max_type_weight + 1e-6:
        notes.append("超过同类型上限")
    else:
        notes.append("同类型占比受控")
    if max_peer_corr is not None and pd.notna(max_peer_corr):
        notes.append(f"最高持仓相关 {max_peer_corr:.2f}")
        if max_peer_corr > constraints.max_pair_correlation:
            notes.append("相关性偏高")
    return "；".join(notes)


def _max_peer_correlation(corr: pd.DataFrame, fund: str) -> float | None:
    if corr.empty or fund not in corr.index:
        return None
    peers = corr.loc[fund].drop(labels=[fund], errors="ignore").dropna()
    if peers.empty:
        return None
    return float(peers.max())


def _correlation_control_rows(returns: pd.DataFrame, constraints: PortfolioConstraints) -> list[dict[str, object]]:
    if returns.empty or len(returns.columns) < 2:
        return [
            {
                "control_type": "correlation",
                "item": "selected_pairs",
                "value": 0.0,
                "limit": constraints.max_pair_correlation,
                "status": "pass",
                "note": "持仓数量不足，未形成基金对相关性",
            }
        ]
    corr = returns.corr().abs()
    rows: list[dict[str, object]] = []
    max_pair = ("", "", 0.0)
    for index, fund_a in enumerate(corr.columns):
        for fund_b in corr.columns[index + 1 :]:
            value = float(corr.loc[fund_a, fund_b])
            if value > max_pair[2]:
                max_pair = (str(fund_a), str(fund_b), value)
            if value > constraints.max_pair_correlation:
                rows.append(
                    {
                        "control_type": "correlation",
                        "item": f"{fund_a}/{fund_b}",
                        "value": value,
                        "limit": constraints.max_pair_correlation,
                        "status": "warn",
                        "note": "持仓基金历史收益相关性高于阈值",
                    }
                )
    rows.append(
        {
            "control_type": "correlation",
            "item": "max_pair_correlation" if not max_pair[0] else f"{max_pair[0]}/{max_pair[1]}",
            "value": max_pair[2],
            "limit": constraints.max_pair_correlation,
            "status": "pass" if max_pair[2] <= constraints.max_pair_correlation + 1e-9 else "warn",
            "note": "当前组合最高基金间相关性",
        }
    )
    return rows


def _format_control_value(value: object) -> str:
    if value in {None, ""} or pd.isna(value):
        return ""
    numeric = float(value)
    if abs(numeric) <= 1.0:
        return f"{numeric:.1%}"
    return f"{numeric:.2f}"


def _drawdown_constrained_funds(scored: pd.DataFrame, top_n: int, max_drawdown_floor: float = -0.45) -> list[str]:
    if scored is None or scored.empty:
        return []
    candidates = scored[scored["max_drawdown"] >= max_drawdown_floor] if "max_drawdown" in scored.columns else scored
    if len(candidates) < max(2, min(top_n, len(scored))):
        candidates = scored
    ordered = candidates.sort_values("rank", ascending=True) if "rank" in candidates.columns else candidates
    return [str(fund) for fund in ordered.head(min(top_n, len(ordered))).index]


def _risk_parity_weights(returns: pd.DataFrame) -> dict[str, float]:
    if returns.empty or len(returns.columns) == 0:
        return {}
    vol = returns.std(ddof=1).replace(0.0, np.nan)
    inverse = (1.0 / vol).replace([np.inf, -np.inf], np.nan).fillna(0.0)
    if float(inverse.sum()) <= 0:
        equal = 1.0 / len(returns.columns)
        return {str(fund): equal for fund in returns.columns}
    normalized = inverse / inverse.sum()
    return {str(fund): float(weight) for fund, weight in normalized.items()}


def _portfolio_return(returns: pd.DataFrame, weights: pd.DataFrame) -> pd.Series:
    columns = {str(column): column for column in returns.columns}
    series = pd.Series(0.0, index=returns.index)
    total_weight = 0.0
    for row in weights.itertuples(index=False):
        fund = str(row.fund)
        if fund not in columns:
            continue
        weight = float(row.weight)
        series = series.add(returns[columns[fund]].fillna(0.0) * weight, fill_value=0.0)
        total_weight += weight
    if total_weight <= 0:
        return pd.Series(dtype=float)
    return series / total_weight


def _summary(series: pd.Series) -> dict[str, float]:
    series = series.dropna()
    if series.empty:
        return {"annual_return": 0.0, "annual_volatility": 0.0, "max_drawdown": 0.0, "sharpe": float("nan"), "win_rate": 0.0}
    cumulative = (1 + series).cumprod()
    annual_return = cumulative.iloc[-1] ** (252 / len(series)) - 1
    annual_volatility = series.std(ddof=1) * np.sqrt(252)
    return {
        "annual_return": float(annual_return),
        "annual_volatility": float(annual_volatility),
        "max_drawdown": float(max_drawdown(cumulative)),
        "sharpe": float(annual_return / annual_volatility) if annual_volatility > 0 else float("nan"),
        "win_rate": float((series > 0).mean()),
    }


def _lookup_row(frame: pd.DataFrame, fund: str) -> pd.Series:
    if fund in frame.index:
        return frame.loc[fund]
    return pd.Series(dtype=object)


def _bounded_int(value: object, minimum: int, maximum: int) -> int:
    try:
        numeric = int(float(value))
    except (TypeError, ValueError):
        numeric = minimum
    return min(max(numeric, minimum), maximum)


def _bounded_float(value: object, minimum: float, maximum: float) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        numeric = minimum
    if pd.isna(numeric):
        numeric = minimum
    return min(max(numeric, minimum), maximum)

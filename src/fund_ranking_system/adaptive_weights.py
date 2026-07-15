from __future__ import annotations

from pathlib import Path

import pandas as pd

from .metadata import display_fund
from .scoring import SCORE_METRICS, percentile_scores


FEATURE_LABELS = {
    "annual_return": "年化收益",
    "sharpe": "Sharpe",
    "max_drawdown": "最大回撤",
    "calmar": "Calmar",
    "annual_volatility": "年化波动",
    "rolling_positive_ratio": "滚动正收益比例",
}


def score_funds_with_adaptive_weights(
    metrics: pd.DataFrame,
    base_weights: dict[str, float],
    reference_weights: dict[str, float] | None = None,
    adaptation_strength: float = 0.35,
    winsor_limits: tuple[float, float] | None = (0.01, 0.99),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Score funds with per-fund dynamic factor weights.

    The base profile still defines investor preference. The dynamic layer adjusts that
    reference weight vector around each fund's risk/return profile, making local
    factor importance visible without hiding the original assumptions.
    """
    features = [feature for feature in SCORE_METRICS if feature in base_weights and feature in metrics.columns]
    if not features:
        raise ValueError("No supported factors are available for adaptive weighting.")

    base = _normalize({feature: base_weights[feature] for feature in features})
    reference = _normalize({feature: (reference_weights or base_weights).get(feature, base[feature]) for feature in features})
    factor_scores = percentile_scores(metrics, reference, winsor_limits=winsor_limits)

    weight_rows: list[dict[str, object]] = []
    dynamic_scores = pd.Series(0.0, index=metrics.index, dtype=float)
    for fund in metrics.index:
        score_row = factor_scores.loc[fund]
        dynamic_weights = _fund_dynamic_weights(score_row, reference, adaptation_strength)
        for feature in features:
            factor_score = float(score_row[f"{feature}_score"])
            dynamic_scores.loc[fund] += factor_score * dynamic_weights[feature]
            weight_rows.append(
                {
                    "fund": fund,
                    "fund_name": metrics.loc[fund].get("fund_name", fund),
                    "feature": feature,
                    "feature_label": FEATURE_LABELS.get(feature, feature),
                    "profile_base_weight": base[feature],
                    "ml_reference_weight": reference[feature],
                    "dynamic_weight": dynamic_weights[feature],
                    "weight_delta": dynamic_weights[feature] - reference[feature],
                    "factor_score": factor_score,
                    "adjustment_direction": _direction_label(dynamic_weights[feature] - reference[feature]),
                    "adjustment_reason": _feature_reason(feature, score_row, dynamic_weights[feature] - reference[feature]),
                }
            )

    scored = metrics.join(factor_scores)
    scored["dynamic_score"] = dynamic_scores
    scored["dynamic_rank"] = scored["dynamic_score"].rank(ascending=False, method="min").astype(int)
    weight_table = pd.DataFrame(weight_rows)
    scored["top_dynamic_factors"] = scored.apply(
        lambda row: _top_dynamic_factors(str(row.name), weight_table),
        axis=1,
    )
    scored["dynamic_weight_reason"] = scored.apply(
        lambda row: _fund_reason(str(row.name), factor_scores.loc[row.name], weight_table),
        axis=1,
    )
    return scored.sort_values(["dynamic_score", "annual_return"], ascending=False), weight_table


def save_adaptive_weight_outputs(
    metrics: pd.DataFrame,
    base_weights: dict[str, float],
    reports_dir: str | Path,
    profile: str,
    top_n: int = 10,
    reference_weights: dict[str, float] | None = None,
    base_scored: pd.DataFrame | None = None,
) -> tuple[Path, Path, Path, pd.DataFrame, pd.DataFrame]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    adaptive_scored, weight_table = score_funds_with_adaptive_weights(
        metrics,
        base_weights,
        reference_weights=reference_weights,
    )

    if "fund_type" in adaptive_scored.columns:
        adaptive_scored["dynamic_type_rank"] = adaptive_scored.groupby("fund_type")["dynamic_score"].rank(
            ascending=False,
            method="min",
        ).astype(int)
    if base_scored is not None:
        base_lookup = base_scored[["rank", "composite_score"]].rename(
            columns={"rank": "base_rank", "composite_score": "base_score"}
        )
        adaptive_scored = adaptive_scored.join(base_lookup, how="left")

    ranking_path = reports_dir / f"ranking_adaptive_{profile}.csv"
    weights_path = reports_dir / "adaptive_factor_weights.csv"
    report_path = reports_dir / "adaptive_weight_report.md"
    adaptive_scored.to_csv(ranking_path)
    weight_table.to_csv(weights_path, index=False)
    report_path.write_text(
        build_adaptive_weight_report(adaptive_scored, weight_table, profile, top_n),
        encoding="utf-8",
    )
    return ranking_path, weights_path, report_path, adaptive_scored, weight_table


def build_adaptive_weight_report(
    adaptive_scored: pd.DataFrame,
    weight_table: pd.DataFrame,
    profile: str,
    top_n: int,
) -> str:
    if adaptive_scored.empty:
        return "# 基金级动态权重报告\n\n可用基金数据不足，无法生成动态权重。"

    ranking_rows = [
        "| 动态排名 | 基金 | 动态评分 | 原排名 | 原评分 | 主要动态权重 | 调整说明 |",
        "|---:|---|---:|---:|---:|---|---|",
    ]
    for fund, row in adaptive_scored.head(top_n).iterrows():
        ranking_rows.append(
            "| {rank} | {fund} | {score:.2f} | {base_rank} | {base_score} | {factors} | {reason} |".format(
                rank=int(row["dynamic_rank"]),
                fund=display_fund(str(fund), row),
                score=float(row["dynamic_score"]),
                base_rank=_format_optional_int(row.get("base_rank")),
                base_score=_format_optional_float(row.get("base_score")),
                factors=row.get("top_dynamic_factors", ""),
                reason=row.get("dynamic_weight_reason", ""),
            )
        )

    weight_rows = [
        "| 基金 | 年化收益 | Sharpe | 最大回撤 | Calmar | 年化波动 | 滚动正收益比例 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for fund in adaptive_scored.head(min(top_n, 8)).index:
        fund_weights = _weight_dict(str(fund), weight_table)
        row = adaptive_scored.loc[fund]
        weight_rows.append(
            "| {fund} | {annual_return:.1%} | {sharpe:.1%} | {max_drawdown:.1%} | {calmar:.1%} | {annual_volatility:.1%} | {rolling_positive_ratio:.1%} |".format(
                fund=display_fund(str(fund), row),
                annual_return=fund_weights.get("annual_return", 0.0),
                sharpe=fund_weights.get("sharpe", 0.0),
                max_drawdown=fund_weights.get("max_drawdown", 0.0),
                calmar=fund_weights.get("calmar", 0.0),
                annual_volatility=fund_weights.get("annual_volatility", 0.0),
                rolling_positive_ratio=fund_weights.get("rolling_positive_ratio", 0.0),
            )
        )

    return f"""# 基金级动态权重报告

## 定位

本报告回答“不同基金是否应该使用完全相同的因子权重”。系统仍保留 `{profile}` 投资者画像作为基础偏好，再根据每只基金自身的收益、回撤、波动、风险调整收益和收益稳定性，对因子权重做局部微调。

动态权重不是用户画像的替代品，而是基金级解释层：同样是 `{profile}`，高波动或深回撤基金会更强调回撤和波动控制；风险调整后收益更稳定的基金会更强调 Sharpe、Calmar 和滚动正收益比例；收益优势明显且风险压力较小的基金会适度提高收益因子权重。

## Top {top_n} 动态权重排名

{chr(10).join(ranking_rows)}

## Top 基金动态权重明细

{chr(10).join(weight_rows)}

## 使用边界

动态权重用于解释和研究对照，不代表对未来收益的预测承诺。若基金样本期较短、数据质量不足或市场风格发生变化，应结合原始排名、ML 辅助排名、LIME 局部解释和 Walk-Forward 验证一起判断。
"""


def adaptive_weight_snapshot(weight_table: pd.DataFrame, funds: list[object], max_funds: int = 5) -> str:
    rows = [
        "| 基金 | 年化收益 | Sharpe | 最大回撤 | Calmar | 年化波动 | 滚动正收益比例 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for fund in funds[:max_funds]:
        fund_rows = weight_table[weight_table["fund"].astype(str) == str(fund)]
        if fund_rows.empty:
            continue
        first = fund_rows.iloc[0]
        weights = dict(zip(fund_rows["feature"], fund_rows["dynamic_weight"], strict=False))
        rows.append(
            "| {fund} | {annual_return:.1%} | {sharpe:.1%} | {max_drawdown:.1%} | {calmar:.1%} | {annual_volatility:.1%} | {rolling_positive_ratio:.1%} |".format(
                fund=display_fund(str(fund), pd.Series({"fund_name": first.get("fund_name", "")})),
                annual_return=float(weights.get("annual_return", 0.0)),
                sharpe=float(weights.get("sharpe", 0.0)),
                max_drawdown=float(weights.get("max_drawdown", 0.0)),
                calmar=float(weights.get("calmar", 0.0)),
                annual_volatility=float(weights.get("annual_volatility", 0.0)),
                rolling_positive_ratio=float(weights.get("rolling_positive_ratio", 0.0)),
            )
        )
    return "\n".join(rows)


def _fund_dynamic_weights(
    score_row: pd.Series,
    reference_weights: dict[str, float],
    adaptation_strength: float,
) -> dict[str, float]:
    strength = min(max(adaptation_strength, 0.0), 1.0)
    risk_pressure = _risk_pressure(score_row)
    stability_strength = max(0.0, _avg_score(score_row, ["sharpe", "calmar", "rolling_positive_ratio"]) - 50.0) / 50.0
    signals = {
        "annual_return": 0.55 * _centered(score_row, "annual_return") - 0.35 * risk_pressure,
        "sharpe": 0.45 * _centered(score_row, "sharpe") + 0.25 * stability_strength,
        "max_drawdown": 0.65 * risk_pressure + 0.20 * _centered(score_row, "max_drawdown"),
        "calmar": 0.35 * _centered(score_row, "calmar") + 0.35 * risk_pressure + 0.15 * stability_strength,
        "annual_volatility": 0.65 * risk_pressure + 0.20 * _centered(score_row, "annual_volatility"),
        "rolling_positive_ratio": 0.45 * _centered(score_row, "rolling_positive_ratio") + 0.25 * stability_strength,
    }
    adjusted = {}
    for feature, weight in reference_weights.items():
        signal = signals.get(feature, 0.0)
        multiplier = min(max(1.0 + strength * signal, 0.55), 1.65)
        adjusted[feature] = weight * multiplier
    return _normalize(adjusted)


def _risk_pressure(score_row: pd.Series) -> float:
    drawdown_pressure = max(0.0, 100.0 - float(score_row.get("max_drawdown_score", 50.0))) / 100.0
    volatility_pressure = max(0.0, 100.0 - float(score_row.get("annual_volatility_score", 50.0))) / 100.0
    return (drawdown_pressure + volatility_pressure) / 2.0


def _centered(score_row: pd.Series, feature: str) -> float:
    return (float(score_row.get(f"{feature}_score", 50.0)) - 50.0) / 50.0


def _avg_score(score_row: pd.Series, features: list[str]) -> float:
    values = [float(score_row.get(f"{feature}_score", 50.0)) for feature in features]
    return sum(values) / len(values)


def _normalize(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(float(weight), 0.0) for weight in weights.values())
    if total <= 0:
        equal = 1.0 / len(weights)
        return {feature: equal for feature in weights}
    return {feature: max(float(weight), 0.0) / total for feature, weight in weights.items()}


def _direction_label(delta: float) -> str:
    if delta > 1e-6:
        return "up"
    if delta < -1e-6:
        return "down"
    return "flat"


def _feature_reason(feature: str, score_row: pd.Series, delta: float) -> str:
    label = FEATURE_LABELS.get(feature, feature)
    score = float(score_row.get(f"{feature}_score", 50.0))
    if delta > 1e-6:
        if feature in {"max_drawdown", "annual_volatility"}:
            return f"{label}权重上调，用于强化该基金的下行风险识别。"
        if score >= 60:
            return f"{label}得分相对靠前，局部解释中提高其区分度。"
        return f"{label}对该基金附近的排序更敏感，权重小幅上调。"
    if delta < -1e-6:
        return f"{label}在当前基金上的区分度相对较弱，权重小幅下调。"
    return f"{label}保持参考权重。"


def _top_dynamic_factors(fund: str, weight_table: pd.DataFrame, count: int = 3) -> str:
    fund_rows = weight_table[weight_table["fund"].astype(str) == str(fund)].sort_values(
        "dynamic_weight",
        ascending=False,
    )
    return "；".join(
        f"{row.feature_label} {float(row.dynamic_weight):.1%}"
        for row in fund_rows.head(count).itertuples(index=False)
    )


def _fund_reason(fund: str, score_row: pd.Series, weight_table: pd.DataFrame) -> str:
    risk_pressure = _risk_pressure(score_row)
    fund_rows = weight_table[weight_table["fund"].astype(str) == str(fund)].sort_values(
        "weight_delta",
        ascending=False,
    )
    raised = [str(row.feature_label) for row in fund_rows.head(2).itertuples(index=False) if float(row.weight_delta) > 0]
    factors = "、".join(raised) if raised else "核心因子"
    if risk_pressure >= 0.45:
        return f"该基金风险压力较高，动态权重更强调{factors}。"
    if _avg_score(score_row, ["sharpe", "calmar", "rolling_positive_ratio"]) >= 65:
        return f"该基金风险调整后表现和稳定性较好，动态权重更强调{factors}。"
    return f"根据该基金当前因子分布，动态权重更强调{factors}。"


def _weight_dict(fund: str, weight_table: pd.DataFrame) -> dict[str, float]:
    rows = weight_table[weight_table["fund"].astype(str) == str(fund)]
    return {
        str(row.feature): float(row.dynamic_weight)
        for row in rows.itertuples(index=False)
    }


def _format_optional_int(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(int(float(value)))


def _format_optional_float(value: object) -> str:
    if pd.isna(value):
        return ""
    return f"{float(value):.2f}"

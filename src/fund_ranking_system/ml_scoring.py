from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from .metrics import calculate_metrics
from .metadata import display_fund
from .scoring import LOWER_IS_BETTER, SCORE_METRICS, score_funds


@dataclass(frozen=True)
class MLWeightResult:
    weights: dict[str, float]
    coefficient_table: pd.DataFrame
    diagnostics: dict[str, object]


def build_ml_training_samples(
    nav: pd.DataFrame,
    risk_free_rate: float = 0.02,
    lookback_days: int = 252,
    holding_days: int = 63,
    step_days: int = 63,
    min_funds: int = 3,
) -> pd.DataFrame:
    """Create walk-forward fund-level samples for ML-assisted factor learning."""
    columns = [
        "period_id",
        "fund",
        "train_start",
        "train_end",
        "hold_start",
        "hold_end",
        *SCORE_METRICS,
        "future_return",
        "future_return_rank",
    ]
    nav = nav.sort_index().dropna(how="all").ffill()
    if len(nav) < lookback_days + holding_days:
        return pd.DataFrame(columns=columns)

    rows: list[dict[str, object]] = []
    period_id = 0
    start = 0
    while start + lookback_days + holding_days <= len(nav):
        train = nav.iloc[start : start + lookback_days]
        hold = nav.iloc[start + lookback_days : start + lookback_days + holding_days]
        available = train.columns[train.notna().sum() >= max(60, int(lookback_days * 0.8))]
        available = [
            fund
            for fund in available
            if hold[fund].notna().sum() >= max(20, int(holding_days * 0.5))
        ]
        if len(available) >= min_funds:
            try:
                train_metrics = calculate_metrics(
                    train[available],
                    risk_free_rate=risk_free_rate,
                )
            except ValueError:
                start += step_days
                continue
            period_rows = []
            for fund in train_metrics.index:
                future_series = hold[fund].dropna()
                if len(future_series) < 2:
                    continue
                row = {
                    "period_id": period_id,
                    "fund": fund,
                    "train_start": train.index[0].date().isoformat(),
                    "train_end": train.index[-1].date().isoformat(),
                    "hold_start": hold.index[0].date().isoformat(),
                    "hold_end": hold.index[-1].date().isoformat(),
                    "future_return": float(future_series.iloc[-1] / future_series.iloc[0] - 1),
                }
                for feature in SCORE_METRICS:
                    row[feature] = float(train_metrics.loc[fund, feature])
                period_rows.append(row)
            if period_rows:
                period_frame = pd.DataFrame(period_rows)
                if period_frame["future_return"].nunique(dropna=True) <= 1:
                    period_frame["future_return_rank"] = 50.0
                else:
                    period_frame["future_return_rank"] = (
                        period_frame["future_return"].rank(pct=True, method="average") * 100
                    )
                rows.extend(period_frame.to_dict(orient="records"))
                period_id += 1
        start += step_days

    return pd.DataFrame(rows, columns=columns)


def fit_ml_factor_weights(
    training_samples: pd.DataFrame,
    base_weights: dict[str, float],
    alpha: float = 1.0,
    blend: float = 0.60,
    min_samples: int = 12,
) -> MLWeightResult:
    """Learn non-negative factor weights from walk-forward samples."""
    feature_columns = [feature for feature in SCORE_METRICS if feature in base_weights]
    base = _normalize_weights({feature: base_weights[feature] for feature in feature_columns})
    fallback_table = _coefficient_table(
        feature_columns=feature_columns,
        coefficients=np.zeros(len(feature_columns)),
        learned_weights=base,
        base_weights=base,
        final_weights=base,
    )

    if training_samples.empty or len(training_samples) < min_samples:
        return MLWeightResult(
            weights=base,
            coefficient_table=fallback_table,
            diagnostics={
                "status": "fallback_insufficient_samples",
                "sample_count": int(len(training_samples)),
                "period_count": 0,
                "model_r2": np.nan,
                "rank_ic": np.nan,
                "top_k_hit_rate": np.nan,
                "blend": 0.0,
            },
        )

    samples = training_samples.dropna(subset=feature_columns + ["future_return_rank"]).copy()
    if len(samples) < min_samples:
        return MLWeightResult(
            weights=base,
            coefficient_table=fallback_table,
            diagnostics={
                "status": "fallback_insufficient_clean_samples",
                "sample_count": int(len(samples)),
                "period_count": int(training_samples.get("period_id", pd.Series(dtype=int)).nunique()),
                "model_r2": np.nan,
                "rank_ic": np.nan,
                "top_k_hit_rate": np.nan,
                "blend": 0.0,
            },
        )

    x = _directed_features(samples[feature_columns])
    x = x.fillna(x.median(numeric_only=True)).fillna(0.0)
    x_standardized = _standardize(x)
    y = samples["future_return_rank"].astype(float).to_numpy()
    intercept, coefficients = _ridge_fit(x_standardized.to_numpy(dtype=float), y, alpha=alpha)
    fitted = intercept + x_standardized.to_numpy(dtype=float).dot(coefficients)
    model_r2 = _r2_score(y, fitted)
    rank_ic = _mean_period_spearman(samples, fitted)
    top_k_hit_rate = _top_k_hit_rate(samples, fitted)

    positive = np.maximum(coefficients, 0.0)
    if float(positive.sum()) <= 1e-12:
        return MLWeightResult(
            weights=base,
            coefficient_table=_coefficient_table(
                feature_columns=feature_columns,
                coefficients=coefficients,
                learned_weights=base,
                base_weights=base,
                final_weights=base,
            ),
            diagnostics={
                "status": "fallback_no_positive_signal",
                "sample_count": int(len(samples)),
                "period_count": int(samples["period_id"].nunique()),
                "model_r2": float(model_r2),
                "rank_ic": float(rank_ic),
                "top_k_hit_rate": float(top_k_hit_rate),
                "blend": 0.0,
            },
        )

    learned = dict(zip(feature_columns, positive / positive.sum(), strict=True))
    final_weights = _blend_weights(base, learned, blend=blend)
    coefficient_table = _coefficient_table(
        feature_columns=feature_columns,
        coefficients=coefficients,
        learned_weights=learned,
        base_weights=base,
        final_weights=final_weights,
    )
    return MLWeightResult(
        weights=final_weights,
        coefficient_table=coefficient_table,
        diagnostics={
            "status": "trained",
            "sample_count": int(len(samples)),
            "period_count": int(samples["period_id"].nunique()),
            "model_r2": float(model_r2),
            "rank_ic": float(rank_ic),
            "top_k_hit_rate": float(top_k_hit_rate),
            "blend": float(blend),
        },
    )


def save_ml_outputs(
    nav: pd.DataFrame,
    metrics: pd.DataFrame,
    base_weights: dict[str, float],
    reports_dir: str | Path,
    profile: str,
    top_n: int = 10,
    risk_free_rate: float = 0.02,
    base_scored: pd.DataFrame | None = None,
    lookback_days: int = 252,
    holding_days: int = 63,
    step_days: int = 63,
) -> tuple[Path, Path, Path, Path, Path, Path]:
    """Generate ML-assisted weights, ranking, and report outputs."""
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    samples = build_ml_training_samples(
        nav,
        risk_free_rate=risk_free_rate,
        lookback_days=lookback_days,
        holding_days=holding_days,
        step_days=step_days,
    )
    result = fit_ml_factor_weights(samples, base_weights)
    ml_scored = score_funds(metrics, result.weights)
    ml_scored = ml_scored.rename(
        columns={
            "composite_score": "ml_score",
            "rank": "ml_rank",
        }
    )
    ml_scored["ml_model_status"] = result.diagnostics["status"]
    original_scored = base_scored if base_scored is not None else score_funds(metrics, base_weights)
    comparison = build_ranking_comparison(original_scored, ml_scored, result.coefficient_table)

    samples_path = reports_dir / "ml_training_samples.csv"
    weights_path = reports_dir / "ml_learned_weights.csv"
    ranking_path = reports_dir / f"ranking_ml_{profile}.csv"
    report_path = reports_dir / "ml_model_report.md"
    comparison_path = reports_dir / f"ranking_comparison_{profile}.csv"
    comparison_report_path = reports_dir / "ranking_comparison.md"
    samples.to_csv(samples_path, index=False)
    result.coefficient_table.to_csv(weights_path, index=False)
    ml_scored.to_csv(ranking_path)
    comparison.to_csv(comparison_path, index=False)
    report_path.write_text(
        build_ml_report(
            ml_scored,
            result,
            profile=profile,
            top_n=top_n,
        ),
        encoding="utf-8",
    )
    comparison_report_path.write_text(
        build_ranking_comparison_markdown(comparison, top_n=top_n),
        encoding="utf-8",
    )
    return (
        samples_path,
        weights_path,
        ranking_path,
        report_path,
        comparison_path,
        comparison_report_path,
    )


def build_ranking_comparison(
    original_scored: pd.DataFrame,
    ml_scored: pd.DataFrame,
    coefficient_table: pd.DataFrame,
) -> pd.DataFrame:
    """Compare the original profile ranking against the ML-assisted ranking."""
    rows: list[dict[str, object]] = []
    top_features = coefficient_table.sort_values("final_weight", ascending=False)["feature"].head(2).tolist()
    for fund in original_scored.index.intersection(ml_scored.index):
        original_row = original_scored.loc[fund]
        ml_row = ml_scored.loc[fund]
        original_rank = int(original_row["rank"])
        ml_rank = int(ml_row["ml_rank"])
        rank_change = original_rank - ml_rank
        rows.append(
            {
                "fund": fund,
                "fund_name": original_row.get("fund_name", ml_row.get("fund_name", fund)),
                "original_rank": original_rank,
                "ml_rank": ml_rank,
                "rank_change": rank_change,
                "original_score": float(original_row["composite_score"]),
                "ml_score": float(ml_row["ml_score"]),
                "change_direction": _rank_change_label(rank_change),
                "comparison_reason": _comparison_reason(rank_change, top_features),
            }
        )
    return pd.DataFrame(rows).sort_values(["ml_rank", "original_rank"])


def build_ranking_comparison_markdown(comparison: pd.DataFrame, top_n: int = 10) -> str:
    if comparison.empty:
        return "# 原始排名 vs ML 排名对比\n\n可用排名数据不足，无法生成对比。"

    rows = [
        "| 基金 | 原始排名 | ML排名 | 排名变化 | 原始评分 | ML评分 | 说明 |",
        "|---|---:|---:|---:|---:|---:|---|",
    ]
    for row in comparison.head(top_n).itertuples(index=False):
        rows.append(
            "| {fund} | {original_rank} | {ml_rank} | {rank_change:+d} | {original_score:.2f} | {ml_score:.2f} | {reason} |".format(
                fund=display_fund(str(row.fund), pd.Series({"fund_name": row.fund_name})),
                original_rank=int(row.original_rank),
                ml_rank=int(row.ml_rank),
                rank_change=int(row.rank_change),
                original_score=float(row.original_score),
                ml_score=float(row.ml_score),
                reason=row.comparison_reason,
            )
        )

    return f"""# 原始排名 vs ML 排名对比

本报告比较当前投资者画像的人工权重排名与机器学习辅助排名。`排名变化` 为正表示该基金在 ML 辅助排名中上升，为负表示下降。

## Top {top_n} 对比

{chr(10).join(rows)}

## 解释边界

ML 排名变化反映的是历史样本中学习到的因子权重变化，不代表未来收益承诺。排名变化较大的基金应结合原始指标、LIME 局部解释、数据质量和风险标签一起判断。
"""


def build_ml_report(
    ml_scored: pd.DataFrame,
    result: MLWeightResult,
    profile: str,
    top_n: int,
) -> str:
    diagnostics = result.diagnostics
    weight_rows = "\n".join(
        "| {feature} | {base:.1%} | {learned:.1%} | {final:.1%} | {coefficient:.4f} |".format(
            feature=row.feature,
            base=row.base_weight,
            learned=row.learned_weight,
            final=row.final_weight,
            coefficient=row.coefficient,
        )
        for row in result.coefficient_table.itertuples(index=False)
    )
    ranking_rows = [
        "| ML排名 | 基金 | ML评分 | 年化收益率 | 最大回撤 | Sharpe |",
        "|---:|---|---:|---:|---:|---:|",
    ]
    for fund, row in ml_scored.head(top_n).iterrows():
        ranking_rows.append(
            "| {rank} | {fund} | {score:.2f} | {ret:.2%} | {drawdown:.2%} | {sharpe:.3f} |".format(
                rank=int(row["ml_rank"]),
                fund=display_fund(str(fund), row),
                score=float(row["ml_score"]),
                ret=float(row["annual_return"]),
                drawdown=float(row["max_drawdown"]),
                sharpe=float(row["sharpe"]),
            )
        )

    status_text = {
        "trained": "模型已基于历史滚动窗口完成训练，并将学习权重与当前投资者画像权重进行融合。",
        "fallback_insufficient_samples": "可用历史样本不足，系统退回当前投资者画像基础权重。",
        "fallback_insufficient_clean_samples": "清洗后的有效样本不足，系统退回当前投资者画像基础权重。",
        "fallback_no_positive_signal": "训练样本中没有稳定的正向因子信号，系统退回当前投资者画像基础权重。",
    }.get(str(diagnostics["status"]), "系统使用当前投资者画像基础权重。")

    return f"""# 机器学习辅助评分报告

## 定位

本模块用于把项目升级为机器学习辅助版本。系统使用 Walk-Forward 历史窗口生成基金级训练样本，以训练期风险收益指标解释下一持有期的相对收益排名，再把模型学到的非负因子重要性转换为评分权重。

主排名仍保留人工设定的投资者画像权重；本报告提供一份 ML 辅助排名，用于研究对照和展示模型迭代能力。

## 模型状态

- 投资者画像：`{profile}`
- 状态：`{diagnostics['status']}`
- 有效训练样本：{diagnostics['sample_count']}
- 有效滚动窗口：{diagnostics['period_count']}
- 训练集 R²：{float(diagnostics['model_r2']) if pd.notna(diagnostics['model_r2']) else float('nan'):.3f}
- 平均 Rank IC：{float(diagnostics['rank_ic']) if pd.notna(diagnostics['rank_ic']) else float('nan'):.3f}
- TopK 命中率：{float(diagnostics['top_k_hit_rate']) if pd.notna(diagnostics['top_k_hit_rate']) else float('nan'):.1%}
- ML 权重融合比例：{float(diagnostics['blend']):.0%}

{status_text}

## 学习到的权重

| 因子 | 原画像权重 | ML学习权重 | 最终融合权重 | 标准化系数 |
|---|---:|---:|---:|---:|
{weight_rows}

## Top {top_n} ML 辅助排名

{chr(10).join(ranking_rows)}

## 使用边界

该机器学习模块不构成未来收益预测承诺，也不输出买入、持有或卖出指令。训练样本来自历史窗口，可能受市场阶段、样本数量和基金池结构影响。应将 ML 辅助排名与原始多因子排名、LIME 局部解释、Walk-Forward 验证和风险提示一起使用。
"""


def _directed_features(frame: pd.DataFrame) -> pd.DataFrame:
    directed = frame.copy()
    for feature in directed.columns:
        if feature in LOWER_IS_BETTER:
            directed[feature] = -directed[feature]
    return directed


def _standardize(frame: pd.DataFrame) -> pd.DataFrame:
    std = frame.std(ddof=0).replace(0.0, np.nan)
    return (frame - frame.mean()) / std.fillna(1.0)


def _ridge_fit(x: np.ndarray, y: np.ndarray, alpha: float) -> tuple[float, np.ndarray]:
    design = np.column_stack([np.ones(len(x)), x])
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    coefficients = np.linalg.pinv(design.T.dot(design) + penalty).dot(design.T).dot(y)
    return float(coefficients[0]), coefficients[1:].astype(float)


def _r2_score(y: np.ndarray, fitted: np.ndarray) -> float:
    total = float(np.square(y - y.mean()).sum())
    if total <= 1e-12:
        return 1.0
    residual = float(np.square(y - fitted).sum())
    return 1.0 - residual / total


def _mean_period_spearman(samples: pd.DataFrame, fitted: np.ndarray) -> float:
    predictions = pd.Series(fitted, index=samples.index)
    values = []
    for _, group in samples.groupby("period_id"):
        if len(group) < 3:
            continue
        target = group["future_return_rank"]
        predicted = predictions.loc[group.index]
        if target.nunique(dropna=True) <= 1 or predicted.nunique(dropna=True) <= 1:
            continue
        values.append(float(predicted.rank().corr(target.rank())))
    return float(np.nanmean(values)) if values else np.nan


def _top_k_hit_rate(samples: pd.DataFrame, fitted: np.ndarray, top_pct: float = 0.2) -> float:
    predictions = pd.Series(fitted, index=samples.index)
    hit_rates = []
    for _, group in samples.groupby("period_id"):
        if group.empty:
            continue
        count = max(1, int(np.ceil(len(group) * top_pct)))
        predicted_top = set(predictions.loc[group.index].nlargest(count).index)
        actual_top = set(group["future_return_rank"].nlargest(count).index)
        hit_rates.append(len(predicted_top & actual_top) / count)
    return float(np.nanmean(hit_rates)) if hit_rates else np.nan


def _rank_change_label(rank_change: int) -> str:
    if rank_change > 0:
        return "up"
    if rank_change < 0:
        return "down"
    return "unchanged"


def _comparison_reason(rank_change: int, top_features: list[str]) -> str:
    factors = "、".join(top_features) if top_features else "学习权重"
    if rank_change > 0:
        return f"ML 辅助模型更看重 {factors}，该基金在融合权重下排名上升。"
    if rank_change < 0:
        return f"ML 辅助模型更看重 {factors}，该基金在融合权重下排名下降。"
    return f"ML 辅助模型更看重 {factors}，该基金排名基本保持不变。"


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = float(sum(max(value, 0.0) for value in weights.values()))
    if total <= 0:
        equal = 1.0 / len(weights)
        return {feature: equal for feature in weights}
    return {feature: max(value, 0.0) / total for feature, value in weights.items()}


def _blend_weights(
    base_weights: dict[str, float],
    learned_weights: dict[str, float],
    blend: float,
) -> dict[str, float]:
    blend = min(max(blend, 0.0), 1.0)
    combined = {
        feature: (1 - blend) * base_weights[feature] + blend * learned_weights[feature]
        for feature in base_weights
    }
    return _normalize_weights(combined)


def _coefficient_table(
    feature_columns: list[str],
    coefficients: np.ndarray,
    learned_weights: dict[str, float],
    base_weights: dict[str, float],
    final_weights: dict[str, float],
) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "feature": feature,
                "direction": "lower_is_better" if feature in LOWER_IS_BETTER else "higher_is_better",
                "coefficient": float(coefficients[index]),
                "abs_coefficient": float(abs(coefficients[index])),
                "base_weight": float(base_weights[feature]),
                "learned_weight": float(learned_weights[feature]),
                "final_weight": float(final_weights[feature]),
            }
            for index, feature in enumerate(feature_columns)
        ]
    ).sort_values("final_weight", ascending=False)

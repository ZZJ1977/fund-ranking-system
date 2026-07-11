from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .metadata import display_fund
from .scoring import LOWER_IS_BETTER, score_funds


def generate_lime_explanations(
    scored: pd.DataFrame,
    weights: dict[str, float],
    top_n: int = 10,
    n_samples: int = 400,
    kernel_width: float | None = None,
    random_state: int = 42,
) -> pd.DataFrame:
    """Explain top funds with a lightweight tabular LIME-style surrogate model."""
    if not weights:
        raise ValueError("Weights must not be empty.")

    base_scored = scored if "composite_score" in scored.columns else score_funds(scored, weights)
    feature_columns = list(weights)
    features = _feature_frame(base_scored, feature_columns)
    ordered_funds = base_scored.sort_values("composite_score", ascending=False).head(top_n).index
    rng = np.random.default_rng(random_state)
    sample_count = max(n_samples, len(feature_columns) + 2)
    width = kernel_width or np.sqrt(len(feature_columns)) * 0.75

    rows: list[dict[str, object]] = []
    for fund in ordered_funds:
        explanation = _explain_one_fund(
            fund=fund,
            scored=base_scored,
            features=features,
            weights=weights,
            n_samples=sample_count,
            kernel_width=width,
            rng=rng,
        )
        rows.extend(explanation)

    return pd.DataFrame(rows)


def save_lime_outputs(
    scored: pd.DataFrame,
    weights: dict[str, float],
    reports_dir: str | Path,
    top_n: int = 10,
    n_samples: int = 400,
    random_state: int = 42,
) -> tuple[Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    explanations = generate_lime_explanations(
        scored,
        weights,
        top_n=top_n,
        n_samples=n_samples,
        random_state=random_state,
    )
    csv_path = reports_dir / "lime_explanations.csv"
    markdown_path = reports_dir / "lime_explanations.md"
    explanations.to_csv(csv_path, index=False)
    markdown_path.write_text(
        build_lime_markdown(scored, explanations, top_n),
        encoding="utf-8",
    )
    return csv_path, markdown_path


def build_lime_markdown(
    scored: pd.DataFrame,
    explanations: pd.DataFrame,
    top_n: int,
) -> str:
    if explanations.empty:
        return "# LIME 局部解释\n\n可用样本不足，无法生成 LIME 局部解释。"

    rows = [
        "| 基金 | 局部正向敏感因子 | 局部负向敏感因子 | 代理模型R² | 说明 |",
        "|---|---|---|---:|---|",
    ]
    for fund in explanations["fund"].drop_duplicates().head(top_n):
        fund_rows = explanations[explanations["fund"] == fund]
        positive = fund_rows[fund_rows["local_weight"] > 0].sort_values(
            "local_weight",
            ascending=False,
        )
        negative = fund_rows[fund_rows["local_weight"] < 0].sort_values("local_weight")
        first = fund_rows.iloc[0]
        row = scored.loc[fund] if fund in scored.index else pd.Series(dtype=object)
        rows.append(
            "| {fund} | {positive} | {negative} | {r2:.3f} | {summary} |".format(
                fund=display_fund(str(fund), row),
                positive=_factor_text(positive),
                negative=_factor_text(negative),
                r2=float(first["surrogate_r2"]),
                summary=_summary_sentence(positive, negative),
            )
        )

    return f"""# LIME 局部解释

本报告把 LIME 定位为补充性的局部解释模块：系统仍以确定性的多因子评分和精确因子贡献分解作为主解释，LIME 用于回答“在某只基金附近，如果单个因子小幅变化，综合评分会怎样局部响应”。

实现方式：

```text
选取单只基金 -> 在其因子附近生成扰动样本 -> 调用现有评分模型得到综合评分 -> 按距离加权拟合局部线性代理模型
```

`local_weight` 表示该因子在当前基金附近上升 1 个样本标准差时，局部代理模型估计的综合评分变化。正值表示该因子上升倾向于抬高综合评分，负值表示倾向于压低综合评分。对于 `annual_volatility`，模型方向本来就是越低越好，因此它的局部权重通常为负。

## Top {top_n} 局部解释

{chr(10).join(rows)}

## 使用边界

LIME 是局部近似解释，不是未来收益预测，也不是买入、持有或卖出建议。当代理模型R²较低时，说明该基金附近的评分响应不容易被线性模型近似，应优先参考精确因子贡献分解和原始指标。
"""


def _explain_one_fund(
    fund: object,
    scored: pd.DataFrame,
    features: pd.DataFrame,
    weights: dict[str, float],
    n_samples: int,
    kernel_width: float,
    rng: np.random.Generator,
) -> list[dict[str, object]]:
    feature_columns = list(weights)
    instance = features.loc[fund]
    scale = _feature_scale(features)
    samples = _sample_neighborhood(instance, features, scale, n_samples, rng)
    predictions = _predict_composite_scores(features, samples, weights)
    centered = (samples[feature_columns] - instance[feature_columns]) / scale[feature_columns]
    distances = np.sqrt(np.square(centered.to_numpy(dtype=float)).sum(axis=1))
    kernel_weights = np.exp(-(distances**2) / (kernel_width**2))
    intercept, coefficients = _weighted_ridge_fit(
        centered.to_numpy(dtype=float),
        predictions,
        kernel_weights,
    )
    surrogate_predictions = intercept + centered.to_numpy(dtype=float).dot(coefficients)
    surrogate_r2 = _weighted_r2(predictions, surrogate_predictions, kernel_weights)
    black_box_score = float(predictions[0])
    surrogate_score = float(intercept)

    rows: list[dict[str, object]] = []
    for feature, coefficient in zip(feature_columns, coefficients, strict=True):
        value = float(instance[feature])
        rows.append(
            {
                "fund": fund,
                "fund_name": scored.loc[fund].get("fund_name", fund),
                "feature": feature,
                "feature_value": value,
                "feature_direction": "lower_is_better" if feature in LOWER_IS_BETTER else "higher_is_better",
                "local_weight": float(coefficient),
                "abs_weight": float(abs(coefficient)),
                "local_direction": _local_direction(float(coefficient)),
                "black_box_score": black_box_score,
                "surrogate_score": surrogate_score,
                "surrogate_error": surrogate_score - black_box_score,
                "surrogate_r2": float(surrogate_r2),
                "n_samples": n_samples,
            }
        )
    return sorted(rows, key=lambda row: row["abs_weight"], reverse=True)


def _feature_frame(frame: pd.DataFrame, feature_columns: list[str]) -> pd.DataFrame:
    missing = [feature for feature in feature_columns if feature not in frame.columns]
    if missing:
        raise ValueError(f"Missing features for LIME explanation: {missing}")
    features = frame[feature_columns].apply(pd.to_numeric, errors="coerce")
    medians = features.median(numeric_only=True).fillna(0.0)
    return features.fillna(medians).astype(float)


def _feature_scale(features: pd.DataFrame) -> pd.Series:
    std = features.std(ddof=0).replace(0.0, np.nan)
    iqr = (features.quantile(0.75) - features.quantile(0.25)) / 1.349
    scale = std.fillna(iqr).replace(0.0, np.nan).fillna(1.0)
    return scale.astype(float)


def _sample_neighborhood(
    instance: pd.Series,
    background: pd.DataFrame,
    scale: pd.Series,
    n_samples: int,
    rng: np.random.Generator,
) -> pd.DataFrame:
    feature_columns = list(background.columns)
    samples = rng.normal(
        loc=instance[feature_columns].to_numpy(dtype=float),
        scale=scale[feature_columns].to_numpy(dtype=float),
        size=(n_samples, len(feature_columns)),
    )
    sampled = pd.DataFrame(samples, columns=feature_columns)
    lower = background.quantile(0.01)
    upper = background.quantile(0.99)
    sampled = sampled.clip(lower=lower, upper=upper, axis=1)
    sampled.iloc[0] = instance[feature_columns]
    sampled.index = [f"lime_sample_{index}" for index in range(len(sampled))]
    return sampled


def _predict_composite_scores(
    background: pd.DataFrame,
    samples: pd.DataFrame,
    weights: dict[str, float],
) -> np.ndarray:
    combined = pd.concat([background, samples], axis=0)
    predicted = score_funds(combined, weights)
    return predicted.loc[samples.index, "composite_score"].reindex(samples.index).to_numpy(dtype=float)


def _weighted_ridge_fit(
    x: np.ndarray,
    y: np.ndarray,
    sample_weights: np.ndarray,
    alpha: float = 1e-3,
) -> tuple[float, np.ndarray]:
    design = np.column_stack([np.ones(len(x)), x])
    weights = np.clip(sample_weights.astype(float), 1e-8, None)
    sqrt_weights = np.sqrt(weights)
    weighted_design = design * sqrt_weights[:, None]
    weighted_y = y * sqrt_weights
    penalty = np.eye(design.shape[1]) * alpha
    penalty[0, 0] = 0.0
    coefficients = np.linalg.pinv(weighted_design.T.dot(weighted_design) + penalty).dot(
        weighted_design.T,
    ).dot(weighted_y)
    return float(coefficients[0]), coefficients[1:].astype(float)


def _weighted_r2(y: np.ndarray, fitted: np.ndarray, sample_weights: np.ndarray) -> float:
    weights = np.clip(sample_weights.astype(float), 1e-8, None)
    mean = float(np.average(y, weights=weights))
    total = float(np.sum(weights * np.square(y - mean)))
    if total <= 1e-12:
        return 1.0
    residual = float(np.sum(weights * np.square(y - fitted)))
    return 1.0 - residual / total


def _local_direction(coefficient: float) -> str:
    if coefficient > 1e-9:
        return "increases_score"
    if coefficient < -1e-9:
        return "decreases_score"
    return "neutral"


def _factor_text(frame: pd.DataFrame, limit: int = 3) -> str:
    if frame.empty:
        return "无明显因子"
    return "；".join(
        f"{row.feature}: {row.local_weight:+.2f}"
        for row in frame.head(limit).itertuples(index=False)
    )


def _summary_sentence(positive: pd.DataFrame, negative: pd.DataFrame) -> str:
    positive_names = "、".join(str(value) for value in positive["feature"].head(2))
    negative_names = "、".join(str(value) for value in negative["feature"].head(2))
    if positive_names and negative_names:
        return f"局部来看，{positive_names} 上升倾向于抬高评分，{negative_names} 上升倾向于压低评分。"
    if positive_names:
        return f"局部来看，{positive_names} 上升倾向于抬高评分。"
    if negative_names:
        return f"局部来看，{negative_names} 上升倾向于压低评分。"
    return "局部扰动下各因子影响较弱。"

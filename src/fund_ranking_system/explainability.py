from __future__ import annotations

from pathlib import Path

import pandas as pd

from .metadata import display_fund
from .scoring import LOWER_IS_BETTER, percentile_scores


def calculate_factor_contributions(
    metrics: pd.DataFrame,
    weights: dict[str, float],
) -> pd.DataFrame:
    """Decompose a weighted percentile score into exact factor contributions."""
    weight_sum = sum(weights.values())
    if weight_sum <= 0:
        raise ValueError("Weight sum must be positive.")
    normalized = {metric: weight / weight_sum for metric, weight in weights.items()}
    scores = percentile_scores(metrics, normalized)
    rows: list[dict[str, object]] = []
    for fund in metrics.index:
        for metric, weight in normalized.items():
            score = float(scores.loc[fund, f"{metric}_score"])
            contribution = score * weight
            rows.append(
                {
                    "fund": fund,
                    "fund_name": metrics.loc[fund].get("fund_name", fund),
                    "factor": metric,
                    "direction": "lower_is_better" if metric in LOWER_IS_BETTER else "higher_is_better",
                    "factor_score": score,
                    "weight": weight,
                    "contribution": contribution,
                }
            )
    return pd.DataFrame(rows)


def generate_ranking_explanation(
    metrics: pd.DataFrame,
    weights: dict[str, float],
    top_n: int = 10,
) -> pd.DataFrame:
    contributions = calculate_factor_contributions(metrics, weights)
    top_funds = (
        metrics.sort_values("composite_score", ascending=False).head(top_n).index
        if "composite_score" in metrics.columns
        else metrics.index[:top_n]
    )
    rows: list[dict[str, object]] = []
    for fund in top_funds:
        fund_contrib = contributions[contributions["fund"] == fund].copy()
        positive = fund_contrib.sort_values("contribution", ascending=False).head(3)
        negative = fund_contrib.sort_values("contribution", ascending=True).head(2)
        rows.append(
            {
                "fund": fund,
                "fund_name": metrics.loc[fund].get("fund_name", fund),
                "top_positive_factors": _factor_text(positive),
                "weak_factors": _factor_text(negative),
                "explanation": _sentence(metrics.loc[fund], positive, negative),
            }
        )
    return pd.DataFrame(rows).set_index("fund")


def save_explainability_outputs(
    scored: pd.DataFrame,
    weights: dict[str, float],
    reports_dir: str | Path,
    top_n: int = 10,
) -> tuple[Path, Path, Path]:
    reports_dir = Path(reports_dir)
    reports_dir.mkdir(parents=True, exist_ok=True)
    contributions = calculate_factor_contributions(scored, weights)
    explanations = generate_ranking_explanation(scored, weights, top_n=top_n)
    contribution_path = reports_dir / "factor_contributions.csv"
    explanation_path = reports_dir / "ranking_explanations.csv"
    markdown_path = reports_dir / "factor_contributions.md"
    contributions.to_csv(contribution_path, index=False)
    explanations.to_csv(explanation_path)
    markdown_path.write_text(build_explainability_markdown(scored, explanations, top_n), encoding="utf-8")
    return contribution_path, explanation_path, markdown_path


def build_explainability_markdown(
    scored: pd.DataFrame,
    explanations: pd.DataFrame,
    top_n: int,
) -> str:
    rows = [
        "| 基金 | 主要正向因素 | 相对弱项 | 解释 |",
        "|---|---|---|---|",
    ]
    for fund, row in explanations.head(top_n).iterrows():
        rows.append(
            f"| {display_fund(str(fund), scored.loc[fund])} | {row['top_positive_factors']} | {row['weak_factors']} | {row['explanation']} |"
        )
    return f"""# 因子贡献解释

当前评分模型是确定性的线性加权模型，因此可以直接进行精确贡献分解，而不需要使用近似解释方法。

每个因子的贡献为：

```text
factor_contribution = factor_percentile_score * normalized_weight
```

## Top {top_n} 解释

{chr(10).join(rows)}
"""


def _factor_text(frame: pd.DataFrame) -> str:
    return "；".join(
        f"{row.factor}: {row.contribution:.2f}"
        for row in frame.itertuples(index=False)
    )


def _sentence(row: pd.Series, positive: pd.DataFrame, negative: pd.DataFrame) -> str:
    positive_names = "、".join(str(value) for value in positive["factor"].head(2))
    weak_names = "、".join(str(value) for value in negative["factor"].head(2))
    return f"该基金综合评分主要由 {positive_names} 支撑，相对弱项集中在 {weak_names}。"

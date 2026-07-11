from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd


TEXT_KEYWORDS = {
    "成长": 0.8,
    "优势": 0.6,
    "精选": 0.5,
    "稳健": 0.4,
    "消费": 0.3,
    "债券": -0.2,
    "新兴": 0.7,
    "产业": 0.4,
    "指数": 0.0,
}


def build_research_enhancement(scored: pd.DataFrame, reports_dir: str | Path) -> tuple[Path, Path]:
    """Create a lightweight research appendix with name-keyword examples."""
    reports_dir = Path(reports_dir)
    research = scored.copy()
    if "fund_name" not in research.columns:
        research["fund_name"] = research.index.astype(str)
    research["text_factor"] = research.apply(_text_factor, axis=1)
    research["future_score_proxy"] = _future_score_proxy(research)
    explanation = _linear_explanation(research)

    csv_path = reports_dir / "research_enhancement.csv"
    md_path = reports_dir / "research_enhancement.md"
    research[
        [
            "fund_name",
            "annual_return",
            "annual_volatility",
            "max_drawdown",
            "sharpe",
            "calmar",
            "rolling_positive_ratio",
            "text_factor",
            "future_score_proxy",
        ]
    ].to_csv(csv_path)
    md_path.write_text(_research_markdown(explanation), encoding="utf-8")
    return csv_path, md_path


def _text_factor(row: pd.Series) -> float:
    name = str(row.get("fund_name", ""))
    score = 0.0
    for keyword, weight in TEXT_KEYWORDS.items():
        if keyword in name:
            score += weight
    return score


def _future_score_proxy(frame: pd.DataFrame) -> pd.Series:
    # This is a research proxy, not a real future return label.
    return (
        0.35 * _rank01(frame["annual_return"])
        + 0.25 * _rank01(frame["sharpe"])
        + 0.20 * _rank01(frame["calmar"])
        + 0.10 * _rank01(frame["rolling_positive_ratio"])
        + 0.10 * _rank01(frame["text_factor"])
    )


def _rank01(series: pd.Series) -> pd.Series:
    if series.nunique(dropna=True) <= 1:
        return pd.Series(0.5, index=series.index)
    return series.rank(pct=True).fillna(0.5)


def _linear_explanation(frame: pd.DataFrame) -> pd.DataFrame:
    feature_columns = [
        "annual_return",
        "annual_volatility",
        "max_drawdown",
        "sharpe",
        "calmar",
        "rolling_positive_ratio",
        "text_factor",
    ]
    features = frame[feature_columns].fillna(0.0)
    target = frame["future_score_proxy"].fillna(0.0)
    standardized = (features - features.mean()) / features.std(ddof=0).replace(0, 1)
    x = np.column_stack([np.ones(len(standardized)), standardized.to_numpy()])
    coefficients = np.linalg.pinv(x).dot(target.to_numpy())[1:]
    explanation = pd.DataFrame(
        {"feature": feature_columns, "coefficient": coefficients}
    )
    explanation["abs_importance"] = explanation["coefficient"].abs()
    return explanation.sort_values("abs_importance", ascending=False)


def _research_markdown(explanation: pd.DataFrame) -> str:
    rows = "\n".join(
        f"| {row.feature} | {row.coefficient:.4f} | {row.abs_importance:.4f} |"
        for row in explanation.itertuples(index=False)
    )
    return f"""# 研究附录

## 定位

本附录不构成真实收益预测模型。`future_score_proxy` 是基于历史指标构造的代理目标，用于演示如何把额外特征接入项目。

## 名称关键词示例

系统会从基金名称中提取关键词，例如成长、优势、精选、稳健、消费、债券、新兴、产业、指数，并形成一个名称关键词示例特征。该特征不等同于基于基金季报或公告文本构建的正式文本因子。

## 可解释模型

这里使用标准化线性模型近似解释各特征对代理目标的影响。系数绝对值越大，表示该特征在当前样本中的解释权重越高。

| 因子 | 系数 | 绝对重要性 |
|---|---:|---:|
{rows}

"""

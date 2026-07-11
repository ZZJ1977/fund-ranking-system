from __future__ import annotations

from pathlib import Path

import pandas as pd

from .scoring import SCORE_METRICS


def factor_correlation(metrics: pd.DataFrame, method: str = "spearman") -> pd.DataFrame:
    """Calculate factor correlation for scoring metrics."""
    columns = [column for column in SCORE_METRICS if column in metrics.columns]
    if len(columns) < 2:
        return pd.DataFrame()
    return metrics[columns].corr(method=method)


def save_factor_diagnostics(
    metrics: pd.DataFrame,
    csv_path: str | Path,
    markdown_path: str | Path,
) -> tuple[Path, Path]:
    corr = factor_correlation(metrics)
    csv_path = Path(csv_path)
    markdown_path = Path(markdown_path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    corr.to_csv(csv_path)
    markdown_path.write_text(build_factor_diagnostics_markdown(corr), encoding="utf-8")
    return csv_path, markdown_path


def build_factor_diagnostics_markdown(corr: pd.DataFrame) -> str:
    if corr.empty:
        return "# 因子相关性诊断\n\n可用因子数量不足，无法计算相关性。"
    high_pairs = []
    columns = list(corr.columns)
    for i, left in enumerate(columns):
        for right in columns[i + 1 :]:
            value = corr.loc[left, right]
            if pd.notna(value) and abs(value) >= 0.75:
                high_pairs.append((left, right, value))
    pair_lines = "\n".join(
        f"- `{left}` 与 `{right}` 的 Spearman 相关系数为 {value:.2f}"
        for left, right, value in high_pairs
    ) or "- 暂未发现绝对值超过 0.75 的高相关因子对。"
    return f"""# 因子相关性诊断

本诊断使用 Spearman 相关系数检查评分因子之间的信息重叠。

## 高相关因子对

{pair_lines}

## 解释

Sharpe、Calmar、收益率、波动率和最大回撤之间存在结构性关联。保留这些指标的原因是它们刻画的风险含义不同：Sharpe 更关注整体波动下的风险调整收益，Calmar 更关注极端回撤下的收益表现。本报告用于提示潜在冗余，而不是机械删除指标。
"""
